"""Write PILOT3-FREEZE.json (v1.3).  python3 -m pilot2.freeze3 [--final]
Default writes status DRAFT: verify_frozen() refuses DRAFT, so no real run can start from it. Research regenerates
with --final (after PILOT-2 lands and the design is approved) immediately before launch. Makes no model calls."""
import argparse, hashlib, json, time
from pathlib import Path
from pilot import common
from pilot.common import ROOT
from pilot.freeze import fsha, code_files
from pilot2 import run2, score3
STREAM_PAR = 5
LLM_PAR = 20      # global concurrent-call cap (PILOT-2 used 8; attempt 1 at 8 was call-capped at ~1,150 real calls/h)
from pilot.llm import SYSTEM
from pilot.judge import J1

STREAMS = [7240241, 7240242, 7240243, 7240244, 7240245, 7240246, 7240247, 7240248, 7240249, 7240250]
NEW_STREAMS = STREAMS[2:]          # Research decision 1: generated with the pinned eng-pin generator (model-free)
DELETIONS_PER_STREAM = 8           # 2 generator deletions + 6 extra (as PILOT-2)


def tree_sha(d):
    fs = sorted(p for p in Path(d).rglob("*") if p.is_file())
    return hashlib.sha256("".join(f"{p.relative_to(d)}:{fsha(p)}\n" for p in fs).encode()).hexdigest(), len(fs)


def generator_identity():
    g = ROOT / "eng-pin" / "gen"
    files = {str(p.relative_to(ROOT)): fsha(p) for p in sorted(g.glob("*.py"))}
    return {"files": files, "digest": hashlib.sha256("".join(f"{k}:{v}\n" for k, v in files.items()).encode()).hexdigest(),
            "eng_commit": (ROOT / "eng-pin" / "PINNED_COMMIT").read_text().strip(),
            "commands": ["cd eng-pin && python3 gen/gen_stream.py --seed S --out ../data/stream-S",
                         "cd eng-pin && python3 gen/probe_author.py --stream ../data/stream-S --out ../data/stream-S-probes/probes.jsonl"],
            "config": "generator constants only (gen/common.py, gen_stream.py: N_SESSIONS=60, N_KEYS=150, target 80k tokens); seed is the only input",
            "reproduces_v12_streams": "regenerated 7240240/7240241/7240242 (+probes) byte-identical to data/ before generating new seeds"}


def stream_records():
    from pilot2.run2 import load_stream
    out = {}
    for s in STREAMS:
        S = load_stream(s, False)
        if len(S["deleted"]) != DELETIONS_PER_STREAM:
            raise ValueError(f"stream {s}: {len(S['deleted'])} deletions != {DELETIONS_PER_STREAM}")
        ts, nf = tree_sha(ROOT / "data" / f"stream-{s}")
        R = [t for t in S["targets"] if t["cls"] == "R"]
        out[str(s)] = {"manifest_sha256": fsha(ROOT / "data" / f"stream-{s}" / "MANIFEST.json"),
                       "probes_sha256": fsha(ROOT / "data" / f"stream-{s}-probes" / "probes.jsonl"),
                       "stream_tree_sha256": ts, "n_files": nf, "new_in_pilot3": s in NEW_STREAMS,
                       "deleted": S["deleted"], "extra": S["extra"], "n_targets": len(S["targets"]), "n_mix": len(S["probes"]),
                       "n_R_rows": len(R), "n_R_facts": len({t["fact_id"] for t in R}),
                       "n_probes_per_instance": len(S["targets"]) + len(S["probes"])}
    return out


COMMAND = ("cd /Users/a/Documents/Eywa/research/pilot-v1.3 && PYTHONPATH=.:eng-pin nohup sh -c 'python3 -m pilot2.run2 --label PILOT3 "
           "--streams 7240241,7240242,7240243,7240244,7240245,7240246,7240247,7240248,7240249,7240250 --stream-par 5 --llm-par 20 "
           "&& python3 -m pilot2.score3 PILOT3' > runs/PILOT3.out 2>&1 &")


def build(status):
    files, dig = code_files(ROOT, ("pilot", "pilot2", "eng-pin"))
    v12 = json.loads((ROOT / "PILOT-FREEZE.v1.2.json").read_text())
    v12b = json.loads((ROOT / "PILOT2-FREEZE.v1.2.json").read_text())
    prompts = {k: common.sha(getattr(common, k)) for k in
               ("P_A3N_WRITE", "P_CLUSTER", "P_REDACT", "P_A6_SYN", "P_A6M_CITE", "P_A6M_ANSWER_SUFFIX", "A3N_SCHEMA")}
    prompts["ENG_SYNTH_PREFIX"] = common.sha(common.SYNTH_PREFIX)
    prompts["GROK_SYSTEM_OVERRIDE"] = common.sha(SYSTEM); prompts["J1"] = common.sha(J1)
    side = json.loads((ROOT / "runs" / "anchors-7240240.json").read_text())
    return {
        "status": status, "frozen_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "label": "EXPLORATORY PILOT-3 (v1.3 = PILOT-2 design + J1 audit fixes + narrow DoT arm; not confirmatory)",
        "code_digest": dig, "code_files": files, "n_code_files": len(files),
        "pilot2_v12_code_digest": v12b["code_digest"], "prompts_sha256": prompts,
        "prompts_unchanged_vs_v12": {k: v12["prompts"][k]["sha256"] == prompts[k] for k in prompts if k in v12["prompts"]},
        "models": {**v12["models"], "embedder": side["cache_identity"]["embedder"],
                   "embedder_legacy_v12": v12["models"]["embedder"]},
        "eng_commit": (ROOT / "eng-pin" / "PINNED_COMMIT").read_text().strip(),
        "streams": STREAMS, "arms": [a[0] for a in run2.ARMS], "alias_C": run2.ALIAS_C,
        "anchors": {"sha256_npy": fsha(ROOT / "runs" / "anchors-7240240.npy"),
                    "sha256_sidecar": fsha(ROOT / "runs" / "anchors-7240240.json"), **side},
        "probe_files": {f"stream-{s}-probes/probes.jsonl": fsha(ROOT / "data" / f"stream-{s}-probes" / "probes.jsonl") for s in STREAMS},
        "stream_manifests": {f"stream-{s}/MANIFEST.json": fsha(ROOT / "data" / f"stream-{s}" / "MANIFEST.json") for s in (7240240, *STREAMS)},
        "data_matches_v12_freeze": None,  # filled below
        "prereg_v12_hashes_copied": v12["prereg"],
        "params": {**v12["params"], "n_extra_deletions_per_stream": 6, "deletions_per_stream": DELETIONS_PER_STREAM,
                   "bootstrap": "paired hierarchical: resample streams, then whole deletion groups within each drawn stream (J2-07), 10000, seed 0; the old within-stream CI (streams fixed) is reported alongside",
                   "probe_order": {"rule": "sorted probe ids, then random.Random(int(sha256('probe-order|SEED|stream|arm|world')[:16],16)).shuffle (J2-13)",
                                   "seed": run2.PROBE_ORDER_SEED, "workers_per_instance": run2.PROBE_WORKERS,
                                   "answers": "keyed by probe_id; answers.jsonl sorted by probe_id; scoring indexes by probe_id"},
                   "stream_par": STREAM_PAR, "llm_par": LLM_PAR, "rho_cost_cap": score3.RHO,
                   "rho_rule": "A6 total tokens per answered probe incl. writes <= rho x A3n's (prereg v1.2.1 L324); rho=2 set by Research (proposal not vetoed by Aditya); checked by score3 (mean stream-level ratio, plus every-instance flag); p95 latency reported",
                   "scoring": "regex only (as PILOT-2), no judge calls",
                   "primary_leak": "R (all four variants pooled, non-RR); registered dRec* = S u P u W u M DIRECT (prereg L241); X excluded from every primary pool and reported descriptively (L186 lists X: conflict noted in FIXES.md)"},
        "generator": generator_identity(),
        "stream_records": stream_records(),
        "memo": "fresh: v1.3 memo key (call-v2, effort) and vector key (full-asset embedder id) do not match v1.2 caches",
        "deviations_vs_pilot2": {
            "D3-1": "F01/F02 target authoring: C gold from compute_rows over the full deletion set; touched inherited U targets dropped; R eligibility by value_regex over surviving raw (R yield falls).",
            "D3-2": "Arm A3+DoTn (narrow DoT): A3 forget_mode=dot, touch-only attribution identical to A3n (J2-17). A3+DoT keeps PILOT-2 exposure provenance under its own name.",
            "D3-3": "Scoring: strict judge parsing / no imputation (F09), M in primary via DERIVED/AGG (F06), grouped bootstrap (F05), fact residue unknown + co-occurrence candidates (F12), head-based abstention (F04), actual-attempt costs (F07).",
            "D3-4": "Runtime: resume check before construction + nonzero exit on instance error (F03/F04), verify_frozen gate (F10), full-asset embedder identity + adopted v1.2 anchors (F08).",
            "D3-5": "Scale: 10 streams (7240241-7240242 as PILOT-2 + 8 new seeds 7240243-7240250 from the pinned generator), 8 deletions/stream; stream-level parallelism STREAM_PAR.",
            "D3-6": "Workload (J2-13): frozen seeded probe order per (stream, arm, world); answers keyed by probe id.",
            "D3-7": "Inference (J2-07): hierarchical bootstrap streams->deletion groups; old within-stream CI also reported.",
            "D3-9": "Throughput: global model-call cap raised 8 -> 20 (--llm-par 20); scheduling only, model/prompts/effort unchanged. Attempt 1 (cap 8) stopped after 28 min and archived as runs/PILOT3-abort1; its calls are memo hits in the relaunch (shared memo, disclosed).",
            "D3-8": "Scorer pilot2/score3 (REPORT.md + SUMMARY.json): R primary, X descriptive, retained, current-state, residue, cost/rho, per-stream."},
        "command": COMMAND,
    }


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--final", action="store_true"); a = ap.parse_args()
    fz = build("FROZEN" if a.final else "DRAFT")
    v12 = json.loads((ROOT / "PILOT-FREEZE.v1.2.json").read_text())
    fz["data_matches_v12_freeze"] = (all(fz["probe_files"][k] == v for k, v in v12["probe_files"].items())
                                     and all(fz["stream_manifests"][k] == v for k, v in v12["stream_manifests"].items())
                                     and fz["anchors"]["sha256_npy"] == v12["anchors"]["sha256_npy"])   # the v1.2 streams; new streams are recorded in stream_records
    (ROOT / "PILOT3-FREEZE.json").write_text(json.dumps(fz, indent=1))
    print(fz["status"], fz["code_digest"], fz["n_code_files"], "data_matches_v12:", fz["data_matches_v12_freeze"])


if __name__ == "__main__":
    main()
