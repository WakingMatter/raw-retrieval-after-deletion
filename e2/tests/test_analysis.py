from e2.analysis import analyze


def rows(pattern):
    """pattern: per stream list of (A6, A6-syn, RR) correctness tuples."""
    out = []
    for s, tasks in enumerate(pattern):
        for i, t in enumerate(tasks):
            for arm, ok in zip(("A6", "A6-syn", "RR"), t):
                out.append({"seed": s, "task_id": f"T{i}", "arm": arm, "cls": "AGG" if i % 2 else "CURRENT",
                            "correct": ok, "correct_lenient": ok})
    return out


def test_identical_arms_give_NI_not_ADV():
    r = analyze(rows([[(1, 1, 1), (0, 0, 0), (1, 1, 1), (0, 1, 0)]] * 3 + [[(1, 1, 1), (0, 0, 0), (1, 0, 1), (0, 0, 0)]] * 3))
    assert r["primary"]["outcome"] == "O2 NI" and not r["primary"]["H_ADV"]
    assert r["S1_informative"]["n_all_wrong_excluded"] == 9


def test_clear_advantage_is_ADV():
    r = analyze(rows([[(1, 0, 0), (1, 0, 0), (1, 1, 1), (1, 0, 0)], [(1, 0, 0), (1, 0, 0), (1, 0, 0), (0, 0, 0)],
                      [(1, 0, 0), (1, 0, 0), (1, 0, 0), (1, 0, 0)], [(1, 0, 0), (1, 1, 0), (1, 0, 0), (1, 0, 1)]]))
    assert r["primary"]["outcome"] == "O1 ADV"


def test_endpoint_class_drop_and_floors():
    r = analyze(rows([[(1, 1, 1), (0, 0, 0)]] * 4), endpoint_classes=("CURRENT",))
    assert r["n_paired_tasks"] == 4 and r["class_floors"]["AGG"]["floored"] and not r["class_floors"]["CURRENT"]["floored"]


def test_strict_rejects_incomplete_and_duplicates():
    import pytest
    base = rows([[(1, 1, 1), (0, 1, 0)]] * 3)
    with pytest.raises(ValueError):
        analyze(base[:-1], strict=True)
    with pytest.raises(ValueError):
        analyze(base + base[:1], strict=True)
    analyze(base, strict=True)
