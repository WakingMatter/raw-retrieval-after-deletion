"""PILOT-2 scorer (EXPLORATORY). Reuses frozen pilot/score.py row logic with class R added; writes
runs/<label>/SUMMARY2.json + REPORT.md. Regex scoring only (no judge)."""
import json, re, sys
from collections import defaultdict
from pilot import score as S0
from pilot.common import ROOT, DATA
from gen.probe_author import LedgerOnlyStream
from pilot2.residue2 import cooccurrence_candidates
S0.LEAK_CLS = ("S", "P", "W", "M", "X", "R")
L = sys.argv[1]; RD = ROOT / "runs" / L
D, rows = S0.score(RD)
(RD / "rows.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
f = lambda x: "—" if x is None else f"{x:.3f}"
out = {"label": L, "per_arm_variant": {}, "fact_residue": {}, "cooccurrence_candidates": {}, "retained": {}, "contrasts": {}}
grp = defaultdict(list)
for r in rows:
    if "recF" in r and not r.get("void"):
        grp[(r["arm"], r["cls"], r["variant"])].append(r)
for (a, c, v), rs in sorted(grp.items()):
    b = S0.boot(rs, rs, lambda r: r["recF"], lambda r: r["recC"])
    out["per_arm_variant"][f"{a}|{c}:{v}"] = {"n": len(rs), "RecF": S0.mean(r["recF"] for r in rs), "RecC": S0.mean(r["recC"] for r in rs), "dRec": b}
for a in S0.ARMS:
    rr = S0.retained_rows(rows, a)
    out["retained"][a] = {"n": len(rr), "AccF": S0.mean(r["accF"] for r in rr), "AccC": S0.mean(r["accC"] for r in rr)}
    R2 = [r for r in rows if r["arm"] == a and r["cls"] in ("R", "X") and "recF" in r]
    out["contrasts"][a] = {"pooled_R_X_n": len(R2), "RecF": S0.mean(r["recF"] for r in R2), "RecC": S0.mean(r["recC"] for r in R2)}
for a, b in (("A3+DoT", "A3n"), ("A3+DoTn", "A3n"), ("A3+DoT", "A3+DoTn"), ("A6", "A3n"), ("A6", "A3+DoT"), ("A6", "A3+DoTn"), ("A6", "RS")):
    ra = [r for r in rows if r["arm"] == a and r["cls"] in ("R", "X") and "recF" in r]
    rb = [r for r in rows if r["arm"] == b and r["cls"] in ("R", "X") and "recF" in r]
    out["contrasts"][f"{a}_minus_{b}_dRec_RX"] = S0.boot(ra, rb, lambda r: r["recF"] - r["recC"], lambda r: r["recF"] - r["recC"])
for seed, S in D.items():
    st = LedgerOnlyStream(DATA / f"stream-{seed}"); keys, ents = st.world["keys"], st.world["entities"]
    for (a, w), X in S["arms"].items():
        k = f"{seed}:{a}-{w}"
        out["fact_residue"][k] = None   # v1.3 F12: needs subject-slot-value adjudication; co-occurrence is not residue
        out["cooccurrence_candidates"][k] = cooccurrence_candidates(S["tg"]["targets"], X["artifacts"], keys, ents)
out["costs"] = S0.costs(D)
(RD / "SUMMARY2.json").write_text(json.dumps(out, indent=1, default=str))
o = [f"# {L} — EXPLORATORY PILOT-2 (regex-scored, no judge)", "", "| arm | class:variant | n | RecF | RecC | ΔRec [lo,hi] |", "|---|---|---|---|---|---|"]
for k, v in out["per_arm_variant"].items():
    a, cv = k.split("|"); d = v["dRec"] or {}
    o.append(f"| {a} | {cv} | {v['n']} | {f(v['RecF'])} | {f(v['RecC'])} | {f(d.get('est'))} [{f(d.get('lo95'))},{f(d.get('hi95'))}] |")
o += ["", "Retained (U + MIX value) accuracy:", ""] + [f"- {a}: n {v['n']} AccF {f(v['AccF'])} AccC {f(v['AccC'])}" for a, v in out["retained"].items()]
o += ["", "Contrasts (ΔRec on R+X rows):", ""] + [f"- {k}: {json.dumps(v)}" for k, v in out["contrasts"].items()]
o += ["", "Actual attempts owned by arm in this run (includes retries; excludes memo hits):", ""] + [
    f"- {a}: {json.dumps(c.get('actual_attempts_this_run'))}" for a, c in out["costs"].items()]
o += ["", "Unadjudicated co-occurrence candidates (subject name + deleted value in one artifact; NOT fact-level residue):", ""] + [
    f"- {k}: {len(v)} candidate targets; fact residue unknown" for k, v in out["cooccurrence_candidates"].items()]
(RD / "REPORT.md").write_text("\n".join(o) + "\n"); print("\n".join(o))
