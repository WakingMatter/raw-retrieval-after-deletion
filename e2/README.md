# E2 harness (draft, not frozen)

Settling experiment: A6 (summaries served) vs A6-syn vs reranked raw (RR), after deletion, B = 2k, MiniMax-M3.1-Flash.
Prereg draft: `../prereg-E2/PREREG-E2-DRAFT.md`. Decisions: `DEFAULTS.md`. Cost: `COST.md`. Knobs+hashes: `E2-FREEZE-DRAFT.json`.

- `e2/minimax_api.py` API answerer (official endpoint, key from `$MINIMAX_API_KEY` or `~/.mmx/config.json`; never logged),
  retry/backoff, window/RPM pause-until-reset, credit-overflow floor guard, per-call response cache (resumable).
- `e2/arms_e2.py` A6E2 (serving fix + trace), RerankedRaw, LLM adapter. Imports pilot-v1.3 read-only.
- `e2/tasks.py`, `e2/make_data.py` post-delete task author (10 per class) and data generation.
- `e2/run_e2.py` runner. `--dry` uses a fake answerer (zero calls). Confirmatory seeds need `--confirm` AND a frozen
  `prereg-E2/PREREG-E2.md`.
- `e2/smoke.py` <=20-call live smoke; `e2/cost.py` cost table; `e2/make_freeze.py` freeze-file draft.
- Tests: `python3 -m pytest tests` (from `e2/`).
