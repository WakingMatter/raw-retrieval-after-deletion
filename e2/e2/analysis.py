"""E2 prespecified analysis (prereg §2, §6). One function used for DEV (labelled not-results) and CONFIRM.

Unit: per task, paired difference of correctness between arms; averaged within stream; t-interval across streams.
  H-ADV : A6-RR and A6-A6syn both > 0 at alpha=.025 two-sided  <=> lower bound of each two-sided 97.5% CI > 0
  H-NI  : upper bound of the one-sided 97.5% CI for (A6 - RR) < MARGIN (= upper bound of the two-sided 95% CI)
  outcome O1 ADV if H-ADV; O2 NI if H-NI and not H-ADV; else O3 inconclusive.
Primary metric: `correct` (strict: gold hit and no deleted/outdated value mentioned; AGG exactly one number = gold),
restricted to ENDPOINT_CLASSES.
Prespecified sensitivities (DEFAULTS #20-24), reported next to the primary, never replacing it:
  S1 informative tasks: drop tasks that every arm gets wrong (primary metric), same contrasts.
  S2 lenient scoring: `correct_lenient` (gold hit regardless of other mentions).
  S3 all four classes (only differs from primary if a class was dropped from the endpoint before freeze).
Per-class floors: per-arm accuracy per class; a class is FLOORED if its best arm is < FLOOR."""
from __future__ import annotations
import math
from collections import defaultdict
from statistics import mean, stdev

ARMS = ("A6", "A6-syn", "RR")
CONTRASTS = {"A6-RR": ("A6", "RR"), "A6-A6syn": ("A6", "A6-syn")}
ALL_CLASSES = ("AGG", "DERIVED", "MULTIHOP", "CURRENT")
MARGIN, FLOOR = 0.10, 0.15


def tint(xs, conf):
    from scipy.stats import t
    n = len(xs); m = mean(xs)
    if n < 2:
        return {"n": n, "mean": m, "lo": None, "hi": None}
    se = stdev(xs) / math.sqrt(n); q = t.ppf(1 - (1 - conf) / 2, n - 1)
    # unrounded: outcome decisions use full precision (rev 5, Astra finding 10); reports round for display only
    return {"n": n, "mean": m, "lo": m - q * se, "hi": m + q * se, "sd": stdev(xs)}


def by_task(rows, metric="correct", strict=False):
    """strict (CONFIRM): any duplicate (seed, task, arm) row or incomplete arm triplet is an error, never dropped."""
    out = defaultdict(dict)
    for r in rows:
        k = (r["seed"], r["task_id"])
        if strict and r["arm"] in out[k]:
            raise ValueError(f"duplicate row {k} {r['arm']}")
        out[k][r["arm"]] = (bool(r.get(metric)), r["cls"])
    bad = [k for k, v in out.items() if not set(ARMS) <= v.keys()]
    if strict and bad:
        raise ValueError(f"incomplete arm triplets: {bad[:5]} (+{max(0, len(bad) - 5)})")
    return {k: v for k, v in out.items() if set(ARMS) <= v.keys()}


def contrasts(tasks):
    per = {c: defaultdict(list) for c in CONTRASTS}
    for (seed, _), v in tasks.items():
        for c, (a, b) in CONTRASTS.items():
            per[c][seed].append(int(v[a][0]) - int(v[b][0]))
    per_stream = {c: [mean(x) for _, x in sorted(d.items())] for c, d in per.items()}
    res = {}
    for c, xs in per_stream.items():
        if not xs:
            continue
        res[c] = {"ci97.5": tint(xs, 0.975), "ci95": tint(xs, 0.95), "n_tasks": sum(len(x) for x in per[c].values())}
    adv = all(c in res and (res[c]["ci97.5"]["lo"] or -1) > 0 for c in CONTRASTS)
    ni = "A6-RR" in res and res["A6-RR"]["ci95"]["hi"] is not None and res["A6-RR"]["ci95"]["hi"] < MARGIN
    outcome = "O1 ADV" if adv else ("O2 NI" if ni else "O3 inconclusive")
    return {"contrasts": res, "H_ADV": adv, "H_NI": ni, "outcome": outcome,
            "per_stream": {c: [round(x, 4) for x in v] for c, v in per_stream.items()},
            "n_streams": {c: len(v) for c, v in per_stream.items()}}


def accuracy(tasks):
    acc = {}
    for arm in ARMS:
        acc[arm] = {"all": round(mean(v[arm][0] for v in tasks.values()), 4) if tasks else None}
        for c in ALL_CLASSES:
            xs = [v[arm][0] for v in tasks.values() if v[arm][1] == c]
            acc[arm][c] = round(mean(xs), 4) if xs else None
    return acc


def analyze(rows, endpoint_classes=ALL_CLASSES, strict=False):
    full = by_task(rows, strict=strict)
    prim = {k: v for k, v in full.items() if v["A6"][1] in endpoint_classes}
    informative = {k: v for k, v in prim.items() if any(v[a][0] for a in ARMS)}
    lenient = {k: v for k, v in by_task(rows, "correct_lenient").items() if v["A6"][1] in endpoint_classes}
    acc_all = accuracy(full)
    floors = {c: {"best_arm_acc": max((acc_all[a][c] or 0) for a in ARMS),
                  "worst_arm_acc": min((acc_all[a][c] or 0) for a in ARMS),
                  "all_wrong": sum(1 for v in full.values() if v["A6"][1] == c and not any(v[a][0] for a in ARMS)),
                  "n": sum(1 for v in full.values() if v["A6"][1] == c)} for c in ALL_CLASSES}
    for c in floors:
        floors[c]["floored"] = floors[c]["best_arm_acc"] < FLOOR
    return {"endpoint_classes": list(endpoint_classes), "n_paired_tasks": len(prim),
            "primary": contrasts(prim), "accuracy": acc_all,
            "S1_informative": dict(contrasts(informative), n_tasks=len(informative),
                                   n_all_wrong_excluded=len(prim) - len(informative)),
            "S2_lenient": dict(contrasts(lenient), accuracy=accuracy(lenient)),
            "S3_all_classes": contrasts(full) if tuple(endpoint_classes) != ALL_CLASSES else "same as primary",
            "class_floors": floors,
            "per_class_contrasts_descriptive": {c: contrasts({k: v for k, v in full.items() if v["A6"][1] == c})
                                                for c in ALL_CLASSES}}
