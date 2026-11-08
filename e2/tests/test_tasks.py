import json
from e2.paths import DATA
from e2.tasks import author_e2, score


def test_deterministic_and_disjoint():
    d = DATA / "stream-7260002"
    a, b = author_e2(d), author_e2(d)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    keys = [t["key"] for t in a["tasks"]]
    assert len(keys) == len(set(keys))
    assert {t["cls"] for t in a["tasks"]} == {"AGG", "DERIVED", "MULTIHOP", "CURRENT"}
    assert len(a["extra_deleted"]) == 6 and not set(a["extra_deleted"]) & set(a["generator_deleted"])


def test_confirmatory_supply_is_full():
    sup = json.loads((DATA / "SUPPLY.json").read_text())
    for s in range(7260001, 7260033):
        assert sup[str(s)]["n_tasks"] == 40, s


def test_score_rules():
    agg = {"cls": "AGG", "gold": 2, "truth_any": [r"\b2\b"], "wrong_any": []}
    assert score(agg, "Two values.")["correct"] and not score(agg, "3")["correct"]
    cur = {"cls": "CURRENT", "gold": "Mumbai", "truth_any": [r"\bMumbai\b"], "wrong_any": [r"\bPune\b"]}
    assert score(cur, "Mumbai")["correct"] and not score(cur, None)["correct"]
    both = score(cur, "Pune, now Mumbai")
    assert both["mentions_wrong"] and not both["correct"] and both["correct_lenient"]
    assert not score(agg, "2, maybe 3")["correct"] and not score(agg, "none found")["correct"]
    assert score(agg, "2 values (2 sessions)")["correct"]


def test_agg_zero_and_abstention_rev5():
    z = {"cls": "AGG", "gold": "0", "truth_any": [], "wrong_any": []}
    assert score(z, "0")["correct"] and score(z, "Zero.")["correct"] and score(z, "none")["correct"]
    assert not score(z, "1")["correct"]
    cur = {"cls": "CURRENT", "gold": "Mumbai", "truth_any": [r"\bMumbai\b"], "wrong_any": []}
    r = score(cur, "Not found in memory; Mumbai perhaps")
    assert r["abstained"] and not r["correct"] and not r["correct_lenient"]


def test_agg_gold_not_constant_rev5():
    from collections import Counter
    golds = Counter()
    for s in (7260001, 7260002, 7260003, 7260004):
        golds.update(t["gold"] for t in author_e2(DATA / f"stream-{s}")["tasks"] if t["cls"] == "AGG")
    assert len(golds) >= 2, golds
    assert max(golds.values()) < sum(golds.values()), golds
