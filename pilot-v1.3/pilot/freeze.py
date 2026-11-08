"""Write PILOT-FREEZE.json (run before the first PILOT call)."""
import hashlib, json, time
from pathlib import Path
from . import common
from .common import ROOT

def fsha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def prereg_sha(p):
    lines = Path(p).read_bytes().split(b"\n", 1)[1]
    return hashlib.sha256(lines).hexdigest()

def code_files(root, dirs):
    """v1.3 F10: freezes include the pinned Eng runtime (eng-pin) next to the pilot code."""
    code = sorted(p for d in dirs for p in (root / d).rglob("*.py")
                  if "__pycache__" not in str(p) and not p.name.startswith("_"))
    files = {str(p.relative_to(root)): fsha(p) for p in code}
    return files, hashlib.sha256("".join(f"{k}:{v}\n" for k, v in files.items()).encode()).hexdigest()


def verify_frozen(filename, B, streams, arms=None, root=ROOT):
    """v1.3 F10 (modified from Astra): refuse a real (non-fake, non-smoke) run unless every frozen code file, probe
    file, stream manifest AND each manifest member, the anchors (+ sidecar identity), B, streams and arms match, and
    the freeze is not a DRAFT. Returns the code digest for RUN-META. Never makes a freeze pass after patching."""
    p = root / filename
    if not p.exists():
        raise ValueError(f"No freeze {filename}: refusing a real run")
    fz = json.loads(p.read_text())
    if fz.get("status") == "DRAFT":
        raise ValueError(f"{filename} is a DRAFT; regenerate it with --final before a real run")
    for rel, expected in fz["code_files"].items():
        if not (root / rel).exists() or fsha(root / rel) != expected:
            raise ValueError(f"Frozen code mismatch: {rel}")
    dirs = sorted({rel.split("/")[0] for rel in fz["code_files"]})
    if code_files(root, dirs)[1] != fz["code_digest"]:
        raise ValueError("Code digest mismatch (files added or removed since freeze)")
    for field in ("probe_files", "stream_manifests"):
        for rel, expected in fz[field].items():
            path = root / "data" / rel
            if fsha(path) != expected:
                raise ValueError(f"Frozen input mismatch: {rel}")
            if field == "stream_manifests":
                for child, expected_child in json.loads(path.read_text())["files"].items():
                    if fsha(path.parent / child) != expected_child:
                        raise ValueError(f"Manifest member mismatch: {rel} -> {child}")
    an = fz["anchors"]
    if fsha(root / "runs" / "anchors-7240240.npy") != an["sha256_npy"]:
        raise ValueError("Frozen anchors mismatch")
    if "sha256_sidecar" in an and fsha(root / "runs" / "anchors-7240240.json") != an["sha256_sidecar"]:
        raise ValueError("Frozen anchor sidecar (cache identity) mismatch")
    expected_streams = fz.get("streams", fz.get("seeds", {}).get("pilot_streams"))
    if B != fz["params"]["B"] or list(streams) != list(expected_streams):
        raise ValueError(f"Run parameters (B={B}, streams={streams}) differ from the freeze")
    if arms is not None and "arms" in fz and list(arms) != list(fz["arms"]):
        raise ValueError(f"Arms {arms} differ from frozen arms {fz['arms']}")
    return fz["code_digest"]


def main():
    code = sorted(p for d in ("pilot", "eng-pin") for p in (ROOT / d).rglob("*.py") if "__pycache__" not in str(p))
    files = {str(p.relative_to(ROOT)): fsha(p) for p in code}
    digest = hashlib.sha256("".join(f"{k}:{v}\n" for k, v in files.items()).encode()).hexdigest()
    sr = ROOT.parent / "stance-reads"
    prompts = {k: {"sha256": common.sha(getattr(common, k)), "text": getattr(common, k)} for k in
               ("P_A3N_WRITE", "P_CLUSTER", "P_REDACT", "P_A6_SYN", "P_A6M_CITE", "P_A6M_ANSWER_SUFFIX", "A3N_SCHEMA")}
    from .llm import SYSTEM
    from .judge import J1
    prompts["GROK_SYSTEM_OVERRIDE"] = {"sha256": common.sha(SYSTEM), "text": SYSTEM}
    prompts["J1"] = {"sha256": common.sha(J1), "text": J1}
    prompts["ENG_SYNTH_PREFIX"] = {"sha256": common.sha(common.SYNTH_PREFIX), "text": common.SYNTH_PREFIX}
    info = json.loads((ROOT / "runs" / "anchors-7240240.json").read_text())
    fz = {"frozen_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "label": "EXPLORATORY pilot (v1.2.1 §P)",
          "code_digest": digest, "code_files": files, "prompts": prompts,
          "models": {"answer/synth/write/redact/cluster": common.ANSWER_MODEL + " (grok CLI; reports grok-4.7-build)",
                     "judge_J1": common.JUDGE_MODEL + " (codex CLI)", "embedder": "gte-modernbert-base:603317bc2561e506"},
          "eng_commit": (ROOT / "eng-pin" / "PINNED_COMMIT").read_text().strip(),
          "seeds": {"anchor_fit": 7240240, "pilot_streams": [7240241, 7240242]},
          "anchors": {"sha256_npy": fsha(ROOT / "runs" / "anchors-7240240.npy"), **info},
          "probe_files": {f"stream-{s}-probes/probes.jsonl": fsha(ROOT / "data" / f"stream-{s}-probes" / "probes.jsonl") for s in (7240241, 7240242)},
          "stream_manifests": {f"stream-{s}/MANIFEST.json": fsha(ROOT / "data" / f"stream-{s}" / "MANIFEST.json") for s in (7240240, 7240241, 7240242)},
          "prereg": {"v1.2": {"path": str(sr / "2026-10-23-PREREG-currency-v1.2.md"), "sha256_lines2_EOF": prereg_sha(sr / "2026-10-23-PREREG-currency-v1.2.md")},
                     "v1.2.1": {"path": str(sr / "2026-10-23-PREREG-currency-v1.2.1.md"), "sha256_lines2_EOF": prereg_sha(sr / "2026-10-23-PREREG-currency-v1.2.1.md")}},
          "params": {"B": 2000, "K": common.K_ANCHORS, "SYN_CAP_TOKENS": common.SYN_CAP_TOKENS, "REFRESH_AT": list(common.REFRESH_AT),
                     "grok_reasoning_effort": "low", "fill_safety": 1.15, "bootstrap": "2-stage stream-cluster, 10000, seed 0"},
          "command": "cd /Users/a/Documents/Eywa/research/pilot-v1.2 && python3 -m pilot.run --label PILOT --streams 7240241,7240242 && python3 -m pilot.score --label PILOT --judge && python3 -m pilot.report --label PILOT"}
    (ROOT / "PILOT-FREEZE.json").write_text(json.dumps(fz, indent=1))
    print(digest)

if __name__ == "__main__":
    main()
