# PREREG-E3 — DRAFT, NOT FROZEN — **RECOMMENDATION: SHELVED** (rev 2, 24 Oct 2026 ~19:40 IST)

> **Rev 2 status.** Under Aditya's 19:08 IST rule, the exploratory RR-2hop pass on E2's 320 DERIVED tasks
> (`e3/explore-rr2hop/REPORT.md`) gave **A6 − RR-2hop = −18.75pp** [95% CI −24.2, −13.3]. That is far below the +3pp shelve
> threshold, so the rule says **shelve E3**. The DERIVED lead is a single-pass retrieval artifact. This draft is
> updated as asked (arms, co-primary test, power, cost, ceiling) so it is complete if E3 is ever revived. **No freeze
> candidate was prepared and nothing is frozen or launched.**

**Status:** DRAFT, drafted 24 Oct 2026 (~18:50 IST). No E3 data exists and no E3 API call has been made. Nothing here
binds until a freeze commit adds `e3/E3-FREEZE.json` with code hashes. E2 artifacts (`prereg-E2/PREREG-E2.md`,
`e2/E2-FREEZE.json`, hashed `e2/e2/*.py`) are read-only inputs and are not modified by E3.

**Provenance of the question.** E2 CONFIRM (commit 4f70d9b) gave prespecified outcome **O2** (raw beats A6 overall,
A6−RR −0.057, 95% CI [−0.087, −0.027]). In a class breakdown that E2 reported but did *not* prespecify as a test,
DERIVED was the one class where A6 beat RR: **+0.109 [+0.061, +0.157]** (32 streams × 10 tasks). E3 is a confirmatory
test of that exploratory lead only. It does not reopen E2's overall result.

---

## 1. Hypotheses

* **H1 (co-primary; both parts must hold).** On DERIVED questions asked after deletion, A6 accuracy exceeds that of
  **both** raw comparators:
  * **H1a:** A6 − RR > 0;
  * **H1b:** A6 − RR-2hop > 0, where RR-2hop is a two-step reranked raw retriever (§3).
  * The DERIVED lead is confirmed only if both hold (§4, §7).
* **H2 (secondary).** A6 − RR-agg > 0: query-time aggregation over RR's text.
* **H3 (secondary mechanism).** A6 − A6-syn > 0 on DERIVED. Does the synthesized summary carry the effect?

## 2. Data, seeds, task mix

* **Generator and task author.** The same frozen pilot generator (`pilot-v1.3/eng-pin`, `gen.gen_stream`) and the E2 author
  (`e2.tasks.author_e2`) as E2. Deletion recipe, gold (post-delete ledger at t_end), the bridge step (bridge count kept at
  E2's 10), the question template (`DERIVED_Q`), and scoring (`e2.tasks.score`) are all unchanged.
* **Seeds (fresh, disjoint from E2).** E2 used CONFIRM 7260001–7260032, reserve 7260033–7260049, and DEV 7269001–7269004.
  E3 uses:
  * CONFIRM **7270001–7270048** (48 streams);
  * reserve **7270049–7270064**, used in order, **skipping 7270053**;
  * DEV **7279001–7279004**.
* **DERIVED-heavy mix.** Each stream gets **every eligible DERIVED task, capped at 16**, in E2's priority order
  (deletion-touched first, then a seeded shuffle). No AGG, MULTIHOP or CURRENT probes are asked, because probes are
  independent answer calls and other classes would only add cost.
  * Eligible means a derived key (lead/owner → office city or team name) that is active post-delete.
  * A seed with fewer than 12 eligible DERIVED tasks is skipped and replaced by the next reserve seed.
* **Offline supply check (done for this draft, model-free, in /tmp only, nothing committed).** I generated all 68 E3 seeds
  and authored them with E2's bridge count. Eligible DERIVED tasks per stream ranged 11–21 (median 16). Only 7270053 is
  below 12.
  * The 48 CONFIRM streams have m = 13–16 tasks each (mean 15.23), for **731 DERIVED tasks** in total.
  * **308 (42%)** of those are deletion-touched. E2's DERIVED set was 188/320 = 59% touched, because E2 capped DERIVED at 10.
  * DEV streams have 12, 16, 16 and 16 tasks after the cap (7279001: 12 eligible).
  * Re-verify these counts at freeze with the frozen E3 author.

## 3. Arms

All arms use the same answerer (**MiniMax-M3.1-Flash**, E2 answer prompt, E2 retry policy including the separate 429/2062
budget), the same embedder and reranker (gte-reranker-modernbert-base, fp32), and the same budget **B = 2000** estimated tokens.

| Arm | Role | Definition |
|---|---|---|
| **A6** | primary | E2 A6 unchanged: computed memory with summaries in a ⅕B header, 200-token cap, raw fill to B, post-delete recompute. |
| **RR** | co-primary comparator | E2 RR unchanged: cosine top-50 → rerank → fill to B. |
| **RR-2hop** | **co-primary comparator** | `e3/e3/rr2hop.py`. Hop 1 = RR. One bridge call to the same model on hop-1's served text names the bridging person (prompt `BRIDGE_PROMPT`, v2); hop 2 = cosine top-50 → rerank on `"{entity} {question}"`. The two ranked lists are interleaved and deduplicated, then prefix-filled to the same B. Same answer prompt. If the bridge returns NONE or fails, hop 1 only is served. |
| **RR-agg** | secondary (H2) | Unchanged from rev 1: an RR-retrieved note under A6's synth instruction and cap, in a ⅕B header plus raw fill. |
| **A6-syn** | secondary (H3) | E2 A6-syn unchanged. |

* **RR-k (top-200) is dropped, because RR-2hop subsumes it.** The E2 DERIVED gap is a second-hop retrieval failure:
  the attr leaf is outside RR's top-50 on 311/320 (AUDIT). A deeper single-query pool does not fix it.
  * Measured offline (`e3/explore-rr2hop/offline_diag.py`, zero API): with top-200 the attr leaf enters the pool on
    121/320 but is **served on only 27/320**, and the ref leaf falls from 316 to 255 served.
  * RR-2hop targets the second hop directly: 240/320 attr leaves served live, and 292/320 with an oracle bridge.
  * So RR-k is a strictly weaker control for the same failure mode, and it costs 4× the reranker load.
* The bridge and RR-agg calls must not see gold, the ledger or deletion metadata; they see only the question and retrieved
  surviving raw units.
* **Known bias.** The bridge prompt text is written for the DERIVED question shape. At freeze it is either kept and
  disclosed, or replaced with a generic "name the entity the question depends on but does not name" prompt and
  re-qualified on DEV. **Freeze item.**

## 4. Analysis (mirrors E2's frozen method)

* **Unit.** Per task, the paired correctness difference (score ∈ {0,1}, E2 `score()` strict). Average within each stream
  to get a per-stream mean, then compute a t-interval across the n streams.
* **Co-primary test (prespecified): intersection–union with 97.5% bounds.**
  * C1a = A6 − RR and C1b = A6 − RR-2hop.
  * The lead is confirmed only if the **lower bound of the two-sided 97.5% t CI is > 0 for both** (each one-sided α = .0125).
  * An intersection–union test needs no multiplicity correction to control error at .0125. Using 97.5% rather than 95%
    is a deliberate conservative choice that matches E2's two-contrast H-ADV (α = .025 each two-sided). Holm is not
    used, because "confirmed" requires both contrasts, not either.
* **Secondary contrasts.**
  * C3 = A6 − RR-agg, 97.5% CI.
  * C4 = A6 − A6-syn, 95% CI, descriptive.
  * RR-2hop − RR, 95% CI, descriptive.
* **RR-2hop diagnostics (reported, cannot change labels).** Bridge entity accuracy against the gold ref-leaf person,
  attr-leaf and ref-leaf served rates, and the share of tasks that fall back to hop 1.
* **Strata (descriptive, prespecified).** Deletion-touched vs untouched; slot (office city vs team name); and whether a
  surviving inference statement states the gold (one hop vs composition needed).
* **Failures.** A failed answer call scores 0, as in E2. A failed bridge call falls back to hop 1. Calls, retries and
  failures are reported per arm.

## 5. Power and stream count

The inputs are E2 CONFIRM DERIVED data (32 streams × 10 tasks):
* the per-stream SD of A6 − RR is **0.1329**;
* discordant pairs: 50 tasks were A6-only correct and 15 RR-only correct, out of 320.

Power is computed with E2's own `e2/e2/power.py::power` (noncentral t, one-sided α = .025, which equals the lower bound of
a two-sided 95% CI), at the design effect **δ = +0.05**.

* **Variance model (estimate, assumption stated).** The task-level variance of the paired difference is
  0.156 + 0.047 − 0.109² = **0.191**.
  * At m = 10 this predicts a per-stream SD of 0.138, against the observed 0.133. So E2 shows no detectable
    between-stream component, and I model the per-stream SD as sqrt(0.191 / m).
  * Over the planned m distribution (13–16, mean 15.23) the effective SD is **0.112**.
* **Power at δ = +0.05 (estimates):**

| n streams | scaled SD 0.112 | conservative (no scaling, SD 0.1329) |
|---|---|---|
| 32 | 0.684 | — |
| 40 | 0.784 | 0.641 |
| 44 | 0.823 | — |
| **48** | **0.855** | 0.723 |
| 56 | 0.905 | 0.790 |
| 58 | — | 0.804 |

* **Choice: n = 48 CONFIRM streams.** This is the smallest multiple of the 8-process batch size that gives power ≥ 0.8
  under the variance model E2 supports (44 is the strict minimum).
  * If per-stream SD does not shrink with more tasks (the conservative column), 48 streams give 0.72, and ≥ 0.8 would
    need **58** streams.
* **DEV stream-addition rule (proposed; finalize before freeze).** Compute the per-stream SD of A6 − RR on the 4 DEV
  streams. If it exceeds 0.13, use 58 streams (reserve seeds in order). Otherwise keep 48. Nothing else may change n.
* **Winner's-curse note.** E2's +10.9pp is the best of four classes in an unplanned breakdown, so the design targets
  +5pp rather than +10.9pp.

### 5a. Rev 2: power for the co-primary intersection test (estimates)

* E2 + exploration inputs: the per-stream SD of A6 − RR is 0.1329, and of A6 − RR-2hop is 0.1519 (32 streams × 10).
* The task-level variance model for A6 − RR-2hop (p10 = .050, p01 = .237) gives SD 0.129 at m = 15.23.
* Power is from `e2/e2/power.py::power` at **δ = +0.05** and **one-sided α = .0125** per contrast.
* The power of the intersection is at most the smaller of the two marginal powers (and above their product when the
  contrasts are positively correlated).

| n streams | SD 0.112 | SD 0.129 | SD 0.1329 | SD 0.152 |
|---|---|---|---|---|
| 48 | 0.779 | 0.645 | 0.616 | 0.491 |
| 58 | 0.861 | 0.741 | 0.712 | 0.583 |
| 64 | 0.896 | 0.787 | 0.761 | 0.632 |
| 80 | 0.954 | 0.879 | 0.858 | 0.743 |

* **If revived:** to keep each marginal power ≥ 0.8 under the conservative SD, n would need to be about **64–80 streams**,
  against 48 in rev 1. The reserve range would have to grow.
* This is moot at present, because the exploratory point estimate for A6 − RR-2hop is **−0.19**, not +0.05.

## 6. Prediction (made before any E3 data)

* Rev 1 predictions (C1 +5 to +9pp; RR-k does not close the gap; RR-agg closes most of it) are superseded by the
  exploratory data:
  * RR-agg did **not** close the gap (−0.3pp vs RR).
  * RR-2hop **reversed** it: A6 − RR-2hop = −18.75pp, against my committed prediction of about +2pp.
* If E3 were run as drafted, I would predict **H1b fails**, with the C1b upper bound < 0.

## 7. Prespecified outcomes and kill criterion

**Co-primary (C1a = A6 − RR, C1b = A6 − RR-2hop; 97.5% CIs):**

| Outcome | Condition | Reading |
|---|---|---|
| **E3-O1** | C1a and C1b lower bounds both > 0 | Lead confirmed: A6 beats single-pass and two-step reranked raw on post-delete derived attributes. |
| **E3-O1r** | C1a lower bound > 0, but C1b includes 0 or is < 0 | **Lead killed as a memory claim.** A6 only beats a single-pass retriever; it is a retrieval-depth artifact. |
| **E3-O2** | C1a includes 0 | **Lead killed** (no advantage over RR). |
| **E3-O3** | C1b upper bound < 0 | **Lead killed and reversed**: two-step raw retrieval beats A6. |

**Kill criterion.** Anything other than E3-O1 kills the DERIVED lead, and E2's O2 stands with no class-level exception.
Under E3-O1, C3 (RR-agg) at 97.5% qualifies the claim as in rev 1: if C3 includes 0, the edge is aggregation timing.

## 8. Artifact check (is the DERIVED advantage an artifact?)

This check is model-free. It is computed from traces and summaries after the run and before outcome labelling, and it
is reported in full whatever the outcome.

* **AC1, gold literally in the header.** For each DERIVED task, check whether the gold value matches (`truth_any` regex)
  in the text of an A6 summary served for that task.
  * Lenient level: anywhere in the served summary.
  * Strict level: in the same sentence as the subject's name.
  * Report A6, RR, RR-2hop, RR-agg and A6-syn accuracy split by AC1 hit/miss × deletion-touched.
* **AC2, gold split across raw chunks.** For each DERIVED task, the support chain is the lead/owner assertion plus the
  person's office/team assertion. Locate both at paragraph level with `_paragraph_index` on the surviving ledger rows.
  * Classify the task as *both hops in the same raw unit* or *hops in separate units*.
  * For RR and RR-2hop, record whether each hop's unit is in the served set (0, 1 or 2 hops).
  * Also record whether stale wrong values (`wrong_any`) appear in the served raw units.
* **AC3, reading rule (prespecified).** The advantage is labelled **"composition-in-header"** if both hold:
  1. under E3-O1, ≥ 75% of the C1 effect (sum of per-task A6 − RR) comes from AC1-hit tasks; and
  2. on AC1-miss tasks the A6 − RR difference has a CI that includes 0.

  If C3 also includes 0 (F-precompute), the report must state that the DERIVED advantage is an aggregation-timing effect
  that a raw-side step reproduces.

**E2 context (exploratory, computed offline from E2 CONFIRM traces for this draft; not E3 evidence).**

AC1 (lenient), with gold in the served A6 summary on 168/320 tasks:

| Subset | n | A6 | RR | A6-syn |
|---|---|---|---|---|
| gold in header, touched | 89 | .517 | .157 | .169 |
| gold in header, untouched | 79 | .797 | .671 | .646 |
| gold not in header, touched | 99 | .141 | .141 | .172 |
| gold not in header, untouched | 53 | .528 | .660 | .585 |

So in E2 the whole DERIVED advantage sits in tasks where the summary literally states the answer. Without that, A6 ties
RR on touched tasks and trails it on untouched tasks.

AC2 at session level (coarse; E3 will use paragraph level):
* Support spans 2–6 sessions per task (2: 118 tasks, 3: 142, 4: 48, 5–6: 12).
* RR served every support session on 142/320 tasks, and still had accuracy .359 there (A6 .486).
* RR served only 1 of 2 support sessions on 59 tasks: RR .034, A6 .237.
* RR's DERIVED errors were mostly stale or wrong values (mentions_wrong 115, abstained 73).

Both point toward composition and recency adjudication, not pure retrieval, as the gap. That is why RR-agg is the key
fairness arm.

## 9. Cost estimate and ceiling (ESTIMATE; tokens = input + output + cache-read as recorded)

Per-stream figures come from E2 CONFIRM (mean over 32 streams) and the two E3 explorations:
* A6 lifecycle about 224k (up to about 470k);
* about 1.65k per A6, A6-syn or RR answer;
* **RR-agg about 3.2k per probe**, measured (RR-agg exploration: 1.03M / 320);
* **RR-2hop about 3.3k per probe**, measured (1,059,540 / 320, of which the bridge is about 1.5k).

| Per stream (m ≈ 15.2 DERIVED probes) | Tokens (est.) |
|---|---|
| A6 lifecycle | ~224k (up to ~470k) |
| A6, A6-syn and RR answers | ~75k |
| RR-2hop (bridge + answer) | ~50k |
| RR-agg (note + answer) | ~49k |
| **Total per stream** | **~400k** (RR-k removed, −25k) |

| Run | Tokens (est.) |
|---|---|
| 48 streams + 4 DEV | **~21M** |
| 64 streams + 4 DEV (§5a) | **~27M** |
| 80 streams + 4 DEV | **~34M** |

* Retry overhead is unknown and small. The explorations had 58 and 54 transient errors, all retried.
* **Ceiling, set at freeze so that E2's breach does not recur.** E2 froze "reranker CPU-seconds ≤ 76" from DEV run at
  different contention, then breached it on 8 streams (max 93.1 s) because 8 processes shared the CPU. E3 fixes this as
  follows:
  1. **Reranker cost is metered as reranker pairs scored per stream**, which is deterministic: 50 per RR probe, 100 per
     RR-2hop probe, plus RR-agg's 50. CPU-seconds are reported descriptively only. The pair ceiling is 1.2× the DEV
     per-stream maximum, and it cannot breach through contention.
  2. **Token and call ceilings are measured on DEV under the exact confirmatory layout**: same process count, reranker
     single-locked per process, torch threads = 4. Each is set at 1.5× the DEV per-stream maximum, separately for the
     A6 lifecycle, RR, RR-2hop and RR-agg.
  3. **Reranker parallelism is lowered.** At most 4 stream processes run concurrently (E2 used 8), and the RR-family
     reranks within a stream run serially.
  * The overrun rule is unchanged from E2: an over-ceiling stream qualifies the result as not cost-bounded and does not
    change the accuracy outcome.
* **Wall time (estimate).** About 3–4 h for 48 streams with 4 processes; longer at 64–80 streams.

## 10. Code required before freeze

The data path, A6, A6-syn, RR, the answerer, scoring and the CI code are E2's frozen code, imported unchanged. New code
lives in `e3/` and is hashed in `e3/E3-FREEZE.json`. Nothing under `e2/e2/` changes.
1. `e3/tasks_e3.py`: a wrapper around `author_e2` that keeps DERIVED tasks only, caps them at 16, and applies the
   12-task minimum and seed-skip rule.
2. RR-2hop: done, `e3/e3/rr2hop.py` (offline tests in `e3/tests/`). RR-k is dropped (§3).
3. RR-agg: a new arm class and the note prompt.
4. `e3/artifact_check.py` (AC1–AC3).
5. `e3/report.py`, plus a sign test on DEV numbers, the same check that was added for E2 after `SIGN-CHECK.md`.

## 11. Risks and reasons not to run

1. **The lead is post hoc.** DERIVED is the best of four classes in an unplanned breakdown. Hence the +5pp target and
   the fresh seeds.
2. **The E2 mechanism already looks like composition-in-header (§8).** If RR-agg closes the gap, E3 spends about 20M
   tokens to learn something a cheaper study could show.
   * **Cheaper staged alternative (exploratory, not confirmatory):** run RR-agg only on E2's 320 CONFIRM DERIVED tasks.
     That is about 320 × ~4.7k ≈ **~1.5M tokens (estimate)**.
   * If RR-agg ≥ A6 there, the confirmatory E3 is probably not worth running. If RR-agg clearly trails A6, run E3 as drafted.
3. **The claim stays narrow even under E3-O1.** E2's overall O2 (raw better overall, MULTIHOP −24pp) stands. A DERIVED win
   would be a class-specific exception, not a reversal.
4. **A6 is not cost-matched.** A6 spends about 224k lifecycle tokens per stream, about 15k per DERIVED probe at E3's
   volume, against about 1.7k for RR and about 4.5k (est.) for RR-agg. A6 winning C1 but not C3 is not a cost-effective
   win.
5. **A6's configuration was ill-tuned in E2.** 74% of served summaries were truncated at the 200-token cap. E3 tests this
   configuration, not A6 in general.
6. **Cost and ceilings.** E3 needs ~20–21M tokens (est.), ~1.6× E2. E2 breached its cost ceiling (reranker seconds on 8
   streams; A6 tokens on 7260031), and RR-2hop doubles RR's reranker pairs (RR-k, dropped in rev 2, would have quadrupled them); see the §9 ceiling.
7. **"Same frozen harness" is only partly literal.** The pipeline is identical, but the DERIVED-only author, RR-agg and
   the artifact check are new code. They need their own freeze and DEV qualification.
8. **Rev 2: the exploratory data already answer the question.** RR-2hop beats A6 by about 19pp on the discovery tasks
   (`e3/explore-rr2hop/REPORT.md`). A confirmatory E3 would spend about 21–34M tokens (est.) to test a lead that a fair
   retriever has already reversed. Recommendation: **shelve**.
