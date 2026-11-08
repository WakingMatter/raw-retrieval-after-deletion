"""T1–T12 (v1.2.1 §8) + poisoning guard, DoT/redact, eager, memo. Fakes only: HashEmbedder + fake LLM, no model calls."""
import builtins, json, re
from pathlib import Path
import numpy as np
import pytest
from pilot.store import Additive, quantize, input_set_hash, cache_key, DB
from pilot.embed import HashEmbedder
from pilot.llm import LLM
from pilot.arms import A6, A3
from pilot import common

CAN = "QX-4821-ZK"


def fake(role, prompt):
    if role.startswith("a3_write"):
        sid = re.search(r"NEW SESSION \((s\d+)", prompt).group(1)
        body = prompt.split("NEW SESSION")[1]
        first = [l for l in body.splitlines()[1:] if l.strip()][:2]
        ids = re.findall(r"\[(n\d{4}) \|", prompt.split("NEW SESSION")[0])
        ops = [{"op": "ADD", "text": f"{sid}: " + " ".join(first)[:300], "date": "2030-01-01"}]
        if ids:
            ops.append({"op": "UPDATE", "id": ids[0], "text": f"merged with {sid}", "date": "2030-01-01"})
        return json.dumps({"ops": ops})
    if role == "a3_redact":
        return "redacted note"
    if role == "a3_cluster":
        return "cluster summary"
    if role == "synth":
        ids = re.findall(r"^\[(s\d+:\d{3}|wb:\d{3}:\d{3}) \|", prompt, re.M)
        return "Summary. " + (" ".join(f"[{i}]" for i in ids[:2]) if ids else "")
    if "SOURCES" in prompt and "wb" in role:
        return "answer"
    return "answer: " + ("QX-4821-ZK" if CAN in prompt else "something")


SESS = {f"s{i:02d}": f"# s{i:02d}\n\nUser talks about topic {i % 3} alpha beta {i}.\n\nMore detail {i} gamma." for i in range(1, 9)}
SESS["s03"] += f"\n\nAdmin note: Bo's badge code is {CAN}."
T = {s: f"2030-01-{int(s[1:]):02d}T10:00:00" for s in SESS}


@pytest.fixture
def env(tmp_path):
    emb = HashEmbedder()
    rng = np.random.default_rng(0)
    anchors = rng.standard_normal((16, 32))
    llm = LLM(tmp_path / "calls", fake=fake)
    return tmp_path, emb, anchors, llm


def mk6(env, name="A6", **kw):
    tmp, emb, anchors, llm = env
    return A6(name, "F", tmp / name, llm, emb, anchors=anchors, **kw)


def ingest_all(arm, skip=()):
    for i, s in enumerate(sorted(SESS)):
        if s not in skip:
            arm.ingest(s, SESS[s], T[s], i)


# T1 -------------------------------------------------------------------------------------------------
def test_T1_subtract_equals_rebuild_fuzzed():
    rng = np.random.default_rng(1)
    for trial in range(30):
        an = rng.standard_normal((16, 24)); a = Additive(an)
        vs = {f"u{i}": quantize(rng.standard_normal(24)) for i in range(200)}
        for u, q in vs.items():
            a.add(u, q)
        gone = rng.choice(list(vs), 60, replace=False)
        for u in gone:
            a.remove(u, vs[u])
        surv = {u: q for u, q in vs.items() if u not in set(gone)}
        r = Additive.rebuild(an, surv)
        assert np.array_equal(a.sum, r.sum) and np.array_equal(a.count, r.count)
        assert a.sum.tobytes() == r.sum.tobytes() and a.digest() == r.digest()


# T2 -------------------------------------------------------------------------------------------------
def test_T2_digest_order_independence_and_ranking_agreement():
    rng = np.random.default_rng(2)
    an = rng.standard_normal((16, 24)); items = [(f"u{i}", quantize(rng.standard_normal(24))) for i in range(100)]
    a, b = Additive(an), Additive(an)
    for u, q in items: a.add(u, q)
    for u, q in reversed(items): b.add(u, q)
    assert a.digest() == b.digest()
    qv = rng.standard_normal(24); qv /= np.linalg.norm(qv)
    fl = [(-float((q / common_scale()) @ qv), u) for u, q in items]
    ref = [(-float((q.astype(np.float64) / np.linalg.norm(q)) @ qv), u) for u, q in items]
    agree = sum(x[1] == y[1] for x, y in zip(sorted(fl)[:10], sorted(ref)[:10]))
    print("T2 top-10 ranking agreement float-vs-quantised:", agree, "/10")
    assert agree >= 9


def common_scale():
    from pilot.store import SCALE
    return float(SCALE)


# T3 -------------------------------------------------------------------------------------------------
def test_T3_never_serve_on_key_mismatch(env):
    a = mk6(env); ingest_all(a)
    n = next(n for n in range(16) if len(a._input_set(n, "2031")) >= 2)
    c1 = a.summary(n, "2031", "t"); calls = len(a.stats["calls"])
    assert a.summary(n, "2031", "t") is c1 and len(a.stats["calls"]) == calls          # exact key -> served
    a.caches[n] = dict(c1, key="0" * 64)                                                  # tamper the key
    c2 = a.summary(n, "2031", "t")
    assert len(a.stats["calls"]) == calls + 1 and c2["key"] == c1["key"]                  # mismatch -> recomputed
    # a different t_query that changes the input set changes the key
    ids_early = a._input_set(n, "2030-01-03")
    if len(ids_early) >= 2 and ids_early != a._input_set(n, "2031"):
        assert cache_key(input_set_hash(ids_early), a.syn_prompt_sha, common.ANSWER_MODEL) != c1["key"]


# T4 + T12 ---------------------------------------------------------------------------------------------
def test_T4_T12_forget_cascade_transitive(env, monkeypatch):
    a = mk6(env); ingest_all(a)
    r1 = a.ask("topic 0 alpha", "2031", 2000, "warm_W", write_back=True)
    wb1 = r1["wb_id"]
    # v1.3 F11: serve wb1 to the second read so dependency capture is actually exercised (v1.2 asserted `... or True`)
    item = {"text": a.units[wb1]["text"], "kind": "wb", "ref": wb1}
    trace = {"header_tokens_est": 0.0, "raw_tokens_est": common.item_cost(item["text"])}
    with monkeypatch.context() as m:
        m.setattr(a, "read", lambda *args, **kwargs: ([item], trace))
        r2 = a.ask("topic 0 alpha and the earlier answer", "2031", 2000, "warm_W", write_back=True)
    wb2 = r2["wb_id"]
    assert wb1 in r2["served"]
    assert wb1 in a.units[wb2]["derived_from"]
    assert set(a.units[wb1]["derived_from"]) <= a._closure(a.units[wb2]["derived_from"])
    # force wb2 to derive ONLY from wb1 (write-back of a write-back) and wb1 from s03
    a.units[wb1]["derived_from"] = ["s03:002"]; a.units[wb2]["derived_from"] = [wb1]
    others = {n: dict(c) for n, c in a.caches.items()}
    rec = a.forget("s03", "2031")
    assert wb1 in rec["writebacks_deleted"] and wb2 in rec["writebacks_deleted"]          # T12
    assert not any(u.startswith("s03:") for u in a.units)
    for n in rec["caches_invalidated"]:
        assert n not in a.caches                                                           # T4 dependents gone
    for n, c in a.caches.items():                                                          # T4 others identical
        assert c == others[n]
    assert rec["kc1a_subtraction_equals_rebuild"]


# T5 -------------------------------------------------------------------------------------------------
def test_T5_canary_bytes(env):
    a = mk6(env); ingest_all(a)
    a.ask("badge code Bo", "2031", 2000, "warm_W", write_back=True)
    a.db.checkpoint()
    assert any(CAN.encode() in f.read_bytes() for f in a.db.files())
    a.forget("s03", "2031")
    a.db.close_for_scan()
    for f in a.db.files():
        assert CAN.encode() not in f.read_bytes(), f
    assert all(CAN not in t for _, _, t in a.derived_artifacts())


# T6 -------------------------------------------------------------------------------------------------
def test_T6_P_and_W_end_to_end(env):
    a = mk6(env); ingest_all(a)
    w = a.ask("Bo badge code", "2031", 2000, "warm_W", write_back=True)
    assert w["wb_id"] in a.units and any(d.startswith("s03:") for d in w["wb_derived_from"])
    p = a.ask("Bo badge code", "2031", 2000, "warm_P")
    assert "wb_id" not in p
    a.forget("s03", "2031")
    assert w["wb_id"] not in a.units
    for n, c in a.caches.items():
        assert not any(d.startswith("s03:") for d in c["deps"])


# T7 -------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("mode", ["redact", "dot"])
def test_T7_A3_ops_redact_and_dot(env, mode):
    tmp, emb, anchors, llm = env
    a = A3("A3", "F", tmp / f"a3{mode}", llm, emb, forget_mode=mode)
    for i, s in enumerate(sorted(SESS)):
        a._write(s, SESS[s], T[s], "ingest")
        if i + 1 in (4, 8):
            a.refresh("ingest")
    touched = [n for n, x in a.notes.items() if "s03" in x["sources"]]
    sole = [n for n in touched if a.notes[n]["sources"] == ["s03"]]
    mixed = [n for n in touched if n not in sole]
    assert touched and a.clusters
    rec = a.forget("s03", "2031", SESS["s03"])
    assert not any("s03" in x["sources"] for x in a.notes.values())
    if mode == "dot":
        assert set(rec["notes_deleted"]) == set(touched) and not rec["notes_redacted"]
    else:
        assert set(rec["notes_deleted"]) == set(sole) and set(rec["notes_redacted"]) == set(mixed)
        assert all(a.notes[n]["text"] == "redacted note" for n in mixed)
    for c in a.clusters.values():
        assert all(m in a.notes for m in c["members"])
        if mode == "dot":
            assert "s03" not in c["sources"]


# T8 -------------------------------------------------------------------------------------------------
def test_T8_budget_and_header(env):
    a = mk6(env); ingest_all(a)
    for B in (200, 600, 2000):
        served, tr = a.read("topic alpha", "2031", B, "probe")
        assert tr["header_tokens_est"] <= B / 5 + 1e-9
        assert tr["header_tokens_est"] + tr["raw_tokens_est"] <= B + 1e-9
        assert sum(common.item_cost(it["text"]) for it in served) <= B + 1e-9


# T9 -------------------------------------------------------------------------------------------------
def test_T9_clean_world_digest_equals_forget_world(env):
    f = mk6(env, "F6"); ingest_all(f); f.forget("s03", "2031")
    tmp, emb, anchors, llm = env
    c = A6("C6", "C", tmp / "C6", llm, emb, anchors=anchors); ingest_all(c, skip=("s03",))
    assert f.add.digest() == c.add.digest()


# T10 ------------------------------------------------------------------------------------------------
def test_T10_latency_on_every_read(env):
    a = mk6(env); ingest_all(a)
    a.ask("topic alpha", "2031", 2000, "probe")
    assert a.stats["calls"] and all(c["latency"] is not None for c in a.stats["calls"] if not c["memo"])
    assert all("latency" in c and "in" in c and "out" in c for c in a.stats["calls"])


# T11 ------------------------------------------------------------------------------------------------
def test_T11_A6m_cited_only_and_audit_unread(env, monkeypatch):
    a = mk6(env, "A6m", edges="model"); ingest_all(a)
    real_open = builtins.open
    def guarded(path, mode="r", *k, **kw):
        if Path(str(path)).name.startswith("AUDIT") and not any(m in mode for m in "aw"):
            raise AssertionError("arm read the audit file")
        return real_open(path, mode, *k, **kw)
    monkeypatch.setattr(builtins, "open", guarded)
    for q in ("topic 0 alpha", "topic 1 beta", "gamma detail"):
        a.ask(q, "2031", 2000, "probe")
    a.forget("s03", "2031")
    a.ask("topic 0 alpha", "2031", 2000, "probe")
    monkeypatch.setattr(builtins, "open", real_open)
    assert a.caches
    for n, c in a.caches.items():
        cited = set(re.findall(r"\[([^\]]+)\]", c["text"]))
        assert set(c["deps"]) <= cited and set(c["deps"]) != set(a._input_set(n, "2031")) or len(c["deps"]) <= 2
    rows = [json.loads(l) for l in real_open(a.audit_path)]
    assert rows and all(set(r["cited"]) <= set(r["code_known"]) for r in rows if "node" in r)


# extra: eager, poisoning guard, memo -----------------------------------------------------------------
def test_eager_recomputes_at_forget_lazy_does_not(env):
    lazy = mk6(env, "L"); eager = mk6(env, "E", recompute="eager")
    for a in (lazy, eager):
        ingest_all(a)
        for q in ("topic 0 alpha", "topic 1 beta", "topic 2 gamma", "Bo badge"):
            a.ask(q, "2031", 2000, "probe")
    rl, re_ = lazy.forget("s03", "2031"), eager.forget("s03", "2031")
    assert rl["caches_invalidated"] == re_["caches_invalidated"] and rl["caches_invalidated"]
    assert not rl["eager_recomputed"] and set(re_["eager_recomputed"]) == set(re_["caches_invalidated"])
    assert not any(c["phase"] == "forget_eager" for c in lazy.stats["calls"])
    assert any(c["phase"] == "forget_eager" for c in eager.stats["calls"])


def test_poisoning_guard_never_caches_bad_outputs(tmp_path):
    bad = ["", "Error: rate limit exceeded", "I can't help with that."]
    seq = iter(bad * 3)
    llm = LLM(tmp_path, fake=lambda role, p: next(seq))
    r = llm.call("synth", "p1")
    assert not r["ok"] and not list((tmp_path / "memo").iterdir())
    emb = HashEmbedder(); a = A6("P", "F", tmp_path / "a", llm, emb, anchors=np.random.default_rng(0).standard_normal((16, 32)))
    ingest_all(a)
    llm.fake = lambda role, p: "Error: upstream 500"
    a.read("topic alpha", "2031", 2000, "probe")
    assert not a.caches


def test_memo_identical_prompt_identical_output(tmp_path):
    n = {"c": 0}
    def f(role, p):
        n["c"] += 1; return f"out{n['c']}"
    llm = LLM(tmp_path, fake=f)
    a, b = llm.call("synth", "same"), llm.call("synth", "same")
    assert a["text"] == b["text"] and n["c"] == 1 and b["memo_hit"]
    assert llm.call("synth", "other")["text"] != a["text"]
