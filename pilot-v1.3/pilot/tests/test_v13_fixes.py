"""v1.3 regression tests: one (or more) per Astra J1 finding applied in pilot-v1.3 (see FIXES.md).
Offline only: HashEmbedder, random anchors, fake LLM callables. No model calls, no network."""
import json, re, sqlite3, sys
from pathlib import Path
import numpy as np
import pytest
from pilot.store import DB
from pilot.embed import HashEmbedder
from pilot import common


class FakeEmbedder(HashEmbedder):
    """Drop-in for pilot.embed.Embedder in driver tests (no ONNX model)."""
    def __init__(self, cache_dir=None):
        pass


def _fake_anchors(emb, out):
    A = np.random.default_rng(0).standard_normal((common.K_ANCHORS, 32)); A /= np.linalg.norm(A, axis=1, keepdims=True)
    return A, "fake-anchors"


def run_driver(mod, monkeypatch, tmp_path, label, arms, extra=()):
    """Run a driver main() (pilot.run or pilot2.run2) with --fake --smoke on one stream under a tmp ROOT."""
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    monkeypatch.setattr(mod, "Embedder", FakeEmbedder)
    monkeypatch.setattr(mod, "load_or_fit", _fake_anchors)
    if hasattr(mod, "verify_frozen"):
        monkeypatch.setattr(mod, "verify_frozen", lambda *a, **k: {"skipped": "test"})
    monkeypatch.setattr(sys, "argv", ["x", "--label", label, "--smoke", "--fake", "--streams", "7240241", "--arms", arms, *extra])
    return mod.main()


def nrows(db):
    c = sqlite3.connect(str(db)); n = c.execute("SELECT count(*) FROM obj").fetchone()[0]; c.close(); return n


# ---------------------------------------------------------------- F03: resume must not destroy stores
def test_F03_db_refuses_existing_store(tmp_path):
    d = DB(tmp_path / "store.sqlite"); d.put("raw", "a", {"x": 1}); d.close_for_scan()
    with pytest.raises(FileExistsError):
        DB(tmp_path / "store.sqlite")
    assert nrows(tmp_path / "store.sqlite") == 1


def test_F03_driver_resume_skips_DONE_before_construction(tmp_path, monkeypatch):
    from pilot import run
    run_driver(run, monkeypatch, tmp_path, "T", "A6")
    inst = tmp_path / "runs" / "T" / "stream-7240241" / "A6-F"
    assert (inst / "DONE").exists()
    n0 = nrows(inst / "db" / "store.sqlite"); assert n0 > 0
    ans0 = (inst / "answers.jsonl").read_text()
    run_driver(run, monkeypatch, tmp_path, "T", "A6")          # resume: every instance DONE
    assert nrows(inst / "db" / "store.sqlite") == n0
    assert (inst / "answers.jsonl").read_text() == ans0


# ---------------------------------------------------------------- synthetic run-dir fixture (scorer tests)
def make_run(root, answers, arms=("A6",), targets=None, probes=None, meta=None, seeds=(1,)):
    """answers: {(arm, world): {probe_id: answer_text or (answer_text, ok)}}; unspecified probes answer 'x'."""
    rd = Path(root) / "runs" / "R"; rd.mkdir(parents=True, exist_ok=True)
    targets = targets if targets is not None else [
        {"probe_id": "s1:U:DIRECT:K1", "cls": "U", "variant": "DIRECT", "deleted_session": "s1", "key": "K1",
         "truth_any": [r"\bPune\b"], "deleted_any": [], "deleted_value": None, "question": "q?"}]
    probes = probes if probes is not None else [
        {"category": "current", "expect": "value", "question": "q1", "truth_any": [r"\bOslo\b"], "wrong_any": [r"\bRome\b"]},
        {"category": "absent", "expect": "abstain", "question": "q2", "truth_any": [], "wrong_any": [r"\bRome\b"]}]
    (rd / "RUN-META.json").write_text(json.dumps(meta if meta is not None else
                                                 {"finished": "t", "errors": [], "arms": list(arms), "streams": list(seeds)}))
    pids = [t["probe_id"] for t in targets] + [f"mix:{i:02d}:{p['category']}" for i, p in enumerate(probes)]
    for seed in seeds:
        sd = rd / f"stream-{seed}"; sd.mkdir(exist_ok=True)
        (sd / "targets.json").write_text(json.dumps({"targets": targets, "probes": probes}))
        for a in arms:
            for w in ("F", "C"):
                d = sd / f"{a}-{w}"; d.mkdir(exist_ok=True)
                rows = []
                for pid in pids:
                    v = answers.get((a, w), {}).get(pid, "x")
                    txt, ok = v if isinstance(v, tuple) else (v, True)
                    rows.append({"probe_id": pid, "answer": txt, "ok": ok})
                (d / "answers.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
                (d / "log.json").write_text(json.dumps({"warm": [], "forget": [], "ingest": []}))
                (d / "artifacts.json").write_text("[]")
                (d / "stats.json").write_text(json.dumps({"calls": [], "poison": []}))
                (d / "residue_bytes.json").write_text("{}")
                (d / "DONE").write_text("t")
    (rd / "calls.jsonl").write_text("")
    return rd


# ---------------------------------------------------------------- F04: failures are never denominators / safe
def test_F04_driver_exits_nonzero_on_instance_error(tmp_path, monkeypatch):
    from pilot import run
    def boom(*a, **k):
        raise RuntimeError("injected")
    monkeypatch.setattr(run, "run_instance", boom)
    with pytest.raises(SystemExit) as e:
        run_driver(run, monkeypatch, tmp_path, "E", "A6")
    assert e.value.code == 1
    meta = json.loads((tmp_path / "runs" / "E" / "RUN-META.json").read_text())
    assert meta["errors"] and meta["arms"] == ["A6"]


def test_F04_load_refuses_incomplete_runs(tmp_path):
    from pilot import score
    rd = make_run(tmp_path / "ok", {})
    D, rows = score.score(rd)                                    # complete fixture scores
    assert {r["cls"] for r in rows} == {"U", "MIX"}
    rd = make_run(tmp_path / "err", {}, meta={"finished": "t", "errors": [["A6", "F", 1, "tb"]], "arms": ["A6"]})
    with pytest.raises(ValueError, match="incomplete"):
        score.load(rd)
    rd = make_run(tmp_path / "done", {}); (rd / "stream-1" / "A6-C" / "DONE").unlink()
    with pytest.raises(ValueError, match="Missing completed instance"):
        score.load(rd)
    rd = make_run(tmp_path / "miss", {}); p = rd / "stream-1" / "A6-F" / "answers.jsonl"
    p.write_text("".join(p.read_text().splitlines(True)[:-1]))
    with pytest.raises(ValueError, match="Missing, duplicate"):
        score.load(rd)
    rd = make_run(tmp_path / "fail", {("A6", "F"): {"s1:U:DIRECT:K1": ("", False)}})
    with pytest.raises(ValueError, match="Unmeasured"):
        score.load(rd)
    rd = make_run(tmp_path / "undeclared", {}, meta={"finished": "t", "errors": [], "arms": ["A6", "RS"]})
    with pytest.raises(ValueError, match="Missing completed instance"):
        score.load(rd)


def test_F04_mix_abstention_requires_exact_contract(tmp_path):
    from pilot import score
    pid = "mix:01:absent"
    for ans, want in [("", 0), ("Dana Lee owns it.", 0), ("Not found in memory.", 1), ("not found in memory", 1),
                      ("Not found in memory. No excerpt names an owner.", 1), ("Rome. Not found in memory", 0)]:
        rd = make_run(tmp_path / f"m{len(ans)}{want}", {("A6", "F"): {pid: ans}, ("A6", "C"): {pid: ans}})
        _, rows = score.score(rd)
        r = [x for x in rows if x["probe_id"] == pid][0]
        assert r["accF"] == want, ans
        assert r["okF"] is True and r["okC"] is True


# ---------------------------------------------------------------- F01/F02: PILOT-2 target authoring (ledger-only, real data)
@pytest.fixture(scope="module")
def streams2():
    from pilot2.run2 import load_stream
    return {seed: load_stream(seed, False) for seed in (7240241, 7240242)}


def test_F01_C_gold_uses_full_deletion_set(streams2):
    from gen import ledger
    from gen.probe_author import LedgerOnlyStream
    for seed, S in streams2.items():
        st = LedgerOnlyStream(common.DATA / f"stream-{seed}"); keys = st.world["keys"]
        rows = ledger.compute_rows(st.events, keys, set(S["deleted"]))
        cv = [{"view": 0, "view_from": None, "view_until": None, "rows": rows}]
        touched = {e["key"] for e in st.events if e.get("session") in S["deleted"] and e.get("key")}
        for t in S["targets"]:
            if t["cls"] == "U":
                assert t["key"] not in touched, t["probe_id"]
            if t.get("key") and t["variant"] != "AGG":
                g = ledger.gold_at(cv, t["key"], S["t_end"])
                assert t["gold_c"] == {"status": g["status"], "value": g["value"]}, t["probe_id"]
                if t["cls"] == "U":
                    assert g["status"] == "active" and re.search(t["truth_any"][0], g["value"])
    pids = {t["probe_id"] for t in streams2[7240242]["targets"]}
    assert "s26:U:DIRECT:K095" not in pids          # Astra's Cassandra counterexample (absent under full deletion set)


def test_F02_R_targets_have_no_literal_support_in_surviving_raw(streams2):
    for seed, S in streams2.items():
        surv = "\n".join(S["text"][s] for s, _ in S["sessions"] if s not in S["deleted"])
        R = [t for t in S["targets"] if t["cls"] == "R"]
        assert R, seed
        for t in R:
            assert not re.search(t["deleted_any"][0], surv, re.I), (seed, t["probe_id"], t["deleted_value"])
        # Astra's relation-mediated counterexamples in 7240242 must not be R targets any more
        if seed == 7240242:
            assert not any(t["deleted_value"] in ("Observability", "Pune") for t in R)


# ---------------------------------------------------------------- F05: grouped bootstrap
def test_F05_bootstrap_keeps_deletion_groups_whole():
    from pilot.score import boot
    rows = [{"seed": 1, "probe_id": f"g1:{i}", "deletion": "1:g1", "d": 1} for i in range(4)]
    rows += [{"seed": 1, "probe_id": f"g{j}:0", "deletion": f"1:g{j}", "d": 0} for j in range(2, 6)]
    b = boot(rows, rows, lambda r: r["d"], lambda r: 0, n=4000)
    assert b["est"] == 0.5 and b["n_pairs"] == 8 and b["n_groups"] == 5
    assert b["resampling_unit"] == "stream_then_deletion"
    assert b["lo95"] == 0.0           # P(no draw of g1) = 0.8**5 = 0.33; a row bootstrap gives lo95 > 0 here
    mix = [{"seed": 1, "probe_id": f"m{i}", "d": i % 2} for i in range(6)]
    m = boot(mix, mix, lambda r: r["d"], lambda r: 0, n=200)
    assert m["resampling_unit"] == "stream" and m["degenerate"]    # one stream, no deletion ids -> no fake precision


# ---------------------------------------------------------------- F06: primary selector
def test_F06_primary_includes_M_excludes_X():
    from pilot.score import leak_rows
    rows = [{"arm": "A6", "cls": c, "variant": v, "probe_id": f"{c}{v}"} for c, v in
            (("S", "DIRECT"), ("M", "DERIVED"), ("M", "AGG"), ("X", "DIRECT"), ("S", "ENUM"))]
    assert {r["probe_id"] for r in leak_rows(rows, "A6")} == {"SDIRECT", "MDERIVED", "MAGG"}
    assert {r["probe_id"] for r in leak_rows(rows, "A6", variant="ENUM")} == {"SENUM"}
    assert {r["probe_id"] for r in leak_rows(rows, "A6", cls=("X",))} == {"XDIRECT"}


# ---------------------------------------------------------------- F07: retries billed
def test_F07_failed_attempts_are_billed(tmp_path, monkeypatch):
    from pilot import llm as L
    from pilot.score import costs
    monkeypatch.setattr(L.time, "sleep", lambda s: None)
    n = {"k": 0}
    def fake(role, prompt):
        n["k"] += 1
        return "" if n["k"] == 1 else "Answer: blue"          # first attempt is an invalid (empty) answer
    llm = L.LLM(tmp_path, fake=fake)
    r = llm.call("answer", "x" * 400)
    assert r["ok"] and len(r["attempt_history"]) == 2 and not r["attempt_history"][0]["ok"]
    r2 = llm.call("answer", "x" * 400)
    assert r2["memo_hit"]
    rec = lambda r: {"phase": "q", "role": "answer", "ok": True, "memo": r["memo_hit"], "in": 100, "out": 1, "latency": 0.1,
                     "attempt_history": [] if r["memo_hit"] else r["attempt_history"]}
    D = {1: {"arms": {("A6", "F"): {"log": {"forget": []}, "stats": {"calls": [rec(r), rec(r2)]}}}}}
    act = costs(D)["A6"]["actual_attempts_this_run"]
    assert act["attempts"] == 2 and act["failed_attempts"] == 1 and act["in"] == 200
    old = {1: {"arms": {("A6", "F"): {"log": {"forget": []}, "stats": {"calls": [{k: v for k, v in rec(r).items() if k != "attempt_history"}]}}}}}
    assert costs(old)["A6"]["actual_attempts_this_run"] is None    # pre-v1.3 stats -> unknown, never zero


# ---------------------------------------------------------------- F08: cache identities
def test_F08_vector_cache_namespaced_by_encoder(tmp_path):
    import threading
    from types import SimpleNamespace
    from pilot.embed import Embedder
    def mk(mid, val):
        e = Embedder.__new__(Embedder)
        e.cache_dir, e.lock, e.mem, e.loaded, e.model_id = tmp_path, threading.Lock(), {}, True, mid
        e.e = SimpleNamespace(embed=lambda t: [val, 0.0]); return e
    assert list(mk("enc-a", 1.0).vec("same text")) == [1.0, 0.0]
    assert list(mk("enc-b", 2.0).vec("same text")) == [2.0, 0.0]      # v1.2 served enc-a's cached [1,0]
    assert list(mk("enc-a", 9.0).vec("same text")) == [1.0, 0.0]      # same identity still hits the cache


def test_F08_memo_key_includes_effort(tmp_path):
    from pilot.llm import LLM
    a = LLM(tmp_path, fake=lambda r, p: "Answer: x", reasoning_effort="low")
    assert not a.call("answer", "q")["memo_hit"] and a.call("answer", "q")["memo_hit"]
    b = LLM(tmp_path, fake=lambda r, p: "Answer: y", reasoning_effort="high")
    assert not b.call("answer", "q")["memo_hit"]


def test_F08_anchor_identity_enforced(tmp_path):
    from types import SimpleNamespace
    from pilot import anchors as AN
    out = tmp_path / "anchors.npy"; np.save(out, np.eye(2))
    emb = SimpleNamespace(model_id="enc-a")
    (tmp_path / "anchors.json").write_text(json.dumps({"n_chunks": 1}))                 # v1.2-style sidecar, no identity
    with pytest.raises(ValueError):
        AN.load_or_fit(emb, out)
    (tmp_path / "anchors.json").write_text(json.dumps({"cache_identity": AN.cache_identity(emb)}))
    A, _ = AN.load_or_fit(emb, out); assert A.shape == (2, 2)
    with pytest.raises(ValueError):
        AN.load_or_fit(SimpleNamespace(model_id="enc-b"), out)


def test_F08_frozen_anchors_adopted():
    from pilot.anchors import cache_identity
    from pilot.embed import Embedder
    info = json.loads((common.ROOT / "runs" / "anchors-7240240.json").read_text())
    assert info["adopted_from"]["legacy_embedder"] == "gte-modernbert-base:603317bc2561e506"
    assert info["cache_identity"]["k"] == 16 and info["cache_identity"]["embedder"].startswith("gte-modernbert-base:")


# ---------------------------------------------------------------- F09: strict judge parsing, no imputation
def test_F09_judge_strict_and_unmeasured_excluded(tmp_path):
    from pilot.judge import judge, parse_verdicts
    from pilot.llm import LLM
    with pytest.raises(ValueError):
        parse_verdicts('[{"i": 0, "leak": "false"}]', 2)               # Astra's counterexample: string + partial
    with pytest.raises(ValueError):
        parse_verdicts('[{"i": 0, "leak": true}, {"i": 0, "leak": false}]', 2)   # duplicate id
    assert parse_verdicts('ok [{"i": 1, "leak": false}, {"i": 0, "leak": true}]', 2) == {0: True, 1: False}
    rows = [{"_jid": k, "question": "q", "deleted_value": "v", "answer": k} for k in ("F", "C")]
    errs = []
    out = judge(LLM(tmp_path, fake=lambda r, p: '[{"i": 0, "leak": "false"}]'), rows, errors=errs)
    assert out == {"F": None, "C": None} and len(errs) == 1
    out = judge(LLM(tmp_path / "b", fake=lambda r, p: '[{"i": 0, "leak": true}, {"i": 1, "leak": false}]'), rows)
    assert out == {"F": True, "C": False}


def test_F09_summary_requires_both_judgments(tmp_path):
    from pilot import score as SC
    tg = [{"probe_id": "s1:S:DIRECT:K1", "cls": "S", "variant": "DIRECT", "deleted_session": "s1", "key": "K1",
           "truth_any": [], "deleted_any": [r"\bPune\b"], "deleted_value": "Pune", "question": "q?"}]
    rows = make_run(tmp_path, answers={}, targets=tg)
    D, R = SC.score(rows)
    for r in R:
        if r["cls"] in SC.PRIMARY_CLS:
            r["jF"], r["jC"] = True, None                          # v1.2: (1 or 0) - (None or 0) = +1
    p = SC.summarize(rows, D, R)["per_arm"]["A6"]
    assert p["judge_dLeak"] is None and p["judge_pairs_measured"] == 0 and p["judge_pairs_unmeasured"] >= 1


# ---------------------------------------------------------------- F12: co-occurrence is a candidate, not residue
def test_F12_cooccurrence_is_candidate_not_residue(tmp_path):
    from pilot2.residue2 import cooccurrence_candidates
    keys = {"K1": {"subject_name": "Meera Joshi"}}
    tg = [{"probe_id": "s1:S:DIRECT:K1", "cls": "S", "variant": "DIRECT", "key": "K1",
           "deleted_any": [r"\bDublin\b"], "deleted_value": "Dublin"}]
    art = [("summary", "n09", "Meera Joshi owns auth-gateway. Ishaan Khanna's Dublin parking paperwork is unrelated.")]
    c = cooccurrence_candidates(tg, art, keys, {})
    assert len(c) == 1 and c[0]["artifacts"][0]["id"] == "n09"           # kept with evidence for review
    src = (Path(__file__).parents[2] / "pilot2" / "score2.py").read_text()
    assert 'out["fact_residue"][k] = None' in src and "n += any(" not in src
    from pilot import score as SC
    rows = make_run(tmp_path, answers={}, targets=[dict(tg[0], truth_any=[], question="q?", deleted_session="s1")])
    D, _ = SC.score(rows)
    D[1]["arms"][("A6", "F")]["artifacts"] = [("summary", "n00", "nothing about her; Dublin weather")]
    r = SC.residue(D)["1:A6-F"]
    assert r["semantic_hits"] is None and r["value_regex_hits"] == 1


# ---------------------------------------------------------------- narrow DoT arm (J2-17)
def test_narrow_DoT_deletes_only_writer_touched_notes(tmp_path):
    from pilot.tests.test_pilot import fake as fake_writer, SESS, T
    from pilot.embed import HashEmbedder
    from pilot.llm import LLM
    from pilot.arms import A3
    from pilot2 import run2
    from pilot2.arms2 import A3DoT2
    from pilot import score as SC
    spec = {name: (cls, kw, worlds) for name, cls, kw, worlds in run2.ARMS}
    assert spec["A3+DoTn"] == (A3, {"forget_mode": "dot"}, ("F",)) and run2.ALIAS_C["A3+DoTn"] == "A3n"
    assert "A3+DoTn" in SC.ARMS and spec["A3+DoT"][0] is A3DoT2           # exposure DoT kept under its own name
    emb, llm = HashEmbedder(), LLM(tmp_path / "calls", fake=fake_writer)
    arms = {"n": A3("A3+DoTn", "F", tmp_path / "n", llm, emb, forget_mode="dot"),
            "x": A3DoT2("A3+DoT", "F", tmp_path / "x", llm, emb)}
    for a in arms.values():
        for i, s in enumerate(sorted(SESS)):
            a._write(s, SESS[s], T[s], "ingest")
            if i + 1 in (4, 8):
                a.refresh("ingest")
    narrow_touched = {n for n, x in arms["n"].notes.items() if "s03" in x["sources"]}
    exposed = {n for n in arms["x"].notes if "s03" in arms["x"]._prov(n)}
    rn = arms["n"].forget("s03", "2031", SESS["s03"]); rx = arms["x"].forget("s03", "2031", SESS["s03"])
    assert narrow_touched and set(rn["notes_deleted"]) == narrow_touched                 # exactly writer-touched notes
    assert set(rx["notes_deleted"]) == exposed and exposed >= narrow_touched
    assert len(exposed) > len(narrow_touched)              # fixture distinguishes the two arms


# ---------------------------------------------------------------- F10: real runs must match the freeze
def test_F10_verify_frozen_gate(tmp_path):
    import shutil
    from pilot.freeze import verify_frozen
    from pilot2 import freeze3
    root = Path(__file__).parents[2]
    fz = freeze3.build("FROZEN")
    sim = tmp_path / "root"
    for d in ("pilot", "pilot2", "eng-pin"):
        shutil.copytree(root / d, sim / d, ignore=shutil.ignore_patterns("__pycache__", "runs", "*.npy", "*.onnx"))
    (sim / "runs").mkdir(); (sim / "data").mkdir()
    for f in ("anchors-7240240.npy", "anchors-7240240.json"):
        shutil.copy(root / "runs" / f, sim / "runs" / f)
    for rel in list(fz["probe_files"]) + list(fz["stream_manifests"]):
        shutil.copytree(root / "data" / rel.split("/")[0], sim / "data" / rel.split("/")[0], dirs_exist_ok=True)
    (sim / "F.json").write_text(json.dumps(fz))
    arms = fz["arms"]
    assert verify_frozen("F.json", 2000, freeze3.STREAMS, arms=arms, root=sim) == fz["code_digest"]
    for bad in (dict(B=1000), dict(streams=freeze3.STREAMS[:2]), dict(arms=arms[:-1])):
        kw = dict(B=2000, streams=freeze3.STREAMS, arms=arms) | bad
        with pytest.raises(ValueError):
            verify_frozen("F.json", kw["B"], kw["streams"], arms=kw["arms"], root=sim)
    sess = sorted((sim / "data" / "stream-7240241" / "sessions").glob("*.md"))[0]       # nested manifest member
    orig = sess.read_bytes(); sess.write_bytes(orig + b" ")
    with pytest.raises(ValueError, match="Manifest member"):
        verify_frozen("F.json", 2000, freeze3.STREAMS, arms=arms, root=sim)
    sess.write_bytes(orig)
    (sim / "eng-pin" / "gen" / "zz_new.py").write_text("x = 1\n")                         # unlisted eng-pin file
    with pytest.raises(ValueError, match="digest"):
        verify_frozen("F.json", 2000, freeze3.STREAMS, arms=arms, root=sim)
    (sim / "eng-pin" / "gen" / "zz_new.py").unlink()
    (sim / "D.json").write_text(json.dumps(fz | {"status": "DRAFT"}))
    with pytest.raises(ValueError, match="DRAFT"):
        verify_frozen("D.json", 2000, freeze3.STREAMS, arms=arms, root=sim)
    for drv, name in (("pilot/run.py", "PILOT-FREEZE.json"), ("pilot2/run2.py", "PILOT3-FREEZE.json")):
        src = (root / drv).read_text()
        assert f'verify_frozen("{name}"' in src and '"freeze_digest": freeze_digest' in src
