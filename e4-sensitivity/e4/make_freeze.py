"""E4 freeze (DEFAULTS D11), modelled on e2/make_freeze.py. Writes e4-sensitivity/E4-FREEZE.json: hashes of the
prereg, runner, analyzer, arms (incl. the final generic bridge prompt), every imported e2/e3/pilot/eng-pin module,
the anchors, the data/tasks/SUPPORT files of the frozen streams, and the reranker weights. No secret is read.

    python3 -m e4.make_freeze --final      # writes E4-FREEZE.json (status FROZEN)
`run_e4 --confirm` refuses to start unless verify_frozen() returns [] and the seeds are frozen_streams()."""
from __future__ import annotations
import hashlib, json, time
from pathlib import Path
from .paths import E4, RESEARCH, PILOT, ENG_PIN, DATA, planned_streams, MAIN, RESERVE, DEV

FREEZE = E4 / "E4-FREEZE.json"


def h(p: Path):
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None


def hs(s: str):
    return hashlib.sha256(s.encode()).hexdigest()


def build(final=False, streams=None):
    from . import arms_e4, run_e4
    from e2 import arms_e2 as A, minimax_api as M
    streams = streams or planned_streams()
    assert len(streams) == 16, streams
    for s in streams:
        T = json.loads((DATA / f"tasks-{s}.json").read_text())
        assert len(T["tasks"]) == 40 and not any(T["shortfall"].values()), s
    from huggingface_hub import try_to_load_from_cache
    rr_file = try_to_load_from_cache(A.RERANKER_REPO, "model.safetensors", revision=A.RERANKER_REV)
    pilot_files = ["pilot/arms.py", "pilot/common.py", "pilot/store.py", "pilot/embed.py", "pilot/anchors.py",
                   "pilot/llm.py", "runs/anchors-7240240.npy"]
    fr = {
        "status": "DRAFT - NOT FROZEN",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "model": {"model": M.MODEL, "effort": M.EFFORT, "max_tokens": M.MAX_TOKENS, "route": M.ROUTE,
                  "pause_floor_pct": 2.0, "key_source": "env MINIMAX_API_KEY / ~/.mmx config; never logged"},
        "streams": streams, "dev": DEV, "main_pool": MAIN, "reserve_pool": RESERVE,
        "stream_note": "7280011 skipped (MULTIHOP shortfall 3, 37 tasks) -> reserve 7280017 (generator shortfall only)",
        "design": {"B_all": run_e4.B_ALL, "F0_cells": run_e4.F0_CELLS, "RRK_B": run_e4.RRK_B,
                   "K_bounds": [run_e4.K_MIN, run_e4.K_MAX], "T4": run_e4.T4_VARIANTS, "workers": run_e4.WORKERS,
                   "families": "F1 = T1 cells B in {500..8000} (1/5, cap 200); F0 = B125 (1/5, 25) and (2/5, 50); "
                               "alpha 0.025 each, Holm within; IUT over RR, RR-2hop, A6-syn (+RR-K at 4000/8000)",
                   "kill": "all 7 cells: upper bound A6-RR at 1-0.05/7 < 0.05 -> scoped kill; else inconclusive"},
        "bridge_prompt_sha256": hs(arms_e4.BRIDGE_PROMPT_GENERIC),
        "bridge_prompt_name": next(n for n in dir(arms_e4) if n.startswith("BRIDGE_PROMPT_GENERIC_V")
                                   and getattr(arms_e4, n) == arms_e4.BRIDGE_PROMPT_GENERIC),
        "answer_prefix_sha256": hs(A.E2_PREFIX),
        "prereg_sha256": h(E4 / "PREREG-E4.md"),
        "e4_code_sha256": {p.name: h(p) for p in sorted((E4 / "e4").glob("*.py")) if p.name != "make_freeze.py"}
                          | {"make_freeze.py": h(E4 / "e4" / "make_freeze.py")},
        "e2_code_sha256": {p.name: h(p) for p in sorted((RESEARCH / "e2" / "e2").glob("*.py"))},
        "e3_code_sha256": {p.name: h(p) for p in sorted((RESEARCH / "e3" / "e3").glob("*.py"))},
        "pilot_v1_3_sha256": {f: h(PILOT / f) for f in pilot_files},
        "eng_pin_sha256": {str(p.relative_to(ENG_PIN)): h(p) for p in sorted((ENG_PIN / "gen").glob("*.py"))},
        "task_files_sha256": {f"tasks-{s}.json": h(DATA / f"tasks-{s}.json") for s in streams},
        "support_files_sha256": {f"SUPPORT-{s}.json": h(DATA / f"SUPPORT-{s}.json") for s in streams},
        "stream_text_sha256": {s: hashlib.sha256(b"".join(f.read_bytes() for f in
                                                          sorted((DATA / f"stream-{s}" / "sessions").glob("*.md")))).hexdigest()
                               for s in map(str, streams)},
        "stream_manifest_sha256": {str(s): h(DATA / f"stream-{s}" / "MANIFEST.json") for s in streams},
        "reranker": {"id": A.RERANKER_ID, "safetensors_sha256": h(Path(rr_file)) if isinstance(rr_file, str) else None},
    }
    if final:
        fr["status"] = "FROZEN"
    return fr


VERIFY_KEYS = ("streams", "design", "bridge_prompt_sha256", "answer_prefix_sha256", "prereg_sha256", "e4_code_sha256",
               "e2_code_sha256", "e3_code_sha256", "pilot_v1_3_sha256", "eng_pin_sha256", "task_files_sha256",
               "support_files_sha256", "stream_text_sha256", "stream_manifest_sha256", "reranker")


def frozen_streams():
    return json.loads(FREEZE.read_text())["streams"]


def verify_frozen() -> list:
    if not FREEZE.exists():
        return ["E4-FREEZE.json missing"]
    fr = json.loads(FREEZE.read_text())
    if fr.get("status") != "FROZEN":
        return ["E4-FREEZE.json not FROZEN"]
    now = json.loads(json.dumps(build(final=True, streams=fr["streams"])))
    return [k for k in VERIFY_KEYS if fr.get(k) != now.get(k)]


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(); ap.add_argument("--final", action="store_true")
    a = ap.parse_args(argv)
    fr = build(final=a.final)
    out = FREEZE if a.final else E4 / "E4-FREEZE-DRAFT.json"
    out.write_text(json.dumps(fr, indent=1))
    print(out)


if __name__ == "__main__":
    main()
