"""Aggregate runs/<tag>/stream-*.json into call counts (global sha dedup, ordered tier 1 -> 2 -> 3) and token /
wall-clock ESTIMATES from measured E2/E3 CONFIRM stats. Every token and second here is an estimate."""
import glob, json, statistics as st, sys
from collections import defaultdict
from .paths import RUNS

# Measured E2 CONFIRM (synth n=1147, answer n=4160) and E3 (bridge n=376) means; chars->tokens 0.354 measured on
# 3,840 E2 answer prompts. Used only to turn dry-run counts into estimates.
SYN_IN, SYN_OUT, SYN_LAT = 2923, 2607, 21.8
ANS_OUT, ANS_LAT, ANS_LAT_P90 = 99, 2.47, 4.31
BR_OUT, BR_LAT = 117, 2.65
C2T = 0.354
CONC = 8          # planned max_parallel API calls (429s seen at ~16)


def main(tag="DRY"):
    files = sorted(glob.glob(str(RUNS / tag / "stream-*.json")))
    seen = set(); g = defaultdict(lambda: {"n": 0, "uniq": 0, "in_chars": 0})
    tasks, walls, rer = [], [], []
    for f in files:
        r = json.load(open(f)); walls.append(r["wall_s"]); rer.append(r["rerank_s_probe_hop1"])
        tasks += r["tasks"]
        def key(x):
            c = x["ctx"]; t = c.get("tier")
            arm = c.get("variant") or c.get("arm")
            ph = c.get("phase") or "probe"
            return (0 if ph == "warm" else (t or 1), x["role"], arm, ph)
        for x in sorted(r["calls"], key=lambda x: key(x)[0]):
            k = key(x); g[k]["n"] += 1
            if x["h"] not in seen:
                seen.add(x["h"]); g[k]["uniq"] += 1; g[k]["in_chars"] += x["chars"]
    out = {"streams": len(files), "groups": [], "tiers": {}}
    for k in sorted(g, key=str):
        v = g[k]; role = k[1]
        if role == "synth":
            tin, tout, lat = v["uniq"] * SYN_IN, v["uniq"] * SYN_OUT, v["uniq"] * SYN_LAT
        elif role == "bridge":
            tin, tout, lat = v["in_chars"] * C2T, v["uniq"] * BR_OUT, v["uniq"] * BR_LAT
        else:
            tin, tout, lat = v["in_chars"] * C2T, v["uniq"] * ANS_OUT, v["uniq"] * ANS_LAT
        row = {"tier": k[0], "role": role, "arm": k[2], "phase": k[3], "calls_nominal": v["n"],
               "calls_unique": v["uniq"], "est_in_tok": round(tin), "est_out_tok": round(tout), "est_lat_s": round(lat)}
        out["groups"].append(row)
        # RR-2hop answer upper bound: one new answer per unique bridge (fake bridge always says NONE)
        if role == "bridge":
            ub = {"tier": k[0], "role": "answer(UB)", "arm": "RR-2hop", "phase": "probe", "calls_nominal": v["n"],
                  "calls_unique": v["uniq"], "est_in_tok": round(tin), "est_out_tok": v["uniq"] * ANS_OUT,
                  "est_lat_s": round(v["uniq"] * ANS_LAT)}
            out["groups"].append(ub)
    for row in out["groups"]:
        t = out["tiers"].setdefault(row["tier"], {"calls_unique": 0, "est_in_tok": 0, "est_out_tok": 0, "est_lat_s": 0})
        for c in t: t[c] += row[c]
    for t in out["tiers"].values():
        t["est_api_wall_h_at_conc8"] = round(t["est_lat_s"] / CONC / 3600, 2)
    by = defaultdict(list)
    for x in tasks: by[x["cls"]].append(x)
    q = lambda xs, p: sorted(xs)[min(len(xs) - 1, int(p * len(xs)))]
    out["support_est"] = {c: {"n": len(v), "median": round(st.median([x["support_est"] for x in v]), 1),
                              "max": round(max(x["support_est"] for x in v), 1),
                              **{f"over_B{B}": sum(x["support_est"] > B for x in v) for B in (500, 1000, 2000)}}
                          for c, v in sorted(by.items())}
    rp = [x["rr_pool"] for x in tasks]; ap = [x["a6_pool"] for x in tasks if x["a6_pool"]]
    out["rr_top50_pool_est"] = {"median": round(st.median(rp)), "q10": round(q(rp, .1)), "q90": round(q(rp, .9)),
                                **{f"frac_lt_B{B}": round(sum(p < B for p in rp) / len(rp), 3) for B in (2000, 4000, 8000)}}
    out["a6_raw_pool_est_B2000"] = {"median": round(st.median(ap)), "q10": round(q(ap, .1)), "max": round(max(ap)),
                                    "frac_lt_8000": round(sum(p < 8000 for p in ap) / len(ap), 3)}
    out["local"] = {"stream_wall_s_median": st.median(walls), "stream_wall_s_max": max(walls),
                    "rerank_hop1_s_median": st.median(rer), "n_tasks": len(tasks)}
    (RUNS / tag / "SUMMARY.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main(*sys.argv[1:])
