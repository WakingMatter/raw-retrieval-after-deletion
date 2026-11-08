# Release notes

This package is the code, data and scored outputs behind the paper, with the changes below. Each change is listed with its effect on what you can reproduce.

## 1. One file replaced: the embedder wrapper

At run time, `pilot-v1.3/pilot/embed.py` loaded `gte-modernbert-base` through a wrapper class from private code that is not part of this release. The released `embed.py` loads it through `pilot-v1.3/pilot/gte_onnx.py`, a short public wrapper that does the same thing:
- CLS pooling and L2 normalisation;
- truncation at 512 tokens;
- one text per `session.run`;
- single-threaded CPU inference.

The encoder identity (`model_id`, built from hashes of the model files and the pooling, normalisation and length settings) is computed exactly as before. A vector cache built with the original wrapper is therefore still addressed correctly.

Verification (8 Nov 2026, Python 3.13, onnxruntime 1.29.0, tokenizers 0.23.3):
- **Same model files.** The Hugging Face files of `Alibaba-NLP/gte-modernbert-base` at revision `e7f32e3c00f91d699e8c43b53106206bcc72bb22` (`onnx/model.onnx`, `tokenizer.json` and the config files) reproduce the encoder identity recorded in `pilot-v1.3/PILOT3-FREEZE.json` (`gte-modernbert-base:1a034ed7…fd00f`) exactly. These are the files the runs used.
- **Same vectors.** On those files, the original wrapper (frozen hash `c42b2909…bc31a`) and the public one gave bit-identical vectors (maximum absolute difference 0) for:
  - 2,000 texts drawn at random (seed 20261108) from the 86,101 distinct E2 session paragraphs and warm-up tasks;
  - 10 texts of 2,100–2,500 tokens, which exercise truncation.

The change, in full:

```diff
-"""gte-modernbert-base via Eng's vendored OnnxEmbedder (p3mech e55ad50, CLS pooling, L2, max 512, deterministic
+"""gte-modernbert-base via the public wrapper in gte_onnx.py (CLS pooling, L2, max 512, deterministic
 single-thread), with a content-addressed on-disk vector cache. One text per session.run (batch-composition
-independent)."""
+independent). Released version: the original run used an equivalent private wrapper; see RELEASE-NOTES.md."""
-import sys
-sys.path.insert(0, str(ENG_PIN / "arms" / "vendor" / "p3mech_e55ad50"))
-from eywa.ask.embedder import OnnxEmbedder  # noqa: E402
+from .gte_onnx import GteOnnxEmbedder
-MODEL_DIR = Path(os.environ.get("EYWA_MODELS_DIR", Path.home() / ".eywa/models")) / "gte-modernbert-base"
+MODEL_DIR = Path(os.environ.get("GTE_MODEL_DIR", Path.home() / "models" / "gte-modernbert-base"))
-        self.cfg = SimpleNamespace(embedder_path=str(MODEL_DIR), deterministic=True, embedder_dim=768)
-        self.e = OnnxEmbedder(self.cfg)
+        self.e = GteOnnxEmbedder(MODEL_DIR, dim=768, deterministic=True)
```

Consequence: `E2-FREEZE.json` and `E4-FREEZE.json` record the hash of the original `embed.py` and of the full pinned generator tree. The freeze check therefore reports a mismatch on `pilot_v1_3_sha256` and `eng_pin_sha256`, and `--confirm` runs are refused on this copy. Exploratory and dry runs, the tests and the analysis scripts are not affected.

## 2. Pinned generator tree trimmed

`pilot-v1.3/eng-pin/` was pinned at commit `863fb79` (`PINNED_COMMIT`). This release includes only the modules the paper's code imports:
- `arms/__init__.py`, `adapters.py`, `base.py`, `common.py`, `a2_rag.py`;
- `gen/`, except `semireal_inject.py`.

The rest of that tree belongs to other work and is not released: other arms, tests, protocol documents and reviews, and a vendored copy of private code. In `arms/adapters.py`, the class `P3MechOnnxEmbedder` now raises `NotImplementedError`. The paper's experiments never call it.

## 3. Model-generated text removed from the run outputs

`e2/runs/CONFIRM/` and `e4-sensitivity/runs/CONFIRM/` hold the confirmatory outputs, with every string under the keys `answer`, `parsed` and `raw` set to null. Those keys hold the answer model's answers and summaries. Kept: task metadata, correctness flags (strict and lenient), what each arm served, budget accounting, token counts, timings and cache keys.

The raw API response cache is not redistributed.

Effect on reproduction:
- **E4:** `python3 -m e4.analyze_e4 --tag CONFIRM` reproduces `results/e4-ANALYSIS.json` exactly.
- **E2:** `scripts/confirm_report.py` reproduces every accuracy, contrast and confidence interval in `results/e2-CONFIRM-REPORT.json`. Two things differ:
  - `freeze_verify` (see §1).
  - `header_gold_coverage_desc`, a descriptive count of how often the gold answer appears in the served summary header. It needs the summary text, so it reads 0 here. The values from the run are in `results/e2-CONFIRM-REPORT.json`.

## 4. Other exclusions

- Exploratory, development, smoke and dry-run outputs; logs; vector caches; quota and usage logs.
- The audit packet for the model audit of scored rows (§7 and Appendix D.2 of the paper), because it contains answer text. Its result is reported in the paper.

## 5. Paths

Hard-coded local paths in `E1/*.py` were replaced with paths relative to this repository. Frozen manifests and preregistrations keep the paths recorded when they were frozen, because their hashes cover those bytes.
