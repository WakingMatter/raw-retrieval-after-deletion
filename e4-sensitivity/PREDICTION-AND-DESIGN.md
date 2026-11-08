# E4-sensitivity: how much do B, the summary cap, the header share and history length matter? Predictions and design

Status: DESIGN + OFFLINE DRY RUN only (25 Oct 2026). **Zero model API calls made.** Written before any E4 run.
Every token/hour number is an **estimate** unless marked "counted" (from the dry run) or "measured" (from E2/E3 logs).
Frozen E2/E3/pilot/eng-pin files are imported read-only. Nothing in them was edited.

## 1. Why

Aditya asked how three E2 choices were made: the 200-token summary cap, the synthetic generator, and B = 2000.
E2 found RR .607 > A6 .550 > A6-syn .516 (A6 − RR = −0.057 [−0.087, −0.027]); E3 found RR-2hop .659 on DERIVED.
E4 asks whether A6 has *any* region of (budget, cap, header share, history length) where it beats raw retrieval.

## 2. What the generator supports (finding that reshapes the grid)

- **Knobs:** `make_data` (eng-pin) exposes only `--seed` and `--out`. Hard-coded values: 60 sessions over 90 days,
  ~80k tokens per stream, 40 entities, 150 keys, session indices hard-coded in `schedule()`, 2-digit session ids,
  and one change per key (no supersession chains). History length is **not** a knob today.
- **Support never exceeds B, even B = 500.** Gold-support cost was measured by the Astra audit method (union of ledger
  evidence paragraphs). On E2 CONFIRM the class maxima are AGG 267.9, CURRENT 198.9, DERIVED 441.6, MULTIHOP 347.3
  est. tokens. On the 16 E4 streams (counted, 640 tasks) the medians and maxima are AGG 59.8 / 324.3, CURRENT
  62.1 / 177.1, DERIVED 143.8 / 305.9, MULTIHOP 144.9 / 284.0. **0 tasks over B = 500.** So on the current generator
  the B ladder tests *ranking precision*, not capacity. Aditya's hypothesis ("A6 gains as B shrinks below support")
  cannot be tested without longer histories.
- **Long-history fork, `gen_long` (specified, NOT implemented):** a new module beside the eng-pin generator, never
  editing it, that:
  1. scales the session-index literals in `schedule()` by a factor L ∈ {1, 4};
  2. sets N_SESSIONS = 60·L, HORIZON_DAYS = 90·L, TARGET_STREAM_TOKENS ≈ 80k·L;
  3. adds `CHAIN_LEN` supersessions per key (1 → 3) so CURRENT/AGG support grows with history;
  4. uses 3-digit session ids;
  5. passes a regression test that L = 1, CHAIN_LEN = 1 is **byte-identical** to eng-pin output for 3 seeds.

  More entities would need vocabulary expansion, which is out of scope. The goal is AGG/CURRENT support of ~600–2,000
  est. tokens at L = 4, CHAIN_LEN = 3. That is a design target, not a measurement; the generator must be run and
  support re-measured before any T0 claim.
- **RR is pool-bound at large B (counted).** The RR top-50 rerank pool is median 3,541 est. tokens (q10 2,852,
  q90 4,613). It is below B for 65.8% of tasks at B = 4000 and 100% at B = 8000. So RR at B = 8000 serves its
  whole top-50, and any A6 gain there could be an artefact of RR's fixed K. A6's raw pool is never below 8,000
  (median 23,597). **Fix: add RR-K**, the same arm with K = ⌈2·B / mean chunk cost⌉ (≈ 150 at 4000, ≈ 300 at 8000;
  estimate), at B ∈ {4000, 8000}.

## 3. Arms

A6 (E2 A6E2 with cell overrides: B, header share, cap), A6-syn (no header; diagnostic at every B), RR (E2), RR-K
(B ≥ 4000), and RR-2hop (E3 RR2Hop with a **generic** bridge prompt, `e4/arms_e4.py::BRIDGE_PROMPT_GENERIC`). The E3
bridge prompt was DERIVED-specific. The generic prompt is drafted and untested, and gets a 2-stream DEV pilot
(seeds 7289001/2) before freeze.

**Warm state is reused.** Each stream is ingested and warmed once at the E2 reference config (B = 2000, share 1/5,
cap 200). Every cell then *re-caps the stored raw synth text* (`A6E4` keeps the uncapped text), so synth calls are
shared across all cells and a cell changes only what is served. Consequence: cells differ only at read time. The
warm-phase write-backs were made at the reference config in every cell. This is stated as a design property, not
hidden.

**Cap ≠ prompt confound.** The E2 synth prompt asks for "≤ 50 words" (E2 override of the pilot's 120). Real summaries
ignore it: raw cost median 248.4, q90 484.1, and 99.3% / 74.3% / 15.5% exceed cap 100 / 200 / 400 (measured, 401
summaries). Varying the cap therefore varies *truncation* of a ~250-token summary, not the length of a summary
written to fit. **T4** adds prompt-matched caps: the synth prompt's word limit is set to the cap (100 → ≤ 60 words,
400 → ≤ 250 words, uncapped → no limit) at B = 2000, share 1/5, with fresh synth calls.

## 4. Cells and the fractional/prioritized design

Effective cap = min(cap, B·share), and cells with equal (B, share, eff_cap) collapse. The 40 nominal A6 cells
(5 B × 4 caps × 2 shares) reduce to **31 unique cells (counted)**.

| Tier | What | Unique cells | Run order |
|---|---|---|---|
| **T1** (primary) | B ladder {500, 1k, 2k, 4k, 8k} × {A6 (1/5, cap 200), A6-syn, RR, RR-2hop} | 5 A6 + 5×3 others | 1st |
| **T2** | remaining cap × share cells at B ∈ {1k, 2k, 4k} | 17 | 2nd |
| **T3** | remaining cells at B ∈ {500, 8k} | 9 | 3rd |
| **T4** | prompt-matched caps {100, 400, none} at B = 2000, 1/5 | 3 | 4th |
| **T5** | RR-K at B ∈ {4k, 8k} | 2 | with T1 |
| **T0** | long history: gen_long L ∈ {1, 4} × CHAIN_LEN ∈ {1, 3} (fractional: (1,1), (4,3), plus (4,1) to separate length from chains) × T1 ladder | 3 histories | after gen_long exists |

Streams: 16 fresh seeds `[7280001–7280010, 7280012–7280017]` (7280011 short of 3 MULTIHOP, replaced by reserve 7280017);
reserves 7280018–7280032; DEV 7289001–2. 40 tasks per stream (AGG / CURRENT / DERIVED / MULTIHOP, 10 each),
10 warm probes. Spend is approved for rigor, so **all tiers run on all 16 streams**. The tiers fix order, and fix
which comparisons are primary, not which ones get cut.

## 5. Predictions and kill/claim rules (written before any run)

Unit: the per-stream mean over 40 tasks, paired across arms within a stream. 95% CIs are a paired t-interval over 16
streams, with a stream bootstrap as a check. The primary family is the T1 A6 − RR contrast at 5 budgets, Holm-adjusted.

- **P1 (short history, T1):** RR ≥ A6 at every B ≤ 4000. The gap is widest at B = 500, because the 100-token header
  is a 99%-truncated summary taking 20% of a small budget. *Estimate of size:* −0.05 to −0.10 at B = 500.
- **P2 (RR ceiling):** at B = 8000, A6 − RR moves toward 0 or above, because RR cannot use budget beyond its
  ~3.5k pool. If A6 > RR at 8000 but A6 ≤ RR-K there, the "win" is the K artefact and **no claim** is made.
- **P3 (header):** A6 − A6-syn > 0 at B = 2000 (E2: +0.034), shrinking toward 0 as B grows.
- **P4 (cap/share, T2–T3):** cap 100 < cap 200 for A6 at B ≥ 1000. Cap 400 ≈ cap 200 (|Δ| < 0.03). Share 2/5 ≤
  share 1/5 at B ≤ 1000. T4: prompt-matched cap 100 > truncated cap 100.
- **P5 (2-hop):** RR-2hop ≥ RR overall, with the gain concentrated in MULTIHOP/DERIVED. If generic RR-2hop < RR,
  the generic bridge is the suspect, and that is reported instead of "2-hop doesn't work".
- **P6 (long history, T0; Aditya's hypothesis):** A6 gains relative to RR as B shrinks below support size and as
  history grows. Formally: the interaction [A6 − RR](L = 4, CHAIN 3, B = 500) − [A6 − RR](L = 1, B = 2000) > 0.
- **Claim rule (computed memory has a niche):** some cell has A6 − RR > 0 with Holm-adjusted 95% CI > 0, **and**
  in that cell A6 ≥ RR-K (if B ≥ 4000) and A6 ≥ RR-2hop. Otherwise it is "no niche against the strongest raw arm".
- **Kill rule:** if A6 never beats RR in any cell of T1–T4 **and** of T0 (long histories), then computed memory has
  no accuracy niche on this generator. That result is written up as such, with the caveat that the generator's
  support ceiling (≤ ~440 tokens at L = 1) was the regime tested unless T0 ran.
- **Precision:** E2 per-stream SD of A6 − RR was 0.0824, which gives a 16-stream CI half-width of ≈ ±0.044 (estimate).
  Effects below ~0.045 are reported as "not resolved", not as "no effect".

## 6. Offline dry run (counted; zero API calls)

`python -m e4.dry_run --tag DRY --streams … --vec _vec-pN`, run as 4 processes × 4 streams, each with one
`Reranker(threads=4)`. The fake LLM's synth text has realistic *length*: its cost is drawn by prompt hash from the
401 real E2 CONFIRM summary costs. Fake answers are "Not found." and the fake bridge always says NONE, so RR-2hop
answers are an **upper bound** (one per unique bridge). Calls are de-duplicated by sha256(role, prompt), mirroring
the response cache, with T0 → T1 → T2 → T3 order. Aggregation is in `e4/dry_summary.py`, output
`runs/DRY/SUMMARY.json`.

| Tier | Group | Nominal calls | Unique calls (counted) | In tok (est.) | Out tok (est.) |
|---|---|---:|---:|---:|---:|
| warm | A6 synth | 405 | 405 | 1.18M | 1.06M |
| warm | A6 answers | 160 | 160 | 0.27M | 0.02M |
| T1 | A6 synth (lazy, probe) | 177 | 176 | 0.51M | 0.46M |
| T1 | A6 answers | 3,200 | 3,200 | 7.94M | 0.32M |
| T1 | A6-syn answers | 3,200 | 3,200 | 7.55M | 0.32M |
| T1 | RR answers | 3,200 | 2,779 | 4.53M | 0.28M |
| T1 | RR-2hop bridge | 3,200 | 2,779 | 4.49M | 0.33M |
| T1 | RR-2hop answers (UB) | 3,200 | 2,779 | 4.49M | 0.28M |
| T2 | A6 answers | 10,880 | 7,118 | 13.25M | 0.70M |
| T3 | A6 answers | 5,760 | 2,766 | 9.80M | 0.27M |
| **T1–T3 total** | | | **25,362** | **54.0M** | **4.0M** |

Synth calls: 581 for 16 streams (~36 per stream; E2 had 1,147 / 32 ≈ 36, so consistent).
RR dedup comes from the pool ceiling: 421 of 3,200 RR prompts repeat a smaller-B prompt (expected mostly at B = 4000/8000, where the top-50 pool runs out).

Token constants (measured in E2/E3): answer prompt tokens = chars × 0.354; answer out 99; bridge out 117;
synth 2,923 in / 2,607 out. COST.md's synth-out of 766 understates CONFIRM's measured 2,607.

**Not counted by the dry run (estimates):**
- T4: 3 caps × 581 fresh synth ≈ 1,743 synth (≈ 5.1M in / 4.5M out) + 3 × 640 = 1,920 answers (≈ 2.4M in).
- T5 RR-K: 2 × 640 = 1,280 answers (≈ 4.5M in; B-sized prompts).
- RR-2hop generic-bridge DEV pilot: 2 streams ≈ 160 bridge + 160 answers.
- T0: answer calls ≈ T1's per history (prompts are bounded by B) → +2 × 14.9k ≈ 30k calls, ≈ 60M in. Synth and
  local ingest scale with history (≈ ×4 at L = 4, unmeasured until gen_long exists).

## 7. Wall-clock (estimates)

- API: Σ(mean latency per unique call) = 74,374 s for T1–T3. At 8 concurrent calls (429s appeared at ~16) that is
  **≈ 2.6 h**. Synth is the long tail: p90 41.2 s per call, and the warm phase is sequential per stream (~36 ×
  21.8 s ≈ 13 min per stream). Running 4 streams at a time puts T1–T3 at **≈ 3–4 h**. T4 + T5 add ≈ 1.5 h.
  T0 adds ≈ 4–8 h (wide; depends on gen_long).
- Local, measured in the dry run: ingest + warm 180–191 s per stream; full stream 223–235 s per process (4 processes
  ran in parallel with no visible slowdown vs 1). Hop-1 rerank is 30.5 s per 40 tasks (≈ 0.76 s per query, top-50).
  Hop-2 rerank is ≤ 5× hop-1 (upper bound, ≈ 2.5 min per stream). Embedding caches `runs/_vec-p0..3` are reused
  by the real run (same `--vec` per partition).
- **Total for T1–T5 ≈ 5–6 h elapsed, ≈ 65M in / 9M out tokens (estimate).** T0 is extra.

## 8. Risks and threats

1. The generic bridge prompt is untested, so RR-2hop ≠ the E3 arm.
2. Warm state is shared, so the write-back content reflects the reference config, not each cell.
3. Fake-summary lengths are sampled, not generated, so real dedup in T2/T3 could differ (estimate ±10%).
4. Support < B everywhere on L = 1. Without gen_long the headline hypothesis is untested, not refuted.
5. One model (MiniMax-M3.1-Flash), one reranker, one generator family.

## 9. Files

- `e4/paths.py`: seeds and paths
- `e4/make_data.py`: data plus SUPPLY.json, 7280011 shortfall
- `e4/arms_e4.py`: A6E4 with raw-keeping and cell re-capping, `eff_cap`, generic bridge draft
- `e4/dry_run.py`: offline driver
- `e4/dry_summary.py`: counts and estimates
- `runs/DRY/SUMMARY.json`: dry-run output (counted calls; estimated tokens)
