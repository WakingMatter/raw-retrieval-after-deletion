# E4-sensitivity: defaults and fixes ledger

One row per decision. Each row says what was decided, why, and when. Rows are added in order and never rewritten;
a later row can supersede an earlier one by number. Times are IST.

## D01 · 20:33 · Generic-bridge DEV acceptance criteria (written before the v1 pilot summary was read)

The v1 pilot was launched at 20:19, before Astra's F07/F11 asked for criteria to be fixed first. These criteria were
written after launch but **before any pilot output was opened** (`runs/BRIDGE-PILOT-v1/SUMMARY.json`, `rows.jsonl`).
Unit: DEV seeds 7289001 and 7289002, 40 tasks each, B ∈ {500, 2000, 8000}. Expected bridge entity per task:
MULTIHOP → the hop entity; DERIVED → the current reference-slot value; AGG/CURRENT → NONE.

A prompt version is ACCEPTED if all three hold, pooled over the two DEV seeds:
1. NONE (or unparseable) on ≥ 80% of AGG + CURRENT task×B rows (the bridge must not drag in noise);
2. a correct entity on ≥ 60% of MULTIHOP + DERIVED rows at B = 2000;
3. RR-2hop accuracy ≥ RR accuracy − 0.05 over all rows (no gross harm).

At most 2 revisions after v1 (v2, v3). Each revision is written here, with its reason, before it runs. If no version
passes, the best version by criterion 2 among those meeting criterion 3 is frozen, and the failure is reported. DEV
results are never pooled with MAIN, and no prompt is changed after the freeze.

## D02 · 20:30 · Astra hostile review: receipt

One review, using gpt-6-astra via Codex CLI at xhigh effort.
- Prompt: `astra-2026-10-25/E4-hostile-review/prompt.md`. Output: `E4-hostile-review.md`.
- Weekly Codex use, read live from `account/rateLimits/read`: **3% before** (20:14:34) and **5% after**
  (20:30:33). That is **2 points**. The watchdog kill threshold of 90% was never approached.
- Verdict **FIX-THEN-RUN**, with 13 findings: 3 blocker, 8 must-fix, 2 should-fix. All 13 are accepted as valid.
  D03–D12 record each fix. Findings that only apply to an arm we no longer run are marked moot, with the reason.

## D03 · 20:42 · gen_long built; long histories do NOT put support above B (step 2, F03/F08)

- **Build.** `e4/gen_long.py` scales the schedule literals by L and adds CHAIN_LEN supersessions per SUPERSEDE key.
  It uses 3-digit ids only when (L, C) ≠ (1, 1). At (1, 1) it delegates to the unchanged eng-pin modules.
- **Identity check.** L = 1, C = 1 output is byte-identical to eng-pin on 3 seeds (7280001, 7280005, 7289001;
  67 files each), recorded in `runs/GEN-LONG-IDENTITY.txt`. A separate check on 7280017 was also identical. The
  forked schedule at (1, 1) also gives an identical ledger. Test: `e4/test_gen_long.py`.
- **Support at L = 4** (seeds 7280001–4, 160 tasks each, measured with `e4/long_support.py`):

  | Setting | Stream tokens (median) | Union support median / max | Minimal support median / max | Tasks above B = 500 |
  |---|---:|---:|---:|---:|
  | C = 3 | 338,486 | 114 / 340 | 106 / 196 | 0 |
  | C = 1 | 338,968 | 118 / 291 | 104 / 193 | 0 |

  C = 6 failed an eng-pin warm-up assertion and was not pursued.
- **Why.** Support is bounded by the facts a task needs, not by history length. AGG's distinct-value count is capped
  by the value pools (≤ 16), and CURRENT needs only the latest fact (F03).
- **Decision.** T0 is NOT run, as the brief requires ("only if step 2 succeeded"). P6 (Aditya's long-history
  hypothesis) is withdrawn as untested on this generator, not refuted. F08 and F09 are moot for this run; they
  constrain any future long-history generator.

## D04 · 20:42 · Capacity probe: add an F0 rung at B = 125 (F03)

- **Necessary-support estimate.** "Minimal" support is the cheapest paragraph per needed leaf fact. This is the
  necessary-support estimate; the union measure over-counts redundant evidence (F03). Zero-count AGG tasks need no
  positive support.
- **Measured on the 16 MAIN streams** (640 tasks): minimal support exceeds B on 22.7% of tasks at B = 125 (DERIVED
  0.41, MULTIHOP 0.43, AGG 0.07, CURRENT 0) and on 0% at B = 250.
- **Decision.** B = 125 is the only budget on this generator where necessary support crosses B. It is added as
  family F0, the capacity family, with two A6 cells: share 1/5 (header 25) and share 2/5 (header 50). Both use
  nominal cap 200, so the effective caps are 25 and 50.
- **Comparators at B = 125:** RR, RR-2hop and A6-syn.
- **Report.** Accuracy restricted to tasks whose minimal support exceeds B is reported descriptively. B = 250 is
  not added, because no task's necessary support crosses it.

## D05 · 20:42 · Claim rule made executable (F01, F04)

- **Families.** F1 = the five T1 cells, B ∈ {500, 1000, 2000, 4000, 8000} at A6 (1/5, cap 200). F0 = the two
  B = 125 cells. Familywise one-sided α = 0.05, split Bonferroni-style into **α = 0.025 per family**, with Holm
  within each family.
- **Per-cell test.** This is an intersection-union test. For each required comparator C, run a one-sided paired
  t-test (df = 15) on the per-stream mean of A6 − C, with H0: Δ ≤ 0. The cell's p-value is the **maximum** over
  its comparators.
- **Required comparators:** RR, RR-2hop and A6-syn at every B, plus RR-K at B ∈ {4000, 8000}. Including A6-syn
  (F04) means a claimed niche is attributable to the computed summaries, not to A6's cluster routing.
- **Claim.** "Computed memory has a niche" if any cell is Holm-significant in its family. The reduced test
  without A6-syn is reported descriptively as a "retrieval-package advantage". It cannot carry the claim.
- **Reporting.**
  - Two-sided 95% paired t-CIs are shown unadjusted.
  - Each comparison also gets a one-sided lower bound at the Bonferroni level α_fam / k (conservative).
  - A stream bootstrap (10,000 resamples of whole streams) is a check, not the test.
- **T2–T4 cells** are exploratory. They are reported with Holm over their own set, but they **cannot** carry the
  claim or the kill. "Strongest raw arm" means the tested raw arms only.

## D06 · 20:42 · Kill rule replaced by a margin-based scoped kill (F02)

- **Margin.** δ = +0.05 accuracy, the smallest advantage worth building for.
- **Scoped kill.** For every cell in F1 ∪ F0 (7 cells), the one-sided upper confidence bound on A6 − RR at
  level 1 − 0.05/7 (Bonferroni) must be below +0.05. The verdict is then "no meaningful accuracy niche for this
  A6 at these budgets". It is scoped to:
  - this generator, at short history only;
  - this recency-window summarizer (≤ 50-word prompt);
  - MiniMax-M3.1-Flash;
  - the tested raw arms.
- **Inconclusive.** If neither the claim nor the kill holds, the verdict is "inconclusive", and every cell whose
  upper bound reaches δ is listed.
- **Not covered.** No long-history kill is possible (D03). Nothing is said about cells that were not sampled.

## D07 · 20:42 · Estimand, shared warm state, summary failure policy (F05)

- **Estimand.** The stream-mean paired strict accuracy (E2 `score`) over the stream's 40 tasks. Classes are fixed
  at 10 each, so the class weights are equal and fixed.
- **Conditions.** The estimand is conditional on the reference warm policy: warm once per stream at B = 2000,
  share 1/5, cap 200, with E2 write-backs. It is also conditional on the cached-draw procedure: one response per
  (role, prompt, model, effort), reused.
- **Summary materialization** (`run_e4.A6Run`, `materialize`):
  - After integrity checks, every summary any task's top-3 nodes need is synthesized once.
  - A failed synth is retried once, then frozen as "none" for every cell, so there are no order-dependent later
    retries.
  - The raw text, its sha256, deps, key and cost are written to the stream output.
- **Lifecycle claims.** Cell-specific warm trajectories are not run, so no lifecycle claim is made.

## D08 · 20:42 · T1 is a reference-policy ladder; occupancy is logged (F06)

- **What T1 varies.** T1 varies B under the policy (share 1/5, cap 200), so the effective cap and the header
  occupancy move with B. It is reported as a policy ladder, not as a factor effect.
- **Exploratory contrasts.** Cap and share effects are estimated within B, in T2–T3.
- **Logging.** Every A6 row logs header tokens, raw tokens, number of summaries served and pool exhaustion.
- P6 is withdrawn (D03).

## D09 · 20:42 · RR-K pinned; generic bridge actually wired (F07)

- **RR-K.** K = ⌈2B / c̄⌉, clamped to [50, 600].
  - c̄ is the mean `item_cost` of the stream's surviving RR items, rendered exactly as RR serves them, at the
    query time. It is computed per stream.
  - RR-K applies at B ∈ {4000, 8000} only.
  - Each row logs K and pool exhaustion.
- **Generic bridge.** E3's `RR2Hop` class is not used, because it hard-codes the DERIVED bridge. `run_e4.py` calls
  `bridge_prompt_generic` itself, using the same `ranked`, `interleave`, `parse_entity`, `hop2_query` and `fill`.
- **DEV qualification.** D01 sets the acceptance criteria and the revision limit. RR stays a comparator whatever
  the bridge result is.

## D10 · 20:42 · T4 redefined as a length-instructed contrast at identical serving cells (F10)

- **Variants.**

  | Variant | Synth instruction (replaces "≤ 50 words") | Served at |
  |---|---|---|
  | len100 | "≤ 50 words, and keep your whole reply under 100 tokens" | B = 2000, share 1/5, cap 100 |
  | len400 | "≤ 200 words, and keep your whole reply under 400 tokens" | B = 2000, share 1/5, cap 400 |

- **Comparison.** Each is compared with the reference prompt at the identical serving cell, which is in T2.
- **Inputs.** The inputs are identical post-delete states: the warm phase is replayed from the response cache with
  the reference prompt, and only probe-time summaries are re-synthesized. Cache keys separate automatically,
  because the prompt sha256 enters the key.
- **Uncapped.** Dropped. At B = 2000 with share 1/5 the header is 400 tokens, so uncapped equals cap 400.
- **Naming and compliance.** The variants are called "length-instructed", not "matched". Compliance (the share of
  raw summaries at or under the cap) is measured and reported. T4 is exploratory.

## D11 · 20:42 · Freeze the executable instrument (F11)

- **Hashed by `e4/make_freeze.py`.** The freeze covers:
  - the runner and analyzer;
  - the arms (bridge prompt v-final);
  - paths and seeds, and the cells and families (in PREREG-E4.md);
  - the data and tasks for the 16 MAIN streams;
  - the SUPPORT files;
  - the imported E2/E3/pilot modules.
- **Checks.** `run_e4 --confirm` calls `verify_frozen()` and asserts the seeds are the planned streams.
  `analyze_e4` asserts a complete `(seed, task, arm, cell)` inventory before scoring.
- **Integrity.** The deletion-integrity check is E2's full version: units, write-back provenance, summary deps and
  RR chunks.
- **Policies.**
  - A failed call scores as wrong and is never dropped.
  - No post-hoc exclusions, endpoint changes or resampling.
  - Reserves are used only for generator shortfall, which has already happened (7280011 → 7280017).
  - Class and subset breakdowns are descriptive.

## D12 · 20:42 · Cost and token reporting (F12, F13)

- **Dry-run counts.** These are conditional on fake content. The RR-2hop answer ceiling is task × B (3,200 for T1),
  not 2,779.
- **REPORT.md** reports the following, measured from `api-events-*.jsonl` and `elapsed_s`:
  - **metered** tokens per arm: live calls only, from the API events;
  - **logical** tokens per arm: every row's usage, including cache hits;
  - logical versus live call counts;
  - the bridge and synth costs.
- **Shared cache.** Cells that are identical in the cache are not replications. Evidence-budget matching is not
  compute matching.

## D13 · 20:41 · Bridge pilot v1 result, and v2 (written before v2 runs)

v1 (`runs/BRIDGE-PILOT-v1/SUMMARY.json`, 578 live calls, 796,845 in / 84,136 out tokens, measured) **failed**:
criterion 1, NONE on AGG + CURRENT = 0.758 (91/120; needs ≥ 0.80); criterion 2, correct entity on MULTIHOP +
DERIVED at B = 2000 = 0.45 (18/40; needs ≥ 0.60). Criterion 3 passed: RR-2hop 0.646 vs RR 0.567 over 240 rows.
Failure modes, read from rows: 15 of 22 misses at B = 2000 were NONE when a name was expected (the prompt invites
NONE when unsure). The other 7 named a different service, project or person. v1 also named an entity on 14 AGG
rows (e.g. "How many different values has Quasar's lead had") and 15 CURRENT rows (e.g. "Who owns vault-bridge?").
v2 (`e4/arms_e4.py::BRIDGE_PROMPT_GENERIC_V2`) makes two changes:
- It states the relation-versus-named test explicitly, with the four relation shapes, and says that counting
  questions and "who owns/leads X" questions are named, so they get NONE.
- It asks for the most recent best reading instead of NONE when any excerpt links the relation to a name.
  A wrong guess costs less than NONE, because hop 1 is kept in the interleave.

Same DEV seeds, same B set, same criteria. v1 is kept in code for the record.

## D14 · 20:55 · Bridge pilot v2 result, and v3 (written before v3 runs; the last revision D01 allows)

v2 (`runs/BRIDGE-PILOT-v2/`, 357 live calls, 496,643 in / 39,353 out tokens, measured) **failed and was worse
than v1**:
- criterion 1: 0.675 (81/120);
- criterion 2: 0.30 (12/40);
- criterion 3 passed: RR-2hop 0.604 vs RR 0.567.

Per class, over all three B: MULTIHOP bridge-right went from 0.45 (v1) to 0.567, but DERIVED collapsed from 0.367
to 0.017. Reading the rows: for DERIVED ("Which team is the person who owns vault-bridge on?"), v2 named the
*final attribute* (a team or city) instead of the intermediate person. The best-guess wording pushed it into
answering the question. CURRENT questions about a named person's team or city ("Which team is X on?") were also
answered instead of NONE.

v3 (`e4/arms_e4.py::BRIDGE_PROMPT_GENERIC_V3`) makes these changes:
- It states the job as naming an intermediate.
- It lists the expected reply type for each relation shape (person, service, project).
- It forbids attributes (team, city, region, date, number).
- It lists named-subject question types (who owns or leads a named thing; a named person's team or city; how many
  values) as NONE.
- It keeps v2's most-recent best guess.

Same DEV seeds, B set and criteria. **Freeze rule (D01):** if v3 passes, freeze v3. If not, freeze the version
with the best criterion 2 among those meeting criterion 3, and report the failure. RR-2hop then stays as a
comparator with a known-weak bridge, and the bridge accuracy is reported.

## D15 · 21:00 · Run order: confirmatory pass first, exploratory pass second (written before any CONFIRM call)

Throughput is set by the Token Plan rate limit (2062), not by our CPU. Measured on E2 CONFIRM: 5,312 live calls,
1,264 rate-limit errors, about 5,257 s wall per process group. The full E4 main phase is about 2,100 answer calls
per stream (estimate from the cell inventory), so it runs for many hours. To make the confirmatory result land
first, each stream's main phase runs in two passes:
- pass 1, `--tiers T1,F0,T5` → `main-{seed}.json`: every comparator (RR, RR-2hop with its bridge, A6-syn) at every
  B, the five T1 cells, both F0 cells and RR-K. This is everything the claim and kill rules read.
- pass 2, `--tiers T2,T3` → `main-T2_T3-{seed}.json`: the 26 exploratory cells, after pass 1 has finished on all
  16 streams.

Pass 2 rebuilds the same stream from the same cache, so warm-up and summary synth calls are memo hits. Summary
keys that failed in pass 1 are forced to "none" in pass 2 (`force_none`), so D07's rule holds: a failed summary
is "none" in every cell, with no late retry. `analyze_e4.load` concatenates the passes' rows and adds up
their reranker CPU and stage walls. `inventory` still requires each (arm, cell) pair exactly once per task and
an identical inventory on every stream. T4 runs only after a stream's pass 1 exists.
Checked with the fake LLM on DEV 7289001: pass 1 + pass 2 together give the same rows as the one-pass smoke run.

## D16 · 21:05 · Bridge pilot v3 result: passes; v3 is frozen

v3 (`runs/BRIDGE-PILOT-v3/`, 294 live calls, 410,719 in / 18,678 out tokens, 28 rate-limit errors retried; all
measured) **passes all three D01 criteria**:
- criterion 1: 0.817 (98/120) NONE on AGG + CURRENT (needs ≥ 0.80);
- criterion 2: 0.825 (33/40) correct entity on MULTIHOP + DERIVED at B = 2000 (needs ≥ 0.60);
- criterion 3: RR-2hop 0.683 vs RR 0.567 over 240 rows (needs ≥ RR − 0.05).

Per class over all three B, bridge-right is MULTIHOP 0.767 and DERIVED 0.783, against v1's 0.45 / 0.367 and v2's
0.567 / 0.017. `BRIDGE_PROMPT_GENERIC = BRIDGE_PROMPT_GENERIC_V3`. v1 and v2 stay in code for the record.
Caveat: three prompt versions were tried on the same two DEV seeds, so the DEV bridge accuracy is optimistic.
CONFIRM streams are fresh, and the bridge accuracy on them is reported from the CONFIRM rows.
Bridge-pilot spend, all three versions (measured live calls): 1,229 calls; 1,704,207 in / 142,167 out tokens.

Smoke check of D15 (fake LLM, DEV 7289001): pass 1 has 1,080 rows and pass 2 has 1,040 rows. Merged, they equal
the one-pass run's rows (53 (arm, cell) pairs, the same answers). D15's claim is verified.

Astra live usage at 21:04 IST: 7% of the weekly window. It was 5% right after the review (20:30). The review
is the only Astra job this task ran, so the extra 2 points come from other Codex use on this account.
