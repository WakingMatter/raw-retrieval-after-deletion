# T0-REDESIGN: a tier where gold support exceeds the budget B

Status: DRAFT design, not frozen, not reviewed. Zero model calls made. Written 2026-10-25 ~22:00 IST.
This file does not amend PREREG-E4.md or E4-FREEZE.json; T0 stays dropped from the frozen E4 run (D03).
Everything below marked "estimate" is an estimate. Every other number comes from `t0r/wide_support.py` (see T0-SUPPORT.md).

## 1. The gap this closes

In the frozen E4 streams almost every task's minimal gold support fits under B=500, so a budget-matched
raw-retrieval arm can in principle put all the evidence in context. That is why E4 cannot test the
case computed memory is supposed to win: **the evidence needed is larger than the budget.**
T0-redesign builds tasks whose minimal support is, by construction, many paragraphs spread across the whole stream.

## 2. Generator: `t0r/gen_wide.py` (new file, model-free, deterministic)

Each stream has 60 sessions, one every 1.5 days from 2030-01-07. Each fact paragraph holds one fact plus a filler sentence.
Noise paragraphs are added at 40% of the number of fact paragraphs. Query time is the end of the stream ("right now").
There are 40 tasks per stream, 10 in each family:

| Family | What builds the support | Question | Gold | Distractors |
|---|---|---|---|---|
| COUNT | 260 services; each has a DB migration chain of 1–4 steps over 10 DBs (Zipf popularity) | "How many services run on {db} right now?" | count of services whose *latest* DB is {db} | ~35% of services get a hypothetical, rejected or dropped migration |
| SUM | 150 teams; each states its region once (Zipf region sizes) and has a headcount chain of 1–4 steps | "Combined headcount of all teams based in {region} right now?" | sum of the latest headcounts | ~30% get "plans to grow" statements |
| DELTA | one setting; a base value plus K relative ±steps, K ∈ {6…130} | "What is {setting} of {svc} right now?" | base plus the sum of the steps | rejected or hypothetical steps |
| ARGMAX | M ∈ {15…260} incidents over 8 teams inside a disjoint 6-session window; winner margin ≥ max(2, M//20) | "Which team logged the most incidents between {d1} and {d2}?" | the top team | near-miss incident mentions |

Minimal support is every paragraph needed to derive gold:
- COUNT: the latest paragraph of every service that ever touched the DB.
- SUM: each team's region paragraph plus its latest headcount.
- DELTA: the base plus all steps.
- ARGMAX: the paragraphs for the top 2 teams.

Union support is minimal support plus every superseded or distractor paragraph about the task's entities.

Scoring reuses `e2.tasks.score`:
- COUNT, SUM and DELTA use cls AGG: exactly one distinct number, equal to gold.
- ARGMAX uses a truth_any / wrong_any regex.

Determinism check: generating seeds 7290001 and 7290009 twice gives byte-identical output.

## 3. Measured support (scale 1, seeds 7290001–7290016, 640 tasks)

Units are answer-prompt tokens, computed with `pilot.common.item_cost` on the arm-visible chunk `[sNN:SEG | t] text`.

| Family | p10 | p50 | p90 | max | >500 | >1000 | >2000 | >4000 | >8000 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| ARGMAX | 777 | 2,328 | 7,567 | 10,090 | 1.00 | 0.79 | 0.53 | 0.31 | 0.07 |
| COUNT | 1,655 | 2,956 | 9,092 | 11,643 | 1.00 | 1.00 | 0.77 | 0.33 | 0.10 |
| DELTA | 706 | 2,552 | 9,216 | 10,165 | 0.99 | 0.79 | 0.50 | 0.30 | 0.10 |
| SUM | 805 | 1,440 | 6,203 | 6,331 | 1.00 | 0.70 | 0.30 | 0.10 | 0.00 |
| **ALL** | 798 | 2,233 | 7,090 | 11,643 | **1.00** | **0.82** | **0.53** | 0.26 | 0.07 |

- A stream is about 281,562 tokens (median) and about 4,036 paragraphs, so the mean chunk is about 70 tokens.
- Mean minimal support is 3,141 tokens.
- Median paragraphs in minimal support: COUNT 39.5, SUM 21, DELTA 31, ARGMAX 30. The maxima are 94–158.
- Median union/minimal ratio: COUNT 2.84, ARGMAX 2.6, SUM 1.9, DELTA 1.22.

Over-budget tasks per stream (for cell sizes): about 39.9 at B500, 32.8 at B1000, 21.0 at B2000, 10.4 at B4000 and 2.7 at B8000.
A fresh seed block, 7290101–7290116, reproduces this: ALL shares are 1.00 / 0.82 / 0.54 / 0.26 / 0.07.
Scale 0.5 is too small (only 0.54 of tasks exceed B1000). Scale 2 doubles the stream to about 562k tokens.
**Proposal: scale 1.**

## 4. Arms (all at B ∈ {500, 1000, 2000, 4000, 8000})

- **RR**: frozen E4 RR, which is cosine top-50, then the gte reranker, then a prefix fill to B.
- **RR-K**: frozen E4 rule, K = ceil(2B/c̄) clamped to [50, 600]. With c̄ ≈ 70 this gives K ≈ 50, 50, 58, 115 and 229.
  RR-K is the budget-matched strongest raw-retrieval arm. Plain RR's top-50 cannot fill B ≥ 4000.
- **A6**: frozen E4 A6 T1 cell definition (top-3 node summaries, 1/5 share, cap 200).
- **A6-syn**: frozen E4 definition.
- **ORACLE** (new, validity gate): only the task's minimal_refs chunks, in chronological order, with no budget cap.
  One call per task. It measures whether the reader can aggregate at all.
- RR-2hop is dropped: these questions have no bridge entity.

Open design decision for Aditya: frozen A6 stores generic summaries, so it is unlikely to carry exact counts or sums.
An aggregate-aware computed arm would compute at write time (for example a per-entity ledger of latest values).
That would be the fair test of "computed memory beats retrieval when support exceeds B".
Such an arm needs its own design and pilot and is **not** specified here.

## 5. Estimand, rules and predictions (written before any calls)

**Estimand.** For each cell B, take the tasks with minimal support > B (the set S_B).
The estimand is d_B = mean over streams of the per-stream mean of (A6 correct − comparator correct) on S_B.
A stream-cluster t CI over 16 streams is used. Paired within task.

**Validity gate.** This is decided on ORACLE outcomes only, before any arm comparison is read:
- A family enters the primary analysis only if its ORACLE accuracy on S_1000 is ≥ 0.6.
- If no family passes, the verdict is **INVALID (reader-limited)**: the reader cannot aggregate even with perfect evidence, so the experiment says nothing about memory.

**Primary family.** Cells B ∈ {500, 1000, 2000, 4000}. B=8000 is exploratory because only about 2.7 tasks per stream are over budget there.
Comparators are RR and RR-K, combined by intersection-union (IUT), with one-sided α=0.025 and Holm across the 4 cells.

**Verdicts:**
- **CLAIM**: the gate passes, and at least one cell survives Holm with the lower bound of A6−RR > 0 AND the lower bound of A6−RR-K > 0.
- **KILL (scoped to A6 as frozen)**: the gate passes, and in all 4 cells the upper bound of A6 − RR-K at level 1−0.05/4 is < δ=0.05.
- Otherwise **INCONCLUSIVE**.

**Negative control (exploratory).** On tasks with support ≤ B, predict A6−RR-K ≤ 0, because RR-K can fit all the evidence there.

**Predictions** (my priors; the probabilities are estimates):
1. ORACLE accuracy falls as the number of minimal paragraphs grows. COUNT tasks with more than 100 minimal paragraphs are the weakest, with ORACLE accuracy below 0.5 (p≈0.6). At least one family passes the gate (p≈0.85).
2. RR and RR-K accuracy on S_B is far below ORACLE once support/B > 2 (RR-K below 0.2 there, p≈0.7).
3. Frozen A6 does not beat RR-K by δ: **KILL is the most likely verdict** (p≈0.55). CLAIM p≈0.15, INCONCLUSIVE p≈0.30. The reason is that generic summaries rarely keep exact counts or sums.
4. ARGMAX is the family most likely to favour A6, because a summary can say "team X had the most incidents" without counting.

**Power** (estimate): with 16 streams and about 10–40 tasks per stream per cell, assume a per-stream SD of differences of about 0.08–0.12. That gives an SE of about 0.02–0.03, so the minimum detectable effect after Holm is about 0.07–0.10. These SDs are guesses and are not measured.

## 6. Dry-run cost (ESTIMATE; nothing has run)

Inputs measured from E4 CONFIRM pass 1 so far (runs/CONFIRM/api-events-*):

| Role | Calls | Mean input tokens | Mean output tokens |
|---|---:|---:|---:|
| answer | 2,700 | 1,920 | 92 |
| synth | 148 | 2,719 | 2,484 (median latency 17 s) |

Throughput was about 90–100 answers/min across 4 processes, with heavy 2062 retries.

All of the following are estimates:
- **Answer calls:** 4 arms × 5 B + 1 ORACLE = 21 per task. Over 640 tasks that is 13,440 calls.
- **Answer input:** about 72.5k per task, roughly B + 350 overhead per arm-cell, plus ORACLE at about 3.5k. Total about **46M input tokens**.
- **Answer output:** about 150 per call, because aggregation answers are longer than E4's 92. Total about **2M**.
- **A6 synth:** wide streams are about 3.3× E4's L=1 streams. Assuming about 100 nodes per stream, 16 streams give about 1,600 calls, or about 8M input and 4M output. This is the least certain line, because node count on a 4k-paragraph stream has not been measured.
- **Total:** about **55M input / 6M output**, about 15k calls.
- **Wall-clock:** about 2.5 h for answers at the measured rate, plus about 0.6 h of synth, plus ingest and embedding of about 64k paragraphs (not measured). That is about 3.5–4.5 h with 4 processes.
- **Reranker CPU:** RR-K reranks up to 229 candidates per query at B8000. This is not measured; the T4 RR-K CPU-seconds from frozen E4 will anchor it.

Quota mapping (tokens to % of the MiniMax window and week) will be re-estimated from the measured CONFIRM totals in REPORT.md before any freeze.

## 7. Work remaining before a freeze (all zero-call except the smoke test)

1. Write an adapter that writes each gen_wide stream in the harness format that `e4.dry_run.load` expects (events, world, BRIDGE, warm, forgets).
   T0′ has no deletions, forgets or warm questions, so these are left empty or trivial.
2. Write a new `t0r/run_t0r.py` that imports the frozen arms unchanged and adds ORACLE.
   No frozen file is edited.
3. Write a new `t0r/analyze_t0r.py` with the gate, the IUT/Holm rules and the negative control above.
4. Measure A6 node count and ingest time on one wide stream (zero calls).
5. Run a DEV smoke test on the tuning seeds 7289101–7289104: 1 stream, all arms. This costs calls, so it needs Aditya's approval.
6. Hostile review, then write E4-T0R-FREEZE.json, hashing gen_wide.py, wide_support.py, run_t0r.py, analyze_t0r.py and this file.
   Confirm seeds: 7290101–7290116.

**Seed note.** Seeds 7290001–7290016 were used only for model-free support measurement. They are proposed as the scale-tuning block, and the confirm block is 7290101–7290116.

**Layout note.** All T0′ code lives in `t0r/`, not `e4/`. `e4/make_freeze.py` hashes every `e4/*.py`, so new files there break `verify_frozen()`, and `run_e4 --confirm` calls it at start.
For about a minute (commit cd7fa50) the files sat in `e4/`. They were moved in the next commit, before any frozen launch.
