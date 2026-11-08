"""Score RR-2hop paired against E2 CONFIRM A6 / RR / A6-syn and the E3 RR-agg exploration on the same 320 DERIVED
tasks. Applies the PREDICTION.md rule. Writes RESULTS.json."""
from __future__ import annotations
import glob, json, math, re, statistics as S
from collections import defaultdict
from scipy import stats
from common import HERE, RUN, leaves
from e3.paths import E2

rows = defaultdict(dict); tasks = {}
for f in sorted(glob.glob(str(RUN / "stream-*/answers.jsonl"))):
    s = int(f.split("stream-")[1].split("/")[0])
    tasks.update({t["task_id"]: t for t in json.load(open(E2 / f"data/tasks-{s}.json"))["tasks"]})
    for l in open(f):
        r = json.loads(l)
        if r["cls"] == "DERIVED":
            rows[r["task_id"]][r["arm"]] = r
for name, fn in (("RR-agg", HERE.parent / "explore-rragg/rragg_answers.jsonl"), ("RR-2hop", HERE / "rr2hop_answers.jsonl")):
    for l in open(fn):
        r = json.loads(l); r.update(r["score"]); rows[r["task_id"]][name] = r
ARMS = ["A6", "RR", "RR-2hop", "RR-agg", "A6-syn"]
assert len(rows) == 320 and all(set(ARMS) <= set(v) for v in rows.values()), "missing rows"
L = leaves()


def ci(per_stream, level):
    v = list(per_stream.values()); n = len(v); m = S.mean(v); sd = S.stdev(v)
    h = stats.t.ppf(1 - (1 - level) / 2, n - 1) * sd / math.sqrt(n)
    return {"mean": round(m, 4), "lo": round(m - h, 4), "hi": round(m + h, 4), "level": level, "n_streams": n, "sd": round(sd, 4)}


def contrast(tids, a, b, level=0.95):
    ps = defaultdict(list)
    for tid in tids:
        ps[tasks[tid]["seed"]].append(int(rows[tid][a]["correct"]) - int(rows[tid][b]["correct"]))
    return ci({s: S.mean(v) for s, v in ps.items()}, level)


def norm(x):
    return re.sub(r"[^a-z ]", "", (x or "").lower()).strip()


subsets = {"all": list(rows)}
for tid in rows:
    a = L[tid]["_t"]
    t = "touched" if tasks[tid]["deletion_touched"] else "untouched"
    subsets.setdefault(t, []).append(tid)
    subsets.setdefault(("hdr-gold-" if a["hdr_gold"] else "hdr-nogold-") + t, []).append(tid)
    subsets.setdefault("infstmt-gold-yes" if a["surviving_inference_states_gold"] else "infstmt-gold-no", []).append(tid)
out = {}
for name, tids in subsets.items():
    d = {"n": len(tids)}
    for a in ARMS:
        d[a] = round(S.mean(int(rows[t][a]["correct"]) for t in tids), 3)
        d[a + "_lenient"] = round(S.mean(int(rows[t][a]["correct_lenient"]) for t in tids), 3)
    for a, b in (("A6", "RR-2hop"), ("A6", "RR"), ("RR-2hop", "RR"), ("RR-2hop", "RR-agg")):
        d[f"{a}-{b}"] = contrast(tids, a, b) if len({tasks[x]["seed"] for x in tids}) > 2 else None
    out[name] = d
for a, b in (("A6", "RR-2hop"), ("A6", "RR")):
    out["all"][f"{a}-{b}_97.5"] = contrast(subsets["all"], a, b, 0.975)

h = [rows[t]["RR-2hop"] for t in rows]
ent_ok = [norm(r["entity"]) == norm(L[r["task_id"]]["ref"]["value"]) for r in h]
attr_served = [bool(set(L[r["task_id"]]["attr"]["chunks_surviving"]) & set(r["served"])) for r in h]
ref_served = [bool(set(L[r["task_id"]]["ref"]["chunks_surviving"]) & set(r["served"])) for r in h]
rr_attr = [bool(set(L[t]["attr"]["chunks_surviving"]) & set(rows[t]["RR"]["served"])) for t in rows]
acc = lambda m: round(S.mean(int(rows[r["task_id"]]["RR-2hop"]["correct"]) for r, k in zip(h, ent_ok) if k == m), 3) if any(k == m for k in ent_ok) else None
out["rr2hop_meta"] = {
    "bridge_ok": sum(bool(r["bridge_ok"]) for r in h), "entity_nonnull": sum(r["entity"] is not None for r in h),
    "entity_matches_gold_ref_person": sum(ent_ok), "acc_when_entity_correct": acc(True), "acc_when_entity_wrong_or_none": acc(False),
    "attr_leaf_served": sum(attr_served), "ref_leaf_served": sum(ref_served), "both_leaves_served": sum(a and b for a, b in zip(attr_served, ref_served)),
    "RR_attr_leaf_served": sum(rr_attr), "answer_ok": sum(bool(r["ok"]) for r in h),
    "abstained": sum(bool(r.get("abstained")) for r in h), "mentions_wrong": sum(bool(r.get("mentions_wrong")) for r in h),
    "raw_tokens_est_max": max(r["raw_tokens_est"] for r in h),
    "tokens": {k: sum(int((r.get(u) or {}).get(k) or 0) for r in h for u in ("bridge_usage", "answer_usage"))
               for k in ("input_tokens", "output_tokens", "cache_read_input_tokens")},
    "tokens_bridge": {k: sum(int((r.get("bridge_usage") or {}).get(k) or 0) for r in h) for k in ("input_tokens", "output_tokens")},
    "memo_hits": sum(bool(r["bridge_memo"]) + bool(r["answer_memo"]) for r in h),
    "retried_calls": sum((r["bridge_attempts"] > 1) + (r["answer_attempts"] > 1) for r in h),
}
gap = out["all"]["A6-RR-2hop"]["mean"]
out["rule"] = {"A6_minus_RR2hop": gap, "outcome":
               "SHELVE E3: RR-2hop within 3pp of A6 or above -> DERIVED lead is a single-pass retrieval artifact" if gap <= 0.03
               else "FREEZE E3 with RR-2hop co-primary: A6 leads by >= 6pp" if gap >= 0.06
               else "IN BETWEEN (3-6pp): recommend"}
json.dump(out, open(HERE / "RESULTS.json", "w"), indent=1)
print(json.dumps({k: out[k] for k in ("rule", "rr2hop_meta")}, indent=1))
for k in ("all", "touched", "untouched", "hdr-gold-touched", "infstmt-gold-no", "infstmt-gold-yes"):
    d = out[k]; print(k, d["n"], {a: d[a] for a in ARMS}, "A6-2hop", d["A6-RR-2hop"], "2hop-RR", d["RR-2hop-RR"])
