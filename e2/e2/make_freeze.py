"""Write E2-FREEZE-DRAFT.json: every knob and file hash the E2 run depends on. DRAFT: regenerated at freeze time and
then committed alongside the frozen prereg. Contains no secret (the key is referenced by variable/path only)."""
from __future__ import annotations
import hashlib, json, time
from pathlib import Path
from .paths import E2, PILOT, ENG_PIN, DATA
from . import minimax_api as M, arms_e2 as A, tasks as T
from .make_data import CONFIRM, DEV, EXTRA
from . import power as PW, qualify as Q


def h(p: Path):
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None


def build(final=False):
    from pilot.common import SYNTH_PREFIX
    pilot_files = ["pilot/arms.py", "pilot/common.py", "pilot/store.py", "pilot/embed.py", "pilot/anchors.py",
                   "pilot/llm.py", "runs/anchors-7240240.npy"]
    eng_files = sorted(str(p.relative_to(ENG_PIN)) for p in (ENG_PIN / "gen").glob("*.py"))
    from huggingface_hub import try_to_load_from_cache
    rr_file = try_to_load_from_cache(A.RERANKER_REPO, "model.safetensors", revision=A.RERANKER_REV)
    from pilot.arms import P_A6_SYN
    syn_sha = hashlib.sha256(P_A6_SYN.replace("≤ 120 words", f"≤ {A.SYN_WORDS} words").encode()).hexdigest()
    dr = next((p for p in (E2 / "runs" / t / "DEV-REPORT.json" for t in ("DEV3", "DEV2", "DEV")) if p.exists()), E2 / "runs" / "DEV" / "x")
    dev_rule = json.loads(dr.read_text()).get("stream_rule") if dr.exists() else None
    fr = {
        "status": "DRAFT - NOT FROZEN",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "answer_model": {"route": M.ROUTE, "endpoint": M.ENDPOINT, "model": M.MODEL, "effort": M.EFFORT,
                         "max_tokens": M.MAX_TOKENS, "max_tokens_note": "includes thinking tokens",
                         "temperature": "not settable: MiniMax ignores temperature/top_p (server fixed 1.0/0.95); "
                                        "answers are NOT deterministic; reproducibility is by the per-call response cache",
                         "thinking": "always on (cannot be disabled on this model)",
                         "system_sha256": hashlib.sha256(M.SYSTEM.encode()).hexdigest(),
                         "synth_prefix_sha256": hashlib.sha256(SYNTH_PREFIX.encode()).hexdigest(),
                         "key_source": "env MINIMAX_API_KEY (fallback ~/.mmx/config.json api_key); value never logged",
                         "quota_endpoint": M.QUOTA_URL, "pause_floor_pct": 2.0,
                         "cache_key": "sha256(route, role, model, effort, max_tokens, system, prompt)"},
        "arms": {"A6": "A6E2 code edges, lazy keyed recompute, summaries served, skip-and-continue header, synth output "
                       f"capped at {A.SYN_OUT_CAP} est. tokens (sentence-boundary truncation, flagged)",
                 "A6-syn": "same A6 state, no summary header (routing + raw only)",
                 "RR": f"surviving raw paragraphs, cosine top-{A.TOP_K} (gte-modernbert-base), cross-encoder rerank "
                       f"({A.RERANKER_ID}), prefix-fill to B; zero generative calls",
                 "dropped": ["RS (decision: drop)"], "B": A.B_DEFAULT, "header_cap": "B/5 (unchanged)"},
        "tasks": {"n_per_class": T.N_PER_CLASS, "classes": ["AGG", "DERIVED", "MULTIHOP", "CURRENT"],
                  "endpoint_classes": ["AGG", "DERIVED", "MULTIHOP", "CURRENT"],
                  "multihop": "bridge-linked (tasks.make_bridge, BRIDGE.json per stream); kept: DEV2 best arm >= 0.15",
                  "scoring": "strict primary (gold hit and no wrong-value mention; AGG exactly one number == gold); "
                             "S1 informative-task and S2 lenient sensitivities + per-class floors (e2/analysis.py)",
                  "n_extra_deletions": T.N_EXTRA, "n_warm": T.N_WARM, "tasks_py_sha256": h(E2 / "e2" / "tasks.py")},
        "synth": {"per_summary_cap_est_tokens": A.SYN_OUT_CAP, "header_cap_est_tokens": A.HEADER_CAP,
                  "instruction_words": A.SYN_WORDS, "e2_synth_prompt_sha256": syn_sha,
                  "note": "pilot P_A6_SYN with '<= 120 words' replaced by '<= 50 words' (E2 override; pilot untouched)"},
        "qualification": {"gold_min": Q.GOLD_MIN, "n_per_group_per_dev_stream": Q.N_GROUP,
                          "pass": "0 contaminated no_evidence AND 0 failed calls AND gold_evidence acc >= gold_min",
                          "stale_derived": "reported only (not gating)"},
        "qualification_receipt": "QUAL3/QUALIFY.json",
        "k_delivery_min": 0.80,
        "stream_rule": {"margin": PW.MARGIN, "alpha_one_sided": PW.ALPHA, "target_power": PW.TARGET,
                        "base_n": PW.BASE_N, "max_n": PW.MAX_N, "reserve_seeds_in_order": EXTRA,
                        "dev_applied": dev_rule},
        "seeds": {"confirmatory": CONFIRM, "dev": DEV, "reserve": EXTRA,
                  "confirmatory_run": CONFIRM + EXTRA[: (dev_rule or {}).get("added", 0)],
                  "dev_note": "rev 4 regeneration: DEV 7269004 has 38 tasks (2 MULTIHOP short, DEV only); reserve 7260044 has 39"},
        "prereg_draft_sha256": h(E2.parent / "prereg-E2" / "PREREG-E2-DRAFT.md"),
        "task_files_sha256": {p.name: h(p) for p in sorted(DATA.glob("tasks-*.json"))},
        "stream_text_sha256 (sessions/*.md concatenated in name order; includes E2 bridges)": {
            d.name: hashlib.sha256(b"".join(f.read_bytes() for f in sorted((d / "sessions").glob("*.md")))).hexdigest()
            for d in sorted(DATA.glob("stream-*"))},
        "bridge_sha256": {d.name: h(d / "BRIDGE.json") for d in sorted(DATA.glob("stream-*"))},
        "e2_code_sha256": {p.name: h(p) for p in sorted((E2 / "e2").glob("*.py"))},
        "pilot_v1_3_sha256 (untracked dir; read-only imports)": {f: h(PILOT / f) for f in pilot_files},
        "eng_pin_sha256": {f: h(ENG_PIN / f) for f in eng_files},
        "reranker": {"id": A.RERANKER_ID, "safetensors_sha256": h(Path(rr_file)) if isinstance(rr_file, str) else None},
    }
    import sys, platform, importlib.metadata as md
    fr["environment"] = {"python": sys.version.split()[0], "platform": platform.platform(),
                         **{n: _ver(md, n) for n in ("torch", "transformers", "numpy", "sentence-transformers", "huggingface-hub")}}
    fr["stream_manifest_sha256"] = {d.name: h(d / "MANIFEST.json") for d in sorted(DATA.glob("stream-*"))}
    fr["cost_ceiling"] = cost_ceiling(json.loads(dr.read_text()).get("stream_cost") if dr.exists() else None, dr.parent.name)
    fr["e2_answer_prefix_sha256"] = hashlib.sha256(A.E2_PREFIX.encode()).hexdigest()
    if final:
        fr["status"] = "FROZEN"
        fr["prereg_sha256"] = h(E2.parent / "prereg-E2" / "PREREG-E2.md")
    return fr


CEIL_MULT = {"A6_tokens": 1.5, "A6_synth_calls": 1.5, "RR_tokens": 1.5, "reranker_seconds": 3.0}


def cost_ceiling(stream_cost, tag):
    """Per-stream lifecycle ceiling (rev 5, Astra finding 8): multiplier x the DEV maximum per stream. Tokens are nominal
    (input + output, cache replays counted at recorded usage). Reranker seconds get 3x because 8 concurrent processes
    share the CPU. Overrun on any confirmatory stream -> H-ADV is reported as NOT cost-bounded (prereg §7)."""
    if not stream_cost:
        return None
    import math
    lim = {k: math.ceil(m * max(float(v[k]) for v in stream_cost.values())) for k, m in CEIL_MULT.items()}
    return {"source": f"{tag}/DEV-REPORT.json stream_cost", "multipliers": CEIL_MULT, "per_stream_max": lim,
            "overrun_rule": "any confirmatory stream above any per_stream_max -> H-ADV not cost-bounded; accuracy outcome still reported"}


VERIFY_KEYS = ("e2_code_sha256", "task_files_sha256", "bridge_sha256", "stream_manifest_sha256", "eng_pin_sha256",
               "pilot_v1_3_sha256 (untracked dir; read-only imports)", "e2_answer_prefix_sha256", "prereg_sha256",
               "stream_text_sha256 (sessions/*.md concatenated in name order; includes E2 bridges)")


def _ver(md, n):
    try:
        return md.version(n)
    except Exception:
        return None


def verify_frozen() -> list:
    """Confirmatory launch gate (rev 5, Astra finding 3): every frozen hash must match the files on disk."""
    f = E2 / "E2-FREEZE.json"
    if not f.exists():
        return ["E2-FREEZE.json missing"]
    fr = json.loads(f.read_text())
    if fr.get("status") != "FROZEN":
        return ["E2-FREEZE.json not FROZEN"]
    now = build(final=True)
    return [k for k in VERIFY_KEYS if fr.get(k) != now.get(k)]


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(); ap.add_argument("--final", action="store_true")
    a = ap.parse_args(argv)
    fr = build(final=a.final)
    out = E2 / ("E2-FREEZE.json" if a.final else "E2-FREEZE-DRAFT.json")
    out.write_text(json.dumps(fr, indent=1))
    print(out)


if __name__ == "__main__":
    main()
