"""Stream-addition rule (prereg §7), fixed 24 Oct 2026 BEFORE any DEV or confirmatory data.

sd_hat = the LARGER of the two sample SDs (ddof=1) of the per-stream mean paired differences on the DEV streams,
         for the two primary contrasts (A6 - RR, A6 - A6syn).
power(n) = one-sided alpha=.025 t-test power at a 10pp shift with n independent streams:
           P(T_{n-1, ncp} > t_{.975, n-1}), ncp = 0.10 / (sd_hat / sqrt(n)).  (For H-NI: true A6 - RR = 0, margin -10pp.)
Rule: if power(32) >= 0.8 keep 32. Otherwise use the smallest n in 33..48 with power(n) >= 0.8, else 48;
the added streams are EXTRA seeds 7260033.. in order. Nothing else may change the stream count."""
from __future__ import annotations
import math
from statistics import stdev

MARGIN, ALPHA, TARGET, BASE_N, MAX_N = 0.10, 0.025, 0.80, 32, 48


def power(n: int, sd: float, delta: float = MARGIN, alpha: float = ALPHA) -> float:
    from scipy.stats import nct, t
    if sd <= 0:
        return 1.0
    df = n - 1
    return float(nct.sf(t.ppf(1 - alpha, df), df, delta / (sd / math.sqrt(n))))


def sd_hat(per_stream: dict[str, list[float]]) -> float:
    return max(stdev(v) for v in per_stream.values())


def n_streams(sd: float) -> dict:
    p32 = power(BASE_N, sd)
    if p32 >= TARGET:
        return {"n": BASE_N, "power_32": p32, "added": 0, "power_n": p32}
    for n in range(BASE_N + 1, MAX_N + 1):
        if power(n, sd) >= TARGET:
            return {"n": n, "power_32": p32, "added": n - BASE_N, "power_n": power(n, sd)}
    return {"n": MAX_N, "power_32": p32, "added": MAX_N - BASE_N, "power_n": power(MAX_N, sd)}
