"""E4 confirmatory analysis (frozen; PREREG-E4.md, DEFAULTS D05-D07, D10-D12).

    python3 -m e4.analyze_e4 --tag CONFIRM [--seeds ...]   -> runs/<tag>/ANALYSIS.json and ANALYSIS.md

Unit of analysis: the stream. Per (stream, arm, cell) mean strict accuracy over the stream's 40 tasks; paired differences
across streams; one-sided paired t (df = n-1). Claim: intersection-union over required comparators (cell p = max),
Holm within F1 and within F0 at alpha 0.025 each. Kill: every F1+F0 cell has one-sided upper bound of A6-RR at
level 1-0.05/7 below delta = 0.05. Everything else is exploratory. A failed call is a wrong answer (never dropped)."""
from __future__ import annotations
import argparse, json, math
from collections import defaultdict
import numpy as np
from scipy import stats
from .paths import RUNS, DATA

ALPHA_FAM, DELTA, KILL_LEVEL = 0.025, 0.05, 0.05 / 7
F1 = [(B, f"B{B}|1/5|{min(200.0, B * 0.2):g}") for B in (500, 1000, 2000, 4000, 8000)]
F0 = [(125, "B125|1/5|25"), (125, "B125|2/5|50")]
ARMS_BASE = ["RR", "RR-2hop", "A6-syn"]


def required(B):
    return ARMS_BASE + (["RR-K"] if B in (4000, 8000) else [])


def merge_passes(parts):
    """A stream's main phase may run in passes (T1,F0,T5 then T2,T3): rows concatenate, CPU/wall accounts add up."""
    m = dict(parts[0]); m["rows"] = [x for p in parts for x in p["rows"]]
    m["passes"] = [p.get("tiers") for p in parts]
    m["summary_misses"] = [x for p in parts for x in p.get("summary_misses", [])]
    m["rerank_total_s"] = sum(p.get("rerank_total_s", 0) for p in parts)
    rk = {}
    for p in parts:
        for k, v in (p.get("rerank") or {}).items():
            rk[k] = [a + b for a, b in zip(rk.get(k, [0.0, 0.0]), v)]
    m["rerank"] = rk
    wall = {}
    for p in parts:
        for k, v in (p.get("wall") or {}).items():
            wall[k] = round(wall.get(k, 0) + v, 1)
    m["wall"] = wall
    return m


def load(tag, seeds):
    out = {}
    for s in seeds:
        f = RUNS / tag / f"main-{s}.json"
        if f.exists():
            parts = [json.loads(f.read_text())] + [json.loads(g.read_text())
                                                   for g in sorted((RUNS / tag).glob(f"main-*-{s}.json"))]
            out[("main", s)] = merge_passes(parts)
        f = RUNS / tag / f"t4-{s}.json"
        if f.exists():
            out[("t4", s)] = json.loads(f.read_text())
    return out


def inventory(R, seeds, phase="main"):
    """Every (task, arm, cell) row must exist exactly once per stream, and every stream must have the same set."""
    sets = {}
    for s in seeds:
        r = R.get((phase, s))
        assert r is not None, f"missing {phase}-{s}.json"
        keys = [(x["task_id"].split(":", 1)[1], x["arm"], x["cell"]) for x in r["rows"]]
        assert len(keys) == len(set(keys)), f"duplicate rows in {phase}-{s}"
        sets[s] = {(k[1], k[2]) for k in keys}
        assert len(keys) == 40 * len(sets[s]), f"{phase}-{s}: {len(keys)} rows for {len(sets[s])} (arm, cell) pairs"
    first = next(iter(sets.values()))
    assert all(v == first for v in sets.values()), "streams differ in (arm, cell) inventory"
    return sorted(first)


def means(R, seeds, phase="main"):
    m = defaultdict(dict)                                  # (arm, cell) -> seed -> mean
    for s in seeds:
        acc = defaultdict(list)
        for x in R[(phase, s)]["rows"]:
            acc[(x["arm"], x["cell"])].append(1.0 if x["correct"] else 0.0)
        for k, v in acc.items():
            m[k][s] = sum(v) / len(v)
    return m


def paired(m, a, b, seeds):
    d = np.array([m[a][s] - m[b][s] for s in seeds])
    n = len(d); mu = float(d.mean()); se = float(d.std(ddof=1) / math.sqrt(n)) if n > 1 else float("nan")
    if se == 0:
        p1 = 0.0 if mu > 0 else 1.0
    else:
        p1 = float(stats.t.sf(mu / se, n - 1))
    tq = stats.t.ppf(0.975, n - 1)
    return {"a": a, "b": b, "diff": mu, "se": se, "p_one_sided": p1, "ci95": [mu - tq * se, mu + tq * se],
            "mean_a": float(np.mean([m[a][s] for s in seeds])), "mean_b": float(np.mean([m[b][s] for s in seeds])),
            "d": d.tolist()}


def upper(d, level):
    d = np.asarray(d); n = len(d); se = d.std(ddof=1) / math.sqrt(n)
    return float(d.mean() + stats.t.ppf(1 - level, n - 1) * se)


def boot_ci(d, B=10000, seed=0):
    rng = np.random.default_rng(seed); d = np.asarray(d)
    bs = d[rng.integers(0, len(d), (B, len(d)))].mean(1)
    return [float(np.quantile(bs, 0.025)), float(np.quantile(bs, 0.975))]


def holm(ps, alpha):
    order = sorted(range(len(ps)), key=lambda i: ps[i]); adj = [0.0] * len(ps); run = 0.0; rej = [False] * len(ps)
    k = len(ps); stop = False
    for r, i in enumerate(order):
        run = max(run, min(1.0, (k - r) * ps[i])); adj[i] = run
        if not stop and ps[i] <= alpha / (k - r):
            rej[i] = True
        else:
            stop = True
    return adj, rej


def family(m, seeds, cells, alpha):
    res = []
    for B, cell in cells:
        comps = {c: paired(m, ("A6", cell), (c, f"B{B}"), seeds) for c in required(B)}
        p_iut = max(c["p_one_sided"] for c in comps.values())
        p_pkg = max(c["p_one_sided"] for k, c in comps.items() if k != "A6-syn")
        for c in comps.values():
            c["lower_bonf"] = c["diff"] - stats.t.ppf(1 - alpha / len(cells), len(seeds) - 1) * c["se"]
        res.append({"B": B, "cell": cell, "comparisons": comps, "p_iut": p_iut, "p_package": p_pkg,
                    "kill_upper_vs_RR": upper(comps["RR"]["d"], KILL_LEVEL),
                    "boot_ci_vs_RR": boot_ci(comps["RR"]["d"])})
    adj, rej = holm([r["p_iut"] for r in res], alpha)
    adjp, rejp = holm([r["p_package"] for r in res], alpha)
    for r, a, j, ap_, jp in zip(res, adj, rej, adjp, rejp):
        r.update(p_holm=a, claim=j, p_package_holm=ap_, package_descriptive=jp)
    return res


def tokens(tag):
    """Metered (live calls in api-events) per ctx arm and role; synth and warm are attributed to A6."""
    met = defaultdict(lambda: {"calls": 0, "in": 0, "out": 0, "latency_s": 0.0})
    for f in sorted((RUNS / tag).glob("api-events-*.jsonl")):
        for line in f.open():
            e = json.loads(line)
            if e.get("kind") != "call":
                continue
            ctx = e.get("ctx") or {}
            arm = ctx.get("e4_arm") or ctx.get("arm") or "A6"
            role = e.get("role")
            key = f"{arm}:{'warm' if ctx.get('cell') == 'warm' else role}"
            u = e.get("usage") or {}
            met[key]["calls"] += 1; met[key]["in"] += u.get("input_tokens", 0) or 0
            met[key]["out"] += u.get("output_tokens", 0) or 0; met[key]["latency_s"] += e.get("latency_s") or 0
    return dict(met)


def logical(R):
    lg = defaultdict(lambda: {"rows": 0, "in": 0, "out": 0, "memo_hits": 0, "elapsed_s": 0.0, "bridge_in": 0,
                              "bridge_out": 0, "bridge_s": 0.0})
    for (ph, s), r in R.items():
        for x in r["rows"]:
            L = lg[x["arm"]]; u = x.get("usage") or {}
            L["rows"] += 1; L["in"] += u.get("input_tokens", 0) or 0; L["out"] += u.get("output_tokens", 0) or 0
            L["memo_hits"] += 1 if x.get("memo_hit") else 0; L["elapsed_s"] += x.get("elapsed_s") or 0
            bu = x.get("bridge_usage") or {}
            L["bridge_in"] += bu.get("input_tokens", 0) or 0; L["bridge_out"] += bu.get("output_tokens", 0) or 0
            L["bridge_s"] += x.get("bridge_s") or 0
    return dict(lg)


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("--tag", default="CONFIRM"); ap.add_argument("--seeds", default="")
    a = ap.parse_args(argv)
    if a.seeds:
        seeds = [int(x) for x in a.seeds.split(",")]
    else:
        from .make_freeze import frozen_streams
        seeds = frozen_streams()
    R = load(a.tag, seeds)
    inv = inventory(R, seeds, "main")
    m = means(R, seeds, "main")
    out = {"seeds": seeds, "n": len(seeds), "inventory_main": [list(k) for k in inv]}
    out["F1"] = family(m, seeds, F1, ALPHA_FAM)
    out["F0"] = family(m, seeds, F0, ALPHA_FAM)
    claim = any(r["claim"] for r in out["F1"] + out["F0"])
    kill = all(r["kill_upper_vs_RR"] < DELTA for r in out["F1"] + out["F0"])
    out["verdict"] = "CLAIM" if claim else ("SCOPED-KILL" if kill else "INCONCLUSIVE")
    # exploratory: every A6 cell vs RR at the same B (Holm over the exploratory set), means for all arms/cells
    expl = []
    conf_cells = {c for _, c in F1 + F0}
    for arm, cell in inv:
        if arm == "A6" and cell not in conf_cells:
            B = int(cell.split("|")[0][1:])
            expl.append(paired(m, ("A6", cell), ("RR", f"B{B}"), seeds))
    if expl:
        adj, _ = holm([e["p_one_sided"] for e in expl], 0.05)
        for e, p in zip(expl, adj):
            e["p_holm_exploratory"] = p
    out["exploratory_vs_RR"] = expl
    out["cell_means"] = {f"{k[0]}::{k[1]}": {"mean": float(np.mean(list(v.values()))),
                                             "per_stream": [v[s] for s in seeds]} for k, v in m.items()}
    # by class (descriptive)
    bycls = defaultdict(lambda: defaultdict(list))
    for s in seeds:
        for x in R[("main", s)]["rows"]:
            bycls[f"{x['arm']}::{x['cell']}"][x["cls"]].append(1.0 if x["correct"] else 0.0)
    out["by_class"] = {k: {c: sum(v) / len(v) for c, v in d.items()} for k, d in bycls.items()}
    # over-budget subset at B=125 (descriptive; minimal support from SUPPORT-*.json)
    over = defaultdict(list)
    for s in seeds:
        f = DATA / f"SUPPORT-{s}.json"
        if not f.exists() and a.seeds:                 # smoke seeds only; the frozen streams all have SUPPORT files
            continue
        sup = json.loads(f.read_text())["tasks"]
        for x in R[("main", s)]["rows"]:
            if x["B"] == 125 and sup[x["task_id"]]["minimal"] > 125:
                over[f"{x['arm']}::{x['cell']}"].append(1.0 if x["correct"] else 0.0)
    out["over_budget_B125"] = {k: {"n": len(v), "acc": sum(v) / len(v)} for k, v in over.items()}
    # T4 (exploratory)
    if all(("t4", s) in R for s in seeds):
        inventory(R, seeds, "t4")
        mt = means(R, seeds, "t4")
        for k, v in mt.items():
            m[k] = v
        t4 = []
        for name, cap in (("len100", 100), ("len400", 400)):
            c = paired(m, ("A6-T4", f"{name}|B2000|1/5|{cap}"), ("A6", f"B2000|1/5|{cap}"), seeds)
            comp = [R[("t4", s)]["compliance"][name] for s in seeds]
            c["compliance"] = {"summaries": sum(x["n"] for x in comp), "failed": sum(x["failed"] for x in comp),
                               "within_cap": sum(x["within_cap"] for x in comp)}
            ref_costs = [sm["cost_raw"] for s in seeds for sm in R[("main", s)]["summaries"] if not sm.get("failed")]
            c["reference_prompt_within_cap"] = {"n": len(ref_costs), "within": sum(1 for x in ref_costs if x <= cap)}
            t4.append({"variant": name, **c})
        out["T4"] = t4
    # cost
    out["metered"] = tokens(a.tag)
    out["logical"] = logical(R)
    out["rerank"] = defaultdict(lambda: [0.0, 0.0])
    walls = defaultdict(float)
    for (ph, s), r in R.items():
        for k, (w, c) in (r.get("rerank") or {}).items():
            out["rerank"][k][0] += w; out["rerank"][k][1] += c
        for k, v in r["wall"].items():
            walls[f"{ph}:{k}"] += v
    out["rerank"] = dict(out["rerank"]); out["stage_wall_s"] = dict(walls)
    out["pauses"] = {f"{ph}-{s}": r.get("pauses") for (ph, s), r in R.items()}
    out["summary_failures"] = sum(1 for (ph, s), r in R.items() if ph == "main" for x in r["summaries"] if x.get("failed"))
    out["summary_misses"] = sum(len(r.get("summary_misses") or []) for r in R.values())
    out["failed_calls"] = {k: sum(1 for r in R.values() for x in r["rows"] if x["arm"] == k and not x["ok"])
                           for k in {x["arm"] for r in R.values() for x in r["rows"]}}
    for fam in ("F1", "F0"):
        for r in out[fam]:
            for c in r["comparisons"].values():
                c.pop("d", None)
                c["a"], c["b"] = "::".join(c["a"]), "::".join(c["b"])
    for e in out["exploratory_vs_RR"] + out.get("T4", []):
        e.pop("d", None); e["a"], e["b"] = "::".join(e["a"]), "::".join(e["b"])
    (RUNS / a.tag / "ANALYSIS.json").write_text(json.dumps(out, indent=1, default=str))
    print(json.dumps({"verdict": out["verdict"], "F1": [(r["cell"], round(r["comparisons"]["RR"]["diff"], 3),
                      round(r["p_holm"], 4), r["claim"]) for r in out["F1"]],
                      "F0": [(r["cell"], round(r["comparisons"]["RR"]["diff"], 3), round(r["p_holm"], 4), r["claim"])
                             for r in out["F0"]]}, indent=1))


if __name__ == "__main__":
    main()
