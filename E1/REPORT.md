# E1: zero-call replay of the lazy / eager / delete-on-touch cost frontier

2026-10-24 IST. **No model calls.** This uses only saved run outputs, read-only: `stats.json`, `log.json`, `residue_bytes.json`, `answers.jsonl` and `calls.jsonl`, plus the memo text for synth outputs. Scripts: `E1/replay_cost.py` → `E1/replay_cost.out`, `E1/a6_serving.py` → `E1/a6_serving.out`, `E1/a6_header_replay.py` → `E1/a6_header_replay.out`. Below, "out:N" means line N of the named `.out` file.

Definitions. **Logical** calls count every call the arm issued, memo hits included; that is what a cold run pays. **Real** calls are `memo:false`. Tokens are logical in+out. Latency is the mean / p95 over real ok calls only, because memo-hit latency just replays the original call and so isn't a fresh measurement. Only DONE instances are counted.

## 1. Per-policy cost tables

**PILOT2** (B=2000, 2 streams, grok answerer; replay_cost.out:5-14, 19-28)

| policy | arm-instance | logical calls | synth | forget-phase calls (tok) | tokens | tokens/answer | forget wall_s total (median) |
|---|---|---|---|---|---|---|---|
| lazy | A6-F | 281 | 52 | 0 | 7,493,210 | 36,375 | 0.46 (0.019) |
| eager | A6-eager-F | 316 | 87 | 55 (1,671,244) | 8,549,606 | 41,503 | 2,781.81 (192.5) |
| delete-on-touch | A3+DoT-F | 719 | 0 | 159 (4,621,801) | 19,961,567 | 96,901 | 2,342.11 (168.0) |
| stored-notes redact | A3n-F | 734 | 0 | 175 (5,471,250) | 20,799,340 | 100,968 | 3,279.13 (187.9) |
| raw baseline | RS-F | 206 | 0 | 0 | 5,331,271 | 25,880 | 0.34 (0.003) |

**PILOT3-GROK-FULL** (5 streams; A3 family not complete under grok; replay_cost.out:35-41, 46-52)

| policy | arm-instance | logical calls | synth | forget-phase calls (tok) | tokens | tokens/answer | forget wall_s total (median) |
|---|---|---|---|---|---|---|---|
| lazy | A6-F | 442 | 99 | 0 | 11,727,010 | 38,324 | 10.85 (0.066) |
| eager | A6-eager-F | 487 | 144 | 88 (2,639,988) | 13,050,432 | 42,648 | 3,191.88 (36.2) |
| lazy, model-cited edges | A6m-F | 442 | 99 | 0 | 12,387,407 | 40,482 | 9.08 (0.057) |
| raw baseline | RS-F | 306 | 0 | 0 | 7,782,285 | 25,432 | 7.91 (0.042) |

**PILOT3-ASTRA** (gpt-6-astra answerer, A3 family only; 2 DONE F streams, 7240241 and 7240242, where 242's F instances finished in the 00:21 IST resume; replay_cost.out:59-62, 67-70). Never pooled with the grok runs.

| policy | arm-instance | logical calls | forget-phase calls (tok) | tokens | tokens/answer | forget wall_s total (median) |
|---|---|---|---|---|---|---|
| delete-on-touch | A3+DoT-F | 580 | 121 (1,374,516) | 6,622,756 | 55,653 | 188.49 (0.020) |
| pure DoT | A3+DoTn-F | 589 | 130 (1,591,488) | 6,851,936 | 57,579 | 215.55 (6.97) |
| redact | A3n-F | 617 | 158 (1,996,783) | 7,258,724 | 60,998 | 381.74 (14.97) |

Real-call latency (mean / p95 s) is in the same rows of replay_cost.out. Example: P3 A6-F 15.9 / 41.6 (n 139) and A6-eager-F 21.5 / 51.5 (n 98) (out:36-37). Treat these as noisy because the samples are memo-thinned and provider latency varied over time. PILOT3-GROK-FULL/REPORT.md:65 logged no p95 (`{}`).

## 2. Headline numbers

1. **Eager costs more and buys nothing at answer time in these runs.**
   - Extra cost over lazy: +45 synth calls and +1,323,422 tokens (+11.3%) in P3 (out:36-37); +35 synth and +1,056,396 tokens (+14.1%) in P2 (out:9-10).
   - Forget-time wall clock goes from 10.85 s to 3,191.88 s over 40 forgets (out:47-48).
   - The F-world terminal answer prompts of A6 and A6-eager are byte-identical in **306/306** (P3) and **206/206** (P2) probes (a6_serving.out:33,16). R/retained/current scores are therefore identical: PILOT3-GROK-FULL/REPORT.md:9-10,57-58; PILOT2/REPORT.md:85,87.
   - Of the eager recomputes, **68/88** (P3) and **41/55** (P2) were later replaced by another recompute of the same node, so their output never survived to probe time (replay_cost.out:54,30). In 63/88 and 36/55 cases the replacement was itself another eager recompute at a later forget.
2. **Delete-on-touch is the most expensive policy at forget time** and the only one that loses retained accuracy.
   - P2: A3+DoT-F used 719 logical calls and 19.96M tokens, 2.66× A6-F's tokens (out:5,9). Its 16 forgets took 2,342 s (out:19).
   - Retained AccF: 0.412 vs 0.912 for A3n (PILOT2/REPORT.md:86,88), and 0.375 vs 0.875 under Astra (PILOT3-ASTRA/REPORT.md:22,21).
   - Pure DoT (A3+DoTn) kept retained 0.875 (PILOT3-ASTRA/REPORT.md:23). Its notes deleted were 264 vs 2,053 for A3+DoT (out:67-68).
3. **Deletion correctness.**
   - X canary RecF is 0 for A6, A6-eager, A6m, RS and A3+DoT in PILOT2 (REPORT.md:16-17,42-43,55-56,67-68,80-81). A3n is 0.25 (REPORT.md:29-30).
   - Under Astra: A3n 0.571, DoT and DoTn 0 (PILOT3-ASTRA/REPORT.md:21-23).
   - Canary bytes in the store files are 0 for every A6/RS/DoT instance, against 5 (P2) and 15 (Astra, 2 streams) for A3n-F (out:21,70).
   - kc1a (subtraction == rebuild) held in 16/16 (P2) and 40/40 (P3) forgets for A6, A6-eager and A6m (out:23-26,47-50).
   - R ΔRec is 0.000 for all four P3 arms (PILOT3-GROK-FULL/REPORT.md:9-12).

## 3. What is only true by construction (read this before citing §2)

- **Lazy ≤ eager in recompute count is guaranteed by the code.** Eager recomputes every invalidated cache at forget time (pilot-v1.3/pilot/arms.py:251-254). The probe-time cache key is the input set at t_query (arms.py:93-101,147-148), so any summary computed before the last ingest that touches that node is superseded anyway. So the eager overhead and the 306/306 prompt identity are consequences of the design plus the memo, not empirical findings about memory policy. The empirical content is the size of the overhead (+11–14% tokens; 68/88 recomputes wasted) on this ingest/forget interleaving.
- **The memo hides cost differences.** Identical prompts reuse one cached output across arms (logical ≠ real; real counts are in out:5-14). The real-call counts are an accounting artifact of run order and shouldn't be compared across arms.
- **Lazy forget wall_s is near zero because A6 forget is pure integer subtraction plus cache invalidation.** No model call happens at forget (arms.py:236-258). The cost is deferred to the next read; it is moved, not removed.
- **DoT vs lazy is confounded by substrate.** DoT runs on the A3 LLM-written notes store (arms.py:430-485), not on the A6 graph. Its cost is mostly the notes pipeline (write, cluster rebuild), not the delete-on-touch rule itself. A fair DoT-on-A6 arm doesn't exist in the saved runs.
- **A6's accuracy equals RS-like raw retrieval partly because A6 mostly serves no summary.** It serves a summary on 55/306 F probes (a6_serving.out:21; see `E1/A6-SERVING.md`). So "computed memory costs 1.5× RS for equal accuracy" (A6-F 11.73M vs RS-F 7.78M tokens, out:36,41) is a statement about this parameterization, not about synthesis.

## 4. Limits

- n is 2 streams (P2), 5 (P3) and 2 F streams (Astra). Answerers differ across runs (grok-4.7 vs gpt-6-astra), so there is no cross-run pooling.
- PILOT3 had 17,610 real calls, of which 14,511 failed (PILOT3-GROK-FULL/REPORT.md:66). Only the 36 clean instances are in the scoring view, and the A3 family has no grok P3 data.
- The logs carry no per-call dollar cost and no tokenizer-exact header sizes. Header costs use the run's own estimator (`local_tokens`×1.15).
- No cold/hot/burst workload was replayed. The only interleaving is the fixed stream schedule: 8 forgets per stream interleaved with 60 ingests (log.json). A burst-forget regime would favour lazy even more, and a read-heavy regime between forgets would narrow the gap. That is not measured here.
- Recomputing a summary for a counterfactual policy would need a model call, which was not done. Every number above is either logged or a deterministic function of logged state.
