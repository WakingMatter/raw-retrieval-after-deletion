# E4-sensitivity · REPORT (CONFIRM)

Scored 2026-10-26 06:23 IST with `PYTHONPATH=$PWD python3 -m e4.analyze_e4 --tag CONFIRM` (frozen code;
`verify_frozen() == []` checked immediately before). Output: `runs/CONFIRM/ANALYSIS.json`
(sha256 `40bb6104…9be7`). Token re-total: `runs/CONFIRM/TOKENS-RETOTAL.json`. n = 16 streams
(7280001–7280010, 7280012–7280017), 40 tasks each; unit = stream; paired across streams; df = 15.
Spec: `PREREG-E4.md`, `DEFAULTS.md` D01–D16, `E4-FREEZE.json`.

## 1. Verdict (rule exactly as frozen)

**SCOPED-KILL.** No F1 or F0 cell is Holm-significant under the IUT (every cell p_IUT = 1.0, Holm p = 1.0), so
there is no CLAIM. For all 7 F1 ∪ F0 cells the one-sided upper bound of A6 − RR at level 1 − 0.05/7 is below
δ = +0.05 (largest: +0.0153 at B = 8000). Per PREREG §4.2 the verdict is: *no meaningful (≥ 5-point) accuracy
niche for this A6 versus RR*, scoped to this generator at short history (L = 1), the recency-window summarizer
with the ≤ 50-word prompt, MiniMax-M3.1-Flash, B ∈ {125, …, 8000}, and the tested raw arms. No long-history
statement is possible (D03, T0 not run).

## 2. Confirmatory cells (A6 vs each required comparator)

diff = mean(A6 − C); 95% CI = two-sided paired t (unadjusted); LB = one-sided Bonferroni lower bound (α 0.025/k);
kill UB = one-sided upper bound of A6 − RR at 1 − 0.05/7; boot = stream-bootstrap 95% CI of A6 − RR (10,000).

| Fam | Cell | A6 | vs RR: diff [95% CI] | vs RR-2hop | vs A6-syn | vs RR-K | p_IUT / Holm | kill UB | boot vs RR |
|---|---|---|---|---|---|---|---|---|---|
| F1 | B500 1/5 cap100 | .4297 | −.1469 [−.1884, −.1053] (RR .5766) | −.1750 [−.2061, −.1439] | +.0312 [+.0134, +.0491] | — | 1 / 1 | −.0929 | [−.1813, −.1078] |
| F1 | B1000 1/5 cap200 | .4969 | −.1141 [−.1424, −.0857] (RR .6109) | −.1953 [−.2177, −.1729] | +.0078 [−.0232, +.0389] | — | 1 / 1 | −.0772 | [−.1375, −.0875] |
| F1 | B2000 1/5 cap200 | .5625 | −.0516 [−.0858, −.0173] (RR .6141) | −.1391 [−.1783, −.0999] | +.0375 [−.0002, +.0752] | — | 1 / 1 | −.0071 | [−.0797, −.0203] |
| F1 | B4000 1/5 cap200 | .5719 | −.0469 [−.0848, −.0089] (RR .6188) | −.1531 [−.2000, −.1062] | +.0297 [+.0101, +.0493] | −.1078 [−.1418, −.0739] | 1 / 1 | +.0025 | [−.0797, −.0140] |
| F1 | B8000 1/5 cap200 | .5797 | −.0422 [−.0864, +.0021] (RR .6219) | −.1516 [−.1983, −.1048] | −.0031 [−.0357, +.0295] | −.1453 [−.1725, −.1181] | 1 / 1 | +.0153 | [−.0812, −.0031] |
| F0 | B125 1/5 cap25 | .2281 | −.2031 [−.2525, −.1538] (RR .4312) | −.2078 [−.2574, −.1583] | −.0187 [−.0461, +.0086] | — | 1 / 1 | −.1390 | [−.2453, −.1563] |
| F0 | B125 2/5 cap50 | .1953 | −.2359 [−.2838, −.1880] (RR .4312) | −.2406 [−.2892, −.1920] | −.0516 [−.0797, −.0234] | — | 1 / 1 | −.1737 | [−.2781, −.1922] |

One-sided p (A6 > C) vs A6-syn: B500 .0010, B1000 .2998, B2000 .0255, B4000 .0028, B8000 .5796, B125/25 .9181,
B125/50 .9993. vs RR, RR-2hop, RR-K: ≥ .9699 everywhere. Bonferroni lower bounds are in `ANALYSIS.json`.
"Retrieval-package advantage" (IUT without A6-syn, descriptive): Holm p = 1 in every cell.

Comparator means: RR .4312 / .5766 / .6109 / .6141 / .6188 / .6219 at B = 125 / 500 / 1000 / 2000 / 4000 / 8000;
RR-2hop .4359 / .6047 / .6922 / .7016 / .7250 / .7312; A6-syn .2469 / .3984 / .4891 / .5250 / .5422 / .5828;
RR-K .6797 (B4000), .7250 (B8000).

## 3. Exploratory (cannot change the verdict)

**T2/T3: the other 26 A6 cells vs RR at the same B** (Holm over the 26 at 0.05): all diffs negative, all Holm p = 1.
Range: −.1781 (B500 2/5 cap100, A6 .3984) to −.0188 (B8000 1/5 cap1600 and B8000 2/5 cap3200, A6 .6031,
CI [−.0629, +.0254]). Full table with CIs: `ANALYSIS.json → exploratory_vs_RR`. Selected:

| A6 cell | A6 | diff vs RR [95% CI] |
|---|---|---|
| B1000 1/5 cap100 | .4828 | −.1281 [−.1635, −.0928] |
| B1000 2/5 cap200 | .5188 | −.0922 [−.1254, −.0589] |
| B2000 1/5 cap100 | .5391 | −.0750 [−.1130, −.0370] |
| B2000 1/5 cap400 | .5328 | −.0813 [−.1206, −.0419] |
| B2000 2/5 cap800 | .5484 | −.0656 [−.1057, −.0255] |
| B4000 2/5 cap1600 | .5766 | −.0422 [−.0856, +.0012] |
| B8000 1/5 cap400 | .5906 | −.0313 [−.0700, +.0075] |
| B8000 1/5 cap1600 | .6031 | −.0188 [−.0629, +.0254] |

**T4 (length-instructed, B2000 share 1/5) vs reference prompt at the identical cell:**

| Variant | A6-T4 | Ref | diff [95% CI] | p one-sided | Compliance (raw ≤ cap) | Ref prompt ≤ cap |
|---|---|---|---|---|---|---|
| len100 (cap 100) | .5484 | .5391 | +.0094 [−.0263, +.0451] | .292 | 1 / 204 (2 failed) | 2 / 202 |
| len400 (cap 400) | .5406 | .5328 | +.0078 [−.0183, +.0339] | .2663 | 9 / 204 (1 failed) | 175 / 202 |

The length instruction did not produce compliant summaries (1 and 9 of 204 within cap), so T4 does not test
what it was meant to test; treat it as uninformative.

**Over-budget subset at B = 125** (tasks whose minimal support > 125; n = 145 task-streams): RR .7034, RR-2hop
.7103, A6-syn .3034, A6 cap25 .2897, A6 cap50 .2345.

**By class at B2000** (descriptive): A6 cap200 AGG .431 / CURRENT .756 / DERIVED .500 / MULTIHOP .562; RR .506 /
.800 / .362 / .787; RR-2hop .506 / .794 / .656 / .850. A6 beats RR only on DERIVED.

## 4. Predictions (PREREG §5) against results

- **P1** (RR ≥ A6 at every B ≤ 4000; widest gap at B500; −.05 to −.10): direction held at every B; among
  B ≥ 500 the widest gap is B500, but its size (−.1469) is outside the predicted range, as is B1000 (−.1141).
- **P2** (gap moves toward 0 at B8000; A6 does not beat RR-K): held (−.0422 at B8000, shrinking monotonically from
  B500; A6 − RR-K = −.1453).
- **P3** (A6 − A6-syn > 0 at B2000, shrinking with B): point estimate +.0375 (CI [−.0002, +.0752]); +.0297 at
  B4000, −.0031 at B8000. Directionally held, not significant at B2000.
- **P4**: cap100 < cap200 held at B1000, 2000, 4000 (1/5) but not B8000 (.5844 vs .5797). cap400 ≈ cap200: within
  ±.03. Share 2/5 ≤ 1/5 at B ≤ 1000 held at B125, B500 (cap100) and B1000 cap100, not B1000 cap200 (.5188 vs .4969).
  T4 len100 > reference at cap100: +.0094, not significant, and compliance failed (above).
- **P5** (RR-2hop ≥ RR, gain in MULTIHOP and DERIVED): held at every B; the gain is mostly DERIVED (e.g. B2000
  .656 vs .362) with a smaller MULTIHOP gain (.850 vs .787).
- **F0 prediction** (A6 − RR closer to 0 or positive at B125 than B500): **failed**; B125 gaps −.2031 / −.2359 vs
  −.1469 at B500.

## 5. Cost

**Metered (live calls, re-totalled from `runs/CONFIRM/api-events-_vec-p{0..3}.jsonl`):** 30,445 calls; 47,356,169
input, 4,817,870 output, 12,051,469 cache-read input tokens. 4 calls with `ok` false; 17,403 HTTP 429 (Token Plan
rate limit 2062, retried) and 2 HTTP 500 (retried) error events. Per file: p0 7,536 calls 11,802,298 in /
1,216,529 out; p1 7,557 / 11,539,253 / 1,186,108; p2 7,600 / 11,785,462 / 1,210,494; p3 7,752 / 12,229,156 /
1,204,739. Includes the calls made by the 3 aborted misindexed pass-2 processes (§6). Excludes the bridge pilots
(1,229 calls, 1,704,207 in / 142,167 out, STATUS checkpoint 1).

| Arm:role | Live calls | In | Out | Latency s |
|---|---|---|---|---|
| A6:answer | 14,255 | 22,937,612 | 1,380,004 | 30,825.6 |
| A6:synth | 585 | 1,504,052 | 1,542,570 | 10,900.6 |
| A6:warm | 160 | 208,924 | 13,722 | 645.8 |
| A6-syn:answer | 3,786 | 5,781,448 | 314,890 | 8,336.7 |
| RR:answer | 3,392 | 3,244,084 | 261,730 | 7,139.8 |
| RR-2hop:answer | 1,882 | 2,818,840 | 127,525 | 3,971.0 |
| RR-2hop:bridge | 3,419 | 3,507,610 | 207,428 | 6,723.5 |
| RR-K:answer | 1,280 | 4,633,328 | 141,514 | 3,298.3 |
| A6-T4:synth | 406 | 1,070,821 | 699,950 | 5,361.4 |
| A6-T4:answer | 1,280 | 1,649,450 | 128,537 | 2,821.2 |

**Logical (every row incl. cache hits):** RR 3,840 rows, 4,006,324 in / 299,422 out (448 memo hits); RR-2hop 3,840,
4,570,324 / 307,360 (1,958 memo hits) + bridge 4,288,763 / 235,201; A6-syn 3,840, 5,789,811 / 316,225; A6 21,120,
43,488,029 / 2,174,830; RR-K 1,280, 4,633,328 / 141,514; A6-T4 1,280, 1,649,450 / 128,537.

**Wall-clock per arm** (sum of per-row `elapsed_s`, concurrent so not end-to-end time): RR 53,191 s; RR-2hop
51,161 s (+ bridge 46,755 s); A6-syn 58,805 s; A6 250,168 s; RR-K 25,018 s; A6-T4 17,993 s. Stage walls summed
over streams: build_warm 11,438.9 s, materialize 1,525.5, rank_hop1_K 3,282.4, bridge 8,179.8, rank_hop2 337.6,
answers 73,941.7, main total 98,706.3; T4 total 7,781.9 s.

**Reranker (wall s / CPU s):** RR 422.2 / 1,324.7; RR-K 2,853.6 / 9,282.5; RR-2hop 304.7 / 1,040.3.

Shared-cache caveat (D12): cells identical in the cache are not replications; evidence-budget matching is not
compute matching.

## 6. Deviations and incidents

1. **Misindexed pass-2 launch, aborted** (02:25 IST 26 Oct): a zsh shell array (1-indexed) gave p0 no streams
   (argparse error) and p1–p3 the wrong vec dir. Processes 84923–84925 were killed after ~2 min; logs in
   `runs/_logs/aborted-p2-misindexed/`; their work dirs became `.partial-1792961863`. The relaunch reused their
   content-addressed cache entries, so results are unaffected; their live calls are inside the metered totals.
2. **1 failed answer call** (`ok` false): 7280007, A6, `7280007:AGG:K049`, cell `B1000|2/5|400` (exploratory),
   empty answer, scored wrong per PREREG §6. `failed_calls` per arm: A6 1, all others 0.
3. **Failed summaries → `force_none` (D07/D15):** 7280012 node 9 and 7280016 node 14 failed in pass 1 and were
   frozen as "none" in every cell, including pass 2 via `force_none` (summary_failures = 2 in `ANALYSIS.json`;
   summary_misses = 0). The 7280012 node 9 synth ended on `max_tokens` (8,192 out). One warm synth (7280014
   node 1) also hit `max_tokens` and succeeded on the D07 retry.
4. **T4 summary failures:** len100 2 (7280016, 7280017 node 7 `max_tokens`), len400 1 (7280016). Scored as is.
5. **T4 compliance failure** (see §3): the length instructions were mostly ignored; T4 is uninformative.
6. **T0 not run** (D03), P6 withdrawn; T0-REDESIGN / `t0r` not run.
7. **Rate limits:** 17,403 retried 429s and 2 retried 500s; 0 PauseGate pauses on every stream (gate floor 2%).
8. Pass split (D15) and `--phase t4` launched with the pass-2 command line (no T4-specific flags) are as
   documented in STATUS checkpoints 3–4.
9. `analyze_e4.py`'s docstring says it writes `ANALYSIS.md`; the frozen code writes only `ANALYSIS.json`. This
   REPORT is the human-readable summary.
