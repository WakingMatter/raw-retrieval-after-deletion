# A6 summary-serving audit: how often A6 served a summary, and why

2026-10-24 IST. Zero model calls. Sources: `E1/a6_serving.out`, which counts every A6-family `answers.jsonl` and computes the cost of every A6 synth output from memo text, and `E1/a6_header_replay.out`. The replay reruns the A6 header decision for every PILOT3 terminal probe from the saved `db/store.sqlite` (opened immutable), the on-disk vector cache (np.load only, no encoder) and the final `artifacts.json` summaries.

## Counts (terminal probes; F world unless noted)

| run | instance | probes with a summary served | max summaries per probe |
|---|---|---|---|
| PILOT3 | A6-F | **55/306** (a6_serving.out:21) | 1 |
| PILOT3 | A6-C | 89/306 (out:23) | 1 |
| PILOT3 | A6-eager-F | 55/306, byte-identical prompts to A6-F in 306/306 (out:25,33) | 1 |
| PILOT3 | A6m-F | 11/306 (out:27) | 1 |
| PILOT2 | A6-F | 54/206 (out:4) | 1 |
| PILOT2 | A6m-F | 6/206 (out:10) | 1 |

PILOT3 A6-F by probe kind (out:22; this matches K1's scratch/audit_k1.out:54-68):
AGG 0/6 · DERIVED 0/6 · multi_hop 0/19 · use_in_task 0/8 · premise_bait 0/3 · unaffected_control 0/4 · current 1/11 · SUMM 4/23 · ENUM 9/40 · HIST 9/53 · DIRECT 28/125 · deleted_retracted_absent 4/8.
The classes that synthesis is supposed to help (AGG, DERIVED, multi-hop) got a summary **0 times out of 31**. Warm reads: 9/37 (out:31).

## Code path

`pilot-v1.3/pilot/arms.py:156-173` (A6.read):
1. Rank nodes by centroid·q and keep the top 3 (lines 158-160).
2. For each top node in rank order, call `self.summary()` first (line 164). This synthesizes the summary if it's missing or stale, so synth tokens are spent even if the summary is then dropped. Skip it if it returns None (fewer than 2 inputs, lines 144-146 and 165-166).
3. `cost = item_cost(text)` (line 170), which is `local_tokens(text+"\n\n")×1.15` (common.py:56-57). `local_tokens` charges 1 per digit and per punctuation mark (eng-pin/arms/adapters.py:59-72), so date-heavy summaries cost a lot.
4. **`if used + cost > B/5: break`** (lines 171-172). With B=2000 the cap is 400 estimated tokens. `break`, not `continue`: the first summary that doesn't fit stops the header loop, and lower-ranked summaries that would fit are never tried.

## Why so few summaries are served (measured)

- Only **50/173** (28.9%) of the distinct A6 synth outputs in PILOT3 fit under 400 even on their own. The median header cost is 452, p90 is 626 (a6_serving.out:32). PILOT2: 38/108 (35.2%), median 435 (out:15).
- The synth prompt asks for "≤ 120 words" (common.py:26-27), but 63/173 outputs exceed 120 words (out:32). Even compliant outputs often exceed 400 estimated tokens because of the per-digit charge on dates.
- The replay reproduces the logged served summaries **exactly in 306/306** A6-F and 306/306 A6-C probes (a6_header_replay.out:4 and the A6-C block). Of the 251 A6-F probes without a summary, **all 251** had a top-3 summary that existed but the first one was over the cap. There was no probe where the top 3 simply had no summary (out:5-7). In **119** of those 251, a lower-ranked top-3 summary would have fit alone but was skipped by `break` (out:6).
- Two summaries never fit together, so at most one summary is ever served (max 1 in every instance above).
- Counterfactual, computed from logged state only, with no new calls: with `continue` instead of `break`, A6-F would serve ≥1 summary on 55+119 = **174/306** probes. With no cap it would be 306/306, at the cost of raw budget.

## Verdict: design as specified, not a code bug, but the design fails to deliver the treatment

- The ⅕B header cap is preregistered: PREREG v1.2.1 line 118 ("summaries of the top-ranked nodes as a header capped at ⅕ B [D]") and T8 at line 465 ("header ≤ ⅕ B"). The code implements it faithfully.
- `break` follows the same prefix-fill "Eng budget law" used for raw items (common.py:60-69, "stop at the first item that would cross B"). The prereg doesn't say whether the header uses prefix-fill or skip-and-continue, so this is an implementation choice consistent with the house rule, not a deviation.
- The cause is the parameter interaction: a 120-word synth target, a digit-heavy estimator with ×1.15 safety, and a 400-token header. The result is that A6 is mostly a raw-retrieval arm restricted to the top-3 nodes. The A6 vs RS answer prompts match in only 26/306 probes (a6_serving.out:35), because A6's raw pool is limited to top-3 node members.
- Consequences:
  - "A6 = A6-eager = A6m" in accuracy (PILOT3-GROK-FULL/REPORT.md:57-59) is not evidence about lazy vs eager or about edge type. On 306/306 probes lazy and eager got identical prompts.
  - Any KC3-style "synthesis earns nothing" reading (prereg L334) from these pilots is under-powered by construction: AGG, DERIVED and multi-hop got zero summaries.
  - Synth tokens are spent on summaries that are then discarded (arms.py:164 runs before 171).
- For E2 (see prereg-E2 draft): the summary length needs to fit the header budget (e.g. a token cap enforced on the synth output, or header cap ≥ the p90 summary cost). Use skip-and-continue or score-ordered packing. Log `top_nodes` and `header_tokens_est` per probe; `run.py:92` currently drops the read trace. Run A6-no-summary as the ablation so that "synthesis delivered" is measured, not assumed.
