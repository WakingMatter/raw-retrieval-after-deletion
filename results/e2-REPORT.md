# E2 confirmatory report (CONFIRM, 32 streams)

*Written 24 Oct 2026 ~18:45 IST from `runs/CONFIRM/CONFIRM-REPORT.json`, produced by `scripts/confirm_report.py`
(the frozen `e2/analysis.py`, strict scoring). Prereg `prereg-E2/PREREG-E2.md` rev 5, sha256 `271fabc0…70b8`;
`verify_frozen()` = [] (no frozen file changed). Answerer: MiniMax M3.1 Flash via the Token Plan API, one model for
every arm. 32/32 streams complete, 0 missing, 3,840 answer rows (1,280 paired tasks × 3 arms).*

Arms: **A6** = computed memory serving keyed summaries plus raw text; **A6-syn** = the same memory with no
synthesized summaries; **RR** = dense retrieval + cross-encoder rerank over surviving raw paragraphs. B = 2,000 tokens.
Differences below are in accuracy (proportion correct); 0.057 = 5.7 percentage points.

## 1. Prespecified outcome

**O2 — raw non-inferior / K-thesis fires.** H-ADV fails; H-NI holds.

- **A6 − RR:** mean −0.057; 95% CI [−0.087, −0.027]; 97.5% CI [−0.091, −0.023] (n = 32 streams).
  H-NI: 95% upper bound −0.027 < +0.10 → holds. H-ADV needs the 97.5% lower bound > 0 → fails.
- **A6 − A6-syn:** mean +0.034; 95% CI [+0.010, +0.057]; 97.5% CI [+0.007, +0.060]. This half of H-ADV passes
  (lower bound > 0), but H-ADV needs both contrasts.

**Direction in plain words.** Raw retrieval with reranking was not just "good enough": it was *better* than computed
memory, by about 6 points overall, with the whole 95% CI below zero. Within computed memory, serving the synthesized
summaries helped by about 3 points compared with not serving them, so **K-synth does not fire** (its CI excludes 0).
By the frozen rule, the claim "computed memory beats raw retrieval after deletion" is killed for this setting. (O2
covers both "raw ≈ A6" and "raw > A6"; this run is the second case. A6 is not described as non-inferior to RR.)

Registered prediction (Research): O2 or O3. Observed: O2. The prediction's "any gain would be on AGG/DERIVED" half
was half right: see DERIVED below.

## 2. Accuracy by arm (strict)

| Arm | All | AGG | DERIVED | MULTIHOP | CURRENT |
|---|---:|---:|---:|---:|---:|
| A6 | 0.550 | 0.472 | 0.472 | 0.506 | 0.750 |
| A6-syn | 0.516 | 0.413 | 0.356 | 0.534 | 0.763 |
| RR | 0.607 | 0.544 | 0.363 | 0.750 | 0.772 |

## 3. Per-class contrasts (descriptive only; not prespecified tests; 320 tasks per class)

| Class | A6 − RR, mean [95% CI] | A6 − A6-syn, mean [95% CI] |
|---|---|---|
| AGG | −0.072 [−0.137, −0.007] | +0.059 [−0.001, +0.119] |
| DERIVED | **+0.109 [+0.061, +0.157]** | **+0.116 [+0.070, +0.162]** |
| MULTIHOP | **−0.244 [−0.298, −0.190]** | −0.028 [−0.059, +0.003] |
| CURRENT | −0.022 [−0.067, +0.024] | −0.013 [−0.049, +0.024] |

- DERIVED is the one class where computed memory beat raw, by about 11 points, and where the summaries carry the gain.
- MULTIHOP drives most of the overall deficit: RR is about 24 points ahead. In the design descriptors, the gold sits in
  A6's served headers on only 37/320 MULTIHOP tasks (vs 168/320 DERIVED, 152/320 CURRENT). [INFERENCE, not tested:
  that low header coverage plausibly explains the MULTIHOP gap.]
- AGG: RR slightly ahead; summaries' help on AGG is borderline (CI touches 0).
- These per-class results were not powered or prespecified as confirmatory tests and should not be quoted as such.

## 4. Sensitivity analyses (all agree with the primary)

- **S1, excluding all-arm-fail tasks** (335 tasks where all three arms were wrong; 945 remain): O2. A6 − RR −0.077,
  95% CI [−0.117, −0.037]; A6 − A6-syn +0.046 [+0.015, +0.077]. Here A6 would also fail a reverse 10-point
  non-inferiority test (lower bound −0.117 < −0.10); that reverse test is descriptive only.
- **S2, lenient scoring:** O2. A6 − RR −0.057 [−0.086, −0.028]; A6 − A6-syn +0.034 [+0.011, +0.057].
- **S3, all classes:** same as primary. No class was floored (all-arm-wrong counts AGG 87, DERIVED 149, MULTIHOP 56,
  CURRENT 43 of 320).

## 5. Treatment delivery (K-delivery)

Summary-served rate on A6 probes: **100%** in AGG, DERIVED, MULTIHOP and CURRENT (threshold 80%). Summaries per probe:
2 on 1,167 probes, 3 on 113. Node status: 2,673 served, 1,137 skipped (no fit), 30 none. Final summary caches: 401,
of which 298 (74%) were truncated to the 200-token cap; median cost 248 raw → 185 served est. tokens.
So this is a valid treatment test: A6 lost while actually delivering its summaries.

## 6. Leaks and failures

- **Leaks:** 0 leak units in all 32 streams (no unit, write-back, summary dependency or RR chunk derived from a deleted
  session).
- **Answer failures:** 0 failed answer calls and 0 max-token stops in every arm.
- **Abstentions** (of 1,280 each): A6 182, A6-syn 210, RR 127. Answers mentioning a wrong value: A6 139, A6-syn 167,
  RR 177.
- **API:** 4,160 answer + 1,152 synth calls; 5 synth calls logged as failed. 1,268 transient errors were retried:
  1,264 Token Plan rate limits (HTTP 429, code 2062) and 4 network timeouts. Every stream finished with all 120 rows.

## 7. Tokens and cost against the frozen ceiling

Totals (API usage): input 8.54M, output 3.45M (≈12.0M input + output), plus 1.35M cache-read input. Pre-run estimate
was 13.3M (base) to 18.7M (high + reserve); the run came in under the base estimate.

Per-stream frozen ceiling (A6 ≤ 564,542 tokens and ≤ 59 synth calls; RR ≤ 100,233 tokens and ≤ 76 reranker CPU-s):
**breached, so `cost_bounded` = false.**
- Reranker CPU-seconds exceeded 76 on 8 streams (7260004, -08, -12, -16, -20, -24, -28, -32; max 93.1 s). These are the
  fourth stream of each process group, consistent with CPU contention from 8 parallel processes.
- A6 tokens exceeded the cap on 1 stream (7260031: 588,546 tokens, 56 synth calls).
- Typical per-stream spend: A6 ~320k–385k tokens and 121–130 calls; RR ~65k–68k tokens and 40 calls.

Per the frozen overrun rule this only qualifies an O1 outcome; the outcome here is O2, so it does not change the
result. It is reported as a deviation from the cost plan. Raw retrieval used roughly a fifth of A6's tokens per stream.

## 8. Limitations

- One mid-size answerer (MiniMax M3.1 Flash); no strong-model calibration was run (prereg §4). Arm rankings may differ
  with stronger answerers.
- One synthetic, seed-deterministic generator, one budget (B = 2k), one deletion schedule. MULTIHOP is a bridge-linked
  co-mention task, not free-standing compositional reasoning.
- Per-class results are descriptive; the DERIVED advantage is a lead for a follow-up, not a confirmed finding.
- 74% of served summaries were truncated to the 200-token cap; a different cap could change A6's numbers.
- The cost ceiling was breached (reranker CPU on 8 streams; A6 tokens on 1), so cost statements are qualified.
- This is a post-deletion utility study only; it says nothing about leakage or deletion-induced utility loss.
- Process note: `runs/CONFIRM/summary.json` holds only the last process group's summary (4 seeds, wall 5,257 s); the
  32 per-stream `answers.jsonl` files and `CONFIRM-REPORT.json` are the record.
