"""Regression tests for Research decisions 3 (J2-07 bootstrap) and 4 (J2-13 frozen probe order). Offline only."""
import json, random, threading, time
from pathlib import Path


# ---------------------------------------------------------------- J2-07: hierarchical vs within-stream bootstrap
def _rows(n_streams=10, groups=3, per=2):
    rows = []
    for s in range(n_streams):
        for g in range(groups):
            for i in range(per):
                # every probe of stream s has the same value: all variance is BETWEEN streams
                rows.append({"seed": s, "probe_id": f"p{g}{i}", "deletion": f"{s}:g{g}", "d": float(s % 2)})
    return rows


def test_J207_hierarchical_resamples_streams_within_stream_does_not():
    from pilot.score import boot, boot_both
    rows = _rows()
    h = boot(rows, rows, lambda r: r["d"], lambda r: 0, n=2000, mode="hierarchical")
    w = boot(rows, rows, lambda r: r["d"], lambda r: 0, n=2000, mode="within_stream")
    assert h["est"] == w["est"] == 0.5
    assert h["resampling_unit"] == "stream_then_deletion" and w["resampling_unit"] == "deletion_within_fixed_stream"
    # streams fixed + constant values within stream -> the old CI collapses; the hierarchical CI sees stream variance
    assert w["degenerate"] and w["lo95"] == w["hi95"] == 0.5
    assert not h["degenerate"] and h["lo95"] < 0.5 < h["hi95"] and h["hi95"] - h["lo95"] > 0.3
    b = boot_both(rows, rows, lambda r: r["d"], lambda r: 0, n=2000)
    assert b["mode"] == "hierarchical" and b["lo95"] == h["lo95"] and b["within_stream"]["hi95"] == w["hi95"]
    # deterministic given the seed
    assert boot(rows, rows, lambda r: r["d"], lambda r: 0, n=2000)["lo95"] == h["lo95"]


def test_J207_within_stream_resamples_groups_and_keeps_them_whole():
    from pilot.score import boot
    rows = [{"seed": 0, "probe_id": f"g{g}p{i}", "deletion": f"0:g{g}", "d": float(g == 0)} for g in range(5) for i in range(4)]
    w = boot(rows, rows, lambda r: r["d"], lambda r: 0, n=4000, mode="within_stream")
    assert not w["degenerate"]
    assert w["lo95"] == 0.0     # whole groups: P(no draw of g0) = 0.8**5; a row bootstrap would give lo95 > 0


# ---------------------------------------------------------------- J2-13: frozen probe order, keyed answers
class _DB:
    def close_for_scan(self): pass
    def files(self): return []


class _FakeArm:
    """Records the submission order of terminal probes; sleeps random amounts so completion order is scrambled."""
    def __init__(self, name, jitter_seed):
        self.name = name; self.stats = {"calls": []}; self.poison_log = []; self.db = _DB()
        self.submitted = []; self._lk = threading.Lock(); self._rng = random.Random(jitter_seed)

    def ask(self, q, t, B, phase, ctx=None, **kw):
        with self._lk:
            self.submitted.append(ctx["probe"]); d = self._rng.random() * 0.02
        time.sleep(d)
        return {"answer": f"ans to {q}", "ok": True, "served": [], "assembled_est": 1}

    def derived_artifacts(self): return []


def _S():
    tg = [{"probe_id": f"s{i:02d}:R:DIRECT:K{i:03d}", "question": f"q{i}", "t_query": "T", "deleted_session": "s99",
           "variant": "DIRECT", "cls": "R"} for i in range(25)]
    return {"seed": 7240299, "sessions": [], "forgets": {}, "targets": tg, "probes": [{"question": "m", "t_query": "T", "category": "current"}],
            "canaries": {}, "deleted": [], "text": {}}


def test_J213_probe_order_frozen_seeded_and_answers_keyed(tmp_path):
    from pilot2 import run2
    S = _S()
    outs = []
    for jit in (1, 2):
        arm = _FakeArm("A6", jit)
        od = tmp_path / f"run{jit}"
        run2.run_instance(arm, "C", S, 2000, od, ())
        po = json.loads((od / "probe_order.json").read_text())
        expect, rs = run2.probe_order([{"probe_id": t["probe_id"]} for t in S["targets"]] + [{"probe_id": "mix:00:current"}], S["seed"], "A6", "C")
        assert po["seed"] == run2.PROBE_ORDER_SEED and po["rng_seed"] == rs and po["order"] == expect
        # submissions start in the frozen order (4 workers pick tasks FIFO)
        assert arm.submitted[:len(expect)] == expect
        ids = [json.loads(l)["probe_id"] for l in (od / "answers.jsonl").read_text().splitlines()]
        assert ids == sorted(ids) and set(ids) == set(expect)
        outs.append(((od / "answers.jsonl").read_text(), po["completion_order_diagnostic"]))
    # different completion orders, byte-identical keyed answers
    assert outs[0][0] == outs[1][0]
    assert expect != sorted(expect)
    # order differs by (arm, world) and is independent of input order
    qs = [{"probe_id": f"p{i}"} for i in range(30)]
    a = run2.probe_order(qs, 1, "A6", "F")[0]
    assert a == run2.probe_order(list(reversed(qs)), 1, "A6", "F")[0]
    assert a != run2.probe_order(qs, 1, "A6", "C")[0] and a != run2.probe_order(qs, 1, "A3n", "F")[0]


def test_J213_scoring_independent_of_answer_file_order(tmp_path):
    from pilot.tests.test_v13_fixes import make_run
    from pilot import score
    tg = [{"probe_id": f"s01:S:DIRECT:K{i:03d}", "cls": "S", "variant": "DIRECT", "deleted_session": "s01",
           "deleted_any": ["zzz"], "deleted_value": "zzz", "question": "q"} for i in range(6)]
    ans = {("A6", "F"): {t["probe_id"]: ("zzz" if i % 2 else "no") for i, t in enumerate(tg)},
           ("A6", "C"): {t["probe_id"]: ("zzz" if i % 3 == 0 else "no") for i, t in enumerate(tg)}}
    r1 = make_run(tmp_path, ans, targets=tg, probes=[])
    rows1 = score.score(r1)[1]
    for p in r1.rglob("answers.jsonl"):
        L = p.read_text().splitlines(); random.Random(3).shuffle(L); p.write_text("\n".join(L) + "\n")
    rows2 = score.score(r1)[1]
    key = lambda rs: sorted((r["arm"], r["probe_id"], r.get("recF"), r.get("recC")) for r in rs)
    assert key(rows1) == key(rows2)
