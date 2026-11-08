# E3 exploration: RR-2hop vs A6 on E2's 320 DERIVED tasks — REPORT

**Run:** 24 Oct 2026, about 19:22–19:31 IST. **Exploratory and post hoc.** These are the same tasks in which the lead
was found, and the bridge prompt was fixed after an aborted first pass (PREDICTION.md, Addendum 1).
Prediction and rule were committed before any call (b8de60d; addendum 5370186).

## Result

Strict accuracy, n = 320 (32 streams × 10); per-stream paired t-CIs:

| Arm | Accuracy |
|---|---|
| **RR-2hop** | **.659** |
| A6 | .472 |
| RR | .362 |
| RR-agg | .359 |
| A6-syn | .356 |

| Contrast | Mean | 95% CI | 97.5% CI |
|---|---|---|---|
| **A6 − RR-2hop** | **−0.1875** | [−0.242, −0.133] | [−0.251, −0.124] |
| A6 − RR | +0.109 | [+0.062, +0.157] | [+0.054, +0.165] |
| RR-2hop − RR | +0.297 | [+0.242, +0.351] | — |

Discordant pairs: 76 tasks have RR-2hop right and A6 wrong; 16 have A6 right and RR-2hop wrong. 135 are both right and
93 both wrong.

**Rule outcome: A6 − RR-2hop = −18.75pp, which is ≤ +3pp. → SHELVE E3.** The DERIVED lead is a single-pass retrieval
artifact: a two-step raw retriever under the same 2,000-token budget and the same answer prompt beats A6 by about 19pp.
My prediction (A6 − RR-2hop ≈ +2pp, range −4 to +6) was wrong in direction and size.

## Strata

| Subset | n | A6 | RR | RR-2hop | A6 − RR-2hop [95% CI] |
|---|---|---|---|---|---|
| touched | 188 | .319 | .149 | .574 | −0.270 [−0.363, −0.176] |
| untouched | 132 | .689 | .667 | .780 | −0.093 [−0.186, −0.001] |
| gold in A6 header, touched | 89 | .517 | .157 | .618 | −0.160 [−0.297, −0.024] |
| gold in A6 header, untouched | 79 | .797 | .671 | .823 | −0.004 [−0.086, +0.078] |
| gold not in header, touched | 99 | .141 | .141 | .535 | −0.373 [−0.483, −0.263] |
| gold not in header, untouched | 53 | .528 | .660 | .717 | −0.261 [−0.447, −0.076] |
| no surviving inference statement of gold (composition needed) | 207 | .261 | .029 | .522 | −0.267 [−0.345, −0.189] |
| surviving inference statement states gold (one hop) | 113 | .858 | .973 | .912 | −0.090 [−0.205, +0.026] |

RR-2hop is at or above A6 in every stratum. The one place it trails RR is one-hop tasks (.912 vs .973): interleaving
hop-2 chunks sometimes displaces hop-1 context the answer used.

## Diagnostics

* **Bridge call.** 320/320 ok; it named someone on 309 and NONE on 11. It matched the gold ref-leaf person on
  **258/320 (81%)**. Misses were mostly a stale owner or lead.
  * Accuracy when the bridge is right: .756; when wrong or NONE: .258.
* **Served context.** The attr leaf was served on **240/320** (RR: 8/320), the ref leaf on 310, and both on 238.
  The maximum served estimate was 1,999.85, so it stays within B.
* **Answers.** 320/320 ok, 20 abstentions, 66 mention a wrong value.
* **Oracle ceiling (zero API, `offline_diag.py`).** With the gold person as the bridge entity, the attr leaf would be
  served on 292/320. The real bridge reached 240.
* **RR-k (top-200 → rerank → fill, zero API, `offline_diag.py`).** The attr leaf is in the top-200 pool on 121/320 but
  served on only **27/320**. The ref leaf drops to 255/320 served, from RR's 316, because the larger pool lets
  question-similar distractors outrank it. **RR-k does not reach the second hop, so RR-2hop subsumes it as the fair
  retrieval control.**

## Tokens and quota (live MiniMax API, cached, PauseGate 2%)

| Pass | Calls | Input | Output | Cache-read |
|---|---|---|---|---|
| v1 (aborted, bad bridge prompt, not scored) | 109 | 146,015 | 8,816 | 23,050 |
| v2 smoke (12 tasks) + full 320 | 638 live (+26 cache hits) | 856,833 | 61,684 | 137,804 |
| **Total live** | **747** | **1,002,848** | **70,500** | **160,854** |

* The total is about **1.23M tokens** including cache-read, against the ~1M asked for. The overrun is the aborted v1 pass.
* The v2 rows' recorded usage, counting cache-hit rows at their original usage, is 858,128 / 61,816 / 139,596. That is
  about 3.3k tokens per task, roughly half for the bridge (428,582 input + 38,839 output).
* There were 54 transient error events, all retried successfully: 38 rows had a retried call, and 0 calls failed.
* **Quota, live `Quota().read()`:**

| Reading | 5-hour window remaining | Weekly remaining |
|---|---|---|
| Before, 19:14 IST | 70% | 86% |
| After, 19:31 IST | 68% | 86% |

## Caveats (why this is exploratory, and what favours RR-2hop)

1. **Same tasks as the discovery, post hoc design.** The bridge prompt was revised after seeing 38 v1 outputs and
   12 v2 smoke outputs.
2. **The bridge prompt knows the DERIVED question shape** ("names a service or project and asks about a person connected
   to it"). A6's summaries are query-independent. A fully generic bridge prompt might do somewhat worse.
   * Even so, the gap would have to shrink by more than 22pp to reach the freeze threshold.
   * The real bridge's 81% entity accuracy is well below the oracle ceiling.
3. **Cost is not matched.** RR-2hop spends about 3.3k tokens per probe (two calls), against about 1.7k for RR. A6 spends
   about 224k lifecycle tokens per stream plus its answers.
4. A6 is E2's configuration (74% of summaries truncated at the 200-token cap). This does not test a better-tuned A6.

## Files

* `PREDICTION.md`, `run_rr2hop.py`, `analyze.py`, `common.py`, `offline_diag.py`
* outputs: `rr2hop_answers.jsonl`, `RESULTS.json`, `offline_diag.json`, `offline_diag.log`, `api-events.jsonl`, `run.log`
* `v1-aborted/`: the v1 rows, kept unscored
