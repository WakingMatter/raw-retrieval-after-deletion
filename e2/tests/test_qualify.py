from e2.qualify import verdict, literal


def rows(gold_correct, contaminated=0, failed=0, n=10):
    r = [{"control": "no_evidence", "ok": True, "contaminated": i < contaminated} for i in range(n)]
    r += [{"control": "gold_evidence", "ok": i >= failed, "correct": i < gold_correct} for i in range(n)]
    r += [{"control": "stale_derived", "ok": True, "repeated_stale": False} for _ in range(n)]
    return r


def test_always_abstain_fails():
    # an answerer that always says "not found": never contaminated, never correct -> must FAIL (positive control)
    v = verdict(rows(gold_correct=0))
    assert v["verdict"] == "FAIL" and "gold_evidence_acc<0.7" in v["reasons"] and v["contaminated"] == 0


def test_responsive_clean_answerer_passes():
    assert verdict(rows(gold_correct=9))["verdict"] == "PASS"


def test_contaminated_or_failed_answerer_fails():
    assert verdict(rows(gold_correct=10, contaminated=1))["verdict"] == "FAIL"
    assert verdict(rows(gold_correct=10, failed=1))["verdict"] == "FAIL"


def test_no_gold_group_fails():
    assert verdict([r for r in rows(10) if r["control"] != "gold_evidence"])["verdict"] == "FAIL"


def test_literal():
    assert literal(r"\bMaya\ Shah\b") == "Maya Shah"


class _RR:
    """Stub RR store: one gold chunk; answer() delegates to a policy so whole-pipeline behaviour is tested."""
    def __init__(self, policy):
        self.policy = policy
        self.chunks = {"s01:001": {"session": "s01", "t": "2030-01-01T00:00", "text": "Owner of order-router is Maya Shah."}}
        self.rr = self

    def scores(self, q, docs):
        return [1.0] * len(docs)

    def read(self, q, t, B):
        return [], {}

    def answer(self, served, q, phase, prefix=None, ctx=None):
        return {"ok": True, "text": self.policy(served, ctx)}, ""


TK = {"task_id": "T1", "cls": "CURRENT", "question": "Who owns order-router?", "t_query": "2030-02-01T00:00",
      "support_sessions": ["s01"], "truth_any": [r"\bMaya\ Shah\b"], "wrong_any": [r"\bLee\ Wong\b"], "gold": "Maya Shah"}


def _run(policy):
    from e2.qualify import run_job
    rr = _RR(policy)
    return verdict([run_job(rr, k, TK) for k in ("no_evidence", "gold_evidence", "stale_derived")])


def test_pipeline_abstainer_fails_reader_passes_leaker_fails():
    assert _run(lambda s, c: "Not found in memory.")["verdict"] == "FAIL"
    reader = lambda s, c: ("Maya Shah" if any("Maya" in it["text"] for it in s) else "Not found in memory.")
    assert _run(reader)["verdict"] == "PASS"
    assert _run(lambda s, c: "Maya Shah")["verdict"] == "FAIL"          # answers without evidence -> contaminated


def test_stale_note_dated_at_outdated_value():
    from e2.qualify import run_job
    seen = []
    rr = _RR(lambda s, c: seen.extend(it["text"] for it in s) or "Lee Wong")
    row = run_job(rr, "stale_derived", dict(TK, wrong_t=["2030-01-15T09:00:00Z"]))
    assert seen[0].startswith("[note | 2030-01-15T09:00]") and row["repeated_stale"]
