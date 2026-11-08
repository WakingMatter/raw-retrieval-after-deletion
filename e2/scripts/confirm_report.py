"""CONFIRM scoring (post-freeze; deliberately OUTSIDE the hashed e2/ package so it cannot alter the frozen code hash).
Uses only the frozen functions: analysis.analyze(rows, strict=True) for the outcome; descriptive extras from
dev_report.api_totals and lifecycle. Writes runs/CONFIRM/CONFIRM-REPORT.json.  Usage: python3 scripts/confirm_report.py"""
import json, sys
from collections import Counter
from pathlib import Path
from statistics import mean, median
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from e2.paths import RUNS
from e2.analysis import analyze, ALL_CLASSES
from e2.dev_report import api_totals
from e2.lifecycle import stream_cost, header_gold_coverage
from e2.make_freeze import verify_frozen

E2 = Path(__file__).resolve().parents[1]
fr = json.loads((E2 / "E2-FREEZE.json").read_text())
base = RUNS / "CONFIRM"
want = fr["seeds"]["confirmatory_run"]
rows, stats, missing = [], {}, []
for s in want:
    d = base / f"stream-{s}"
    if not (d / "answers.jsonl").exists():
        missing.append(s); continue
    rows += [dict(json.loads(l), seed=s) for l in (d / "answers.jsonl").read_text().splitlines() if l.strip()]
    stats[s] = json.loads((d / "stats.json").read_text())
rep = {"label": "CONFIRMATORY", "freeze_verify": verify_frozen(), "prereg_sha256": fr["prereg_sha256"],
       "streams_expected": len(want), "streams_done": len(stats), "missing": missing, "n_rows": len(rows)}
if missing:
    print(json.dumps(rep, indent=1)); raise SystemExit("not all confirmatory streams are complete; not scoring")
rep["analysis"] = analyze(rows, ALL_CLASSES, strict=True)
from outcome_text import describe            # display-only direction readout (sign check 24 Oct 17:0x IST)
rep["outcome_plain"] = {k: describe(rep["analysis"][k]) for k in ("primary", "S1_informative", "S2_lenient")}
a6 = [r for r in rows if r["arm"] == "A6"]
served = lambda r: len((r.get("trace") or {}).get("served_summaries") or [])
rep["served_rate"] = {c: mean(served(r) > 0 for r in a6 if r["cls"] == c) for c in ALL_CLASSES}
rep["summaries_served_per_probe"] = dict(sorted(Counter(served(r) for r in a6).items()))
rep["node_status"] = dict(Counter(n["status"] for r in a6 for n in (r.get("trace") or {}).get("nodes", [])))
summ = [x for st in stats.values() for x in st["summaries"].values()]
rep["final_summaries"] = {"n": len(summ), "truncated": sum(bool(x["truncated"]) for x in summ),
                          "cost_raw_median": median([x["cost_raw"] for x in summ]) if summ else None,
                          "cost_served_median": median([x["cost_served"] for x in summ]) if summ else None}
rep["failures"] = {arm: {"failed_calls": sum(not r["ok"] for r in rows if r["arm"] == arm),
                         "max_tokens_stops": sum(r.get("stop") == "max_tokens" for r in rows if r["arm"] == arm),
                         "abstained": sum(bool(r.get("abstained")) for r in rows if r["arm"] == arm),
                         "mentions_wrong": sum(bool(r.get("mentions_wrong")) for r in rows if r["arm"] == arm)}
                   for arm in ("A6", "A6-syn", "RR")}
rep["leak_units"] = {s: len(st["leak_units"]) for s, st in stats.items()}
cap = fr["cost_ceiling"]["per_stream_max"]
cost = {s: stream_cost(st) for s, st in stats.items()}
rep["stream_cost"] = cost
rep["cost_max_observed"] = {k: max(c[k] for c in cost.values()) for k in cap}
rep["cost_overruns"] = {s: [k for k in cap if c[k] > cap[k]] for s, c in cost.items() if any(c[k] > cap[k] for k in cap)}
rep["cost_bounded"] = not rep["cost_overruns"]
try:
    rep["header_gold_coverage_desc"] = header_gold_coverage(rows, base)
except Exception as e:
    rep["header_gold_coverage_desc"] = {"error": repr(e)}
rep["api"] = api_totals(base / "api-events.jsonl")
(base / "CONFIRM-REPORT.json").write_text(json.dumps(rep, indent=1, default=str))
print(json.dumps({k: rep[k] for k in ("freeze_verify", "streams_done", "n_rows", "cost_bounded")}, default=str))
print(json.dumps(rep["analysis"]["primary"], indent=1, default=str))
