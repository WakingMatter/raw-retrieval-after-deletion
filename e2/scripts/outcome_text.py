"""Plain-language direction readout for a frozen `analysis.contrasts` result (display only; never decides).
Written after the 17:00 IST sign check: the frozen O2 label means *raw (RR) is non-inferior to A6*, not the reverse."""


def describe(p):
    c = p["contrasts"]["A6-RR"]; ci = c["ci95"]; m = ci["mean"]
    lines = [f"Outcome {p['outcome']} (H-ADV {p['H_ADV']}, H-NI {p['H_NI']})."]
    if p["H_ADV"]:
        lines.append("A6 beats both raw (RR) and A6-syn: both 97.5% two-sided lower bounds > 0.")
    elif p["H_NI"]:
        lines.append(f"H-NI: raw (RR) is non-inferior to A6 at +10pp: 95% upper bound of A6-RR = {ci['hi']:+.4f} < +0.10.")
    else:
        lines.append("Neither H-ADV nor H-NI holds: no directional claim.")
    if ci["hi"] is not None and ci["hi"] < 0:
        lines.append(f"Direction: A6 is worse than raw (A6-RR mean {m:+.4f}, 95% CI [{ci['lo']:+.4f}, {ci['hi']:+.4f}] entirely below 0)."
                     + (f" A6 would not be non-inferior to raw at 10pp either (lower bound {ci['lo']:+.4f} < -0.10)."
                        if ci["lo"] < -0.10 else ""))
    elif ci["lo"] is not None and ci["lo"] > 0:
        lines.append(f"Direction: A6 ahead of raw (A6-RR mean {m:+.4f}, 95% CI [{ci['lo']:+.4f}, {ci['hi']:+.4f}]).")
    else:
        lines.append(f"Direction: 95% CI for A6-RR [{ci['lo']:+.4f}, {ci['hi']:+.4f}] includes 0.")
    return " ".join(lines)
