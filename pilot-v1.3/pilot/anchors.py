"""Frozen k=16 anchors: spherical k-means (k-means++ init, seed 7240240) over chunk vectors of the pilot-only
anchor stream 7240240 (dev streams are sealed; deviation disclosed)."""
from __future__ import annotations
import json, sys
from pathlib import Path
import numpy as np
from .common import DATA, K_ANCHORS, sha
from .arms import paragraphs


def fit(emb, seed=7240240, k=K_ANCHORS):
    d = DATA / f"stream-{seed}"
    m = json.load(open(d / "MANIFEST.json"))
    texts = [p for s in m["sessions"] for _, p in paragraphs(s["session"], (d / "sessions" / f"{s['session']}.md").read_text())]
    X = np.stack([np.asarray(emb.vec(t), dtype=np.float64) for t in texts]); X /= np.linalg.norm(X, axis=1, keepdims=True)
    rng = np.random.default_rng(seed)
    C = [X[rng.integers(len(X))]]
    for _ in range(1, k):
        dd = np.min([((X - c) ** 2).sum(1) for c in C], axis=0)
        C.append(X[rng.choice(len(X), p=dd / dd.sum())])
    C = np.stack(C)
    for _ in range(100):
        lab = np.argmax(X @ C.T, 1)
        C2 = np.stack([X[lab == j].mean(0) if (lab == j).any() else C[j] for j in range(k)])
        C2 /= np.linalg.norm(C2, axis=1, keepdims=True)
        if np.array_equal(C2, C):
            break
        C = C2
    return C, {"n_chunks": len(texts), "sizes": np.bincount(np.argmax(X @ C.T, 1), minlength=k).tolist()}


def cache_identity(emb):
    return {"embedder": emb.model_id, "k": K_ANCHORS,
            "fit_manifest": sha((DATA / "stream-7240240" / "MANIFEST.json").read_bytes())}


def load_or_fit(emb, out: Path):
    """v1.3 F08: an existing anchor file is used only if its sidecar records the same encoder + fit identity;
    otherwise refuse (fit to a fresh path / adopt explicitly via pilot.adopt_anchors). Never overwritten silently."""
    identity = cache_identity(emb)
    if out.exists():
        side = out.with_suffix(".json")
        info = json.loads(side.read_text()) if side.exists() else {}
        if info.get("cache_identity") != identity:
            raise ValueError(f"Anchor identity mismatch for {out}; fit to a fresh path or adopt explicitly, then re-freeze")
        A = np.load(out)
    else:
        A, info = fit(emb); np.save(out, A)
        info["cache_identity"] = identity
        (out.with_suffix(".json")).write_text(json.dumps(info))
    return A, sha(A.astype("<f8").tobytes())
