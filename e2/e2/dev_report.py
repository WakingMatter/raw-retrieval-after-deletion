"""DEV-pass report (NOT results): summary-served rate per class (K-delivery), per-arm accuracy, failures, tokens,
per-stream paired differences, sd_hat and the §7 stream-addition decision. Usage: python -m e2.dev_report --tag DEV"""
from __future__ import annotations
import argparse, json
from collections import defaultdict, Counter
from statistics import mean, median
from .paths import RUNS
from .power import sd_hat, n_streams

K_DELIVERY = 0.80
CLASSES = ("AGG", "DERIVED", "MULTIHOP", "CURRENT")


def api_totals(path):
    """Live (non-cached) API calls from the event log: counts, failures, token sums by role."""
    out = {"calls": Counter(), "failed": Counter(), "tokens": defaultdict(Counter), "other_events": Counter()}
    if not path.exists():
        return None
    for l in path.read_text().splitlines():
        e = json.loads(l)
        if e.get("kind") == "call_failed":                         # rev 5: terminal failure after all retries
            out["failed"][e["role"]] += 1; out["other_events"]["call_failed"] += 1; continue
        if e.get("kind") != "call":
            out["other_events"][e.get("kind")] += 1; continue
        out["calls"][e["role"]] += 1
        out["failed"][e["role"]] += (not e.get("ok"))
        out["tokens"][e["role"]].update(e.get("usage") or {})
    tot = Counter()
    for c in out["tokens"].values():
        tot.update(c)
    out["tokens_total"] = dict(tot)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("--tag", default="DEV"); a = ap.parse_args(argv)
    base = RUNS / a.tag
    rows, stats = [], {}
    for d in sorted(base.glob("stream-*")):
        f = d / "answers.jsonl"
        if f.exists():
            seed = int(d.name.split("-")[1])
            rows += [dict(json.loads(l), seed=seed) for l in f.read_text().splitlines() if l.strip()]
            stats[seed] = json.loads((d / "stats.json").read_text())
    rep = {"tag": a.tag, "label": "DEV — not results", "streams": sorted(stats), "n_rows": len(rows)}
    a6 = [r for r in rows if r["arm"] == "A6"]
    served = lambda r: len((r.get("trace") or {}).get("served_summaries") or [])
    rep["served_rate"] = {c: round(mean(served(r) > 0 for r in a6 if r["cls"] == c), 4) for c in CLASSES}
    kd = [r for r in a6 if r["cls"] in ("AGG", "DERIVED", "MULTIHOP")]
    rep["k_delivery_rate"] = round(mean(served(r) > 0 for r in kd), 4)
    rep["k_delivery_pass"] = rep["k_delivery_rate"] >= K_DELIVERY
    rep["summaries_served_per_probe"] = dict(sorted(Counter(served(r) for r in a6).items()))
    rep["node_status"] = dict(Counter(n["status"] for r in a6 for n in (r.get("trace") or {}).get("nodes", [])))
    summ = [s for st in stats.values() for s in st["summaries"].values()]
    rep["final_summaries"] = {"n": len(summ), "truncated": sum(bool(s["truncated"]) for s in summ),
                              "cost_raw_median": median([s["cost_raw"] for s in summ]) if summ else None,
                              "cost_served_median": median([s["cost_served"] for s in summ]) if summ else None}
    acc = defaultdict(dict)
    for arm in ("A6", "A6-syn", "RR"):
        ar = [r for r in rows if r["arm"] == arm]
        if not ar:
            continue
        acc[arm]["all"] = round(mean(r["correct"] for r in ar), 4)
        for c in CLASSES:
            acc[arm][c] = round(mean(r["correct"] for r in ar if r["cls"] == c), 4)
        acc[arm]["failed_calls"] = sum(not r["ok"] for r in ar)
        acc[arm]["max_tokens_stops"] = sum(r.get("stop") == "max_tokens" for r in ar)
        acc[arm]["mentions_wrong"] = sum(bool(r.get("mentions_wrong")) for r in ar)
        if all("correct_lenient" in r for r in ar):
            acc[arm]["all_lenient"] = round(mean(r["correct_lenient"] for r in ar), 4)
    rep["accuracy_DEV"] = acc
    by = defaultdict(dict)
    for r in rows:
        by[(r["seed"], r["task_id"])][r["arm"]] = r["correct"]
    diffs = {"A6-RR": defaultdict(list), "A6-A6syn": defaultdict(list)}
    for (seed, _), v in by.items():
        if {"A6", "RR", "A6-syn"} <= v.keys():
            diffs["A6-RR"][seed].append(v["A6"] - v["RR"]); diffs["A6-A6syn"][seed].append(v["A6"] - v["A6-syn"])
    per = {k: [round(mean(x), 4) for _, x in sorted(d.items())] for k, d in diffs.items()}
    rep["per_stream_mean_diff"] = per
    if all(len(v) >= 2 for v in per.values()):
        s = sd_hat(per); rep["sd_hat"] = round(s, 4); rep["stream_rule"] = n_streams(s)
    from .analysis import analyze
    rep["analysis_DEV_not_results"] = analyze(rows)
    rep["api"] = api_totals(base / "api-events.jsonl")
    rep["synth_calls"] = sum(1 for st in stats.values() for c in st["A6_calls"] if c.get("role") == "synth")
    rep["leak_units"] = {s: len(st["leak_units"]) for s, st in stats.items()}
    rep["reranker_seconds"] = {s: round(st["reranker_seconds"] or 0, 1) for s, st in stats.items()}
    from .lifecycle import stream_cost, header_gold_coverage
    rep["stream_cost"] = {s: stream_cost(st) for s, st in stats.items()}
    try:
        rep["header_gold_coverage_desc"] = header_gold_coverage(rows, base)
    except Exception as e:                                       # descriptive; never blocks the report
        rep["header_gold_coverage_desc"] = {"error": repr(e)}
    (base / "DEV-REPORT.json").write_text(json.dumps(rep, indent=1, default=str))
    print(json.dumps(rep, indent=1, default=str))


if __name__ == "__main__":
    main()
