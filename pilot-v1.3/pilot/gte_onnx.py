"""Minimal public wrapper for the gte-modernbert-base ONNX encoder (Alibaba-NLP/gte-modernbert-base).

Used in place of a private vendored embedder in the released code. Behaviour the experiments depend on:
CLS pooling, L2 normalisation, truncation at 512 tokens, one text per session.run, single-threaded CPU
inference for determinism. Requires `onnxruntime`, `tokenizers` and `numpy`, and the model's
`onnx/model.onnx` (or `onnx/model_quantized.onnx`) and `tokenizer.json` under one directory.
"""
from __future__ import annotations

from pathlib import Path

MAX_LENGTH = 512


class GteOnnxEmbedder:
    def __init__(self, model_dir, dim: int = 768, deterministic: bool = True) -> None:
        self.model_dir = Path(model_dir)
        self.dim = dim
        self.deterministic = deterministic
        self._session = None
        self._tokenizer = None
        self._input_names: set[str] = set()

    def load(self) -> None:
        if self._session is not None:
            return
        import os
        import onnxruntime as ort
        from tokenizers import Tokenizer

        onnx_path = self.model_dir / "onnx" / "model_quantized.onnx"
        if not onnx_path.exists():
            onnx_path = self.model_dir / "onnx" / "model.onnx"
        tok_path = self.model_dir / "tokenizer.json"
        if not onnx_path.is_file() or not tok_path.is_file():
            raise FileNotFoundError(f"gte-modernbert-base model files not found under {self.model_dir}")
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 1 if self.deterministic else (os.cpu_count() or 1)
        opts.inter_op_num_threads = 1
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self._session = ort.InferenceSession(str(onnx_path), sess_options=opts, providers=["CPUExecutionProvider"])
        self._input_names = {i.name for i in self._session.get_inputs()}
        self._tokenizer = Tokenizer.from_file(str(tok_path))
        self._tokenizer.enable_truncation(max_length=MAX_LENGTH)
        self._tokenizer.enable_padding(length=None)
        if len(self.embed("dimension check")) != self.dim:
            raise ValueError(f"embedding dimension is not {self.dim}")

    def embed(self, text: str) -> list[float]:
        import numpy as np

        if self._session is None:
            raise RuntimeError("call load() first")
        enc = self._tokenizer.encode(text)
        ids = np.array([enc.ids], dtype=np.int64)
        mask = np.array([enc.attention_mask], dtype=np.int64)
        feed = {"input_ids": ids, "attention_mask": mask, "token_type_ids": np.zeros_like(ids)}
        feed = {k: v for k, v in feed.items() if k in self._input_names}
        cls = self._session.run(None, feed)[0][:, 0, :]
        cls = cls / np.maximum(np.linalg.norm(cls, axis=1, keepdims=True), 1e-9)
        return cls[0].tolist()
