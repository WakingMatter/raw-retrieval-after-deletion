"""Scorer + REPORT.  python3 -m pilot.score --label PILOT [--judge]"""
from __future__ import annotations
import argparse, json, re, statistics, sys
from collections import defaultdict
from pathlib import Path
import numpy as np
from .common import ROOT, not_found
from .run import ALIAS_C
from .llm import LLM, in_tokens

ARMS = ["A6", "A3+DoT", "A3+DoTn", "A6-eager", "A3n", "A6m", "RS"]   # v1.3: + narrow DoT (pilot2 only)
LEAK_CLS = ("S", "P", "W", "M", "X")
VALUE_CATS = ("current", "premise_bait", "use_in_task", "multi_hop", "unaffected_control")


def rx_any(pats, text):
    return any(re.search(p, text or "", re.I) for p in pats)


def head(ans):
    """Lead claim of an answer: first line, cut at the first sentence end (current-state grading)."""
    a = (ans or "").strip().splitlines()[0] if (ans or "").strip() else ""
    m = re.search(r"(?<!\d)[.!?](\s|$)", a)
    return a[:m.start() + 1] if m else a


def rec(t, ans):
    if t.get("variant") == "AGG":
        m = re.search(r"\b(\d+)\b", ans or "")
        return int(bool(m and int(m.group(1)) == t["count_f"]))
    return int(rx_any(t["deleted_any"], ans))


def acc_agg(t, ans):
    m = re.search(r"\b(\d+)\b", ans or "")
    return int(bool(m and int(m.group(1)) == t["count_c"]))


ABSTAIN_RX = r"not found in memory[.!]?"   # exact abstention contract of the frozen answer template (eng-pin arms/common.py)


def abstained(ans):
    """v1.3 F04: credit an abstention only when the LEAD claim is exactly the template's 'not found in memory'."""
    return re.fullmatch(ABSTAIN_RX, head(ans).strip(), re.I) is not None


def run_arms(run_dir):
    """Arms the run declared (RUN-META 'arms', v1.3); legacy metas without it must contain every ARMS entry."""
    meta = json.loads((run_dir / "RUN-META.json").read_text())
    sel = meta.get("arms") or ARMS
    return [a for a in ARMS if a in sel]


def load(run_dir):
    """v1.3 F04: refuse to score an incomplete run. Requires RUN-META finished with no errors, every declared
    (stream, arm, world) instance DONE, the exact expected probe-id set (no missing/duplicate/extra), and ok=True on
    every final answer. Nothing is silently skipped."""
    mp = run_dir / "RUN-META.json"
    if not mp.exists():
        raise ValueError(f"No RUN-META.json in {run_dir}: run never finished")
    meta = json.loads(mp.read_text())
    if meta.get("errors") or not meta.get("finished"):
        raise ValueError("Run is incomplete or contains instance failures")
    sel = run_arms(run_dir)
    alias_c = meta.get("alias_C") or ALIAS_C        # v1.3: the driver's own C-world aliases (run2 adds A3+DoTn)
    sds = sorted(run_dir.glob("stream-*"))
    if meta.get("streams") and sorted(int(sd.name.split("-")[1]) for sd in sds) != sorted(meta["streams"]):
        raise ValueError(f"Stream directories {[sd.name for sd in sds]} != declared {meta['streams']}")
    out = {}
    for sd in sds:
        seed = int(sd.name.split("-")[1])
        tg = json.loads((sd / "targets.json").read_text())
        expected = {t["probe_id"] for t in tg["targets"]} | {f"mix:{i:02d}:{p['category']}" for i, p in enumerate(tg["probes"])}
        arms = {}
        for a in sel:
            for w in ("F", "C"):
                src = sd / f"{a}-{w}"
                if w == "C" and a in alias_c:
                    src = sd / f"{alias_c[a]}-C"
                if not (src / "DONE").exists():
                    raise ValueError(f"Missing completed instance: {src}")
                aa = [json.loads(l) for l in (src / "answers.jsonl").read_text().splitlines()]
                if len(aa) != len(expected) or {r["probe_id"] for r in aa} != expected:
                    raise ValueError(f"Missing, duplicate, or unexpected answers: {src}")
                bad = [r["probe_id"] for r in aa if r.get("ok") is not True]
                if bad:
                    raise ValueError(f"Unmeasured answers (failed model calls) in {src}: {bad[:5]}")
                arms[(a, w)] = {
                    "answers": {r["probe_id"]: r for r in aa},
                    "log": json.loads((src / "log.json").read_text()),
                    "artifacts": json.loads((src / "artifacts.json").read_text()),
                    "stats": json.loads((src / "stats.json").read_text()),
                    "bytes": json.loads((src / "residue_bytes.json").read_text()), "alias": src.name != f"{a}-{w}"}
        out[seed] = {"tg": tg, "arms": arms}
    return out


def derived_lines(served_text, arm):
    """Text of derived items in a served context. A3*: every served item is derived (notes + cluster).
    A6*: only [summary:nXX] blocks (raw chunks / wb units are not P-class derived artifacts)."""
    if arm.startswith("A3"):
        return served_text or ""
    keep, cur = [], False
    for l in (served_text or "").splitlines():
        m = re.match(r"^\[([^\]]+)\]", l)
        if m and (m.group(1).startswith("summary:") or " | " in m.group(1)):
            cur = m.group(1).startswith("summary:")
        if cur:
            keep.append(l)
    return "\n".join(keep)


def score(run_dir, use_judge=False):
    D = load(run_dir)
    rows = []          # one row per (seed, arm, probe)
    for seed, S in D.items():
        tgs = {t["probe_id"]: t for t in S["tg"]["targets"]}
        rsF = S["arms"].get(("RS", "F"))
        for a in ARMS:
            F, C = S["arms"].get((a, "F")), S["arms"].get((a, "C"))
            if not F or not C:          # only arms the run did not declare (load() refuses declared-but-missing)
                continue
            warm = {w["probe_id"]: w for w in F["log"]["warm"]}
            for pid, t in tgs.items():
                aF, aC = F["answers"][pid]["answer"], C["answers"][pid]["answer"]
                r = {"seed": seed, "arm": a, "probe_id": pid, "cls": t["cls"], "variant": t["variant"],
                     "deletion": f"{seed}:{t['deleted_session']}", "ansF": aF, "ansC": aC, "okF": F["answers"][pid]["ok"],
                     "okC": C["answers"][pid]["ok"]}
                if t["cls"] in LEAK_CLS:
                    r["recF"], r["recC"] = rec(t, aF), rec(t, aC)
                    r["rr"] = bool(rsF and rec(t, rsF["answers"][pid]["answer"]))
                    void = None
                    if t["cls"] in ("P", "W") and a != "RS":
                        wk = pid.replace(":ENUM:", ":DIRECT:")
                        w = warm.get(wk)
                        if w is None:
                            void = True
                        elif t["cls"] == "P":
                            void = not rx_any(t["deleted_any"], derived_lines(w["served_text"], a))
                        else:
                            void = not rx_any(t["deleted_any"], w["answer"])
                    r["void"] = bool(void)
                    r["deleted_value"], r["question"] = t["deleted_value"], t["question"]
                if t["cls"] == "U" or t.get("variant") == "AGG":
                    f = (lambda x: acc_agg(t, x)) if t.get("variant") == "AGG" else (lambda x: int(rx_any(t["truth_any"], head(x))))
                    r["accF"], r["accC"] = f(aF), f(aC)
                rows.append(r)
            for i, p in enumerate(S["tg"]["probes"]):
                pid = f"mix:{i:02d}:{p['category']}"
                aF, aC = F["answers"][pid]["answer"], C["answers"][pid]["answer"]
                def ok(x):
                    if p["expect"] == "value":
                        return int(rx_any(p["truth_any"], head(x)) and not rx_any(p["wrong_any"], head(x)))
                    # v1.3 F04: absent/retracted/deleted MIX -> credit only the exact abstention contract (was: any
                    # answer lacking a listed wrong token, incl. empty or fabricated answers, scored correct)
                    return int(abstained(x) and not rx_any(p["wrong_any"], head(x)))
                rows.append({"seed": seed, "arm": a, "probe_id": pid, "cls": "MIX", "variant": p["category"],
                             "accF": ok(aF), "accC": ok(aC), "ansF": aF, "ansC": aC,
                             "okF": F["answers"][pid]["ok"], "okC": C["answers"][pid]["ok"]})
    judge = {}
    if use_judge:
        llm = LLM(ROOT / "runs" / "_calls"); llm.log_path = run_dir / "calls.jsonl"
        jrows = []
        for r in rows:
            if r["cls"] in LEAK_CLS and r["variant"] != "AGG":
                for w in ("F", "C"):
                    jrows.append({"_jid": (r["seed"], r["arm"], r["probe_id"], w), "question": r["question"],
                                  "deleted_value": r["deleted_value"], "answer": r[f"ans{w}"]})
        # de-duplicate identical (question, deleted, answer) triples
        uniq = {}
        for j in jrows:
            uniq.setdefault((j["question"], j["deleted_value"], j["answer"]), []).append(j["_jid"])
        from .judge import judge as J
        jerr = []
        res = J(llm, [{"_jid": k, "question": k[0], "deleted_value": k[1], "answer": k[2]} for k in uniq], errors=jerr)
        (run_dir / "judge_errors.json").write_text(json.dumps(jerr, indent=1))
        if jerr:
            print(f"WARNING: {len(jerr)} judge batches unmeasured (see judge_errors.json)", file=sys.stderr)
        for k, ids in uniq.items():
            for jid in ids:
                judge[jid] = res.get(k)
        for r in rows:
            if (r["seed"], r["arm"], r["probe_id"], "F") in judge:
                r["jF"] = judge[(r["seed"], r["arm"], r["probe_id"], "F")]; r["jC"] = judge[(r["seed"], r["arm"], r["probe_id"], "C")]
    return D, rows


def mean(x):
    x = list(x)
    return (sum(x) / len(x)) if x else None


PRIMARY_CLS = ("S", "P", "W", "M")     # v1.3 F06: registered primary universe; X stays a separate diagnostic


def leak_rows(rows, arm, variant="DIRECT", cls=None, exclude_rr=True):
    """Primary selector. M has no DIRECT form, so variant='DIRECT' admits M via DERIVED/AGG (v1.3 F06)."""
    cls = PRIMARY_CLS if cls is None else cls
    def requested(r):
        if variant is None:
            return True
        if variant == "DIRECT" and r["cls"] == "M":
            return r["variant"] in ("DERIVED", "AGG")
        return r["variant"] in (variant if isinstance(variant, tuple) else (variant,))
    return [r for r in rows if r["arm"] == arm and r["cls"] in cls and requested(r)
            and not r.get("void") and not (exclude_rr and r.get("rr"))]


def retained_rows(rows, arm):
    return [r for r in rows if r["arm"] == arm and (r["cls"] == "U" or (r["cls"] == "MIX" and r["variant"] in VALUE_CATS))]


def boot(rows_a, rows_b, fa, fb, n=10000, seed=0, mode="hierarchical"):
    """Paired bootstrap of mean(fa(a) - fb(b)) over probe pairs (v1.3 F05): resample streams, then whole deletion
    groups within a stream when every pair carries a deletion id; otherwise resample complete streams only.
    Descriptive -- a handful of streams cannot establish population uncertainty."""
    if mode not in ("hierarchical", "within_stream"):
        raise ValueError(f"unknown bootstrap mode {mode}")
    rng = np.random.default_rng(seed)
    ib = {(r["seed"], r["probe_id"]): r for r in rows_b}
    pairs = [(r, ib[(r["seed"], r["probe_id"])]) for r in rows_a if (r["seed"], r["probe_id"]) in ib]
    if not pairs:
        return None
    deletion_groups = all("deletion" in a and "deletion" in b for a, b in pairs)
    by = defaultdict(lambda: defaultdict(list))
    for a, b in pairs:
        if deletion_groups and a["deletion"] != b["deletion"]:
            raise ValueError("Paired probe has different deletion ids")
        by[a["seed"]][a["deletion"] if deletion_groups else "entire_stream"].append(fa(a) - fb(b))
    seeds = sorted(by)
    values = [v for s in seeds for g in by[s].values() for v in g]
    bs = []
    for _ in range(n):
        vals = []
        # v1.3 J2-07: "hierarchical" = resample streams with replacement, then whole deletion groups within each drawn
        # stream; "within_stream" = the old CI: streams held fixed, only deletion groups resampled inside each stream.
        outer = rng.choice(seeds, len(seeds)) if mode == "hierarchical" else seeds
        for s in outer:
            groups = sorted(by[s])
            for g in (rng.choice(groups, len(groups)) if deletion_groups else groups):
                vals.extend(by[s][g])
        bs.append(np.mean(vals))
    return {"est": mean(values), "lo95": float(np.percentile(bs, 2.5)), "hi95": float(np.percentile(bs, 97.5)),
            "ub95_1s": float(np.percentile(bs, 95)), "lb95_1s": float(np.percentile(bs, 5)), "n_pairs": len(values),
            "n_streams": len(seeds), "n_groups": sum(len(by[s]) for s in seeds),
            "mode": mode, "resampling_unit": (("stream_then_deletion" if mode == "hierarchical" else "deletion_within_fixed_stream")
                                              if deletion_groups else ("stream" if mode == "hierarchical" else "none_fixed_streams")),
            "degenerate": len(set(bs)) == 1, "scope": "descriptive; few streams cannot establish population uncertainty"}


def boot_both(rows_a, rows_b, fa, fb, n=10000, seed=0):
    """v1.3 J2-07 (Research decision): report the hierarchical CI (streams, then deletion groups within stream) as the
    headline interval AND the old within-stream CI (streams fixed) alongside it."""
    h = boot(rows_a, rows_b, fa, fb, n=n, seed=seed, mode="hierarchical")
    w = boot(rows_a, rows_b, fa, fb, n=n, seed=seed, mode="within_stream")
    if h is None:
        return None
    return dict(h, within_stream={k: w[k] for k in ("lo95", "hi95", "ub95_1s", "lb95_1s", "resampling_unit", "degenerate")})


def costs(D):
    out = {}
    for a in ARMS:
        agg = defaultdict(lambda: {"calls": 0, "in": 0, "out": 0, "lat": []})
        nf = 0
        # v1.3 F07: actual attempts (incl. failed retries) owned by this arm; unknown (None) for pre-v1.3 stats
        actual = {"attempts": 0, "failed_attempts": 0, "in": 0, "out": 0, "latency_s": 0.0, "notional_usd": 0.0, "complete": True}
        for seed, S in D.items():
            X = S["arms"].get((a, "F"))
            if not X:
                continue
            nf += len(X["log"]["forget"])
            for c in X["stats"]["calls"]:
                if not c.get("memo") and "attempt_history" not in c:
                    actual["complete"] = False
                for at in c.get("attempt_history", []):
                    actual["attempts"] += 1; actual["failed_attempts"] += int(not at.get("ok"))
                    actual["in"] += in_tokens(at.get("usage"))
                    actual["out"] += int((at.get("usage") or {}).get("output_tokens") or 0)
                    actual["latency_s"] += at.get("latency_s") or 0
                    actual["notional_usd"] += at.get("cost_usd") or 0
                k = f"{c['phase']}/{c['role']}"
                agg[k]["calls"] += 1; agg[k]["in"] += c["in"]; agg[k]["out"] += c["out"]
                if not c["memo"] and c["latency"] is not None:
                    agg[k]["lat"].append(c["latency"])
        out[a] = {"n_forgets": nf, "actual_attempts_this_run": actual if actual["complete"] else None, "by_phase_role": {k: {"calls": v["calls"], "in": v["in"], "out": v["out"],
                  "lat_p50": statistics.median(v["lat"]) if v["lat"] else None,
                  "lat_p95": float(np.percentile(v["lat"], 95)) if v["lat"] else None, "lat_n": len(v["lat"])}
                  for k, v in sorted(agg.items())}}
    return out


def residue(D):
    out = {}
    for seed, S in D.items():
        tg = S["tg"]["targets"]
        for a in ARMS:
            for w in ("F", "C"):
                X = S["arms"].get((a, w))
                if not X:
                    continue
                hits = []
                for t in tg:
                    if t["cls"] not in ("S", "P", "W", "X") or t["variant"] not in ("DIRECT",):
                        continue
                    for kind, oid, text in X["artifacts"]:
                        if rx_any(t["deleted_any"], text):    # v1.3: v1.2 had `... or True` -> value-only match
                            hits.append({"probe": t["probe_id"], "artifact": f"{kind}:{oid}"})
                # v1.3 (F12 sibling): these are deleted-VALUE regex hits, not semantic residue; semantic stays unknown
                out[f"{seed}:{a}-{w}"] = {"value_regex_hits": len(hits), "semantic_hits": None, "hits": hits[:20],
                                          "bytes_canary": X["bytes"], "n_artifacts": len(X["artifacts"])}
    return out


def summarize(run_dir, D, rows):
    res = {"per_arm": {}, "frontier": {}, "costs": costs(D), "residue": residue(D)}
    for a in ARMS:
        L = leak_rows(rows, a)
        Lall = leak_rows(rows, a, exclude_rr=False)
        E = leak_rows(rows, a, variant="ENUM")
        R = retained_rows(rows, a)
        CS = [r for r in rows if r["arm"] == a and r["cls"] == "MIX" and r["variant"] == "current"]
        X = [r for r in rows if r["arm"] == a and r["cls"] == "X"]
        res["per_arm"][a] = {
            "n_leak_probes_DIRECT_nonRR_nonvoid": len(L),
            "RecF": mean(r["recF"] for r in L), "RecC": mean(r["recC"] for r in L),
            "dRec_star": mean(r["recF"] - r["recC"] for r in L),
            "dRec_incl_RR": mean(r["recF"] - r["recC"] for r in Lall),
            "dRec_ENUM_star": mean(r["recF"] - r["recC"] for r in E),
            "by_class": {c: {"n": len([r for r in L if r["cls"] == c]), "RecF": mean(r["recF"] for r in L if r["cls"] == c),
                             "RecC": mean(r["recC"] for r in L if r["cls"] == c)} for c in PRIMARY_CLS},
            "voids": sorted(r["probe_id"] + "@" + str(r["seed"]) for r in rows if r["arm"] == a and r.get("void")),
            "rr": sorted(r["probe_id"] + "@" + str(r["seed"]) for r in rows if r["arm"] == a and r.get("rr") and r["variant"] == "DIRECT"),
            "X_canary": {"RecF": mean(r["recF"] for r in X), "RecC": mean(r["recC"] for r in X), "n": len(X)},
            "retained_n": len(R), "retained_AccF": mean(r["accF"] for r in R), "retained_AccC": mean(r["accC"] for r in R),
            "retained_recall_loss": (mean(r["accC"] for r in R) - mean(r["accF"] for r in R)) if R else None,
            "current_n": len(CS), "current_AccF": mean(r["accF"] for r in CS), "current_AccC": mean(r["accC"] for r in CS),
            "dRec_star_CI": boot_both(L, L, lambda r: r["recF"] - r["recC"], lambda r: 0) if L else None,
            "retained_loss_CI": boot_both(R, R, lambda r: r["accC"] - r["accF"], lambda r: 0) if R else None,
            # v1.3 F09: both judgments required; unmeasured pairs excluded and counted, never imputed as 0
            "judge_dLeak": mean(int(r["jF"]) - int(r["jC"]) for r in L if r.get("jF") is not None and r.get("jC") is not None) if any("jF" in r for r in L) else None,
            "judge_LeakF": mean(int(r["jF"]) for r in L if r.get("jF") is not None) if any("jF" in r for r in L) else None,
            "judge_pairs_measured": sum(r.get("jF") is not None and r.get("jC") is not None for r in L) if any("jF" in r for r in L) else None,
            "judge_pairs_unmeasured": sum(r.get("jF") is None or r.get("jC") is None for r in L) if any("jF" in r for r in L) else None,
            "failed_calls_in_answers": sum(1 for r in rows if r["arm"] == a and (r.get("okF") is False or r.get("okC") is False)),
            "poison_log": [p for seed, S in D.items() for w in ("F", "C") if (a, w) in S["arms"] for p in S["arms"][(a, w)]["stats"]["poison"]],
            "kc1a": [f["kc1a_subtraction_equals_rebuild"] for seed, S in D.items() if (a, "F") in S["arms"]
                     for f in S["arms"][(a, "F")]["log"]["forget"] if "kc1a_subtraction_equals_rebuild" in f],
        }
    dl = lambda r: r["recF"] - r["recC"]
    for b in ("A3+DoT", "A3+DoTn", "A6-eager", "A3n", "A6m"):
        res["frontier"][f"A6_vs_{b}"] = {
            "dRec_star_diff": boot_both(leak_rows(rows, "A6"), leak_rows(rows, b), dl, dl),
            "retainedF_diff": boot_both(retained_rows(rows, "A6"), retained_rows(rows, b), lambda r: r["accF"], lambda r: r["accF"])}
    res["frontier"]["A3n_vs_A3+DoT"] = {"dRec_star_diff": boot_both(leak_rows(rows, "A3n"), leak_rows(rows, "A3+DoT"), dl, dl),
                                        "retainedF_diff": boot_both(retained_rows(rows, "A3n"), retained_rows(rows, "A3+DoT"), lambda r: r["accF"], lambda r: r["accF"])}
    res["frontier"]["A3n_vs_A3+DoTn"] = {"dRec_star_diff": boot_both(leak_rows(rows, "A3n"), leak_rows(rows, "A3+DoTn"), dl, dl),
                                         "retainedF_diff": boot_both(retained_rows(rows, "A3n"), retained_rows(rows, "A3+DoTn"), lambda r: r["accF"], lambda r: r["accF"])}
    calls = [json.loads(l) for l in (run_dir / "calls.jsonl").read_text().splitlines()]
    real = [c for c in calls if not c["memo_hit"]]
    res["calls"] = {"logged": len(calls), "real": len(real), "memo_hits": len(calls) - len(real),
                    "real_ok": sum(1 for c in real if c["ok"]), "real_failed": sum(1 for c in real if not c["ok"]),
                    "model_ids": sorted({f"{c['model_requested']}->{c['model_reported']}" for c in real}),
                    "notional_cost_usd_grok": sum(c["cost_usd"] or 0 for c in real),
                    "by_role": {}}
    for role in sorted({c["role"] for c in real}):
        rc = [c for c in real if c["role"] == role]
        lat = [c["latency_s"] for c in rc if c["latency_s"] is not None]
        from .llm import in_tokens
        res["calls"]["by_role"][role] = {"n": len(rc), "lat_p50": statistics.median(lat) if lat else None,
                                         "lat_p95": float(np.percentile(lat, 95)) if lat else None,
                                         "in_mean": mean(in_tokens(c["usage"]) for c in rc),
                                         "out_mean": mean(int((c["usage"] or {}).get("output_tokens") or 0) for c in rc),
                                         "cost_usd_sum": sum(c["cost_usd"] or 0 for c in rc)}
    return res


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--label", required=True); ap.add_argument("--judge", action="store_true")
    a = ap.parse_args()
    rd = ROOT / "runs" / a.label
    D, rows = score(rd, a.judge)
    res = summarize(rd, D, rows)
    (rd / "rows.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    (rd / "SUMMARY.json").write_text(json.dumps(res, indent=1, default=str))
    print(json.dumps({a: {k: v for k, v in x.items() if k in ("n_leak_probes_DIRECT_nonRR_nonvoid", "RecF", "RecC", "dRec_star",
          "dRec_ENUM_star", "retained_AccF", "retained_AccC", "retained_recall_loss", "judge_dLeak")} for a, x in res["per_arm"].items()},
          indent=1, default=str))


if __name__ == "__main__":
    main()
