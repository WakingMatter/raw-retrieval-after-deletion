# E3 explore: RR-agg on E2's DERIVED tasks — PREDICTION (written before any RR-agg call)

Written 24 Oct 2026, 18:50 IST, before launch (live quota at 18:50 IST: 5-hour window 71% remaining, weekly 86%). **Exploratory and post hoc.** The DERIVED lead (E2 class breakdown,
A6−RR +0.109 [+0.061, +0.157]) was found after E2's data were seen, and this check reuses the same 320 E2 CONFIRM
DERIVED tasks (32 streams × 10). It cannot confirm anything; it only decides whether a confirmatory E3
(`prereg-E3/PREREG-E3-DRAFT.md`) is worth freezing.

## What is run
RR-agg, as specified in the PREREG-E3 draft §3, applied to E2's frozen RR retrieval outputs (no re-retrieval, no rerank;
E2 `e2/` untouched):
1. **Note call** (same model MiniMax-M3.1-Flash, same API client/system prompt/effort as E2): E2's A6 summary instruction
   verbatim (`P_A6_SYN` with "≤ 50 words", the exact string A6 used in E2), then the question the excerpts were retrieved
   for, then RR's served raw units for that task in RR's rank order, formatted as A6 formats synth inputs
   (`[YYYY-MM-DDTHH:MM] text`). The note sees no gold, ledger or deletion metadata.
2. The note is capped exactly as A6 summaries (`cap_summary`, 200 est. tokens incl. label) and placed in the header slot
   (`[summary:rr] …`, ≤ B/5). Raw fill = prefix of RR's ranked served list up to B − header (B = 2000), i.e. what RR's
   own fill would give with that header.
3. **Answer call**: E2's answer prompt (`render_prompt`, `E2_PREFIX`), header then raw, scored with E2 `score()` (strict).
Reuse check (done before launch, no API): rebuilding RR's E2 answer prompts from the RR store reproduces all 320 E2 RR
cache keys exactly. A failed call scores 0 (E2 rule).

## Prediction
RR-agg closes most of the A6−RR DERIVED gap: A6 − RR-agg ≈ 0 to +4pp (vs A6 − RR +10.9pp), with the gain concentrated in
deletion-touched tasks where A6's summary carried the gold (E2: A6 .517 vs RR .157 on 89 such tasks).

## Decision rule (on the point estimate of A6 − RR-agg, per-stream paired mean over 32 streams; CI reported alongside)
* **A6 − RR-agg ≤ +0.03** (RR-agg within 3pp of A6, or above it): the DERIVED lead is explained by *when* aggregation
  happens. **Shelve E3**; record this as a paper finding.
* **A6 − RR-agg ≥ +0.06** (RR-agg at least 6pp below A6): **E3 is worth freezing.**
* **Between +0.03 and +0.06**: report the numbers and recommend; no automatic decision.

## Reported
A6, RR, RR-agg accuracy; A6−RR-agg and RR-agg−RR with per-stream paired 95% t-CIs; split by deletion-touched ×
gold-in-A6-summary (as the PREREG-E3 draft §8 table); note-contains-gold rate; tokens (live usage) and live MiniMax
quota readings before and after.
