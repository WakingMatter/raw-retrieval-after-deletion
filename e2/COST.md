# E2 full-run cost (ESTIMATE, 24 Oct 2026 13:08 IST)

Method (`e2/cost.py` → `runs/COST.json`):
- **Call counts are exact for this harness:** an offline dry run of all 32 confirmatory streams with a fake answerer
  (`runs/DRY-ALL-0..7`, zero API calls). Synth counts depend on the answerer's write-backs, so the real count may move
  slightly (dry: 30–39 synth per stream, median 35).
- **Tokens per call are estimates:** 19 live smoke calls (`runs/SMOKE`). Input = dry prompt chars × 0.382 tokens/char
  (measured on the smoke, cached input included). Output = smoke mean (answers 120, synth 766, thinking included);
  "hi" uses the smoke maxima (449 / 1,061) for every call.
- Plan sizes (Aditya): 5-hour window ≈ 125M tokens, week ≈ 1.25B, month ≈ 5B. The plan's exact token accounting
  (cached input, thinking) is not published; this sums input + output.

| Item | Calls | In/call | Out/call | In total | Out total | Out total (hi) |
|---|---:|---:|---:|---:|---:|---:|
| Terminal answers A6 | 1,280 | 1,524 | 120 | 1.95M | 0.15M | 0.57M |
| Terminal answers A6-syn | 1,280 | 1,524 | 120 | 1.95M | 0.15M | 0.57M |
| Terminal answers RR | 1,280 | 1,524 | 120 | 1.95M | 0.15M | 0.57M |
| Warm answers (A6 state, write-back) | 320 | 1,590 | 120 | 0.51M | 0.04M | 0.14M |
| Synth (summary recompute, warm 790 + probe 323) | 1,113 | 3,559 | 766 | 3.96M | 0.85M | 1.18M |
| DEV pass (4 streams, same harness) | 659 | 1,958 | 257 | 1.29M | 0.17M | 0.70M |
| Qualification (stage 0) | 120 | 1,524 | 120 | 0.18M | 0.01M | 0.05M |
| **Total** | **6,052** | | | **11.80M** | **1.54M** | **3.80M** |

| Scenario | Tokens | % of 5-h window (125M) | % of week (1.25B) | % of month (5B) |
|---|---:|---:|---:|---:|
| Base | 13.3M | 10.7% | 1.07% | 0.27% |
| Hi output | 15.6M | 12.5% | 1.25% | 0.31% |
| Hi output + 20% reserve (7,262 calls) | 18.7M | 15.0% | 1.50% | 0.37% |

Strong-model calibration: dropped (head of research, 24 Oct; prereg §4).

**DEV observed (24 Oct 13:38–13:56 IST, `runs/DEV/DEV-REPORT.json`, `runs/QUAL/QUALIFY.json`):**

| Row | Live calls | Input | Output | Cache-read |
|---|---:|---:|---:|---:|
| DEV pass (4 streams) | 649 (135 synth, 514 answer) | 1,017,102 | 395,119 | 152,598 |
| Qualification | 120 | 105,262 | 2,318 | 24,295 |

0 failed calls; 209 HTTP 429 code-2062 rate-limit retries, all recovered. Token Plan: window 97% → 94% remaining,
week 89% → 89% (13:30 → 13:56 IST). Confirmatory projection ≈ 12–13M tokens [INFERENCE: 8 × DEV], wall 1–2 h
with 8 processes [INFERENCE from 13–16 min per DEV stream under rate limiting].

**Current usage** (quota endpoint, read 13:07 IST): 5-hour window 98% remaining (resets 15:30 IST);
week 89% remaining (resets Mon 26 Oct 05:30 IST). The whole run fits in one window with room to spare.

**Wall time (estimate):** per stream ≈ 10 warm answers + ~25 warm synth run in time order (~130 s at the smoke
median latencies 2.2 s / 4.4 s) + 120 probe answers + ~10 synth over 4 threads (~80 s) + ~20 s harness
(embeddings for all 32 confirmatory streams are now cached) + reranker 17–110 s (CPU-contention dependent)
≈ 4–5 min per stream. Run as 8 processes × 4 streams: ≈ 20–40 min if the API's per-minute limit is not hit
(peak demand ≈ 150–300 calls/min); if RPM throttling (code 1002) bites, the harness waits and resumes, so an upper
planning figure is ≈ 2 h (single process, streams serial: 32 × ~4 min). The RPM ceiling is unmeasured.

## DEV2 + QUAL2 observed (rev 4, 24 Oct 2026 15:44–15:58 IST)

| Item | Live calls | Input | Output | Cache-read |
|---|---:|---:|---:|---:|
| DEV2 (4 streams; 64 synth + 447 answer live, rest cache hits) | 511 | 758,984 | 225,539 | 116,920 |
| QUAL2 (120 answers, 88 live) | 88 | 82,789 | 2,782 | 18,790 |

Token Plan readings: 15:44 IST window 99% / week 89% remaining; 15:58 IST window 98% / week 89%.

## DEV3 + QUAL3 observed (rev 5, 24 Oct 2026 16:39–16:49 IST)

| Item | Live calls | Input | Output | Cache-read |
|---|---:|---:|---:|---:|
| DEV3 (4 streams; 513 answer + 1 synth live, other synth calls cache hits) | 514 | 692,980 | 55,452 | 115,775 |
| QUAL3 (156 answers, 154 live) | 154 | 157,175 | 5,331 | 35,548 |

Rate-limit (2062 / HTTP 429) retry events: DEV3 316, QUAL3 44 (4 DEV processes + qualification ran concurrently).
Token Plan readings: 16:37 IST window 97% / week 88% remaining; 16:49 IST window 95% / week 88%.
DEV3 walls per stream 319–473 s with 4 processes in parallel.

**Confirmatory estimate (estimate, not measured):** 32 streams ≈ 32 × ~125 live answer calls ≈ 4,000 calls plus
synthesis (~35 per stream, all new: confirmatory synth prompts are not cached) ≈ 1,100 calls; ≈ 32 × (DEV3 per-stream
nominal tokens) ≈ 13–14 M nominal tokens, of which the cache-read share is unknown. Wall time with 8 processes × 4
streams at DEV3's per-stream walls: ≈ 25–35 min if throttling is no worse than in DEV3; longer under heavier 429s.
