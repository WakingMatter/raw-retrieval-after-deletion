# Raw Retrieval Suffices After Deletion: code and data

This is the reproduction package for *Raw Retrieval Suffices After Deletion: A Preregistered Test of Recomputed Summaries in Agent Memory* (Aditya Vikram Singh, Waking Matter, 2026; arXiv link to follow).

All data here is synthetic. Model-generated text (answers and summaries) is not included; see `RELEASE-NOTES.md`.

## Layout

| Path | What it is |
|---|---|
| `prereg-E2/` | Frozen preregistration of the primary study (`PREREG-E2.md` and its SHA-256) |
| `e2/` | Primary study (E2): harness, tests, the 32 synthetic streams (`data/`), freeze manifest, scored confirmatory outputs (`runs/CONFIRM/`) |
| `e3/`, `prereg-E3/` | Two-step raw retrieval (RR-2hop) follow-up and its exploratory analyses |
| `e4-sensitivity/` | Budget and summary-cap sensitivity study (E4): preregistration, harness, data, freeze manifest, scored confirmatory outputs |
| `E1/` | Cost of correct deletion: scripts and report |
| `pilot-v1.3/` | Shared harness: computed memory, arms, scorer (`pilot/`), and the pinned stream-generator modules (`eng-pin/`) |
| `results/` | Reports exactly as written at run time, for comparison with your reruns |
| `paper/` | Figure script for the paper |

## Requirements

Python 3.13 or later. The confirmatory runs used Python 3.14.7 and NumPy 2.4.2; the tests also pass on Python 3.13 with NumPy 2.5 and SciPy 1.18.

- Analysis only: `numpy`, `scipy`, `huggingface_hub` (used by the freeze check).
- Rerunning the arms also needs `onnxruntime` and `tokenizers` for the embedder, plus `torch` and `transformers` for the reranker. You also need the model files (see below) and an API key for the answer model.

## Check the analysis without calling any model

```sh
# E2: rebuilds runs/CONFIRM/CONFIRM-REPORT.json from the scored outputs
cd e2 && python3 scripts/confirm_report.py

# E4: rebuilds runs/CONFIRM/ANALYSIS.json
cd e4-sensitivity && python3 -m e4.analyze_e4 --tag CONFIRM
```

Compare the results with `results/e2-CONFIRM-REPORT.json` and `results/e4-ANALYSIS.json`. The E4 analysis reproduces exactly. The E2 report reproduces every accuracy, contrast and interval. The exceptions are listed in `RELEASE-NOTES.md`.

## Run the tests

```sh
cd e2 && python3 -m pytest tests
cd e3 && python3 -m pytest tests           # needs a git checkout of this repository
cd pilot-v1.3 && python3 -m pytest pilot/tests
cd e4-sensitivity && python3 -m e4.test_gen_long
```

## Rerun the experiments

The streams are regenerated deterministically from their seeds (`e2/e2/make_data.py`, `e4-sensitivity/e4/make_data.py`); the shipped `data/` folders are their output.

Rerunning the arms needs three things:
- the embedder, `Alibaba-NLP/gte-modernbert-base` at revision `e7f32e3c00f91d699e8c43b53106206bcc72bb22`: `onnx/model.onnx`, `tokenizer.json` and the config files. Set `GTE_MODEL_DIR` to that directory. Leave `onnx/model_quantized.onnx` out: the wrapper uses it when present, and the runs did not.
- the reranker, `Alibaba-NLP/gte-reranker-modernbert-base` at revision `f7481e6055501a30fb19d090657df9ec1f79ab2c`.
- the answer model, MiniMax-M3.1-Flash, with `MINIMAX_API_KEY` set.

```sh
cd e2 && python3 -m e2.run_e2 --tag MYRUN --dry      # fake answerer, no API calls; still needs the embedder and reranker
cd e2 && python3 -m e2.run_e2 --tag MYRUN            # live run (paid API calls)
```

The answer model ignores temperature and runs with thinking always on, so a rerun's answers will differ from ours call by call. Expect the arm-level results to agree within the reported intervals, not to match exactly. The `--confirm` flag is refused on this copy because one frozen file was replaced for the release; see `RELEASE-NOTES.md`.

## Licence

Code: Apache License 2.0 (`LICENSE`). Data, preregistrations and results: CC BY 4.0 (`LICENSE-DATA.md`).

## Citation

To follow with the arXiv identifier.
