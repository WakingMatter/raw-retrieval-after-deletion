"""gen_long: long-history fork of the pinned eng-pin generator (PREDICTION-AND-DESIGN.md §2). Never edits eng-pin.

    python3 -m e4.gen_long --seed S --out DIR --L 4 --chain 3

It imports eng-pin's `gen` package read-only and, only when (L, CHAIN_LEN) != (1, 1), rebinds module globals at
runtime in this process:
  * N_SESSIONS = 60*L, HORIZON_DAYS = 90*L, TARGET_STREAM_TOKENS = 80_000*L (per-session size and the per-session
    distractor share are unchanged, so a long stream is L back-to-back eng-pin-sized quarters);
  * session ids are 3-digit (s000..s239) so lexical order == numeric order;
  * schedule(): the session-index literals of eng-pin's schedule() are scaled by L (assert windows 28/51, change
    windows 58/56/45/55, horizon 60, derived window 2..60, delete window 4..49, forget cap 59), and every
    SUPERSEDE-explicit / SUPERSEDE-implicit key gets CHAIN_LEN successive changes, each to a value not held before
    (so AGG counts and CURRENT histories grow with CHAIN_LEN). Spacing >= 3 sessions between changes, as eng-pin.
At (1, 1) the scheduled RNG draws are exactly eng-pin's (same order, same ranges) and nothing is patched; the
regression test (e4/test_gen_long.py) asserts byte-identical output on 3 seeds.
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
from .paths import ENG_PIN

if str(ENG_PIN) not in sys.path:
    sys.path.insert(0, str(ENG_PIN))
import gen.common as C            # noqa: E402
import gen.gen_stream as G        # noqa: E402
from gen.gen_stream import (Ev, N_BAIT_SLOTS, N_KEYS, RESTATE_FRACTION, SHARES, TYPE_SLOTS, _ev,  # noqa: E402
                            target_count, value_pool)
from gen.vocab import DERIVED_SLOTS  # noqa: E402

GEN_LONG_VERSION = "gen_long-1"
_ORIG = {"session_id": C.session_id, "schedule": G.schedule}


def _sid3(i: int) -> str:
    return f"s{i:03d}"


def make_schedule(L: int, CHAIN: int):
    S = lambda x: x * L  # noqa: E731  (scale a session-index literal)
    H = S(60)

    def schedule(world: dict, rng):
        keys = world["keys"]
        base_keys = sorted(k for k, v in keys.items() if v["kind"] == "base")
        order = list(base_keys)
        rng.shuffle(order)
        counts = {name: target_count(SHARES[name][0], N_KEYS)
                  for name in ("SUPERSEDE-explicit", "SUPERSEDE-implicit", "RETRACT", "TRANSIENT", "RETURN")}
        ctype = {}
        pos = 0
        for name in ("SUPERSEDE-explicit", "SUPERSEDE-implicit", "RETRACT", "TRANSIENT", "RETURN"):
            for k in order[pos:pos + counts[name]]:
                ctype[k] = name
            pos += counts[name]
        n_reread = target_count(SHARES["RE-READ"][0], N_KEYS)
        return_keys = sorted(k for k, c in ctype.items() if c == "RETURN")
        reread_keys = set(rng.sample(return_keys, n_reread))
        bait_cands = []
        for ea, eb in world["pairs"]:
            for slot in TYPE_SLOTS[world["entities"][ea]["type"]]:
                ka, kb = world["key_of"].get((ea, slot)), world["key_of"].get((eb, slot))
                if ka and kb:
                    bait_cands.append((ka, kb))
        rng.shuffle(bait_cands)
        bait, used = [], set()
        for ka, kb in bait_cands:
            if ka in used or kb in used:
                continue
            bait.append((ka, kb))
            used.update((ka, kb))
            if len(bait) == N_BAIT_SLOTS:
                break
        assert len(bait) == N_BAIT_SLOTS
        evs: list[Ev] = []
        uid = [0]

        def nid():
            uid[0] += 1
            return f"u{uid[0]:05d}"

        assert_sess = {}
        for k in base_keys:
            assert_sess[k] = rng.randrange(0, S(28)) if k in ctype else rng.randrange(0, S(51))
        for ka, kb in bait:
            assert_sess[kb] = assert_sess[ka] = min(assert_sess[ka], assert_sess[kb])
        init_val = {}
        for k in base_keys:
            init_val[k] = rng.choice(value_pool(world, k))
        for ka, kb in bait:
            if init_val[kb] == init_val[ka]:
                init_val[kb] = rng.choice([v for v in value_pool(world, kb) if v != init_val[ka]])

        def other(k, *exclude):
            return rng.choice([v for v in value_pool(world, k) if v not in exclude])

        bait_group = {}
        for gi, (ka, kb) in enumerate(bait):
            bait_group[ka] = bait_group[kb] = f"bait{gi}"
        set_sessions = {}
        for k in base_keys:
            a = assert_sess[k]
            A = init_val[k]
            e0 = _ev(world, nid(), a, "ASSERT", "set", k, A, {"change_event": False, "marker": None})
            if k in bait_group:
                e0["render_group"] = bait_group[k]
            evs.append(e0)
            hist = [(a, A)]
            c = ctype.get(k)
            if c in ("SUPERSEDE-explicit", "SUPERSEDE-implicit"):
                prev, held = a, [A]
                for i in range(CHAIN):          # CHAIN_LEN successive changes; i = 0 is eng-pin's single change
                    j = rng.randrange(prev + 3, S(58) - 3 * (CHAIN - 1 - i))
                    B = other(k, *held)
                    et = "SUPERSEDE_EXPLICIT" if c == "SUPERSEDE-explicit" else "SUPERSEDE_IMPLICIT"
                    evs.append(_ev(world, nid(), j, et, "set", k, B,
                                   {"change_event": True, "marker": "explicit" if c == "SUPERSEDE-explicit" else None,
                                    "prose_marker": c == "SUPERSEDE-explicit"}))
                    hist.append((j, B))
                    prev = j
                    held.append(B)
            elif c == "RETRACT":
                j = rng.randrange(a + 3, S(58))
                evs.append(_ev(world, nid(), j, "RETRACT", "withdraw", k, None, {"change_event": True, "marker": "retract"}))
                hist.append((j, None))
            elif c == "TRANSIENT":
                j = rng.randrange(a + 2, S(56))
                m = j + 1 + rng.randrange(2)
                B = other(k, A)
                tset = _ev(world, nid(), j, "TRANSIENT_SET", "set", k, B, {"change_event": True, "marker": "correction"})
                evs.append(tset)
                evs.append(_ev(world, nid(), m, "TRANSIENT_VOID", "set", k, A,
                               {"change_event": True, "marker": "withdraw-correction", "voids_uid": tset["uid"]}))
                hist += [(j, B), (m, A)]
            elif c == "RETURN":
                j = rng.randrange(a + 3, S(45))
                m = rng.randrange(j + 3, S(55))
                B = other(k, A)
                chg = _ev(world, nid(), j, "SUPERSEDE_EXPLICIT", "set", k, B,
                          {"change_event": True, "marker": "explicit", "prose_marker": True, "return_leg": "out"})
                evs.append(chg)
                evs.append(_ev(world, nid(), m, "RETURN", "set", k, A,
                               {"change_event": True, "marker": "revert", "revert_of_uid": e0["uid"],
                                "reverts_change_uid": chg["uid"]}))
                hist += [(j, B), (m, A)]
                if k in reread_keys:
                    r = rng.randrange(m + 2, H)
                    evs.append(_ev(world, nid(), r, "RE_READ", "observe", k, B,
                                   {"change_event": False, "marker": None, "restates_retired_uid": chg["uid"]}))
            set_sessions[k] = hist
        n_restate = int(len(base_keys) * RESTATE_FRACTION)
        for k in rng.sample(base_keys, n_restate):
            hist = set_sessions[k]
            windows = []
            for i, (s, v) in enumerate(hist):
                nxt = hist[i + 1][0] if i + 1 < len(hist) else H
                if v is not None and nxt - s >= 2:
                    windows.append((s + 1, nxt, v))
            if windows:
                lo, hi, v = rng.choice(windows)
                evs.append(_ev(world, nid(), rng.randrange(lo, hi), "RESTATE", "observe", k, v,
                               {"change_event": False, "marker": None}))

        def value_at_session(k, s):
            cur, defined = None, False
            for (si, v) in set_sessions.get(k, []):
                if si < s:
                    cur, defined = v, True
            return cur if defined else None

        touched = {}
        for e in evs:
            touched.setdefault(e["key"], set()).add(e["session"])
        accepted = 0
        for (eid, dslot) in world["derived_candidates"]:
            if accepted == world["n_derived"]:
                break
            _etype, ref_slot, attr_slot = DERIVED_SLOTS[dslot]
            ref_key = world["key_of"][(eid, ref_slot)]
            attr_by_val = {}
            for pname in world["person_names"]:
                pk = world["key_of"].get((world["eid_by_name"][pname], attr_slot))
                if pk:
                    attr_by_val[pname] = pk
            ok = []
            for s in range(2, H):
                P = value_at_session(ref_key, s)
                if P is None or s in touched.get(ref_key, set()):
                    continue
                ak = attr_by_val.get(P)
                if ak is None or s in touched.get(ak, set()):
                    continue
                v = value_at_session(ak, s)
                if v is not None:
                    ok.append((s, v, ak))
            if not ok:
                continue
            dkey = f"K{len(world['keys']):03d}"
            world["keys"][dkey] = {"kind": "derived", "subject": eid, "subject_name": world["entities"][eid]["name"],
                                   "slot": dslot, "ref_key": ref_key, "attr_slot": attr_slot,
                                   "attr_key_by_value": attr_by_val}
            world["key_of"][(eid, dslot)] = dkey
            s, v, ak = rng.choice(ok)
            evs.append(_ev(world, nid(), s, "ASSERT", "observe", dkey, v,
                           {"change_event": False, "marker": None, "derived": True}, parents=[ref_key, ak]))
            accepted += 1
        assert accepted == world["n_derived"], "not enough schedulable derived keys"
        assert len(world["keys"]) == N_KEYS
        n_delete = target_count(SHARES["DELETE"][0], G.N_SESSIONS)
        by_sess = {}
        for e in evs:
            by_sess.setdefault(e["session"], []).append(e)
        sole = {k for k, v in touched.items() if len(v) == 1 and keys.get(k, {}).get("kind") == "base"}
        protected = set()
        for e in evs:
            if e["type"] == "RE_READ":
                protected.add(e["session"])
                ch = [x for x in evs if x["uid"] == e["provenance"]["restates_retired_uid"]][0]
                protected.add(ch["session"])
                rv = [x for x in evs if x["key"] == e["key"] and x["type"] == "RETURN"][0]
                protected.add(rv["session"])
        cands = [s for s in range(4, S(49)) if s not in protected
                 and any(e["key"] in sole and e["op"] == "set" for e in by_sess.get(s, []))
                 and sum(1 for e in by_sess.get(s, []) if e["op"] == "set") >= 2]
        deletes = sorted(rng.sample(cands, n_delete))
        forget_at = []
        for d in deletes:
            f = min(H - 1, d + 3 + rng.randrange(6))
            while f in forget_at:
                f += 1
            forget_at.append(f)
        meta = {"ctype": ctype, "reread_keys": sorted(reread_keys), "bait": bait, "deletes": deletes,
                "forget_at": forget_at, "set_sessions": set_sessions}
        return evs, meta
    return schedule


def configure(L: int = 1, chain: int = 1) -> None:
    """Rebind eng-pin module globals for (L, CHAIN_LEN) in this process. (1, 1) restores eng-pin exactly."""
    n, h, t = 60 * L, 90 * L, 80_000 * L
    for mod in (C, G):
        mod.N_SESSIONS, mod.TARGET_STREAM_TOKENS = n, t
    C.HORIZON_DAYS = h
    G.PER_SESSION_DISTRACTOR_TOKENS = int(t * 0.30 / n)
    if (L, chain) == (1, 1):
        C.session_id = G.session_id = _ORIG["session_id"]
        G.schedule = _ORIG["schedule"]
    else:
        C.session_id = G.session_id = _sid3
        G.schedule = make_schedule(L, chain)


def generate(seed: int, out: str | Path, L: int = 1, chain: int = 1) -> dict:
    configure(L, chain)
    try:
        m = G.generate(seed, out)
    finally:
        configure(1, 1)
    if (L, chain) != (1, 1):        # MANIFEST.json is not in its own file-hash list; correct the eng-pin literal
        m["params"]["horizon_days"] = 90 * L
        m["gen_long"] = {"version": GEN_LONG_VERSION, "L": L, "CHAIN_LEN": chain, "session_id_digits": 3}
        C.write_json(Path(out) / "MANIFEST.json", m)
    return m


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--L", type=int, default=1)
    ap.add_argument("--chain", type=int, default=1)
    a = ap.parse_args(argv)
    m = generate(a.seed, a.out, a.L, a.chain)
    bad = [r for r in m["event_share_table"] if not r["within_tolerance"]]
    print(json.dumps({"seed": a.seed, "L": a.L, "chain": a.chain, "tokens": m["tokens"]["total"],
                      "sessions": len(m["sessions"]), "share_violations": [r["event"] for r in bad]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
