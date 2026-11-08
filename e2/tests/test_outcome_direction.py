"""Sign check (post-freeze, 24 Oct 17:0x IST): the frozen rule mapped by hand.
Frozen PREREG-E2.md §2: H-ADV = lower bound of the two-sided 97.5% CI > 0 for BOTH A6-RR and A6-A6syn.
H-NI = "reranked raw is non-inferior to A6": upper bound of the one-sided 97.5% CI (= two-sided 95% upper) for
(A6 - raw) < +0.10.  O1 if H-ADV; O2 (raw non-inferior / K-thesis) if H-NI and not H-ADV; else O3."""
import sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from e2.analysis import contrasts
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from outcome_text import describe


def tasks_from(streams):
    """streams: list of (n_tasks, a6_minus_rr_wins_for_rr, a6_minus_rr_wins_for_a6, a6_beats_syn) per stream."""
    t = {}
    for s, (n, rr_win, a6_win, syn_loss) in enumerate(streams):
        for i in range(n):
            a6 = 0 if i < rr_win else 1
            rr = 1 if i < rr_win else (0 if i < rr_win + a6_win else 1)
            syn = 0 if rr_win <= i < rr_win + syn_loss else a6
            t[(s, i)] = {"A6": (a6, "AGG"), "RR": (rr, "AGG"), "A6-syn": (syn, "AGG")}
    return t


def test_dev3_by_hand_is_O2_raw_noninferior():
    # DEV3 per-stream A6-RR = -7/40, -3/40, -2/40, -4/38 = -.175, -.075, -.05, -.10526
    # mean -.10132, sd .05407, se .02703; t(.975,3)=3.1824 -> 95% CI [-.1873, -.0153]
    # t(.9875,3)=4.1765 -> 97.5% CI [-.2142, +.0116]
    r = contrasts(tasks_from([(40, 7, 0, 0), (40, 3, 0, 0), (40, 2, 0, 0), (38, 4, 0, 0)]))
    c = r["contrasts"]["A6-RR"]
    assert c["ci95"]["mean"] == pytest.approx(-.10132, abs=1e-4)
    assert c["ci95"]["lo"] == pytest.approx(-.1873, abs=2e-4) and c["ci95"]["hi"] == pytest.approx(-.0153, abs=2e-4)
    assert c["ci97.5"]["lo"] == pytest.approx(-.2142, abs=2e-4)
    assert not r["H_ADV"] and r["H_NI"] and r["outcome"] == "O2 NI"
    d = describe(r)
    assert "raw (RR) is non-inferior to A6" in d and "A6 is worse than raw" in d


def test_A6_clearly_better_on_both_is_O1():
    # A6 beats RR on 8/40 and A6-syn on 8/40 in every stream except jitter -> both lower bounds > 0
    r = contrasts(tasks_from([(40, 0, 8, 8), (40, 0, 6, 7), (40, 0, 9, 6), (40, 0, 7, 9)]))
    assert r["H_ADV"] and r["outcome"] == "O1 ADV"


def test_A6_better_than_raw_by_more_than_margin_but_not_syn_is_O3():
    # A6-RR = +.20, +.15, +.25, +.20 (mean .20, 95% upper > .10) and A6-A6syn = 0 -> no ADV, no NI
    r = contrasts(tasks_from([(40, 0, 8, 0), (40, 0, 6, 0), (40, 0, 10, 0), (40, 0, 8, 0)]))
    assert not r["H_ADV"] and not r["H_NI"] and r["outcome"] == "O3 inconclusive"


def test_noninferiority_margin_sign_boundary():
    # A6-RR = +.05 everywhere +/- small: upper bound < +.10 -> raw non-inferior (O2) even though A6 is ahead
    r = contrasts(tasks_from([(40, 0, 2, 0), (40, 0, 2, 0), (40, 0, 3, 0), (40, 0, 1, 0)]))
    assert r["contrasts"]["A6-RR"]["ci95"]["hi"] < .10 and r["outcome"] == "O2 NI"
    # same but A6 ahead by ~.12: upper bound > +.10 -> NOT non-inferior
    r = contrasts(tasks_from([(40, 0, 5, 0), (40, 0, 4, 0), (40, 0, 6, 0), (40, 0, 5, 0)]))
    assert r["contrasts"]["A6-RR"]["ci95"]["hi"] > .10 and r["outcome"] == "O3 inconclusive"
