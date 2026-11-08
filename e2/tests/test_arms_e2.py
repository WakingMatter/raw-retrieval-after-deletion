import numpy as np
from e2 import paths  # noqa
from e2.arms_e2 import A6E2, cap_summary, label_of, SYN_OUT_CAP, RerankedRaw
from pilot.common import item_cost
from pilot.embed import HashEmbedder


class FakeLLM:
    def __init__(self, synth_text):
        self.synth_text, self.calls = synth_text, []

    def call(self, role, prompt, model=None, schema=None, ctx=None):
        self.calls.append((role, ctx))
        t = self.synth_text if role == "synth" else "ans"
        return {"ok": True, "text": t, "usage": {"input_tokens": 1, "output_tokens": 1}, "memo_hit": False}


def anchors(k=4, dim=32):
    return np.random.default_rng(0).standard_normal((k, dim))


def test_cap_summary_sentence_boundary():
    long = " ".join(f"Sentence number {i} about the ledger api owner." for i in range(200))
    t, tr = cap_summary(long, label_of(3))
    assert tr and item_cost(f"[{label_of(3)}] {t}") <= SYN_OUT_CAP and t.endswith(".")
    short = "Short summary."
    assert cap_summary(short, label_of(3)) == (short, False)


def test_cap_summary_word_fallback():
    t, tr = cap_summary("word " * 2000, label_of(1))
    assert tr and t.endswith("…") and item_cost(f"[{label_of(1)}] {t}") <= SYN_OUT_CAP


def build(tmp_path, synth_text):
    llm = FakeLLM(synth_text)
    a = A6E2("A6", "F", tmp_path / "a6", llm, HashEmbedder(), anchors())
    for i in range(8):
        a.ingest(f"s{i:02d}", "\n\n".join(f"Paragraph {j} of session {i} about owner and region." for j in range(6)),
                 f"2030-01-{i + 1:02d}T00:00:00Z")
    return a, llm


def test_skip_and_continue_and_trace(tmp_path):
    a, _ = build(tmp_path, "x " * 10)
    # make the first top node's summary too big for the header but keep others small
    served, tr = a.read("owner region", "2030-02-01T00:00:00Z", 2000, "probe", syn=True)
    first = tr["top_nodes"][0]
    a.caches[first]["text"] = "y " * 1000          # oversized cached entry (pre-fix output), key still valid
    served, tr = a.read("owner region", "2030-02-01T00:00:00Z", 2000, "probe", syn=True)
    st = {n["node"]: n["status"] for n in tr["nodes"]}
    assert st[first] == "skipped_no_fit"
    assert any(s == "served" for n, s in st.items() if n != first)     # later summaries still served (no break)
    assert tr["header_tokens_est"] <= 400 and tr["header_tokens_est"] + tr["raw_tokens_est"] <= 2000


def test_synth_output_capped_and_flagged(tmp_path):
    long = " ".join(f"Fact {i} is stated here in a sentence." for i in range(400))
    a, _ = build(tmp_path, long)
    _, tr = a.read("owner region", "2030-02-01T00:00:00Z", 2000, "probe", syn=True)
    for n in tr["top_nodes"]:
        c = a.caches.get(n)
        if c:
            assert c["truncated"] and c["cost_served"] <= SYN_OUT_CAP < c["cost_raw"]
    assert any(n["status"] == "served" for n in tr["nodes"])


def test_no_syn_ablation_same_state_no_header_no_synth(tmp_path):
    a, llm = build(tmp_path, "s")
    served, tr = a.read("owner region", "2030-02-01T00:00:00Z", 2000, "probe", syn=False)
    assert tr["served_summaries"] == [] and tr["header_tokens_est"] == 0
    assert not [c for c in llm.calls if c[0] == "synth"]


def test_summary_invalidated_by_forget(tmp_path):
    a, llm = build(tmp_path, "sum")
    a.read("owner region", "2030-02-01T00:00:00Z", 2000, "probe")
    a.forget("s03", "2030-02-02T00:00:00Z", "")
    for n, c in a.caches.items():
        assert not any(d.startswith("s03:") for d in c["deps"])
    n0 = sum(1 for c in llm.calls if c[0] == "synth")
    _, tr = a.read("owner region", "2030-02-03T00:00:00Z", 2000, "probe")
    assert all(not any(d.startswith("s03:") for d in a.caches[n]["deps"]) for n in a.caches)


def test_ask_trace_fields(tmp_path):
    a, _ = build(tmp_path, "sum.")
    r = a.ask("owner region?", "2030-02-01T00:00:00Z", 2000, "probe")
    for k in ("top_nodes", "nodes", "served_summaries", "header_tokens_est", "raw_tokens_est"):
        assert k in r["trace"]


class FakeRR:
    seconds = 0.0

    def scores(self, q, docs):
        return [float(len(set(q.split()) & set(d.split()))) for d in docs]


def test_reranked_raw_forget_and_budget(tmp_path):
    rr = RerankedRaw("RR", "F", tmp_path / "rr", FakeLLM("x"), HashEmbedder(), FakeRR(), top_k=10)
    for i in range(5):
        rr.ingest(f"s{i:02d}", "\n\n".join(f"para {j} owner {i}" for j in range(5)), f"2030-01-0{i + 1}T00:00:00Z")
    rr.forget("s02")
    served, tr = rr.read("owner 2", "2030-02-01T00:00:00Z", 2000)
    assert not any(it["ref"].startswith("s02:") for it in served) and tr["raw_tokens_est"] <= 2000
    assert tr["n_candidates"] == 10
