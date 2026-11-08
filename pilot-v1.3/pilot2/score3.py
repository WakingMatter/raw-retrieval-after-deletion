"""PILOT-3 scorer (EXPLORATORY). Regex scoring only (as PILOT-2; no judge calls).  python3 -m pilot2.score3 <label>
Writes runs/<label>/{rows.jsonl, SUMMARY.json, REPORT.md}. Research decisions (2026-10-23):
  - R is the primary leak measure of PILOT-3 (non-RR, all four R variants pooled; DIRECT-only alongside).
  - X stays OUT of every primary pool (prereg v1.2.1 L241; L186 lists X -- conflict noted in FIXES.md) and is
    reported descriptively only (means, no CI, no contrasts).
  - CIs: hierarchical bootstrap (streams, then deletion groups within stream) + the old within-stream CI (J2-07).
  - Cost cap (prereg L324): A6 total tokens per answered probe incl. writes <= RHO x A3n's; p95 latency reported."""
from __future__ import annotations
import json, statistics, sys
from collections import defaultdict
import numpy as np
from pilot import score as S0
from pilot.common import ROOT, DATA

RHO = 2.0
S0.LEAK_CLS = ("S", "P", "W", "M", "X", "R")       # rows get recF/recC/rr for R and X (X still descriptive only)
R_VARIANTS = ("DIRECT", "HIST", "ENUM", "SUMM")
CONTRASTS = (("A6", "A3n"), ("A6", "A3+DoTn"), ("A6", "A3+DoT"), ("A6", "RS"), ("A6", "A6m"), ("A6", "A6-eager"),
             ("A3+DoTn", "A3n"), ("A3+DoT", "A3n"), ("A3+DoT", "A3+DoTn"))
dl = lambda r: r["recF"] - r["recC"]


def r_rows(rows, arm, variants=R_VARIANTS, exclude_rr=True, seed=None):
    return [r for r in rows if r["arm"] == arm and r["cls"] == "R" and r["variant"] in variants and "recF" in r
            and not r.get("void") and not (exclude_rr and r.get("rr")) and (seed is None or r["seed"] == seed)]


def instance_tokens(X):
    """Logical tokens (in + out) of every call the instance made (writes, clusters, redactions, synth, answers),
    counting memo hits at their recorded size, and the number of answered terminal probes."""
    tok = sum(int(c.get("in") or 0) + int(c.get("out") or 0) for c in X["stats"]["calls"])
    lat = [c["latency"] for c in X["stats"]["calls"] if c.get("latency") is not None and not c.get("memo")]
    return tok, len(X["answers"]), lat


def cost_cap(D, rho=RHO):
    """Per (stream, world): (A6 tokens/answered probe) / (A3n tokens/answered probe); stream-level mean (J2-14)."""
    per, lat = {}, defaultdict(list)
    for seed, S in D.items():
        for w in ("F", "C"):
            a6, a3 = S["arms"].get(("A6", w)), S["arms"].get(("A3n", w))
            if not a6 or not a3 or a6["alias"] or a3["alias"]:
                continue
            t6, n6, l6 = instance_tokens(a6); t3, n3, l3 = instance_tokens(a3)
            lat["A6"] += l6; lat["A3n"] += l3
            per[f"{seed}-{w}"] = {"A6_tok_per_probe": t6 / n6, "A3n_tok_per_probe": t3 / n3, "ratio": (t6 / n6) / (t3 / n3)}
    by_stream = defaultdict(list)
    for k, v in per.items():
        by_stream[k.split("-")[0]].append(v["ratio"])
    stream_ratios = {s: statistics.mean(v) for s, v in by_stream.items()}
    mean_ratio = statistics.mean(stream_ratios.values()) if stream_ratios else None
    p95 = {a: (float(np.percentile(v, 95)) if v else None) for a, v in lat.items()}
    return {"rho": rho, "rule": "A6 total tokens per answered probe (incl. write/cluster/redact/synth) <= rho x A3n's (prereg v1.2.1 L324)",
            "per_instance": per, "per_stream_ratio": stream_ratios, "mean_stream_ratio": mean_ratio,
            "max_instance_ratio": max((v["ratio"] for v in per.values()), default=None),
            "pass_mean": (mean_ratio is not None and mean_ratio <= rho),
            "pass_every_instance": bool(per) and all(v["ratio"] <= rho for v in per.values()),
            "p95_latency_s_real_calls": p95}


def summarize3(run_dir, D, rows, n_boot=10000):
    base = S0.summarize(run_dir, D, rows)
    seeds = sorted(D)
    out = {"label": run_dir.name, "streams": seeds, "n_streams": len(seeds), "primary_R": {}, "R_by_variant": {},
           "registered_primary_dRec_star_SPWM": {}, "X_descriptive": {}, "retained": {}, "current_state": {},
           "residue": {}, "contrasts_R": {}, "cost_cap": cost_cap(D), "per_stream": {}, "calls": base["calls"],
           "costs": base["costs"], "frontier_SPWM": base["frontier"],
           "notes": ["R primary = class R, all four variants pooled, non-RR; X descriptive only (L241; L186 conflict in FIXES.md)",
                     "CI = hierarchical bootstrap (streams, then deletion groups within stream); within_stream = old CI (streams fixed)",
                     "regex scoring only; no judge; residue = value-regex hits + co-occurrence candidates, not semantic residue"]}
    arms = [a for a in S0.ARMS if any(r["arm"] == a for r in rows)]
    for a in arms:
        R = r_rows(rows, a); Rall = r_rows(rows, a, exclude_rr=False); Rd = r_rows(rows, a, variants=("DIRECT",))
        out["primary_R"][a] = {"n_rows": len(R), "n_facts": len({(r["seed"], r["probe_id"].split(":")[-1]) for r in R}),
                               "n_deletion_groups": len({r["deletion"] for r in R}), "RecF": S0.mean(r["recF"] for r in R),
                               "RecC": S0.mean(r["recC"] for r in R), "dRec": S0.boot_both(R, R, dl, lambda r: 0, n=n_boot) if R else None,
                               "dRec_incl_RR": S0.mean(dl(r) for r in Rall), "n_rr": len(Rall) - len(R),
                               "DIRECT_only": {"n": len(Rd), "RecF": S0.mean(r["recF"] for r in Rd), "RecC": S0.mean(r["recC"] for r in Rd),
                                               "dRec": S0.boot_both(Rd, Rd, dl, lambda r: 0, n=n_boot) if Rd else None}}
        for v in R_VARIANTS:
            Rv = r_rows(rows, a, variants=(v,))
            out["R_by_variant"][f"{a}|R:{v}"] = {"n": len(Rv), "RecF": S0.mean(r["recF"] for r in Rv), "RecC": S0.mean(r["recC"] for r in Rv)}
        pa = base["per_arm"][a]
        out["registered_primary_dRec_star_SPWM"][a] = {k: pa[k] for k in ("n_leak_probes_DIRECT_nonRR_nonvoid", "RecF", "RecC", "dRec_star", "dRec_star_CI", "by_class")}
        X = [r for r in rows if r["arm"] == a and r["cls"] == "X" and "recF" in r]
        out["X_descriptive"][a] = {"n": len(X), "RecF": S0.mean(r["recF"] for r in X), "RecC": S0.mean(r["recC"] for r in X),
                                   "by_variant": {v: {"n": len([r for r in X if r["variant"] == v]),
                                                      "RecF": S0.mean(r["recF"] for r in X if r["variant"] == v)} for v in ("DIRECT", "HIST")}}
        out["retained"][a] = {k: pa[k] for k in ("retained_n", "retained_AccF", "retained_AccC", "retained_recall_loss", "retained_loss_CI")}
        out["current_state"][a] = {k: pa[k] for k in ("current_n", "current_AccF", "current_AccC")}
    for k, v in base["residue"].items():
        out["residue"][k] = {"value_regex_hits": v["value_regex_hits"], "semantic_hits": None, "n_artifacts": v["n_artifacts"],
                             "canary_bytes_total": sum(sum(h.values()) for h in v["bytes_canary"].values())}
    from pilot2.residue2 import cooccurrence_candidates
    from gen.probe_author import LedgerOnlyStream
    for seed, S in D.items():
        st = LedgerOnlyStream(DATA / f"stream-{seed}")
        for (a, w), X in S["arms"].items():
            out["residue"].setdefault(f"{seed}:{a}-{w}", {})["cooccurrence_candidates"] = len(
                cooccurrence_candidates(S["tg"]["targets"], X["artifacts"], st.world["keys"], st.world["entities"]))
    for a, b in CONTRASTS:
        if a in arms and b in arms:
            out["contrasts_R"][f"{a}_minus_{b}"] = S0.boot_both(r_rows(rows, a), r_rows(rows, b), dl, dl, n=n_boot)
    cc = out["cost_cap"]["per_instance"]
    for seed in seeds:
        ps = {}
        for a in arms:
            R = r_rows(rows, a, seed=seed); L = [r for r in S0.leak_rows(rows, a) if r["seed"] == seed]
            RT = [r for r in S0.retained_rows(rows, a) if r["seed"] == seed]
            CS = [r for r in rows if r["arm"] == a and r["seed"] == seed and r["cls"] == "MIX" and r["variant"] == "current"]
            ps[a] = {"R_n": len(R), "R_dRec": S0.mean(dl(r) for r in R), "R_RecF": S0.mean(r["recF"] for r in R),
                     "SPWM_n": len(L), "SPWM_dRec_star": S0.mean(dl(r) for r in L),
                     "retained_AccF": S0.mean(r["accF"] for r in RT), "retained_AccC": S0.mean(r["accC"] for r in RT),
                     "current_AccF": S0.mean(r["accF"] for r in CS)}
        out["per_stream"][str(seed)] = {"arms": ps, "cost_ratio_F": (cc.get(f"{seed}-F") or {}).get("ratio"),
                                        "cost_ratio_C": (cc.get(f"{seed}-C") or {}).get("ratio")}
    return out


def report(out):
    f = lambda x: "—" if x is None else f"{x:.3f}"
    ci = lambda b: "—" if not b else f"{f(b['est'])} [{f(b['lo95'])}, {f(b['hi95'])}] (within-stream [{f(b['within_stream']['lo95'])}, {f(b['within_stream']['hi95'])}])"
    o = [f"# {out['label']} — EXPLORATORY PILOT-3 (regex-scored, no judge; {out['n_streams']} streams)", "",
         "Notes: " + " · ".join(out["notes"]), "", "## Primary: R (deletion-only facts), ΔRec = RecF − RecC, non-RR", "",
         "| arm | R rows | facts | groups | RecF | RecC | ΔRec [hier 95%] (within-stream) | DIRECT-only ΔRec | RR |", "|---|---|---|---|---|---|---|---|---|"]
    for a, v in out["primary_R"].items():
        o.append(f"| {a} | {v['n_rows']} | {v['n_facts']} | {v['n_deletion_groups']} | {f(v['RecF'])} | {f(v['RecC'])} | {ci(v['dRec'])} | {ci(v['DIRECT_only']['dRec'])} | {v['n_rr']} |")
    o += ["", "R contrasts (paired, ΔRec_a − ΔRec_b):", ""] + [f"- {k}: {ci(v)}" for k, v in out["contrasts_R"].items()]
    o += ["", "R by variant:", ""] + [f"- {k}: n {v['n']} RecF {f(v['RecF'])} RecC {f(v['RecC'])}" for k, v in out["R_by_variant"].items()]
    o += ["", "## Registered ΔRec* (S∪P∪W∪M, DIRECT, non-RR; X excluded per L241)", ""] + [
        f"- {a}: n {v['n_leak_probes_DIRECT_nonRR_nonvoid']} ΔRec* {ci(v['dRec_star_CI'])}" for a, v in out["registered_primary_dRec_star_SPWM"].items()]
    o += ["", "## X canaries (descriptive only; not in any primary pool)", ""] + [
        f"- {a}: n {v['n']} RecF {f(v['RecF'])} RecC {f(v['RecC'])}" for a, v in out["X_descriptive"].items()]
    o += ["", "## Retained recall (U + MIX value) and current-state (MIX current)", "", "| arm | retained n | AccF | AccC | loss [hier] | current n | cur AccF | cur AccC |", "|---|---|---|---|---|---|---|---|"]
    for a in out["retained"]:
        r, c = out["retained"][a], out["current_state"][a]
        o.append(f"| {a} | {r['retained_n']} | {f(r['retained_AccF'])} | {f(r['retained_AccC'])} | {ci(r['retained_loss_CI'])} | {c['current_n']} | {f(c['current_AccF'])} | {f(c['current_AccC'])} |")
    cc = out["cost_cap"]
    o += ["", f"## Cost cap ρ = {cc['rho']} ({cc['rule']})", "",
          f"- mean stream-level ratio {f(cc['mean_stream_ratio'])}, max instance {f(cc['max_instance_ratio'])} -> **{'PASS' if cc['pass_mean'] else 'FAIL'}** (every instance ≤ ρ: {cc['pass_every_instance']})",
          f"- p95 latency of real calls (s): {json.dumps(cc['p95_latency_s_real_calls'])}",
          f"- calls: {out['calls']['real']} real ({out['calls']['real_failed']} failed), notional ${out['calls']['notional_cost_usd_grok']:.2f}"]
    o += ["", "## Residue (deleted-value regex hits in derived artifacts; NOT semantic residue)", "", "| instance | value hits | co-occurrence cands | canary bytes | artifacts |", "|---|---|---|---|---|"]
    for k, v in sorted(out["residue"].items()):
        o.append(f"| {k} | {v.get('value_regex_hits')} | {v.get('cooccurrence_candidates')} | {v.get('canary_bytes_total')} | {v.get('n_artifacts')} |")
    o += ["", "## Per stream", "", "| stream | arm | R n | R ΔRec | R RecF | SPWM n | ΔRec* | ret AccF | ret AccC | cur AccF |", "|---|---|---|---|---|---|---|---|---|---|"]
    for s, v in out["per_stream"].items():
        for a, x in v["arms"].items():
            o.append(f"| {s} | {a} | {x['R_n']} | {f(x['R_dRec'])} | {f(x['R_RecF'])} | {x['SPWM_n']} | {f(x['SPWM_dRec_star'])} | {f(x['retained_AccF'])} | {f(x['retained_AccC'])} | {f(x['current_AccF'])} |")
        o.append(f"| {s} | cost A6/A3n | F {f(v['cost_ratio_F'])} | C {f(v['cost_ratio_C'])} | | | | | | |")
    return "\n".join(o) + "\n"


def main(label):
    rd = ROOT / "runs" / label
    D, rows = S0.score(rd)
    (rd / "rows.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    out = summarize3(rd, D, rows)
    (rd / "SUMMARY.json").write_text(json.dumps(out, indent=1, default=str))
    txt = report(out); (rd / "REPORT.md").write_text(txt); print(txt)
    with open(ROOT / "PROGRESS.md", "a") as fh:
        import time
        fh.write(f"- {time.strftime('%Y-%m-%d %H:%M:%S IST')} — {label}: score3 wrote REPORT.md + SUMMARY.json "
                 f"(cost cap mean ratio {out['cost_cap']['mean_stream_ratio']}, pass={out['cost_cap']['pass_mean']})\n")


if __name__ == "__main__":
    main(sys.argv[1])
