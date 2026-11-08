#!/usr/bin/env python3
"""Synthetic stream generator (prereg §5.1; ENG-BUILD-BRIEF §3).

    python3 gen/gen_stream.py --seed S --out DIR

Deterministic from --seed: the same seed gives byte-identical output (no wall
clock, no environment, no unordered iteration). Outputs in DIR:

    events.jsonl       the ledger / event script (one row per event, ledger order)
    gold.jsonl         validity intervals per view, computed from events.jsonl only
    deps.json          derived->parent and fact->source-session edges, per view,
                       plus the precomputed deletion closure per session
    warmup.jsonl       60 SPARK warm-up tasks (prereg §5.4; see warmup_author.py)
    world.json         entities, keys, look-alike pairs, bait slots (generator metadata)
    sessions/sNN.md    rendered prose (the only thing an arm ever sees)
    render_trace.jsonl per-segment kind/tokens (generator metadata; never shown to arms)
    MANIFEST.json      seed, parameters, event-share table, token counts, file sha256s

Probes are NOT generated here: prereg §5.3 says they are authored from the
ledger after the instrument freeze (gen/probe_author.py).
"""
from __future__ import annotations

import argparse
import random
import sys
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gen import ledger  # noqa: E402
from gen.common import (GENERATOR_VERSION, N_SESSIONS, PREREG_SHA256, TARGET_STREAM_TOKENS,  # noqa: E402
                        add_minutes, est_tokens, manifest_files, session_id, session_start, sub_seed,
                        write_json, write_jsonl, write_text)
from gen.render import TemplateRenderer  # noqa: E402
from gen.vocab import (CONFIG_TWIN_PREFIX, CONFIGS, DERIVED_SLOTS, DISTRACTOR_KINDS,  # noqa: E402
                       MANDATORY_SLOTS, PERSON_FIRST, PERSON_LAST_TWIN, POOLS, PROJECT_TWIN_SUFFIX,
                       PROJECTS, REF_SLOTS, SERVICE_TWIN_SUFFIX, SERVICES, TYPE_SLOTS, T)

# --------------------------------------------------------------------------- §5.1 constants
# Mirrors the prereg §5.1 table exactly; tests/test_event_shares.py parses the
# frozen prereg text and asserts this dict equals it.
SHARES = {
    "ASSERT": ("1.00", "keys"),
    "SUPERSEDE-explicit": ("0.25", "keys"),
    "SUPERSEDE-implicit": ("0.10", "keys"),
    "RETRACT": ("0.05", "keys"),
    "TRANSIENT": ("0.05", "keys"),
    "RETURN": ("0.05", "keys"),
    "RE-READ": ("0.03", "keys"),
    "DELETE": ("0.03", "sessions"),
    "DERIVED": ("0.15", "keys"),
    "DISTRACTOR": ("0.30", "tokens"),
}
N_ENTITIES = 40
N_KEYS = 150                 # "about 150 (subject, slot) keys"
N_LOOKALIKE_PAIRS = 8
N_BAIT_SLOTS = 6
DISTRACTOR_TOL = 0.03        # tolerance on the "about 30% of tokens" share (design choice, see README)
RESTATE_FRACTION = 0.25      # share of base keys that get one extra same-value restatement (evidence redundancy)
PER_SESSION_DISTRACTOR_TOKENS = int(TARGET_STREAM_TOKENS * 0.30 / N_SESSIONS)


def target_count(share: str, n: int) -> int:
    return int((Decimal(share) * n).quantize(Decimal(1), rounding=ROUND_HALF_UP))


# --------------------------------------------------------------------------- world

def build_world(rng: random.Random) -> dict:
    lasts = sorted(PERSON_LAST_TWIN)
    rng.shuffle(lasts)
    firsts = list(PERSON_FIRST)
    rng.shuffle(firsts)
    persons = [f"{firsts[i]} {lasts[i]}" for i in range(11)]
    person_twins = [(persons[i], f"{firsts[i]} {PERSON_LAST_TWIN[lasts[i]]}") for i in range(3)]
    projects = rng.sample(PROJECTS, 8)
    project_twins = [(projects[i], projects[i] + PROJECT_TWIN_SUFFIX) for i in range(2)]
    services = rng.sample(SERVICES, 8)
    service_twins = [(services[i], services[i] + SERVICE_TWIN_SUFFIX) for i in range(2)]
    configs = rng.sample(CONFIGS, 5)
    config_twins = [(configs[i], CONFIG_TWIN_PREFIX + configs[i]) for i in range(1)]

    names_by_type = {
        "person": persons + [b for _, b in person_twins],
        "project": projects + [b for _, b in project_twins],
        "service": services + [b for _, b in service_twins],
        "config": configs + [b for _, b in config_twins],
    }
    entities = {}
    eid_by_name = {}
    i = 0
    for etype in ("person", "project", "service", "config"):
        for name in names_by_type[etype]:
            eid = f"E{i:02d}"
            entities[eid] = {"id": eid, "type": etype, "name": name, "twin": None}
            eid_by_name[name] = eid
            i += 1
    assert len(entities) == N_ENTITIES
    pairs = []
    for a, b in person_twins + project_twins + service_twins + config_twins:
        ea, eb = eid_by_name[a], eid_by_name[b]
        entities[ea]["twin"] = eb
        entities[eb]["twin"] = ea
        pairs.append([ea, eb])
    assert len(pairs) == N_LOOKALIKE_PAIRS

    n_derived = target_count(SHARES["DERIVED"][0], N_KEYS)
    n_base = N_KEYS - n_derived
    cands = []
    for eid in sorted(entities):
        for slot in TYPE_SLOTS[entities[eid]["type"]]:
            cands.append((eid, slot))
    droppable = [c for c in cands if c[1] not in MANDATORY_SLOTS and entities[c[0]]["twin"] is None]
    drop = set(rng.sample(droppable, len(cands) - n_base))
    base = [c for c in cands if c not in drop]
    absent_pairs = sorted(drop)

    dcands = []
    for eid in sorted(entities):
        for dslot, (etype, _ref, _attr) in DERIVED_SLOTS.items():
            if entities[eid]["type"] == etype:
                dcands.append((eid, dslot))
    rng.shuffle(dcands)  # accepted in order later until n_derived are schedulable

    keys = {}
    for k, (eid, slot) in enumerate(base):
        keys[f"K{k:03d}"] = {"kind": "base", "subject": eid, "subject_name": entities[eid]["name"], "slot": slot}
    key_of = {(v["subject"], v["slot"]): k for k, v in keys.items()}
    person_names = names_by_type["person"]
    return {
        "entities": entities, "pairs": pairs, "keys": keys, "key_of": key_of,
        "derived_candidates": dcands, "n_derived": n_derived, "absent_pairs": absent_pairs,
        "person_names": person_names, "eid_by_name": eid_by_name,
    }


def value_pool(world: dict, key: str) -> list[str]:
    k = world["keys"][key]
    slot = k["slot"]
    if slot in REF_SLOTS:
        return list(world["person_names"])
    if slot == "repo_name":
        slug = k["subject_name"].lower().replace(" ", "-")
        return [p.format(p=slug) for p in POOLS["repo_name"]]
    return list(POOLS[slot])


# --------------------------------------------------------------------------- schedule

class Ev(dict):
    """Event under construction (uid is temporary; ids are assigned after timing)."""


def _ev(world, uid, sess, etype, op, key, value, prov=None, **extra) -> Ev:
    k = world["keys"][key] if key else None
    e = Ev(uid=uid, session=sess, type=etype, op=op, key=key,
           subject=k["subject"] if k else None, subject_name=k["subject_name"] if k else None,
           slot=k["slot"] if k else None, value=value, provenance=prov or {}, rendered=True,
           scripted_literals=[])
    e.update(extra)
    return e


def schedule(world: dict, rng: random.Random) -> tuple[list[Ev], dict]:
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

    # misattribution bait: (key, twin key) on the same slot of a look-alike pair
    bait_cands = []
    for ea, eb in world["pairs"]:
        for slot in TYPE_SLOTS[world["entities"][ea]["type"]]:
            ka, kb = world["key_of"].get((ea, slot)), world["key_of"].get((eb, slot))
            if ka and kb:
                bait_cands.append((ka, kb))
    rng.shuffle(bait_cands)
    bait = []
    used = set()
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
        assert_sess[k] = rng.randrange(0, 28) if k in ctype else rng.randrange(0, 51)
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

    set_sessions = {}  # key -> list of (session index, value or None)
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
            j = rng.randrange(a + 3, 58)
            B = other(k, A)
            et = "SUPERSEDE_EXPLICIT" if c == "SUPERSEDE-explicit" else "SUPERSEDE_IMPLICIT"
            evs.append(_ev(world, nid(), j, et, "set", k, B,
                           {"change_event": True, "marker": "explicit" if c == "SUPERSEDE-explicit" else None,
                            "prose_marker": c == "SUPERSEDE-explicit"}))
            hist.append((j, B))
        elif c == "RETRACT":
            j = rng.randrange(a + 3, 58)
            evs.append(_ev(world, nid(), j, "RETRACT", "withdraw", k, None, {"change_event": True, "marker": "retract"}))
            hist.append((j, None))
        elif c == "TRANSIENT":
            j = rng.randrange(a + 2, 56)
            m = j + 1 + rng.randrange(2)
            B = other(k, A)
            tset = _ev(world, nid(), j, "TRANSIENT_SET", "set", k, B, {"change_event": True, "marker": "correction"})
            evs.append(tset)
            evs.append(_ev(world, nid(), m, "TRANSIENT_VOID", "set", k, A,
                           {"change_event": True, "marker": "withdraw-correction", "voids_uid": tset["uid"]}))
            hist += [(j, B), (m, A)]
        elif c == "RETURN":
            j = rng.randrange(a + 3, 45)
            m = rng.randrange(j + 3, 55)
            B = other(k, A)
            chg = _ev(world, nid(), j, "SUPERSEDE_EXPLICIT", "set", k, B,
                      {"change_event": True, "marker": "explicit", "prose_marker": True, "return_leg": "out"})
            evs.append(chg)
            evs.append(_ev(world, nid(), m, "RETURN", "set", k, A,
                           {"change_event": True, "marker": "revert", "revert_of_uid": e0["uid"],
                            "reverts_change_uid": chg["uid"]}))
            hist += [(j, B), (m, A)]
            if k in reread_keys:
                r = rng.randrange(m + 2, 60)
                evs.append(_ev(world, nid(), r, "RE_READ", "observe", k, B,
                               {"change_event": False, "marker": None, "restates_retired_uid": chg["uid"]}))
        set_sessions[k] = hist

    # restatements: same value, later session, no change event (extra evidence)
    n_restate = int(len(base_keys) * RESTATE_FRACTION)
    for k in rng.sample(base_keys, n_restate):
        hist = set_sessions[k]
        windows = []
        for i, (s, v) in enumerate(hist):
            nxt = hist[i + 1][0] if i + 1 < len(hist) else 60
            if v is not None and nxt - s >= 2:
                windows.append((s + 1, nxt, v))
        if windows:
            lo, hi, v = rng.choice(windows)
            evs.append(_ev(world, nid(), rng.randrange(lo, hi), "RESTATE", "observe", k, v,
                           {"change_event": False, "marker": None}))

    # derived keys
    def value_at_session(k, s):
        cur = None
        defined = False
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
        for s in range(2, 60):
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

    # DELETE: forget whole source sessions (3% of sessions)
    n_delete = target_count(SHARES["DELETE"][0], N_SESSIONS)
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
    cands = [s for s in range(4, 49) if s not in protected
             and any(e["key"] in sole and e["op"] == "set" for e in by_sess.get(s, []))
             and sum(1 for e in by_sess.get(s, []) if e["op"] == "set") >= 2]
    deletes = sorted(rng.sample(cands, n_delete))
    forget_at = []
    for d in deletes:
        f = min(59, d + 3 + rng.randrange(6))
        while f in forget_at:
            f += 1
        forget_at.append(f)
    meta = {"ctype": ctype, "reread_keys": sorted(reread_keys), "bait": bait, "deletes": deletes,
            "forget_at": forget_at, "set_sessions": set_sessions}
    return evs, meta


def add_distractors(world: dict, evs: list[Ev], rng: random.Random) -> list[Ev]:
    used_vals = {}
    for e in evs:
        if e["key"] and e["value"] is not None:
            used_vals.setdefault(e["key"], set()).add(e["value"])
    base_keys = sorted(k for k, v in world["keys"].items() if v["kind"] == "base")
    out = []
    n = 0
    for s in range(N_SESSIONS):
        tokens = 0
        while tokens < PER_SESSION_DISTRACTOR_TOKENS:
            k = rng.choice(base_keys)
            kind = rng.choice(DISTRACTOR_KINDS)
            pool = [v for v in value_pool(world, k) if v not in used_vals.get(k, set())]
            if not pool:
                continue
            v = rng.choice(pool)
            n += 1
            e = _ev(world, f"x{n:05d}", s, "DISTRACTOR", "none", k, v, {"change_event": False})
            e["distractor_kind"] = kind
            text = T[e["slot"]][kind].format(s=e["subject_name"], v=v)
            tokens += est_tokens(text)
            out.append(e)
    return out


# --------------------------------------------------------------------------- timing / ids

def finalize(world: dict, evs: list[Ev], meta: dict, rng: random.Random) -> tuple[list[dict], list[dict]]:
    """Order items inside sessions, assign times and final ids. Returns (events, session scripts)."""
    starts = []
    for i in range(N_SESSIONS):
        starts.append(session_start(i, 9 + rng.randrange(8), rng.randrange(60)))
    by_sess = {}
    for e in evs:
        by_sess.setdefault(e["session"], []).append(e)
    timed = []
    scripts = []
    for i in range(N_SESSIONS):
        items = []
        groups = {}
        for e in sorted(by_sess.get(i, []), key=lambda x: x["uid"]):
            g = e.get("render_group")
            if g:
                if g not in groups:
                    groups[g] = {"kind": "fact", "events": []}
                    items.append(groups[g])
                groups[g]["events"].append(e)
            else:
                items.append({"kind": "distractor" if e["type"] == "DISTRACTOR" else "fact", "events": [e]})
        rng.shuffle(items)
        minute = 1
        for it in items:
            for e in it["events"]:
                e["t"] = add_minutes(starts[i], minute)
                minute += 1
            minute += 1
        scripts.append({"session": session_id(i), "index": i, "t_start": starts[i], "items": items})
        timed.extend(e for it in items for e in it["events"])
    for f_idx, (d, f) in enumerate(zip(meta["deletes"], meta["forget_at"])):
        e = _ev(world, f"z{f_idx}", None, "DELETE", "forget", None, None,
                {"change_event": True, "channel": "harness_forget"})
        e["forget_session"] = session_id(d)
        e["t"] = add_minutes(starts[f], -120)
        e["rendered"] = False
        timed.append(e)
    timed.sort(key=lambda e: (e["t"], e["uid"]))
    uid2id = {}
    for n, e in enumerate(timed, start=1):
        uid2id[e["uid"]] = f"e{n:04d}"
    t_of = {e["uid"]: e["t"] for e in timed}
    out = []
    for n, e in enumerate(timed, start=1):
        row = dict(e)
        row["id"] = uid2id[e["uid"]]
        row["seq"] = n
        if row["session"] is not None:
            row["session"] = session_id(row["session"])
        prov = dict(row["provenance"])
        for fld in ("voids_uid", "revert_of_uid", "reverts_change_uid", "restates_retired_uid"):
            if fld in prov:
                ref = prov.pop(fld)
                prov[fld[:-4]] = uid2id[ref]
                prov[fld[:-4] + "_t"] = t_of[ref]
        row["provenance"] = prov
        row.pop("uid")
        out.append(row)
    id_by_obj = {}
    for e, row in zip(timed, out):
        id_by_obj[id(e)] = row
    for sc in scripts:
        for k, it in enumerate(sc["items"]):
            it["item_id"] = f"{sc['session']}-i{k:02d}"
            it["events"] = [id_by_obj[id(e)] for e in it["events"]]
    return out, scripts


# --------------------------------------------------------------------------- share table

def share_table(world_keys: dict, events: list[dict], trace: list[dict] | None, n_sessions: int = N_SESSIONS) -> list[dict]:
    n_keys = len(world_keys)
    keys_with = {}
    for e in events:
        if e.get("key"):
            keys_with.setdefault(e["type"], set()).add(e["key"])
    count = {
        "ASSERT": len(keys_with.get("ASSERT", set())),
        "SUPERSEDE-explicit": len(keys_with.get("SUPERSEDE_EXPLICIT", set())
                                  - {e["key"] for e in events if e["provenance"].get("return_leg")}),
        "SUPERSEDE-implicit": len(keys_with.get("SUPERSEDE_IMPLICIT", set())),
        "RETRACT": len(keys_with.get("RETRACT", set())),
        "TRANSIENT": len(keys_with.get("TRANSIENT_SET", set())),
        "RETURN": len(keys_with.get("RETURN", set())),
        "RE-READ": len(keys_with.get("RE_READ", set())),
        "DERIVED": sum(1 for v in world_keys.values() if v["kind"] == "derived"),
        "DELETE": len({e["forget_session"] for e in events if e["type"] == "DELETE"}),
    }
    rows = []
    for name, (share, unit) in SHARES.items():
        if unit == "tokens":
            if trace is None:
                continue
            tot = sum(s["tokens"] for s in trace)
            dis = sum(s["tokens"] for s in trace if s["kind"] == "distractor")
            got = dis / tot if tot else 0.0
            rows.append({"event": name, "unit": unit, "prereg_share": float(share), "count": dis, "denominator": tot,
                         "share": round(got, 4), "tolerance": DISTRACTOR_TOL,
                         "within_tolerance": abs(got - float(share)) <= DISTRACTOR_TOL})
            continue
        denom = n_keys if unit == "keys" else n_sessions
        exact = float(Decimal(share) * denom)
        rows.append({"event": name, "unit": unit, "prereg_share": float(share), "count": count[name],
                     "denominator": denom, "exact_target": exact, "share": round(count[name] / denom, 4),
                     "tolerance": 1, "within_tolerance": abs(count[name] - exact) <= 1})
    return rows


# --------------------------------------------------------------------------- driver

def build_ledger(seed: int, with_distractors: bool = True):
    """World + timed events + session scripts (no rendering)."""
    rng_w = random.Random(sub_seed(seed, "world"))
    world = build_world(rng_w)
    rng_s = random.Random(sub_seed(seed, "schedule"))
    evs, meta = schedule(world, rng_s)
    if with_distractors:
        evs = evs + add_distractors(world, evs, random.Random(sub_seed(seed, "distractors")))
    events, scripts = finalize(world, evs, meta, random.Random(sub_seed(seed, "timing")))
    return world, events, scripts, meta


def world_json(world: dict, meta: dict) -> dict:
    keys = {}
    for k, v in world["keys"].items():
        kv = dict(v)
        keys[k] = kv
    return {
        "entities": world["entities"], "pairs": world["pairs"], "keys": keys,
        "absent_pairs": [list(p) for p in world["absent_pairs"]],
        "bait_slots": [list(b) for b in meta["bait"]],
        "change_type": dict(sorted(meta["ctype"].items())),
        "reread_keys": meta["reread_keys"],
    }


def deps_json(views: list[dict], world: dict, session_ids: list[str]) -> dict:
    out = {"views": [], "derived_key_parents": {}}
    for k, v in sorted(world["keys"].items()):
        if v["kind"] == "derived":
            out["derived_key_parents"][k] = {"ref_key": v["ref_key"], "attr_slot": v["attr_slot"],
                                            "attr_key_by_value": v["attr_key_by_value"]}
    for v in views:
        d = ledger.deps_for_rows(v["rows"])
        live = [s for s in session_ids if s not in v["deleted_sessions"]]
        d["session_dependents"] = {s: ledger.closure(d, s) for s in live}
        d.update({k: v[k] for k in ("view", "view_from", "view_until", "deleted_sessions", "forget_event")})
        out["views"].append(d)
    return out


def generate(seed: int, out_dir: str | Path, renderer=None) -> dict:
    from gen.warmup_author import author_warmups  # local import: warm-up author depends on this module

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    world, events, scripts, meta = build_ledger(seed)
    renderer = renderer or TemplateRenderer(seed)
    people = [world["entities"][e]["name"] for e in sorted(world["entities"]) if world["entities"][e]["type"] == "person"]
    trace = []
    for sc in scripts:
        sc["people"] = people
        sc["target_tokens"] = TARGET_STREAM_TOKENS // N_SESSIONS
        r = renderer.render_session(sc)
        write_text(out / "sessions" / f"{sc['session']}.md", r["text"])
        for n, seg in enumerate(r["segments"]):
            trace.append({"session": sc["session"], "seg": n, "kind": seg["kind"], "event_ids": seg["event_ids"],
                          "tokens": seg["tokens"], "chars": seg["chars"]})
    views = ledger.compute_views(events, world["keys"])
    session_ids = [sc["session"] for sc in scripts]
    t_end = add_minutes(scripts[-1]["t_start"], 24 * 60)
    warm = author_warmups(seed, world["keys"], events, views, scripts)
    write_jsonl(out / "events.jsonl", events)
    write_jsonl(out / "gold.jsonl", ledger.gold_rows(views))
    write_json(out / "deps.json", deps_json(views, world, session_ids))
    write_jsonl(out / "warmup.jsonl", warm)
    write_json(out / "world.json", world_json(world, meta))
    write_jsonl(out / "render_trace.jsonl", trace)
    table = share_table(world["keys"], events, trace)
    total_tokens = sum(s["tokens"] for s in trace)
    manifest = {
        "generator": GENERATOR_VERSION, "kind": "synthetic", "seed": seed, "prereg_sha256": PREREG_SHA256,
        "renderer": getattr(renderer, "name", type(renderer).__name__),
        "params": {"n_entities": N_ENTITIES, "n_keys": N_KEYS, "n_lookalike_pairs": N_LOOKALIKE_PAIRS,
                   "n_bait_slots": N_BAIT_SLOTS, "n_sessions": N_SESSIONS, "horizon_days": 90,
                   "target_tokens": TARGET_STREAM_TOKENS, "restate_fraction": RESTATE_FRACTION,
                   "token_estimator": "ceil(chars/4)"},
        "t_start": scripts[0]["t_start"], "t_end": t_end,
        "views": [{k: v[k] for k in ("view", "view_from", "view_until", "deleted_sessions", "forget_event")} for v in views],
        "sessions": [{"session": sc["session"], "t_start": sc["t_start"], "source_group": sc["session"]} for sc in scripts],
        "tokens": {"total": total_tokens,
                   "distractor": sum(s["tokens"] for s in trace if s["kind"] == "distractor")},
        "event_share_table": table,
        "arm_visible": ["sessions/"],
        "files": manifest_files(out),
    }
    write_json(out / "MANIFEST.json", manifest)
    return manifest


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    m = generate(a.seed, a.out)
    bad = [r for r in m["event_share_table"] if not r["within_tolerance"]]
    print(f"seed={a.seed} tokens={m['tokens']['total']} files={len(m['files'])} share_violations={len(bad)}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
