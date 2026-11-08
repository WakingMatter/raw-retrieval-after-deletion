# E3 explore: RR-agg on E2 DERIVED (exploratory, post hoc)

The prediction and decision rule were committed before any call (5878cba). The run started at about 18:50 IST and ended at 18:59 IST.

## Setup
- 320 E2 CONFIRM DERIVED tasks across 32 streams.
- RR's retrieval was reused exactly: 320 of 320 answer-prompt cache keys were reproduced.
- One note call per task: A6's synth instruction, capped at 50 words, using RR's served raw text. The note goes in the header slot and RR raw fills the rest of B.
- Scored with `e2.tasks.score`, paired against E2's saved A6, RR and A6-syn answers.
- CIs are per-stream paired t-CIs at 95%.

## Results (strict accuracy; lenient is identical)
| subset | n | A6 | RR | RR-agg | A6-syn | A6−RR-agg [95% CI] | RR-agg−RR [95% CI] |
|---|---|---|---|---|---|---|---|
| all | 320 | .472 | .362 | .359 | .356 | +.113 [+.067, +.158] | −.003 [−.020, +.014] |
| touched | 188 | .319 | .149 | .160 | .170 | +.149 [+.081, +.218] | +.008 [−.003, +.019] |
| untouched | 132 | .689 | .667 | .644 | .621 | +.034 [−.073, +.141] | −.017 [−.049, +.016] |
| hdr-gold, touched | 89 | .517 | .157 | .169 | .169 | +.358 [+.213, +.504] | +.004 [−.004, +.013] |
| hdr-gold, untouched | 79 | .797 | .671 | .684 | .646 | +.143 [+.028, +.258] | +.012 [−.013, +.036] |
| hdr-nogold, touched | 99 | .141 | .141 | .152 | .172 | −.006 [−.053, +.040] | +.009 [−.010, +.028] |
| hdr-nogold, untouched | 53 | .528 | .660 | .585 | .585 | −.145 [−.322, +.031] | −.073 [−.145, −.002] |

On these tasks, A6−RR is +.109 [+.062, +.157].

Note diagnostics:
- All 320 notes and all 320 answers succeeded. 4 notes were truncated by the cap.
- 121 of 320 notes contain the gold literal; A6's served summaries contain it on 168 of 320 tasks.
- The mean header is about 87 est. tokens.

## Decision
The decision rule is applied to the point estimate. A6−RR-agg is +11.3pp, which is above the +6pp threshold, so the outcome is **FREEZE-worthy (E3 is worth freezing)**.

The prediction (0 to +4pp) was wrong. Aggregating at query time on RR's retrieval does not reproduce A6's DERIVED lead: RR-agg ≈ RR.

The lead sits in the tasks where A6's summary carries the gold literal. On touched tasks, A6's summaries were built before the deletions and so they still hold the value. RR's retrieved raw text no longer holds it, so a note written from that text cannot recover it.

## Cost (live)
- 640 calls, all succeeded. 58 retried transient errors.
- Tokens: 798,881 input, 98,624 output and 131,577 cache-read, for a total of about 1.03M. The note calls account for 363,762 input and 89,065 output of that.
- Quota: 5-hour window 71% → 70% remaining; weekly 86% → 86% (18:50 → 18:59 IST).


## Correction (19:10 IST)
The mechanism paragraph above (A6 summaries "built before the deletions") is wrong; see AUDIT.md. Served summaries were recomputed after deletion with clean lineage; the lead comes from A6's header supplying the second-hop fact that RR's retrieval does not reach.
