"""E2 cost estimate = exact call counts from the offline dry run (runs/DRY-ALL, fake answerer, real harness) x
per-call tokens measured in the <=20-call API smoke (runs/SMOKE). Everything token-valued is an ESTIMATE.
Plan sizes (Aditya, 24 Oct): 5-hour window ~125M tokens; week = 10 windows ~1.25B; month ~4 weeks ~5B."""
from __future__ import annotations
import collections, json, statistics as st
from .paths import RUNS, E2
from .minimax_api import Quota

WINDOW, WEEK, MONTH = 125e6, 1.25e9, 5.0e9
RESERVE = 0.20
N_QUAL = 120          # stage-0 qualification answers (prereg §4)
N_DEV_STREAMS = 4     # DEV pass for K-delivery / variance (same harness, DEV seeds)


def tot_in(u):
    return int(u.get("input_tokens") or 0) + int(u.get("cache_read_input_tokens") or 0) + int(u.get("cache_creation_input_tokens") or 0)


def main(dry_tag="DRY-ALL-"):
    sm = json.loads((RUNS / "SMOKE" / "smoke.json").read_text())
    ev = sm["events"]
    rows = sm["rows"]
    # chars->tokens ratio from smoke answers whose prompt length is known (cache keys link rows to events)
    a_ev = [e for e in ev if e["role"] == "answer"]
    s_ev = [e for e in ev if e["role"] == "synth"]
    chars = sum(r["prompt_chars"] for r in rows)
    toks = sum(tot_in(e["usage"]) for e in a_ev)
    ratio = toks / chars
    a_out = [e["usage"]["output_tokens"] for e in a_ev]
    s_out = [e["usage"]["output_tokens"] for e in s_ev]
    s_in = [tot_in(e["usage"]) for e in s_ev]
    lat_a = [e["latency_s"] for e in a_ev]; lat_s = [e["latency_s"] for e in s_ev]
    tags = sorted(p.name for p in RUNS.glob(dry_tag + "*") if (p / "summary.json").exists())
    calls, seeds, walls, var = [], [], [], collections.Counter()
    for tg in tags:
        d = json.loads((RUNS / tg / "summary.json").read_text())
        calls += d["dry_calls"]; seeds += d["seeds"]; walls.append(d["wall_s"])
        for sd in d["seeds"]:
            for l in open(RUNS / tg / f"stream-{sd}" / "answers.jsonl"):
                var[json.loads(l)["arm"]] += 1
    dry = {"seeds": seeds, "wall_s": max(walls), "tags": tags}
    n_streams = len(seeds)
    by = collections.defaultdict(list)
    for c in calls:
        by[(c["role"], c["ctx"].get("phase"), c["ctx"].get("arm"))].append(c["prompt_chars"])
    syn_ps = []
    for tg in tags:
        for sd in json.loads((RUNS / tg / "summary.json").read_text())["seeds"]:
            stt = json.loads((RUNS / tg / f"stream-{sd}" / "stats.json").read_text())
            syn_ps.append(sum(1 for c in stt["A6_calls"] if c["role"] == "synth"))
    table = []

    def line(name, n, in_chars_mean, out_mean, out_hi, in_override=None):
        tin = in_override if in_override is not None else in_chars_mean * ratio
        table.append({"item": name, "calls": n, "in_per_call": round(tin), "out_per_call": round(out_mean),
                      "in_total": round(n * tin), "out_total": round(n * out_mean), "out_total_hi": round(n * out_hi)})
    ans_mean = st.mean(a_out); ans_hi = max(a_out)
    syn_mean = st.mean(s_out); syn_hi = max(s_out)
    probe_chars = st.mean(by[("answer", "probe", "A6")] + by[("answer", "probe", "RR")])
    for arm in ("A6", "A6-syn", "RR"):
        line(f"terminal answers {arm}", var[arm], probe_chars, ans_mean, ans_hi)
    line("warm answers (A6 state, write-back)", len(by[("answer", "warm", "A6")]), st.mean(by[("answer", "warm", "A6")]), ans_mean, ans_hi)
    syn_chars = by[("synth", "warm", "A6")] + by[("synth", "probe", "A6")]
    line("synth (summary recompute; warm+probe)", len(syn_chars), st.mean(syn_chars), syn_mean, syn_hi)
    per_stream_calls = len(calls) / n_streams
    line(f"DEV pass ({N_DEV_STREAMS} DEV streams, same harness)", round(per_stream_calls * N_DEV_STREAMS),
         st.mean(c["prompt_chars"] for c in calls), (ans_mean * 130 + syn_mean * len(syn_chars) / n_streams) / (130 + len(syn_chars) / n_streams), max(ans_hi, syn_hi))
    line("qualification (stage 0)", N_QUAL, probe_chars, ans_mean, ans_hi)
    base = {k: sum(r[k] for r in table) for k in ("calls", "in_total", "out_total", "out_total_hi")}
    tot = base["in_total"] + base["out_total"]
    tot_hi = base["in_total"] + base["out_total_hi"]
    q = Quota().read()
    res = {
        "measured": {"smoke_live_calls": sm["live_calls"], "answer_calls": len(a_ev), "synth_calls": len(s_ev),
                     "input_tokens_per_prompt_char": round(ratio, 4),
                     "answer_in_median": st.median(tot_in(e["usage"]) for e in a_ev), "answer_out_mean": round(ans_mean, 1),
                     "answer_out_median": st.median(a_out), "answer_out_max": ans_hi,
                     "synth_in_median": st.median(s_in), "synth_out_mean": round(syn_mean, 1), "synth_out_max": syn_hi,
                     "latency_answer_median_s": st.median(lat_a), "latency_synth_median_s": st.median(lat_s)},
        "dry": {"tags": dry["tags"], "streams": n_streams, "calls": len(calls), "calls_per_stream": per_stream_calls,
                "wall_s_max_process": dry["wall_s"],
                "synth_per_stream": {"min": min(syn_ps), "median": st.median(syn_ps), "max": max(syn_ps)}, "arm_rows": dict(var),
                "by_role_phase_arm": {"|".join(map(str, k)): len(v) for k, v in by.items()}},
        "table": table, "base": base,
        "total_tokens_est": tot, "total_tokens_est_hi": tot_hi,
        "with_reserve": {"calls": round(base["calls"] * (1 + RESERVE)), "tokens": round(tot * (1 + RESERVE)),
                         "tokens_hi": round(tot_hi * (1 + RESERVE))},
        "pct": {k: {"window": 100 * v / WINDOW, "week": 100 * v / WEEK, "month": 100 * v / MONTH}
                for k, v in (("base", tot), ("base_hi_output", tot_hi), ("with_reserve_hi", tot_hi * (1 + RESERVE)))},
        "quota_now": q,
    }
    (E2 / "runs" / "COST.json").write_text(json.dumps(res, indent=1, default=str))
    print(json.dumps(res, indent=1, default=str))


if __name__ == "__main__":
    main()
