"""MULTIHOP reachability: every gold answer must be reachable through the evidence chain in surviving text."""
import glob, json, re
import pytest
from e2.paths import DATA
from e2.tasks import author_e2, _merge, ledger, LedgerOnlyStream

TASK_FILES = sorted(glob.glob(str(DATA / "tasks-*.json")))
pytestmark = pytest.mark.skipif(not TASK_FILES, reason="generated data absent")


def paragraphs(seed, sid):
    return (DATA / f"stream-{seed}" / "sessions" / f"{sid}.md").read_text().rstrip("\n").split("\n\n")


@pytest.mark.parametrize("f", TASK_FILES)
def test_every_multihop_gold_reachable(f):
    t = json.loads(open(f).read())
    deleted = set(t["deleted"])
    mh = [x for x in t["tasks"] if x["cls"] == "MULTIHOP"]
    assert mh
    for x in mh:
        # hop 1: question names the person; the question's entity is never named, the paragraph must link them
        assert x["via"] in x["question"] and x["hop_entity"] not in x["question"]
        sup = [s for s in x["support_sessions"] if s not in deleted]
        assert x["bridge_session"] in sup, x["task_id"]
        hits = [p for s in sup for p in paragraphs(t["seed"], s)
                if x["via"] in p and x["hop_entity"] in p and any(re.search(r, p, re.I) for r in x["truth_any"])]
        assert hits, x["task_id"]


def test_bridge_keeps_ledger_golds_and_is_idempotent():
    d = DATA / "stream-7260002"
    a = author_e2(d)
    b = json.loads((d / "BRIDGE.json").read_text())
    for r in b["tasks"]:                               # text edited exactly once
        assert sum(p.count(r["sentence"]) for p in paragraphs(7260002, r["session"])) == 1
    assert author_e2(d)["bridge_sha256"] == a["bridge_sha256"]
    st = LedgerOnlyStream(d)
    keys, t_end = st.world["keys"], st.manifest["t_end"]
    merged = _merge(st.events, b["events"])
    for dl in (set(), set(a["deleted"])):
        r0, r1 = ledger.compute_rows(st.events, keys, dl), ledger.compute_rows(merged, keys, dl)
        for k in keys:
            f0, f1 = ledger.fact_at(r0, k, t_end), ledger.fact_at(r1, k, t_end)
            assert (f0 or {}).get("value") == (f1 or {}).get("value"), k
            assert (f0 or {}).get("status") == (f1 or {}).get("status"), k
        # bridges add evidence only, never a new fact (AGG counts unchanged)
        assert len(r0) == len(r1)
