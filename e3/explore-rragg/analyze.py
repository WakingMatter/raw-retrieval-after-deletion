"""Score RR-agg paired against E2 CONFIRM A6 / RR / A6-syn on the same 320 DERIVED tasks. Writes RESULTS.json."""
from __future__ import annotations
import glob, json, re, sys, math, statistics as S
from collections import defaultdict
from pathlib import Path
HERE = Path(__file__).resolve().parent
E2D = HERE.parents[1] / "e2"
sys.path.insert(0, str(E2D))
from e2 import paths  # noqa
from e2.lifecycle import _final_summaries
from scipy import stats

RUN = E2D / "runs" / "CONFIRM"
rows = defaultdict(dict); tasks = {}; summ = {}
for f in sorted(glob.glob(str(RUN / "stream-*/answers.jsonl"))):
    s = int(f.split("stream-")[1].split("/")[0])
    tasks.update({t["task_id"]: t for t in json.load(open(E2D / f"data/tasks-{s}.json"))["tasks"]})
    summ[s] = _final_summaries(RUN / f"stream-{s}/work")
    for l in open(f):
        r = json.loads(l)
        if r["cls"] == "DERIVED":
            rows[r["task_id"]][r["arm"]] = r
for l in open(HERE / "rragg_answers.jsonl"):
    r = json.loads(l); r.update(r["score"]); rows[r["task_id"]]["RR-agg"] = r
assert len(rows) == 320 and all(len(v) == 4 for v in rows.values()), "missing rows"


def gold_in(text, t):
    return bool(text) and any(re.search(x, text, re.I) for x in t["truth_any"])


def hdr_gold(tid):
    t = tasks[tid]; s = t["seed"]; a6 = rows[tid]["A6"]
    return any(gold_in(summ[s].get(x.split(":", 1)[-1], ""), t) for x in a6["trace"]["served_summaries"])


def ci(per_stream, level=0.95):
    v = list(per_stream.values()); n = len(v); m = S.mean(v); sd = S.stdev(v) if n > 1 else float("nan")
    h = stats.t.ppf(1 - (1 - level) / 2, n - 1) * sd / math.sqrt(n) if n > 1 else float("nan")
    return {"mean": round(m, 4), "lo": round(m - h, 4), "hi": round(m + h, 4), "n_streams": n, "sd": round(sd, 4)}


def contrast(tids, a, b, key="correct"):
    ps = defaultdict(list)
    for tid in tids:
        ps[tasks[tid]["seed"]].append(int(rows[tid][a][key]) - int(rows[tid][b][key]))
    return ci({s: S.mean(v) for s, v in ps.items()})


ARMS = ["A6", "RR", "RR-agg", "A6-syn"]
out = {}
subsets = {"all": list(rows)}
for tid in rows:
    k = ("hdr-gold" if hdr_gold(tid) else "hdr-nogold") + ("-touched" if tasks[tid]["deletion_touched"] else "-untouched")
    subsets.setdefault(k, []).append(tid)
    subsets.setdefault("touched" if tasks[tid]["deletion_touched"] else "untouched", []).append(tid)
for name, tids in subsets.items():
    d = {"n": len(tids)}
    for a in ARMS:
        d[a] = round(S.mean(int(rows[t][a]["correct"]) for t in tids), 3)
        d[a + "_lenient"] = round(S.mean(int(rows[t][a]["correct_lenient"]) for t in tids), 3)
    for a, b in (("A6", "RR-agg"), ("RR-agg", "RR"), ("A6", "RR")):
        d[f"{a}-{b}"] = contrast(tids, a, b)
    out[name] = d
agg = [rows[t]["RR-agg"] for t in rows]
out["rragg_meta"] = {
    "note_ok": sum(r["note_ok"] for r in agg), "answer_ok": sum(r["ok"] for r in agg),
    "note_truncated": sum(bool(r["note_truncated"]) for r in agg),
    "note_contains_gold": sum(gold_in(r["note"], tasks[r["task_id"]]) for r in agg),
    "abstained": sum(bool(r.get("abstained")) for r in agg), "mentions_wrong": sum(bool(r.get("mentions_wrong")) for r in agg),
    "header_tokens_est_mean": round(S.mean(r["header_tokens_est"] for r in agg), 1),
    "tokens": {k: sum(int((r.get(u) or {}).get(k) or 0) for r in agg for u in ("note_usage", "answer_usage"))
               for k in ("input_tokens", "output_tokens", "cache_read_input_tokens")},
    "tokens_note": {k: sum(int((r.get("note_usage") or {}).get(k) or 0) for r in agg) for k in ("input_tokens", "output_tokens")},
    "memo_hits": sum(bool(r["note_memo"]) + bool(r["answer_memo"]) for r in agg),
}
gap = out["all"]["A6-RR-agg"]["mean"]
out["decision"] = ("SHELVE E3: RR-agg within 3pp of A6 or above (aggregation timing explains the DERIVED lead)" if gap <= 0.03
                   else "FREEZE E3: RR-agg >= 6pp below A6" if gap >= 0.06 else "IN BETWEEN: report and recommend")
json.dump(out, open(HERE / "RESULTS.json", "w"), indent=1)
print(json.dumps(out, indent=1))
