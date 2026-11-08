# PREREG E2: does delivered computed memory beat strong raw retrieval after deletion?

> **STATUS: DRAFT. NOT FROZEN. Freeze candidate (rev 5, 24 Oct 2026).** Do not cite this as a preregistration. It becomes binding only when the OPEN items in §10 are resolved and a frozen copy (`PREREG-E2.md`) plus `e2/E2-FREEZE-DRAFT.json` regenerated as `E2-FREEZE.json` is committed with a hash. Rev 1 was drafted with zero model calls; rev 2 applied the head-of-research defaults, the harness, a 19-call API smoke and an offline dry run; rev 3 applies the head-of-research decisions of 24 Oct 13:26 IST (`e2/DEFAULTS.md` #11–19), the DEV pass (4 DEV streams, 649 live calls) and qualification (120 live calls), §4a. Rev 4 (Research sign-off under owner authority pt265u, `e2/DEFAULTS.md` #20–25) re-authors MULTIHOP as a bridge-linked 2-hop, fixes the AGG wording, the scoring rules, the stale-control dating and the floor sensitivity, and reruns DEV + qualification (DEV2/QUAL2, §4a). Rev 5 applies the Astra hostile review (verdict FIX-THEN-RUN, `astra-2026-10-24/E2-hostile-review/E2-hostile-review.md`; `e2/DEFAULTS.md` #26–35): AGG gold is no longer constant, the answer prompt states the precedence rule for every arm, the gates are enforced in code, truncation/abstention/resume handling is fixed, a numeric cost ceiling is frozen, and DEV + qualification are rerun (DEV3/QUAL3, §4a). None of the rev-5 changes alters the hypotheses, the two primary contrasts, α, Δ, the endpoint classes or the O1/O2/O3 rules. No confirmatory seed has been run.
>
> Refs:
> - K1 = `astra-2026-10-24/K1-decision-review/K1-decision-review.md`
> - PR = `stance-reads/2026-10-23-PREREG-currency-v1.2.1.md` (read-only)
> - A6S = `E1/A6-SERVING.md`
> - H = harness `e2/` (README, DEFAULTS.md, COST.md, E2-FREEZE-DRAFT.json)
> - E1 = `E1/REPORT.md`
>
> Labels:
> - **[ASSUMPTION]**: a planning value, not observed.
> - **[OPEN]**: needs Aditya.

## 1. Question

At a matched evidence budget (B = 2k), once deleted sessions have been removed, does an A6 that *actually serves* its keyed cluster summaries answer post-delete questions better than strong raw retrieval? The questions cover aggregate, surviving-support derivation, multi-hop and current/supersession. And is any gain due to the summaries (compression) rather than routing [K1:19]?

**Why E2 is needed.** Pilot ties do not answer this:
- A6-F served a summary on only 55/306 PILOT3 probes, 0 of them on AGG, DERIVED or multi-hop (A6S; `E1/a6_serving.out:21-22`).
- The cause is the ⅕B header cap [PR:118, PR:465] plus `break` at `pilot-v1.3/pilot/arms.py:170-172`. Synth outputs have a median cost of 452 estimated tokens against a 400 cap, and only 50/173 fit (`E1/a6_serving.out:32`).

## 2. Hypotheses and predictions (pre-declared outcomes, after K1:17)

The primary endpoint is per-task correctness on post-delete tasks in world F, scored against exact controlled gold. The analysis unit is the stream mean of paired differences.

- **H-ADV (advantage).** A6 > reranked raw AND A6 > A6−syn on pooled accuracy. Two two-sided contrasts, α = .025 each [K1:50], under the frozen cost ceiling (§7). *Prediction (Research, synthesis):* given the pilots, H-ADV is more likely to fail than to pass. The only plausible place for a gain is distributed-support AGG and derivation tasks, where raw can't fit the support into 2k.
- **H-NI (raw non-inferiority).** Reranked raw is non-inferior to A6. This is the case if the upper bound of the one-sided 97.5% CI for (A6 − raw) is below the margin Δ (§3). (Null hypothesis: A6 − raw ≥ +Δ, i.e. raw is worse than A6 by at least Δ.)
- **Inconclusive.** Neither of the above holds. A small null result is *not* evidence for H-NI [K1:57].

**The three prespecified outcomes and what each licenses:**

| Outcome | Rule | Paper claim |
|---|---|---|
| O1 ADV | H-ADV holds (both contrasts > 0 at α=.025) | "Served computed summaries beat strong raw retrieval after deletion at B=2k" (scoped to this generator and model) |
| O2 NI / kill | H-NI holds and H-ADV fails | K-thesis fires: "raw suffices after deletion; lazy recompute is IVM with a measured cost frontier" |
| O3 Inconclusive | otherwise | Report CIs and the scoped descriptive paper; no directional claim |

*Registered prediction (Research):* O2 or O3. O1 is unlikely; if any gain appears it will be on distributed-support AGG/DERIVED.

**Kill criteria (pre-declared):**
- **K-thesis.** If H-NI holds and H-ADV fails, the claim "computed memory beats raw retrieval after deletion" is killed for this setting. The paper becomes "raw suffices after deletion; lazy recompute is IVM with a measured cost frontier" (E1 provides the frontier).
- **K-synth.** KC3 [PR:334] is reported as stated: if the A6 − (A6−syn) CI includes 0 while summaries cost tokens, no claim is made for synthesized nodes, and routing is reported alone.
- **K-delivery (precondition, not an outcome).** If DEV shows that A6 serves a summary on < 80% of AGG, derivation and multi-hop probes, E2 does not proceed (*DEV: 100%, §4a*); the same rate is reported per confirmatory stream. Fix serving first; the run is not a valid treatment test otherwise.
- **K-answerer.** If MiniMax fails qualification (§4), E2 does not run on any substitute model; Research writes the scoped paper (§9). *Resolved (default).*

## 3. Non-inferiority margin

**Δ = 10 percentage points absolute** on pooled paired accuracy. *Resolved (default):* 5pp is reported as a descriptive secondary only.

Justification:
1. **Feasibility.** Under K1's assumed variance scenarios, 80% power at 10pp needs 17–61 streams, but at 5pp it needs 59–236 [K1:50-55]. We have 32 streams. A 5pp margin would make H-NI unreachable in most scenarios, so it would only be honest as a descriptive secondary.
2. **Relevance.** Saved A6-vs-RS accuracy gaps are within a few points:
   - AccC 0.817 vs 0.829 [pilot-v1.3/runs/PILOT3-GROK-FULL/REPORT.md:57]
   - retained 0.824/0.794 vs 0.882/0.882 [pilot-v1.2/runs/PILOT2/REPORT.md:85,90]

   A 10pp margin is wide enough to absorb answerer noise. It is still narrow enough that a 10pp computed-memory advantage, the size that would justify A6's extra lifecycle cost (+51% tokens vs RS in P3, E1 §1; `E1/replay_cost.out:35-41`), would be detected.
3. **Secondary.** The 5pp CI is also reported, labelled descriptive.

## 4. Answer model (one, fixed for all arms and stages)

- **Primary:** MiniMax M3.1 Flash. *Resolved route:* the Token Plan API key, official endpoint, no CLI, no proxy (owner msg pt263u). Implementation `e2/minimax_api.py`:
  - `POST https://api.minimax.io/anthropic/v1/messages`, model `MiniMax-M3.1-Flash`, `output_config.effort = low`, `max_tokens = 8192` (includes thinking; thinking cannot be disabled).
  - Temperature/top_p are ignored by the server (fixed), so answers are **not deterministic**. Reproducibility is by the per-call response cache (sha256 of route, role, model, effort, max_tokens, system, prompt); reruns hit the cache.
  - Retry with backoff on transport/5xx, on HTTP-200 error envelopes and on HTTP 429 code 2062 ("Token Plan rate limit", seen 209× in DEV + qualification, all recovered); RPM limit (1002) waits ~60 s; window exhaustion (2056) pauses until the quota endpoint's reset time and resumes idempotently; fatal codes stop the run. A floor guard pauses at ≤2% of the 5-hour window remaining so purchased Credits are never drawn.
  - All knobs, prompt hashes, seeds and dependency file hashes are in `e2/E2-FREEZE-DRAFT.json`.
  - It is **pending qualification** [K1:42]. Prompt and settings are identical across arms.
- **Smoke (24 Oct, 19 live calls, not results):** all calls parsed (`end_turn`, 0 errors). Against the saved CLI calibration answers on 12 items: not-found agreement 12/12, identical text 6/12, the rest paraphrases. Answer calls used median 1,316 input / 87 output tokens (output incl. thinking; max 449); synth calls 1,832–3,680 input / 552–1,061 output (`e2/runs/SMOKE/smoke.json`).
- **Qualification (stage 0):** 120 DEV answers [K1:46] in four groups: no-evidence, sufficient-gold-evidence, stale-derived sensitivity, and actual summary delivery.
  - The model must PASS the existing contamination and void criteria (`cm-bench/cmbench/qualify.py:8-10`).
  - It must also pass a **responsive positive control:** an always-abstaining answerer must fail. Current qualify.py can PASS without one [K1:21]. *Implemented* in `e2/qualify.py` (30 calls per DEV stream, 120 total, on the post-delete raw store at t_end):
    - *no_evidence* (10 non-AGG tasks, empty context): contaminated if the answer states the gold or a deleted/outdated value.
    - *gold_evidence* (10 CURRENT tasks; context = the surviving support sessions' paragraphs, reranked, filled to B): accuracy must be ≥ 0.70 (`GOLD_MIN`, freeze item).
    - *stale_derived* (10 tasks; raw context plus a stale note asserting the outdated value, placed first, dated at the time that value was recorded (rev 4)): repeat rate reported, not gating.
    - *gold_evidence_cls* (rev 5, descriptive): 3 AGG (gold > 0), 3 DERIVED and 3 MULTIHOP tasks per DEV stream with the same sufficient-evidence context; per-class accuracy reported, not gating.
    - The stale_derived rows also record `endorses_stale` (stale value without gold) vs `mentions_both` (rev 5).
    - Summary delivery is measured on the DEV pass traces (K-delivery), not here.
    - **PASS = 0 contaminated AND 0 failed calls AND gold_evidence accuracy ≥ 0.70.** Tests (`e2/tests/test_qualify.py`): always-abstain FAILS, evidence-reading answerer PASSES, answer-without-evidence (leaky) FAILS, contaminated or failed-call answerers FAIL.
- **No separate strong-model calibration** (*resolved, head of research, 24 Oct*). Rationale (head of research): MiniMax already matched the saved Astra answers, and the API route agreed with the saved CLI calibration answers on the same 12 items in the smoke (not-found agreement 12/12, identical text 6/12, rest paraphrases). A further strong-model pass would add cost and a second model without changing any gate. Limitation: arm rankings are established for one mid-size answerer only; generalisation to stronger answerers is not claimed.
- **Single sample per call** (*resolved*). The server ignores temperature/top_p, so a rerun of an uncached call may differ. One sample per (arm, task) is drawn and cached; the cache makes the reported run exactly reproducible but does not remove sampling noise, which is part of the stream-level variance. Limitation stated in the paper: no replicate calls, so per-item answer noise is not separated from arm effects except through the paired, stream-level analysis.
- **Same model throughout.** Synthesis, if model-based, uses the same fixed model for summary generation: the synth prompt is PR:163.

## 4a. DEV pass and qualification — DEV — NOT RESULTS

**DEV3 / QUAL3 (rev 5; 24 Oct 2026, 16:39–16:49 IST; supersedes DEV2/QUAL2 below).** Same DEV seeds, tasks regenerated with the rev-5 AGG strata, answer prompt with the rev-5 precedence instruction (all arms). Files: `e2/runs/DEV3/DEV-REPORT.json`, `e2/runs/QUAL3/QUALIFY.json`.

- **Qualification: PASS.** 156 answers (154 live). no_evidence 0/40 contaminated; gold_evidence (CURRENT, gating) 38/40 = .95 (≥ .70 required); 0 failed gating calls. Descriptive per-class sufficient-evidence accuracy: AGG 10/12, DERIVED 11/12, MULTIHOP 12/12 (one further DERIVED descriptive call failed after 8 rate-limit retries; not gating). stale_derived: repeated the stale value 22/40 = .55, all 22 *endorsing* it (stale value without gold), 0 mentioning both.
- **K-delivery: PASS.** A6 served ≥ 1 summary on 100% of probes in every class; 2 summaries on all 158 A6 probes. Node status: 316 served, 153 skipped_no_fit, 5 none. Final summary caches 50, 39 truncated; median cost 245 raw → 190 served est. tokens.
- **Header gold coverage (descriptive, Astra finding 5):** the gold literal appears in A6's served summary header on MULTIHOP 3/38, DERIVED 18/40, CURRENT 23/40 probes (reconstructed from the final post-delete summaries; literal presence is not entailment; AGG excluded because its gold is a count). Interpretation of any A6 result is limited to *this* truncating, query-independent summarizer.
- **Accuracy (DEV3, primary strict, not results):** A6 .551, A6-syn .525, RR .652. By class (A6 / A6-syn / RR): AGG .425/.475/.575; DERIVED .500/.325/.400; MULTIHOP .447/.474/.763; CURRENT .825/.825/.875. No class floored (worst best-arm .50). Tasks wrong in all three arms: 37/158 (AGG 11, DERIVED 15, MULTIHOP 7, CURRENT 4). Failed calls: 1 (RR, 7269004 MULTIHOP, 8 consecutive rate-limit 429s; this led to the rev-5 rate-limit retry budget, §6); max_tokens stops 0; leak units 0 in all 4 streams.
- **Per-stream mean paired differences (DEV3):** A6 − RR = −.175, −.075, −.050, −.105; A6 − A6-syn = +.025, +.050, +.050, −.026. sd̂ = 0.054.
- **§7 rule re-applied on DEV3** (disclosed: the rule was first applied on DEV/DEV2; rev 5 changed the data and prompt, so it is applied once more on the final DEV): power(32) > 0.99 → **32 streams kept**; no reserve streams.
- **Usage (DEV3 + QUAL3):** DEV3 514 live calls (513 answer, 1 synth; all other synth calls were cache hits because the synth prompt is unchanged), 316 rate-limit (2062) retries, tokens 692,980 input + 55,452 output + 115,775 cache-read. QUAL3 154 live calls, 157,175 input + 5,331 output + 35,548 cache-read. Token Plan: 16:39 IST 5-h window 97% remaining, week 88%; 16:49 IST window 95%, week 88%.
- **Per-stream lifecycle cost (DEV3, nominal tokens incl. cache replays):** A6 (warm + synth + both A6 arms) 310,136–376,361 tokens, 29–39 synth calls; RR 63,267–66,822 tokens; reranker 23.6–25.1 s per stream.

**DEV2 / QUAL2 (rev 4; 24 Oct 2026, 15:44–15:58 IST; supersedes DEV/QUAL below).** DEV streams 7269001–7269004 regenerated with the rev-4 task generator (same seeds; 158 tasks, 7269004 has 38) × 3 arms. Files: `e2/runs/DEV2/DEV-REPORT.json` (incl. `analysis_DEV_not_results` from `e2/analysis.py`), `e2/runs/QUAL2/QUALIFY.json`.

- **Qualification: PASS.** 120 answers (88 live, 32 cache hits), 0 failed. no_evidence 0/40 contaminated; gold_evidence 40/40 correct (≥ 0.70 required); stale_derived (note now dated at the outdated value's time) repeat rate 0.70 (28/40; reported, not gating; was 40/40 with the query-time date).
- **K-delivery: PASS.** A6 served ≥ 1 summary on 100% of probes in every class; 2 summaries on all 158 A6 probes. Node status: 316 served, 151 skipped_no_fit, 7 none. Final summary caches 50, 39 truncated; median cost 245 raw → 190 served est. tokens.
- **Accuracy (DEV2, primary strict scoring, not results):** A6 .557, A6-syn .525, RR .646. By class (A6 / A6-syn / RR): AGG .525/.475/.600; DERIVED .475/.350/.375; MULTIHOP .447/.474/.789; CURRENT .775/.800/.825. Lenient (S2) overall: .570/.532/.646. Rows mentioning a deleted/outdated value: 24/25/24. Failed calls 0; max_tokens stops 0; leak units 0 in all 4 streams.
- **MULTIHOP fix worked:** best-arm MULTIHOP accuracy .789 (was .051 on DEV), so MULTIHOP stays in the primary endpoint (DEFAULTS #20 rule: ≥ 0.15). No class is floored (best arm ≥ 0.15 everywhere). Tasks wrong in all three arms: 40/158 (was 80/159): AGG 10, DERIVED 18, MULTIHOP 7, CURRENT 5.
- **Per-stream mean paired differences (DEV2):** A6 − RR = −.100, −.025, −.125, −.105; A6 − A6-syn = +.075, +.075, +.025, −.053. sd̂ = 0.060. (DEV analysis output for orientation only, not a result: 4 streams.)
- **§7 rule applied to DEV2:** power(32) > 0.99 at sd̂ = 0.060 → **32 streams kept**; no reserve streams added.
- **Usage (DEV2 + QUAL2):** DEV2 511 live calls (64 synth, 447 answer; the rest were cache hits on identical prompts), 0 failed, 161 rate-limit (2062) retries all recovered; tokens 758,984 input + 225,539 output + 116,920 cache-read. QUAL2 82,789 input + 2,782 output + 18,790 cache-read. Token Plan: 15:44 IST 5-h window 99% remaining, week 89%; 15:58 IST window 98%, week 89%. Wall time ≈ 8 min (4 processes).

**DEV / QUAL (rev 3, 13:38–13:56 IST; superseded):**

DEV streams 7269001–7269004 (159 tasks; 7269004 has 39) × 3 arms, harness at commit `9f7553e`. Files: `e2/runs/DEV/DEV-REPORT.json`, `e2/runs/QUAL/QUALIFY.json`.

- **Qualification: PASS.** 120 calls, 0 failed. no_evidence: 0/40 contaminated (all "not found in memory"). gold_evidence: 40/40 correct (≥ 0.70 required). stale_derived: 40/40 repeated the stale value (reported, not gating; see §10 item on the control's construction).
- **K-delivery: PASS.** A6 served ≥ 1 summary on 100% of AGG, DERIVED and MULTIHOP probes (119/119) and of CURRENT probes (40/40). Summaries per A6 probe: 2 on 154, 3 on 5. Node status over all A6 probes: 323 served, 152 skipped_no_fit, 2 none. Final summary caches: 43, of which 34 truncated; median cost 245 raw → 187 served est. tokens. The 80% threshold is kept: the observed rate leaves wide headroom, and a confirmatory stream with < 80% would signal a serving regression, not noise.
- **Accuracy (DEV, not results):** A6 0.409, A6-syn 0.421, raw 0.403. By class (A6 / A6-syn / raw): AGG .425/.500/.450; DERIVED .375/.325/.350; MULTIHOP .051/.051/.000; CURRENT .775/.800/.800. Failed calls 0; max_tokens stops 0; leak units 0 in all 4 streams.
- **Floor effect (new, see §10):** 80 of 159 DEV tasks are wrong in all three arms. MULTIHOP is near 0 in every arm: the question names the bridge entity only, so the answer paragraph (which names the project, not the person) is rarely retrieved. Tied-wrong tasks shrink paired differences toward 0, which favours H-NI.
- **Per-stream mean paired differences:** A6 − raw = 0, +.05, +.05, −.077; A6 − A6-syn = +.05, −.025, 0, −.077. sd̂ = 0.060.
- **§7 rule applied:** power(32) > 0.99 at sd̂ = 0.060, so **32 streams are kept**; no reserve streams are added.
- **Usage:** 649 live calls (135 synth, 514 answer; target ≈660), 0 failed; tokens 1,017,102 input + 395,119 output + 152,598 cache-read. Qualification: 105,262 input + 2,318 output + 24,295 cache-read. Token Plan before (13:30 IST): 5-hour window 97% remaining, week 89%; after (13:56 IST): window 94%, week 89%. Wall time 13–16 min per stream (4 processes, rate-limited by 2062 retries).

## 5. Arms (B = 2k, world F only, common warm state cloned) [K1:46]

1. **A6 (fixed serving).** As PR:118, with the A6S fixes:
   - (a) Make summaries fit. *Resolved (head of research, rev 3):* each served summary is capped at **≤ 200 estimated tokens** (label included, `common.py` costing; `SYN_OUT_CAP = B/10`) by sentence-boundary truncation (word-prefix + "…" fallback), flagged `truncated` with raw and served cost logged. The synth instruction is changed from "≤ 120 words" (PR:163) to "≤ 50 words" so the model writes what fits (≈3–4 est. tokens/word under `common.py` costing) and truncation is a backstop. The ⅕B = 400 header cap is unchanged.
     - **Why 200, not 400 (rev 2):** a 400-token per-summary cap equalled the whole 400-token header, so A6 could serve at most one near-cap summary per probe (rev-2 smoke: 1 served, 2 `skipped_no_fit`). At 200, up to two capped summaries fit in the header, so A6's top-3 routed nodes can contribute more than one summary. Skip-and-continue is kept. (The ≤120-word instruction alone is not enough: median 107 words but 452 tokens, `E1/a6_serving.out:32`.)
     - Treatment = "every top-3 node summary that fits the header, in node-rank order, is served". Truncation rate and served count per probe are reported.
   - (b) *Resolved:* header packing is skip-and-continue instead of `break`. On saved P3 states this would raise served probes from 55 to 55+119 = 174/306 (`E1/a6_header_replay.out:6-7`; A6S:34).
   - (c) *Implemented:* every answer row carries a read `trace` (top_nodes; per-node status served / skipped_no_fit / none; served summary ids; header and raw token estimates; raw and write-back counts). `pilot-v1.3/pilot/run.py:92` dropped these; E2 uses its own runner.
   - Implementation: `e2/arms_e2.py` `A6E2` subclasses pilot A6 read-only (code edges, lazy keyed recompute, same warm state for A6 and A6-syn).
2. **A6−syn (ablation, = "A6-no-summary").** Identical to A6 but with no summary header: additive routing plus raw only [PR:123]. Same warm state, same B, same answerer. This isolates summary delivery from routing.
3. **Reranked raw.**
   - Candidates: surviving raw sessions only, in the same paragraph chunks as RS (`pilot-v1.3/pilot/arms.py:494-495`), retrieved by cosine with the same embedder (gte-modernbert-base, `pilot-v1.3/pilot/embed.py:27-33`) to the top-50 (*proposed*, `TOP_K`).
   - Reranking: local cross-encoder `Alibaba-NLP/gte-reranker-modernbert-base` @ f7481e6, fp32 safetensors on CPU (*proposed*; the int8 ONNX export ran ~16 s/pair and was rejected; fp32 runs 50 pairs in ~1.7 s). Its compute (pairs, seconds) is metered per stream and reported [K1:59].
   - Packing: prefix-fill to B by the house budget law (`pilot-v1.3/pilot/common.py:60-69`).
   - Ingest uses zero generative calls, as in RAW-RAG [astra-2026-10-23/J4-lit-deep-read/J4-lit-deep-read.md:205]. This replaces weak RS (no reranker [J4:211]).
4. **RS: dropped** (*resolved, default*).

## 6. Design, sampling and analysis

- **Size:** 32 independent streams × 40 distinct post-delete tasks, 10 per class (aggregate, surviving-support derivation, multi-hop, current/supersession). That is 320 per class and 1,280 paired tasks [K1:46].
- **Seeds:** (rev 5 supply after the AGG regeneration: all 32 confirmatory streams still have 40 tasks; DEV 7269004 has 38; reserve 7260044 has 39.) Confirmatory streams 7260001–7260032 (generator `eng-pin` gen_stream); DEV 7269001–7269004; stream-addition reserve 7260033–7260047 and 7260049, used in that order only if the §7 rule fires (7260048 is skipped: the generator yields 39 tasks, short 1 DERIVED). Supply check after the rev-4 regeneration (same seeds): all 32 confirmatory streams have the full 40 tasks; reserve 7260044 has 39 and DEV 7269004 has 38 (MULTIHOP short) (`e2/data/SUPPLY.json`). *Resolved:* both are used as-is (DEV only / reserve only if reached).
- **Deletion:** the generator's scheduled deletions plus 6 extra fact-dense sessions forgotten at t_end after all ingest. 10 warm questions on A6 with write-back precede deletion. An integrity check asserts no deleted session survives in units, write-backs, summary dependencies or RR chunks.
- **Task classes** (`e2/tasks.py`, ledger-only, deterministic, keys disjoint across classes; deletion-touched keys first, seeded tie-break): AGG = count of distinct values recorded in surviving sessions (rev 5: keys drawn from base keys with ≥ 1 value in the full ledger, stratified by surviving count {0, 1, ≥ 2} and interleaved 2, 1, 0, so gold is not constant; confirmatory AGG gold distribution 0 → 96, 1 → 96, 2 → 128 tasks, so a constant answer scores at most .40), stated in the question ("Count only values recorded in sessions that are still in memory (deleted sessions do not count), and ignore values that were only proposed, quoted or hypothetical"); DERIVED = derived key (lead/owner → office/team) with surviving support; MULTIHOP = 2-hop reverse composition through a person who owns/leads exactly one entity, *bridge-linked* (rev 4): the later of the two surviving gold assertions gets one appended sentence restating the other fact (true at that time in both the undeleted and post-delete ledgers) and the matching OBSERVE event, so the chain is retrievable from the question; golds, deletions and fact counts are unchanged (tested, `tests/test_multihop_bridge.py`). This makes MULTIHOP a bridge-linked co-mention task, not a free-standing compositional one, and it is reported as such; CURRENT = current value of a superseded key.
- **Strata:** fits-in-budget vs distributed-support are pre-declared descriptive strata [K1:46]. *Label limits (rev 5, Astra finding 6):* every task's surviving support fits within B (max 441.6 est. tokens), so "distributed" means support spread over sessions, not support exceeding B; no claim is made about over-budget support. MULTIHOP is bridge-linked co-mention retrieval and claims are restricted to that.
- **Scoring:** exact controlled gold (`e2/tasks.py:score`), identical for every arm (DEFAULTS #21–22). AGG: the answer must contain exactly one distinct number (digits or one–ten) and it must equal gold; zero or several distinct numbers score wrong. AGG gold 0 is accepted as "0", "zero" or "none". Other classes, **primary (strict):** gold regex hit AND no deleted/outdated value mentioned; an answer containing "not found in memory" scores wrong even if it also names the gold (abstention override, rev 5). Refusals and failed calls (no answer after all retries; rate-limit throttling has its own retry budget) score wrong; `max_tokens` truncations are scored as returned, cached (first sample final) and flagged; both are reported as failure denominators. Calls that fail after all retries are not cached, are retried if the run is resumed, and count as failures if they still fail. **Answer prompt (rev 5, all arms identical):** the fixed precedence instruction in `e2/arms_e2.py:E2_PREFIX` (answer from the underlying current facts when an inferred statement conflicts with them; prefer the most recent excerpt when excerpts disagree); its hash is frozen.
- **Human audit protocol (descriptive; never changes a score):** after scoring, a sample of rows is exported with the arm label removed and rows shuffled: all rows where strict and lenient disagree, all rows with `abstained` or `max_tokens`, and 20 randomly chosen (seeded) rows per class that score wrong in all arms. The auditor marks each as gold-correct / gold-wrong / ambiguous; the agreement rate with the automatic score is reported per class. Arm labels are re-attached only after marking.
- **Primary analysis:** a paired difference per task, averaged within each stream, then a t-interval across the 32 streams. CONFIRM uses `analyze(strict=True)`: a duplicate (stream, task, arm) row or an incomplete arm triplet is an error, never silently dropped; outcomes are decided on unrounded CI bounds (rounding is for display only). A stream that cannot deliver a complete triplet for every task after resume is reported as a delivery failure and the run is not scored until resolved. The two primary contrasts are A6 − raw and A6 − (A6−syn), at α = .025 each, two-sided. H-NI uses the one-sided 97.5% bound for A6 − raw. The endpoint uses all four classes (MULTIHOP passed the DEV2 floor rule). Implementation: `e2/analysis.py` (tested).
- **Prespecified sensitivity analyses** (reported next to the primary, never replacing it; DEFAULTS #22, #24): **S1** (diagnostic) the same contrasts on tasks *not* wrong in all three arms (ties-at-zero removed, because tied failures pull A6 − RR toward 0 and favour H-NI); **S2** lenient scoring (gold hit regardless of other mentions), which sizes any penalty strict scoring puts on arms that show value history; **per-class floors**: per-arm accuracy per class, a class is *floored* if its best arm is < 0.15. If S1 or S2 reaches a different outcome than the primary, the primary outcome stands and the disagreement is reported in the abstract-level summary.
- **Secondary:** per-class contrasts are descriptive only. Their power is .16–.65 [K1:57].
- **Scope:** this F-only design cannot claim ΔRec or deletion-induced utility loss [K1:59]. It is a new utility study, not confirmation of the leakage family [K1:46].
- **Treatment receipts:** report the summary-served rate per arm and per class from the per-probe logs (§5.1c). The analysis is valid only if K-delivery passed.

## 7. Power and cost ceiling (assumptions, not observations)

**Power** [ASSUMPTION, all from K1:50-55]: Var(stream mean) = V[ρ + (1−ρ)/40], with V ∈ {.20, .50} and ICC ρ ∈ {.05, .10}. Streams are independent.

| V / ICC | Power at 32 streams, 10pp | Streams for 80% at 10pp / 5pp |
|---|---:|---:|
| .20 / .05 | .987 | 17 / 59 |
| .20 / .10 | .890 | 26 / 96 |
| .50 / .05 | .720 | 38 / 143 |
| .50 / .10 | .481 | 61 / 236 |

No saved data supplies MiniMax variance or ICC. P3 has 0 F discordances across 44 relevant tasks, and P2 has 1 across 14 (K1:48, citing `scratch/audit_k1.out:23-25,33-48`).

**Stream-addition rule (fixed 24 Oct 2026, before any DEV or confirmatory data; `e2/e2/power.py`, tested):**
- sd̂ = the larger of the two sample SDs (ddof = 1) of the per-stream mean paired differences on the 4 DEV streams, over the two primary contrasts (A6 − raw, A6 − A6-syn).
- power(n) = one-sided α = .025 t-test power to detect a 10pp shift with n independent streams (noncentral t, df = n − 1). For H-NI this is the power to reject the null A6 − raw ≥ +10pp when the true difference is 0 (rev 5: sign corrected).
- *Limitation (rev 5, Astra):* H-ADV uses two two-sided contrasts at α = .025 each, so its power is lower than the rule's figure; Astra's review computes .713 at sd = .20 with 34 streams. The rule is not changed.
- If power(32) ≥ 0.8: keep 32 streams. Otherwise use the smallest n in 33…48 with power(n) ≥ 0.8, or 48 if none; the added streams are the reserve seeds in order. Nothing else may change the stream count, and the rule is applied once, on DEV only.
- For reference: sd̂ ≤ 0.19 keeps 32; sd̂ = 0.20 gives 34; sd̂ ≥ 0.23 hits the cap of 48 (power at 48 then < 0.8 and "inconclusive" is an expected outcome, stated at freeze).
- Limitation: sd̂ from 4 streams has 3 df and is imprecise; the rule is fixed rather than tuned for that reason.

**Cost ceiling (rev 5, numeric, frozen from DEV3; `E2-FREEZE.json` `cost_ceiling`).** Per confirmatory stream, nominal tokens (input + output; cache replays counted at their recorded usage): A6 lifecycle (warm state + synthesis + both A6 arms' answers; the shared warm state is charged to A6 and A6-syn, never to RR) ≤ **564,542** tokens and ≤ **59** synth calls; RR ≤ **100,233** tokens and ≤ **76** reranker CPU-seconds. These are 1.5× the DEV3 per-stream maximum (3× for reranker seconds, because 8 processes share the CPU). **Overrun rule:** if any confirmatory stream exceeds any limit, H-ADV is reported as *not cost-bounded* (an O1 outcome then carries that qualifier); the accuracy outcome is still reported. Actual per-stream spend is reported. B-matching is not called cost-matching [K1:19, K1:59].

## 8. Call budget (exact counts from the offline dry run; tokens are ESTIMATES) — `e2/COST.md`

| Item | Calls |
|---|---:|
| Terminal answers, 1,280 × 3 arms (A6, A6-syn, RR) | 3,840 |
| Common A6 warm answers (32 × 10) | 320 |
| Synthesis (dry run: 790 warm + 323 probe; 30–39 per stream) | 1,113 |
| DEV pass (4 DEV streams) | 659 |
| Qualification (stage 0) | 120 |
| **Total** | **6,052** |
| With 20% reserve | **7,262** |
| Strong-model calibration | dropped (§4) |

Estimated tokens: 13.3M (base) to 18.7M (max-output + reserve), i.e. 10.7–15.0% of one 5-hour window (≈125M), 1.1–1.5% of the week (≈1.25B), 0.27–0.37% of the month (≈5B). Plan sizes are Aditya's; the token figures are estimates from 19 smoke calls. The 30%-of-month cap is lifted (owner msg pt264u). Estimated wall time 20–40 min (8 processes), up to ≈2 h if rate-limited; the RPM ceiling is unmeasured.

**DEV observed (§4a):** DEV + qualification are now spent: 769 live calls, 1.67M tokens counted by the API (input + output + cache-read) against a 2.39M estimate for those two rows. The confirmatory remainder (5,273 calls) is projected at ≈ 12–13M tokens [INFERENCE: 8 × the 4-stream DEV total, as each DEV stream has the same structure]. DEV hit the "Token Plan rate limit" (HTTP 429, code 2062) at ~16 concurrent requests and ran 13–16 min per stream; with 8 processes the confirmatory run is re-estimated at 1–2 h [INFERENCE].

## 9. Gates

- **26 Oct 2026:** freeze. This requires qualification passed, K-delivery passed on DEV, §10 resolved, and a hash committed [K1:59].
- **30 Oct 2026:** data collection complete [K1:59].
- **If either gate is missed:** no confirmatory claim and no further E2 spend (*confirmed, head of research, 24 Oct*). Deliver the scoped descriptive paper (J3's smallest defensible claim, `astra-2026-10-23/J3-hostile-reviewer/J3-hostile-reviewer.md:372`; J8 scoped study, `.../J8-hostile-reviewer-systems.md:204`), with E1 as the cost section.
- **Top-reviewer bar** [K1:61]: frozen endpoints, qualified controls, delivered-treatment receipts, honest failure denominators, independent-stream inference, and complete lifecycle accounting.

## 10. Decisions

**Resolved (head-of-research defaults and decisions, `e2/DEFAULTS.md` #1–25):** NI margin 10pp (5pp descriptive); per-summary cap 200 est. tokens with a ≤ 50-word synth instruction, header cap ⅕B unchanged; skip-and-continue packing; treatment = summaries served, with the A6-syn ablation; RS dropped; B = 2k only; MiniMax-M3.1-Flash via the Token Plan API key (no CLI, no proxy); if MiniMax fails qualification → scoped paper; per-probe read trace logged; budget cap lifted; no separate strong-model calibration (§4); qualification with a responsive positive control, implemented and PASSED (§4a); K-delivery 80%, PASSED on DEV (§4a); stream-addition rule fixed before DEV and applied: 32 streams (§7); gates: missing 26 Oct freeze or 30 Oct data → scoped descriptive paper, no further E2 spend (§9); DEV 7269004 runs with 39 tasks (DEV only); one sample per call, cache-reproducible, stated as a limitation (§4); Credits guard pauses at ≤ 2% of the 5-hour window; rev 4 (Research sign-off, DEFAULTS #20–25): MULTIHOP bridge-linked and kept in the endpoint (DEV2 best arm .789 ≥ .15); AGG wording and exactly-one-number parse; strict primary scoring with lenient sensitivity S2; stale note dated at the outdated value; S1 floor sensitivity and per-class floors; supply after regeneration (all 32 confirmatory streams have 40 tasks).

**Confirmed at freeze (rev 5, Research under owner authority pt265u):** reranker `gte-reranker-modernbert-base` fp32, cosine top-50 (§5.3); `GOLD_MIN` = 0.70.

**Revision ledger.** rev 1 (zero calls) → rev 2 (defaults, harness, smoke, dry run) → rev 3 (head-of-research decisions #11–19; DEV/QUAL) → rev 4 (Research sign-off #20–25; MULTIHOP bridge, AGG wording, strict/lenient scoring, stale dating; DEV2/QUAL2) → rev 5 (Astra FIX-THEN-RUN, #26–35; AGG strata, precedence prompt, enforced gates, truncation/abstention/resume, cost ceiling, rate-limit budget; DEV3/QUAL3). Every revision was made before any confirmatory seed was run. After the freeze no task class, task, scoring rule, prompt or endpoint changes; any deviation is reported as a deviation.

**Previously OPEN items (DEV pass), now resolved in rev 4:** 1 floor effect → MULTIHOP re-authored, S1 + per-class floors (DEFAULTS #20, #24); 2 AGG gold definition → stated in the question (#21); 3 stale-control dating → dated at the outdated value (#23); 4 task/scoring sign-off → #20–22. No OPEN items remain; the hostile review (Astra) is the last pre-freeze check.
