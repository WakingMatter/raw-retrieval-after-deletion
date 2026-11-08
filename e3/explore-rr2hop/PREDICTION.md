# E3 exploration: RR-2hop on E2's DERIVED tasks — PREDICTION (written before any RR-2hop API call)

**Written:** 24 Oct 2026, 19:15 IST. No RR-2hop model call has been made. Code: `e3/e3/rr2hop.py` (offline tests in
`e3/tests/test_rr2hop.py`, 7 passed), runner `run_rr2hop.py`, scorer `analyze.py`.

**Status: exploratory and post hoc.** These are the same 320 E2 CONFIRM DERIVED tasks (32 streams × 10) in which the
DERIVED lead was found, and RR-2hop was designed after seeing the E2 audit
(`e3/explore-rragg/AUDIT.md`: the attr leaf is outside RR's top-50 in 311/320 tasks). Nothing here is confirmatory.
It decides whether E3 is worth freezing.

## Design (fixed before the run)

* **Hop 1.** Identical to E2 RR: cosine top-50 over surviving paragraph chunks → gte-reranker rerank on the question →
  prefix-fill to B = 2000. The runner asserts hop-1 served == E2 RR served for all 320 tasks before any call.
* **Bridge call.** One call to the same model (MiniMax-M3.1-Flash, E2 settings, role `bridge`) with the hop-1 served text
  and the question. The prompt is `BRIDGE_PROMPT` in `rr2hop.py`: name the entity the question refers to only
  indirectly, preferring the most recent statement; reply with the name or NONE. It sees only surviving retrieved raw
  text and the question (no gold, ledger or deletion metadata).
* **Hop 2.** Cosine top-50 → rerank on `f"{entity} {question}"`.
* **Merge.** Interleave the hop-1 and hop-2 ranked lists (h1[0], h2[0], h1[1], h2[1], …), drop duplicates, prefix-fill to
  the same B = 2000 with E2's budget law.
* **Answer.** The E2 answer prompt (`render_prompt(…, E2_PREFIX)`), same model.
* **Fallback.** If the bridge call fails or returns NONE or an unparseable name, serve hop 1 only, which is the same as RR.
* **Scoring.** E2 `score()` strict. Paired against E2's saved A6, RR and A6-syn answers and the RR-agg exploration.
  Per-stream mean differences, t-CI over 32 streams (95%; 97.5% also reported for the two co-primary contrasts).

## Prediction (Research, estimates)

* Bridge entity equals the gold ref-leaf person on **≥ 85%** of tasks. RR already serves a ref-leaf chunk on 316/320
  (AUDIT), but some of those are stale owners.
* The attr leaf is served on a majority of tasks, against 8/320 for RR.
* **RR-2hop accuracy ≈ .45 (range .40–.52). A6 − RR-2hop ≈ +2pp (range −4 to +6pp).** So I expect the shelve or
  in-between branch, more likely shelve.
* What could keep A6 ahead: stale owner picked by the bridge, the interleave pushing out hop-1 context the answer needs,
  and A6's header carrying an already-composed answer.

## Decision rule (Aditya, 19:08 IST; applied to the point estimate of A6 − RR-2hop, all 320 tasks)

| A6 − RR-2hop | Reading | Action |
|---|---|---|
| **≤ +3pp** (RR-2hop within 3pp of A6, or above it) | The DERIVED lead is a single-pass retrieval artifact | **Shelve E3**; add this to the paper |
| **≥ +6pp** | A6 still leads | **Freeze E3 with RR-2hop as co-primary** (prepare the freeze candidate; don't freeze or launch) |
| between +3 and +6pp | ambiguous | Recommend, with reasons |

## Budget and quota

* Calls: 320 bridge + 320 answer = 640.
* Estimate: about 1.2–1.6M tokens (input ≈ 2.4k per call, plus reasoning output). This is an estimate.
* Live quota before the run (`Quota().read()`, 19:14 IST): **5-hour window 70% remaining, weekly 86% remaining.**
* PauseGate floor 2%; cache under `_cache/` (gitignored).

## Addendum 1 (19:19 IST; heading originally mis-stamped 19:32): bridge prompt fixed after an aborted first pass

* **What happened.** The first pass (v1 prompt, committed in b8de60d) was stopped after 38 of 320 tasks (109 calls;
  146,015 input + 8,816 output + 23,050 cache-read tokens). The v1 prompt ("name the entity the question refers to")
  was read by the model as "answer the question": the bridge returned the answer value ("Austin", "Ads Ranking team")
  or NONE, and matched the gold ref person 0/38 times. That makes hop 2 meaningless, so the arm was not the fair
  retriever asked for. v1 outputs are kept in `v1-aborted/` and are not scored.
* **Fix (design unchanged otherwise).** `BRIDGE_PROMPT` now says "Do not answer the question" and asks for the full
  name of the person connected to the named service or project (its owner or lead), preferring the most recent
  statement, or NONE. It still sees only the question and the hop-1 served surviving text.
* **Smoke.** 12 tasks under v2 (24 calls; these are reused from cache in the full run): the bridge named the gold ref
  person on 8/12 and the answer was correct on 8/12.
  * I saw these outcomes before the full run. The prediction and the rule above are **unchanged**.
* The full 320-task pass uses the v2 prompt.
