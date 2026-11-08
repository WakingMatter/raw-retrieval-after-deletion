"""Deletion-probe target authoring (v1.2 §P, v1.2.1 §3.3a). Ledger-only (+ session text for the
surviving-support check and canary injection); never reads arm outputs. Deterministic per stream seed."""
from __future__ import annotations
import random, re
from .common import ENG_PIN, DATA, sha  # noqa
from gen import ledger
from gen.probe_author import LedgerOnlyStream, SLOT_Q, DERIVED_Q, value_regex

ENUM = " List every value it has had at any time, including earlier, replaced or removed ones."
SLOT_PHRASE = {"office_city": "office city", "team_name": "team", "job_role": "role", "proj_lead": "lead",
               "proj_status": "status", "proj_deadline": "deadline", "repo_name": "code repository",
               "svc_owner": "owner", "host_region": "hosting region", "listen_port": "listening port",
               "db_engine": "database", "cfg_max_rps": "request-per-second ceiling", "cfg_timeout_ms": "timeout"}


def canaries(stream_dir, deleted, seed):
    """One made-up fact per deleted session (X class): '{name}'s badge code is QX-dddd-LL.'"""
    st = LedgerOnlyStream(stream_dir)
    rng = random.Random(int(sha(f"canary|{seed}")[:12], 16))
    ents = sorted(st.world["entities"].items())
    out = {}
    for sd in deleted:
        mentioned = sorted({e["subject"] for e in st.events if e.get("session") == sd and e.get("subject")
                            and e["subject"] in st.world["entities"]})
        eid = rng.choice(mentioned) if mentioned else rng.choice(ents)[0]
        name = st.world["entities"][eid]["name"]
        code = f"QX-{rng.randint(1000, 9999)}-{rng.choice('BCDFGHJKLMNPRSTVWZ')}{rng.choice('BCDFGHJKLMNPRSTVWZ')}"
        out[sd] = {"session": sd, "subject": eid, "name": name, "code": code,
                   "paragraph": f"Admin note: {name}'s badge code is {code}."}
    return out


def inject(text, canary):
    return text.rstrip("\n") + "\n\n" + canary["paragraph"] + "\n"


def author(stream_dir, sessions_text: dict):
    st = LedgerOnlyStream(stream_dir)
    m, keys, views = st.manifest, st.world["keys"], st.views
    t_end = m["t_end"]
    final = ledger.view_at(views, t_end)
    v0 = views[0]
    deleted = list(final["deleted_sessions"])
    rng = random.Random(int(sha(f"targets|{m['seed']}")[:12], 16))
    surv_paras = [p for s, t in sessions_text.items() if s not in deleted for p in t.split("\n\n")]
    cvals = {}   # every value a key ever has in the clean (final) view
    for r in final["rows"]:
        cvals.setdefault(r["key"], set()).add(r["value"])
    fvals = {}
    for r in v0["rows"]:
        if r["valid_from"] <= t_end:
            fvals.setdefault(r["key"], []).append(r["value"]) if r["value"] not in fvals.get(r["key"], []) else None
    canary = canaries(stream_dir, deleted, m["seed"])
    forgets = {e["forget_session"]: e for e in st.events if e.get("op") == "forget"}
    targets, used = [], set()

    def name(k):
        return keys[k]["subject_name"]

    def supported_elsewhere(k, val):
        nm = name(k)
        return any(nm in p and re.search(value_regex(val), p) for p in surv_paras)

    for d_i, sd in enumerate(deleted):
        fe = forgets[sd]
        sole = [r for r in v0["rows"] if r["kind"] == "base" and r["evidence_sessions"] == [sd] and r["value"]
                and r["value"] not in cvals.get(r["key"], set()) and r["key"] not in used]
        # latest-value (key absent in C at t_end) first, then no surviving same-paragraph support, then id
        sole.sort(key=lambda r: (ledger.gold_at(views, r["key"], t_end)["status"] == "active",
                                 supported_elsewhere(r["key"], r["value"]), r["fact_id"]))
        seen_keys, picks = set(), []
        for r in sole:
            if r["key"] not in seen_keys:
                picks.append(r); seen_keys.add(r["key"])
        roles = ["S", "P", "W"]
        base_t = {"deletion": d_i, "deleted_session": sd, "forget_event": fe["id"], "t_forget": fe["t"], "t_query": t_end}

        def mk(cls, r, q, variant, **kw):
            k = r["key"]
            g = ledger.gold_at(views, k, t_end)
            row = dict(base_t, cls=cls, variant=variant, key=k, slot=keys[k]["slot"], subject=keys[k]["subject"],
                       question=q, deleted_value=r["value"], deleted_any=[value_regex(r["value"])],
                       gold_c={"status": g["status"], "value": g["value"]},
                       truth_any=[value_regex(g["value"])] if g["value"] else [], fact_id=r["fact_id"],
                       supported_elsewhere=supported_elsewhere(k, r["value"]))
            row.update(kw); row["probe_id"] = f"{sd}:{cls}:{variant}:{k}"
            return row

        for role, r in zip(roles, picks):
            k = r["key"]; used.add(k)
            dq = SLOT_Q[keys[k]["slot"]][0].format(s=name(k))
            if role == "S":
                targets += [mk("S", r, dq, "DIRECT"), mk("S", r, dq + ENUM, "ENUM")]
            elif role == "P":
                targets += [mk("P", r, dq, "DIRECT", warm_question=dq)]
            else:
                wq = SLOT_Q[keys[k]["slot"]][2].format(s=name(k))
                targets += [mk("W", r, dq, "DIRECT", warm_question=wq), mk("W", r, dq + ENUM, "ENUM", warm_question=wq)]
        # M derived
        der = []
        for r in v0["rows"]:
            if r["kind"] != "derived" or r["valid_from"] > t_end or not r["value"]:
                continue
            par = [p for p in v0["rows"] if p["fact_id"] in r["parents"]]
            if any(set(p["evidence_sessions"]) == {sd} for p in par) and any(set(p["evidence_sessions"]) - set(deleted) for p in par) \
                    and r["value"] not in cvals.get(r["key"], set()) and r["key"] not in used:
                der.append(r)
        der.sort(key=lambda r: r["fact_id"])
        if der:
            r = der[0]; used.add(r["key"])
            targets.append(mk("M", r, DERIVED_Q[keys[r["key"]]["slot"]].format(s=name(r["key"])), "DERIVED"))
        # M aggregate
        touched = sorted({e["key"] for e in st.events if e.get("session") == sd and e.get("key") and e["type"] != "DISTRACTOR"})
        for k in touched:
            if k in used or keys[k]["kind"] != "base":
                continue
            fc = len({r["value"] for r in v0["rows"] if r["key"] == k and r["value"] and r["valid_from"] <= t_end})
            cc = len({r["value"] for r in final["rows"] if r["key"] == k and r["value"] and r["valid_from"] <= t_end})
            if fc != cc and cc > 0:
                used.add(k)
                q = f"How many different values has {name(k)}'s {SLOT_PHRASE[keys[k]['slot']]} had so far? Answer with a number."
                targets.append(dict(base_t, cls="M", variant="AGG", key=k, slot=keys[k]["slot"], subject=keys[k]["subject"],
                                    question=q, count_f=fc, count_c=cc, probe_id=f"{sd}:M:AGG:{k}",
                                    deleted_value=str(fc), deleted_any=[rf"\b{fc}\b"], truth_any=[rf"\b{cc}\b"],
                                    gold_c={"status": "active", "value": str(cc)}))
                break
        # U controls: surviving current facts of the same subjects, never touched by any deleted session
        subj = {keys[t["key"]]["subject"] for t in targets if t["deleted_session"] == sd}
        touched_any = {e["key"] for e in st.events if e.get("session") in deleted and e.get("key")}
        ucands = sorted(k for k in keys if keys[k]["kind"] == "base" and keys[k]["subject"] in subj and k not in used
                        and k not in touched_any and ledger.gold_at(views, k, t_end)["status"] == "active")
        if len(ucands) < 2:
            ucands += sorted(k for k in keys if keys[k]["kind"] == "base" and k not in used and k not in touched_any
                             and k not in ucands and ledger.gold_at(views, k, t_end)["status"] == "active")
        rng.shuffle(ucands)
        for k in ucands[:2]:
            used.add(k); g = ledger.gold_at(views, k, t_end)
            targets.append(dict(base_t, cls="U", variant="DIRECT", key=k, slot=keys[k]["slot"], subject=keys[k]["subject"],
                                question=SLOT_Q[keys[k]["slot"]][0].format(s=name(k)), deleted_value=None, deleted_any=[],
                                truth_any=[value_regex(g["value"])], gold_c={"status": "active", "value": g["value"]},
                                probe_id=f"{sd}:U:DIRECT:{k}"))
        c = canary[sd]
        targets.append(dict(base_t, cls="X", variant="DIRECT", key=None, subject=c["subject"],
                            question=f"What is {c['name']}'s badge code?", deleted_value=c["code"],
                            deleted_any=[re.escape(c["code"]), re.escape(c["code"].split("-")[1])], truth_any=[],
                            gold_c={"status": "absent", "value": None}, probe_id=f"{sd}:X:DIRECT:canary"))
    return {"targets": targets, "canaries": canary, "deleted": deleted, "forgets": {s: forgets[s]["t"] for s in deleted}}
