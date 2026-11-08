"""gte-modernbert-base via the public wrapper in gte_onnx.py (CLS pooling, L2, max 512, deterministic
single-thread), with a content-addressed on-disk vector cache. One text per session.run (batch-composition
independent). Released version: the original run used an equivalent private wrapper; see RELEASE-NOTES.md."""
from __future__ import annotations
import os, threading, hashlib
from pathlib import Path
from types import SimpleNamespace
import numpy as np
from .common import ENG_PIN, sha
from .gte_onnx import GteOnnxEmbedder

MODEL_DIR = Path(os.environ.get("GTE_MODEL_DIR", Path.home() / "models" / "gte-modernbert-base"))


class Embedder:
    def __init__(self, cache_dir: Path):
        self.e = GteOnnxEmbedder(MODEL_DIR, dim=768, deterministic=True)
        self.loaded = False
        self.cache_dir = Path(cache_dir); self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.mem: dict[str, np.ndarray] = {}
        self.legacy_model_id = self.legacy_id()          # v1.2 identity (first 1 MiB + size); kept for adoption checks
        # v1.3 F08: identity = full hashes of every model/tokenizer asset + pooling/normalisation/length config
        assets = []
        for p in sorted(MODEL_DIR.rglob("*")):
            if p.is_file() and p.suffix in (".onnx", ".json", ".txt", ".model"):
                with p.open("rb") as f:
                    assets.append(f"{p.relative_to(MODEL_DIR)}:{hashlib.file_digest(f, 'sha256').hexdigest()}")
        self.model_id = "gte-modernbert-base:" + sha("CLS|L2|512|v2|" + "\n".join(assets))

    @classmethod
    def legacy_id(cls):
        mf = cls.model_files()
        return "gte-modernbert-base:" + sha(open(mf, "rb").read(1 << 20) + str(os.path.getsize(mf)).encode())[:16]

    @staticmethod
    def model_files():
        q = MODEL_DIR / "onnx" / "model_quantized.onnx"
        return q if q.exists() else MODEL_DIR / "onnx" / "model.onnx"

    def vec(self, text: str) -> np.ndarray:
        k = sha(self.model_id + "|" + text)        # v1.3 F08: vectors namespaced by encoder identity
        with self.lock:
            if k in self.mem:
                return self.mem[k]
            p = self.cache_dir / k[:2] / f"{k}.npy"
            if p.exists():
                v = np.load(p); self.mem[k] = v; return v
            if not self.loaded:
                self.e.load(); self.loaded = True
            v = np.asarray(self.e.embed(text), dtype=np.float32)
            p.parent.mkdir(exist_ok=True); np.save(p, v); self.mem[k] = v
            return v

    def embed(self, texts):            # Eng Embedder adapter interface (list -> list[list[float]])
        return [self.vec(t).astype(np.float64).tolist() for t in texts]


class HashEmbedder:
    """Deterministic fake for tests (no model)."""
    model_id = "hash-fake"

    def vec(self, text):
        rng = np.random.default_rng(int(sha(text)[:15], 16))
        v = rng.standard_normal(32).astype(np.float32)
        # shared-word bias so similar texts are near
        for w in set(text.lower().split()):
            r2 = np.random.default_rng(int(sha(w)[:15], 16)); v += 0.5 * r2.standard_normal(32).astype(np.float32)
        return v / np.linalg.norm(v)

    def embed(self, texts):
        return [self.vec(t).astype(np.float64).tolist() for t in texts]
