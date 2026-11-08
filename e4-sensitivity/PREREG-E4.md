# E4-sensitivity: preregistration (confirmatory spec)

Written 2026-10-25, before any confirmatory call. This document **supersedes §5 (predictions, claim and kill rules)
and the T0/T4 rows of §4 in `PREDICTION-AND-DESIGN.md`**. It applies the hostile-review fixes in `DEFAULTS.md`
D02–D12 (review: `astra-2026-10-25/E4-hostile-review/E4-hostile-review.md`). The executable instrument is hashed in
`E4-FREEZE.json` (`e4/make_freeze.py`). `run_e4 --confirm` refuses to start if any hash differs.

## 1. Streams, model, arms

- **Streams.** 16 fresh seeds: 7280001–7280010 and 7280012–7280017. Seed 7280011 had a generator shortfall
  (37 tasks), so reserve 7280017 replaces it. Each stream has 40 tasks (AGG, CURRENT, DERIVED and MULTIHOP, 10 each)
  and 10 warm probes, at short history (L = 1).
- **Model.** MiniMax-M3.1-Flash via the Token Plan API, with E2 settings: response cache, and PauseGate at a 2% floor.
- **Arms.** All arms reuse E2 code:
  - A6 (E2 A6E2 with cell overrides);
  - A6-syn (the same state, with no header);
  - RR (cosine top-50, then rerank, then prefix-fill);
  - RR-K (D09);
  - RR-2hop with the generic bridge prompt that passed DEV: `BRIDGE_PROMPT_GENERIC_V3` (D01, D13–D16).
- **Warm and summary policy** (D07). Warm runs once per stream at the reference config (B = 2000, share 1/5, cap 200).
  Probe-time summaries are materialized once, then frozen. Cells change only what is served.

## 2. Cells

| Set | Cells | Role |
|---|---|---|
| **F1** | A6 at (B, 1/5, cap 200) for B ∈ {500, 1000, 2000, 4000, 8000}, so eff_cap = {100, 200, 200, 200, 200} | confirmatory |
| **F0** | A6 at (125, 1/5, eff 25) and (125, 2/5, eff 50) | confirmatory (capacity probe, D04) |
| Comparators | RR, RR-2hop and A6-syn at every B ∈ {125, 500, 1000, 2000, 4000, 8000}; RR-K at 4000 and 8000 | |
| T2/T3 | the other 26 unique A6 (B, share, eff_cap) cells (`dry_run.a6_cells`) | exploratory |
| T4 | len100 at (2000, 1/5, 100) and len400 at (2000, 1/5, 400), versus the reference prompt at the same cells (D10) | exploratory |
| T0 | **not run** (D03: gen_long does not put support above B) | — |

## 3. Estimand and tests

- **Estimand.** The per-stream mean strict accuracy over 40 tasks, under the reference warm policy (D07). Contrasts
  are paired within a stream.
- **Per-cell test.** For each A6 cell c at budget B and each required comparator C:
  - run a one-sided paired t-test (df = 15) of H0: mean(A6_c − C_B) ≤ 0;
  - the required comparators are RR, RR-2hop and A6-syn, plus RR-K if B ≥ 4000;
  - cell p = max over C (intersection-union).
- **Multiplicity.** Holm within F1 at α = 0.025, and Holm within F0 at α = 0.025. The total one-sided α is 0.05.
- **Reporting.** Each comparison gets a two-sided 95% paired t-CI (unadjusted), a one-sided Bonferroni lower bound
  (α_fam / k) and a stream-bootstrap 95% CI (10,000 resamples) as a check. The variant without A6-syn is the
  "retrieval-package advantage". It is descriptive only.

## 4. Verdict rules (fixed now)

1. **CLAIM: computed memory has a niche.** At least one F1 or F0 cell is Holm-significant under the IUT. The claim
   names the cells and is scoped to the tested raw arms.
2. **SCOPED KILL.** Otherwise, if for **all 7** F1 ∪ F0 cells the one-sided upper bound of A6 − RR at level
   1 − 0.05/7 is below δ = +0.05. The verdict is then "no meaningful (≥ 5-point) accuracy niche for this A6
   versus RR". It is scoped to:
   - this generator at short history;
   - the recency-window summarizer with the ≤ 50-word prompt;
   - MiniMax-M3.1-Flash;
   - B ∈ {125, …, 8000}.
3. **INCONCLUSIVE.** Otherwise. The cells whose upper bound reaches δ are listed.

T2–T4 and all class or subset breakdowns are exploratory. They cannot change the verdict.

## 5. Predictions (directional; from §5 of the design, unchanged except where noted)

- **P1.** RR ≥ A6 at every B ≤ 4000, with the widest gap at B = 500. *Estimate:* −0.05 to −0.10.
- **P2.** At B = 8000, A6 − RR moves toward 0. A6 does not beat RR-K.
- **P3.** A6 − A6-syn > 0 at B = 2000, shrinking with B.
- **P4.** Cap 100 < cap 200 for B ≥ 1000. Cap 400 ≈ cap 200. Share 2/5 ≤ share 1/5 at B ≤ 1000.
  - *Changed (D10).* T4: the len100 prompt at cap 100 is above the reference prompt at cap 100.
- **P5.** RR-2hop ≥ RR overall, with the gain in MULTIHOP and DERIVED.
- **New (F0).** At B = 125, A6 − RR is closer to 0 or positive than at B = 500, because necessary support exceeds B
  on 22.7% of tasks (measured).
- **P6.** Withdrawn, not tested (D03).

## 6. Integrity and analysis rules

- **Failures.** A failed call is scored as wrong. No row is dropped, and there are no post-hoc exclusions.
- **Inventory.** `e4/analyze_e4.py` asserts that every stream has the same (arm, cell) set × 40 tasks, with no
  duplicates.
- **Deletion integrity.** E2's full check runs after every build.
- **Costs** (D12). Reported per arm as metered (live) and logical tokens. Wall-clock per arm is the measured
  `elapsed_s` sum plus stage walls. Reranker wall and CPU seconds are reported per arm.
- **Power** (estimate, from E2's SD of 0.0824). The unadjusted CI half-width is ≈ 0.044. Detecting ≈ 0.08 at 80%
  power needs Holm-adjusted tests. Effects below that are expected to resolve as "inconclusive" unless the upper bound
  falls below δ.
