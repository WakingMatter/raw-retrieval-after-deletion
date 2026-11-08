"""Offline tests for RR-2hop (no API, no model weights: fake embedder, reranker and LLM)."""
from __future__ import annotations
import hashlib, random, re, subprocess, sys
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from e3 import rr2hop as R  # noqa: E402
from e3.paths import RESEARCH  # noqa: E402
from pilot.common import item_cost  # noqa: E402

DIM = 4096
STOP = set("in which does the have their is by of to this a her now".split())


def toks(s):
    return [w for w in re.findall(r"[a-z]+", s.lower()) if w not in STOP]


class FakeEmb:
    def vec(self, text):
        v = np.zeros(DIM)
        for w in toks(text):
            v[int(hashlib.md5(w.encode()).hexdigest(), 16) % DIM] += 1
        return v + 1e-6


class FakeRerank:
    def scores(self, q, texts):
        qs = set(toks(q))
        return [float(len(qs & set(toks(t)))) for t in texts]


class FakeLLM:
    def __init__(self, bridge_text="Ines Pillai", bridge_ok=True):
        self.calls, self.bt, self.bok = [], bridge_text, bridge_ok

    def call(self, role, prompt, ctx=None):
        self.calls.append((role, prompt))
        if role == "bridge":
            return {"ok": self.bok, "text": self.bt if self.bok else None, "usage": {}}
        return {"ok": True, "text": "Chennai", "usage": {}}


def corpus(n_filler=60):
    emb = FakeEmb()
    rows = [("s1:001", "2026-01-01T00:00", "The Atlas project is now led by Ines Pillai."),
            ("s2:001", "2026-01-02T00:00", "Ines Pillai: office city is Chennai."),
            ("s3:001", "2026-01-09T00:00", "Atlas lead question: the project Atlas office city review is pending.")]
    rnd = random.Random(0)
    words = "budget deadline quarter plan vendor invoice sprint roadmap".split()
    for i in range(n_filler):
        rows.append((f"f{i:02d}:001", "2026-01-05T00:00",
                     "Project Atlas leading office: " + " ".join(rnd.choice(words) for _ in range(6))))
    rows.append(("late:001", "2027-01-01T00:00", "Ines Pillai is based in Oslo."))  # after t_query: never served
    return emb, {c: {"t": t, "text": x, "vec": R.unit_vec(emb, x)} for c, t, x in rows}


Q, TQ = "In which city does the person leading project Atlas have their office?", "2026-06-01T00:00"


def test_parse_entity():
    assert R.parse_entity("Ines Pillai") == "Ines Pillai"
    assert R.parse_entity("**Ines Pillai.**\n") == "Ines Pillai"
    assert R.parse_entity("Name: \"Ines Pillai\"") == "Ines Pillai"
    assert R.parse_entity("NONE") is None and R.parse_entity("none.") is None and R.parse_entity("") is None
    assert R.parse_entity(None) is None
    assert R.parse_entity("The excerpts do not clearly say who leads it at all") is None   # over-long -> None


def test_interleave_order_and_dedup():
    a = [{"ref": x} for x in "abc"]; b = [{"ref": x} for x in "bdea"]
    assert [i["ref"] for i in R.interleave(a, b)] == list("abdce")


def test_ranked_respects_time_topk_and_is_deterministic():
    emb, ch = corpus()
    r1 = R.ranked(ch, emb, FakeRerank(), Q, TQ, top_k=10)
    r2 = R.ranked(ch, emb, FakeRerank(), Q, TQ, top_k=10)
    assert [i["ref"] for i in r1] == [i["ref"] for i in r2] and len(r1) == 10
    assert all(i["ref"] != "late:001" for i in R.ranked(ch, emb, FakeRerank(), Q, TQ, top_k=1000))
    assert r1[0]["text"].startswith(f"[{r1[0]['ref']} | ")


def test_second_hop_brings_bridge_fact_within_budget():
    emb, ch = corpus()
    B = 400
    h1 = R.ranked(ch, emb, FakeRerank(), Q, TQ, top_k=5)
    assert "s2:001" not in [i["ref"] for i in h1]            # hop 1 misses the attribute fact
    llm = FakeLLM()
    out = R.RR2Hop(ch, emb, FakeRerank(), llm, top_k=5).ask(Q, TQ, B)
    assert out["entity"] == "Ines Pillai" and "s2:001" in out["served"]
    assert sum(item_cost(f"[{c} | {ch[c]['t'][:16]}] {ch[c]['text']}") for c in out["served"]) <= B
    assert len(out["served"]) == len(set(out["served"]))
    assert [r for r, _ in llm.calls] == ["bridge", "answer"]
    bp = llm.calls[0][1]
    assert bp.startswith(R.BRIDGE_PROMPT) and Q in bp and "late:001" not in bp


def test_none_or_failed_bridge_falls_back_to_hop1():
    emb, ch = corpus()
    for llm in (FakeLLM("NONE"), FakeLLM(bridge_ok=False)):
        a = R.RR2Hop(ch, emb, FakeRerank(), llm, top_k=5)
        out = a.ask(Q, TQ, 400)
        assert out["entity"] is None and out["served"] == out["hop1_served"] and out["hop2_top"] == []


def test_budget_never_exceeded_random():
    rnd = random.Random(1)
    emb, ch = corpus(200)
    for _ in range(20):
        B = rnd.choice([150, 400, 2000])
        out = R.RR2Hop(ch, emb, FakeRerank(), FakeLLM(rnd.choice(["Ines Pillai", "Atlas", "NONE"])), top_k=50).ask(Q, TQ, B)
        assert out["raw_tokens_est"] <= B


def test_e2_frozen_files_untouched():
    p = subprocess.run(["git", "diff", "--name-only", "HEAD", "--", "e2/e2", "e2/E2-FREEZE.json", "prereg-E2"],
                       cwd=RESEARCH, capture_output=True, text=True)
    assert p.returncode == 0 and p.stdout.strip() == ""
