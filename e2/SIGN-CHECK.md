# E2 outcome sign check (24 Oct 2026, ~17:05 IST, before any confirmatory scoring)

**Trigger.** Research's 17:00 IST status note said of DEV3: "A6 would be shown non-inferior to RR (A6−RR −.101,
95% CI [−.187, −.015])". That sentence had the direction backwards. The code does not.

**Frozen rule (PREREG-E2.md §2, §3, §6; unchanged).**
- H-ADV: A6 > raw AND A6 > A6-syn; each two-sided 97.5% CI lower bound > 0.
- H-NI: "*Reranked raw is non-inferior to A6*": upper bound of the one-sided 97.5% CI (= two-sided 95% upper bound)
  for (A6 − raw) < +Δ, Δ = +0.10. Null: A6 − raw ≥ +Δ (raw worse than A6 by ≥ 10pp).
- O1 if H-ADV; O2 ("raw suffices", K-thesis) if H-NI and not H-ADV; else O3.

**Code (hashed `e2/analysis.py`).** `ni = ci95.hi(A6−RR) < MARGIN (+0.10)`; `adv = ci97.5.lo > 0` for both contrasts;
O1 precedes O2. This is the frozen rule with the correct sign.

**By hand on DEV3** (per-stream A6−RR −7/40, −3/40, −2/40, −4/38): mean −.10132, sd .05407, se .02703.
t(.975, 3) = 3.1824 → 95% CI [−.1874, −.0153]; t(.9875, 3) = 4.1765 → 97.5% CI [−.2142, +.0116].
H-ADV fails (lower bound < 0). H-NI holds (−.0153 < +.10). Outcome O2: **raw is non-inferior to A6**.
In plain terms A6 is *worse* than raw (CI entirely below 0), and A6 would not be non-inferior to raw at 10pp
(lower bound −.187 < −.10); that reverse-direction test is not a prespecified hypothesis and is reported descriptively only.

**Reading of the frozen text.** H-NI as written bounds only how much worse raw may be than A6; it is satisfied
a fortiori when raw is better. O2 therefore covers both "raw ≈ A6" and "raw > A6"; reports must state which
using the CI, never by calling A6 non-inferior.

**Changes (outside the hash).** No direction bug found in `scripts/confirm_report.py` (it calls the frozen
`analyze`). Added display-only `scripts/outcome_text.py` (plain-language direction readout; never decides) used by
`confirm_report.py`, and `tests/test_outcome_direction.py` (DEV3 by hand → O2; O1, O3 and margin-boundary cases).
`verify_frozen()` = [] after the change.
