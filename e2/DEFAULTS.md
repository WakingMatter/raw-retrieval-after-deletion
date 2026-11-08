# E2 decisions applied (head-of-research defaults, 24 Oct 2026)

| # | Decision | Applied as | Where |
|---|---|---|---|
| 1 | NI margin | Δ = 10pp confirmatory; 5pp CI reported, descriptive only | prereg §3 |
| 2 | Summary fit | **rev 3:** each served summary capped at 200 est. tokens (`common.py` costing, label incl.), sentence-boundary truncation, flagged `truncated`; synth instruction "≤ 50 words" (was ≤ 120); header cap stays ⅕B = 400 | `e2/arms_e2.py` `SYN_OUT_CAP`, `SYN_WORDS`, `cap_summary` |
| 3 | Header packing | skip-and-continue (no `break`) | `A6E2.read` |
| 4 | Treatment | A6 = summaries actually served; A6-syn = no-summary ablation on the same state | `A6E2.ask(syn=)` |
| 5 | RS arm | dropped | `run_e2.ARMS` |
| 6 | B | 2k only | `B_DEFAULT` |
| 7 | Answer model | MiniMax-M3.1-Flash via Token Plan API key, official endpoint; no CLI, no proxy | `e2/minimax_api.py` |
| 8 | If MiniMax fails qualification | no E2 on another model; write the scoped paper | prereg §2 K-answerer |
| 9 | Per-probe read trace | `trace` on every answer row: top_nodes, node status (served / skipped_no_fit / none), served summary ids, header/raw tokens | `answers.jsonl` |
| 10 | Budget | 30%-of-month cap lifted; full 32 streams, no trimming; max out the week if needed | `COST.md` |

Change in rev 3 (head of research, 24 Oct): the per-summary cap was 400 est. tokens, equal to the whole 400-token
header cap, so A6 could serve at most one near-cap summary per probe (rev-2 smoke: 1 served, 2 `skipped_no_fit`).
It is now 200, so up to two capped summaries fit the header; skip-and-continue is kept. The synth instruction asks for
≤ 50 words so the model writes what fits and truncation is a backstop.

## Head-of-research decisions, rev 3 (24 Oct 2026)

| # | Decision | Applied as |
|---|---|---|
| 11 | No separate strong-model calibration | MiniMax matched saved Astra answers and the API route agreed (smoke); prereg §4 |
| 12 | Summary cap 200 (above) | `SYN_OUT_CAP = B/10` |
| 13 | Qualification needs a responsive positive control | `e2/qualify.py`, gold_evidence acc ≥ 0.70; always-abstain must FAIL (tests) |
| 14 | K-delivery stays 80% | justified from DEV A6 served rate; below 80% on DEV → report, do not freeze |
| 15 | Stream-addition rule fixed before DEV | `e2/power.py`; 32 → up to 48 (reserve seeds); prereg §7 |
| 16 | Gates | missing 26 Oct freeze or 30 Oct data → scoped descriptive paper, no further E2 spend |
| 17 | DEV 7269004 short 1 MULTIHOP | runs with 39 tasks, DEV only, noted |
| 18 | One sample per call | per-call cache gives reproducibility; non-determinism is a stated limitation |
| 19 | Credits guard | pause at ≤ 2% of the 5-hour window remaining (kept) |

## Research sign-off decisions, rev 4 (24 Oct 2026, under owner authority pt265u; before any confirmatory data)

| # | Decision | Applied as |
|---|---|---|
| 20 | **Task classes.** Keep AGG, DERIVED, MULTIHOP, CURRENT (10 each). MULTIHOP re-authored as a *bridge-linked* 2-hop: the later of the two surviving gold assertions (attribute value / owner-lead) gets one appended sentence restating the other fact, true at that time in both the undeleted and post-delete ledgers, plus the matching OBSERVE ledger event. Golds, deletions and fact counts are unchanged (tested). MULTIHOP stays in the primary endpoint only if some arm reaches ≥ 0.15 on DEV2 (one further fix allowed); otherwise it is dropped from the endpoint before freeze and reported descriptively. | `tasks.make_bridge`, `BRIDGE.json` per stream; `tests/test_multihop_bridge.py` |
| 21 | **AGG question and parse.** Question: "…had so far? Count only values recorded in sessions that are still in memory (deleted sessions do not count), and ignore values that were only proposed, quoted or hypothetical. Answer with a number." Score: the answer must contain exactly one distinct number (digits or one–ten) and it must equal gold; zero numbers or ≥ 2 distinct numbers score wrong (no guessing the "first" number). | `tasks.AGG_Q`, `tasks.score` |
| 22 | **Wrong-value mentions.** Primary (strict): correct = gold hit AND no deleted/outdated value mentioned. Prespecified sensitivity S2 (lenient): gold hit regardless. "Not found", refusals and failed calls are wrong. Same rule for every arm. Known directional risk: an arm whose context shows value history (e.g. A6 summaries) may hedge more, which strict scoring penalises; S2 reports the size of that effect. | `score()["correct"]`, `["correct_lenient"]` |
| 23 | **Stale-derived control.** The stale note is dated at the time the outdated value was recorded (`wrong_t`), not the query time, so newer evidence legitimately supersedes it. Still reported only, not gating. | `qualify.run_job` |
| 24 | **Floor sensitivity.** S1: primary contrasts recomputed on tasks not wrong in all three arms. Per-class floors: per-arm accuracy per class; a class is *floored* if its best arm < 0.15. Both reported next to the primary, never replacing it. | `e2/analysis.py` |
| 25 | **Supply after regeneration.** All 32 confirmatory streams have 40 tasks. DEV 7269004 has 38 (2 MULTIHOP short), reserve 7260044 has 39 (1 MULTIHOP short); used as-is if reached. | `data/SUPPLY.json` |

## Hostile-review fixes, rev 5 (24 Oct 2026, Research under owner authority pt265u; Astra verdict FIX-THEN-RUN, `astra-2026-10-24/E2-hostile-review/E2-hostile-review.md`; before any confirmatory data)

None of these changes the hypotheses, the two primary contrasts, α, Δ, the endpoint classes or the O1/O2/O3 rules.

| # | Astra finding | Disposition | Where |
|---|---|---|---|
| 26 | AGG gold constant ("2" on all 320 confirmatory tasks): a constant answer was a perfect baseline | AGG keys are now drawn from base keys with ≥ 1 value in the full ledger, stratified by surviving count {0, 1, ≥ 2}, interleaved 2, 1, 0. Gold 0 is accepted as "0", "zero" or "none". Confirmatory AGG gold distribution after regeneration: 0 → 96, 1 → 96, 2 → 128 (a constant "2" now scores .40). | `tasks.author_e2`, `tasks.score`, `tests/test_tasks.py` |
| 27 | Answerer not told the precedence rule; 38 DERIVED/MULTIHOP golds contradicted by a derived assertion | One fixed instruction added to the answer prompt for **all three arms** (`arms_e2.E2_PREFIX`): when an inference about one thing from another conflicts with the underlying current facts, answer from the facts; when excerpts disagree, prefer the most recent. Golds unchanged. Requires DEV3/QUAL3 rerun. | `arms_e2.E2_PREFIX` (A6E2.ask, RerankedRaw.ask, qualify) |
| 28 | Gates not enforced in code | `--confirm` now refuses unless `make_freeze.verify_frozen()` is clean (prereg + code + data hashes), seeds ⊆ frozen `confirmatory_run`, B = 2000, `--stream-threads 1`, not `--dry`, and the frozen qualification receipt says PASS. A leak (deleted session surviving anywhere) raises and stops the stream. `analysis.analyze(strict=True)` raises on duplicate rows or incomplete arm triplets (no silent drop). Freeze manifest adds per-stream manifest hashes, environment versions and the answer-prefix hash. | `run_e2.py`, `make_freeze.py`, `analysis.py` |
| 29 | Truncated answers scored empty and resampled on resume; abstention "Not found in memory; Mumbai…" passed; interrupted runs refused to resume | `max_tokens` answers are scored as returned and cached (first sample is final). Calls that fail after all retries stay uncached, are retried on resume and counted as failures if they still fail. Non-AGG answers containing "not found in memory" score wrong (`abstained`). A resumed stream discards its partial work dir and replays from the call cache. | `run_e2.py`, `minimax_api.py`, `tasks.score` |
| 30 | Exposure: 39/50 summaries truncated; MULTIHOP gold literal in the A6 header on 3/38 | Cap unchanged. Header gold coverage per class is reported (descriptive) and the interpretation is limited to *this truncating summarizer*. | `dev_report`, REPORT |
| 31 | Labels: every task's support fits in B (max 441.6 est. tokens); MULTIHOP is co-mention | Prereg states both: the "distributed-support" stratum is about where support lives, not about exceeding B; MULTIHOP claims are restricted to bridge-linked co-mention retrieval. | prereg §6 |
| 32 | Qualification controls CURRENT-only; stale control conflates mention and endorsement | Added descriptive per-class sufficient-evidence controls (3 AGG with gold > 0, 3 DERIVED, 3 MULTIHOP per DEV stream); stale rows record `endorses_stale` (stale value, no gold) vs `mentions_both`. The PASS rule is unchanged. | `qualify.py` |
| 33 | Cost ceiling undefined | Numeric per-stream lifecycle ceiling frozen from DEV3 (see prereg §7); per-stream metering in `summary.json`; the warm state is charged to both A6 arms. Overrun → H-ADV is reported as not cost-bounded; the accuracy outcome is still reported. | `make_freeze.py` `cost_ceiling`, prereg §7 |
| 34 | Revision paths open | Reranker (gte-reranker-modernbert-base fp32, cosine top-50) and GOLD_MIN = 0.70 confirmed; human-audit protocol written (blinded to arm, descriptive, never changes scores); revision ledger published; no further class drops or task changes after freeze. | prereg §6, §10 |
| 35 | SHOULD-FIX: power note, NI null sign, S1 status, rounding | §7 power note states superiority uses the two-sided contrasts; NI null is A6 − RR ≥ +Δ; S1 is diagnostic; outcome decisions use unrounded CI bounds (rounding for display only). | prereg §3/§6/§7, `analysis.tint` |
| 36 | (found in DEV3) A call failed after 8 consecutive 2062 rate-limit 429s and the failure was not metered | HTTP 429 throttling gets its own retry budget (60 retries, 5–35 s jittered sleeps) that does not consume `max_attempts`; a terminal failure writes a `call_failed` event, counted in `api_totals.failed`. Retry policy only; scoring of a still-failed call unchanged (wrong, reported). | `minimax_api.py`, `dev_report.py`, test `test_rate_limit_2062_has_own_budget_and_failure_is_logged` |
