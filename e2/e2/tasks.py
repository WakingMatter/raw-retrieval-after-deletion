"""E2 task author (ledger-only, model-free, deterministic). DRAFT -- task definitions are a freeze item.

Deletion set per stream = the generator's deletions (forgotten at their scheduled times) + N_EXTRA extra sessions
forgotten at t_end after all ingest (as PILOT-2). Gold = ledger.compute_rows(events, keys, all_deleted) at t_end,
i.e. the world-F post-delete truth. Four classes, N_PER_CLASS each, keys disjoint across classes:

* AGG      -- "How many different values has {s}'s {p} had so far?" over base keys with >=1 value in the full
              ledger, stratified by surviving count {0, 1, >=2} and interleaved 2,1,0 (rev 5, Astra finding 1: gold
              is no longer constant). Deletion-sensitive keys (count differs from the undeleted ledger) first.
* DERIVED  -- surviving-support derivation: derived keys (lead/owner -> office/team) active post-delete.
              Deletion-touched ones (a parent's evidence or the value changed under deletion) first.
* MULTIHOP -- composed 2-hop over base keys, reverse direction to DERIVED: "Which region is the service owned by
              {person} hosted in?" Requires the person to own/lead exactly one entity post-delete.
              BRIDGE (E2 rev 4): the generator's answer paragraph names only the entity, so the chain was not
              retrievable from the question. For each selected task, E2 appends one bridging sentence that names the
              link to the later of the two surviving gold assertions (attribute value / owner-lead): the attribute
              paragraph gets "{person}, who leads {entity}, confirmed the update.", or the owner paragraph gets "For
              the record, {entity} is due {value}." A matching OBSERVE event is added to the ledger (same session,
              same time), so gold, support and deletion semantics stay ledger-consistent. Only true statements are
              bridged (the restated fact holds at that time in both the undeleted and the post-delete ledger).
              Edits and events are recorded in stream-S/BRIDGE.json.
* CURRENT  -- current value of a superseded base key (>=2 surviving values). Deletion-touched first.

Ties within a priority tier are broken by a seeded shuffle (seed = stream seed)."""
from __future__ import annotations
import hashlib, json, random, re
from pathlib import Path
from . import paths  # noqa: F401  (sys.path for pilot-v1.3/eng-pin)
from gen import ledger
from gen.probe_author import LedgerOnlyStream, SLOT_Q, DERIVED_Q, value_regex
from pilot.targets import SLOT_PHRASE

N_EXTRA = 6
N_PER_CLASS = 10
N_WARM = 10
CLASSES = ("AGG", "DERIVED", "MULTIHOP", "CURRENT")
NUM_WORDS = {0: "zero", 1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten"}
HOP = {  # (hop slot, attribute slot) -> question about the entity reached through the person
    ("svc_owner", "host_region"): "Which region is the service owned by {p} hosted in?",
    ("svc_owner", "listen_port"): "Which port does the service owned by {p} listen on?",
    ("svc_owner", "db_engine"): "Which database does the service owned by {p} use?",
    ("proj_lead", "proj_status"): "What is the status of the project led by {p}?",
    ("proj_lead", "proj_deadline"): "When is the project led by {p} due?",
    ("proj_lead", "repo_name"): "Which repository holds the code of the project led by {p}?",
}


def sub_rng(seed: int, tag: str) -> random.Random:
    return random.Random(int(hashlib.sha256(f"{seed}|e2|{tag}".encode()).hexdigest()[:16], 16))


def pick_extra_deletions(st: LedgerOnlyStream, n=N_EXTRA) -> list[str]:
    """The n most fact-dense sessions (non-distractor keyed events) not already deleted; seeded tie-break."""
    m = st.manifest
    gen_del = set(m["views"][-1]["deleted_sessions"])
    dens: dict[str, int] = {}
    for e in st.events:
        if e.get("session") and e.get("key") and e.get("type") != "DISTRACTOR":
            dens[e["session"]] = dens.get(e["session"], 0) + 1
    rng = sub_rng(m["seed"], "extra")
    sess = [s["session"] for s in m["sessions"] if s["session"] not in gen_del]
    tie = {s: rng.random() for s in sess}
    return sorted(sorted(sess, key=lambda s: (-dens.get(s, 0), tie[s]))[:n], key=lambda s: int(s[1:]))


def _vals(rows, k, t):
    out = []
    for r in rows:
        if r["key"] == k and r["value"] and r["valid_from"] <= t and r["value"] not in out:
            out.append(r["value"])
    return out


def _support(rows_by_id, r) -> set[str]:
    s = set(r.get("evidence_sessions") or [])
    for pid in r.get("parents") or []:
        if pid in rows_by_id:
            s |= _support(rows_by_id, rows_by_id[pid])
    return s


BRIDGE_TPL = {
    "proj_lead": ("{p}, who leads {e}, confirmed the update.", "{p} (lead on {e}) signed off on this."),
    "svc_owner": ("{p}, who owns {e}, confirmed the update.", "{p} (owner of {e}) signed off on this."),
}
ATTR_TPL = {
    "host_region": "For the record, {e} is hosted in {v}.", "listen_port": "For the record, {e} listens on port {v}.",
    "db_engine": "For the record, {e} runs on {v}.", "proj_status": "For the record, {e} is {v}.",
    "proj_deadline": "For the record, {e} is due {v}.", "repo_name": "For the record, {e} lives in the {v} repo.",
}
AGG_Q = ("How many different values has {s}'s {p} had so far? Count only values recorded in sessions that are still "
         "in memory (deleted sessions do not count), and ignore values that were only proposed, quoted or hypothetical. "
         "Answer with a number.")
NUM_RX = r"\b(\d+|" + "|".join(NUM_WORDS.values()) + r"|none)\b"


def _merge(events, extra):
    """Insert each bridge OBSERVE right after the event it rides on (ledger order = list order)."""
    after = {}
    for e in extra:
        after.setdefault(e["after"], []).append({k: v for k, v in e.items() if k != "after"})
    out = []
    for e in events:
        out.append(e); out.extend(after.get(e["id"], []))
    return out


def _paragraph_index(d: Path, sid: str, eid: str, value: str) -> int:
    for l in open(d / "render_trace.jsonl"):
        x = json.loads(l)
        if x["session"] == sid and eid in x["event_ids"]:
            paras = (d / "sessions" / f"{sid}.md").read_text().rstrip("\n").split("\n\n")
            assert value in paras[x["seg"]], (sid, eid)
            return x["seg"]
    raise KeyError((sid, eid))


def num_regex(n: int) -> str:
    w = NUM_WORDS.get(n)
    return rf"\b({n}{'|' + w if w else ''})\b"


def author_e2(stream_dir, n_per_class=N_PER_CLASS, n_extra=N_EXTRA) -> dict:
    st = LedgerOnlyStream(stream_dir)
    m, keys = st.manifest, st.world["keys"]
    seed, t_end = m["seed"], m["t_end"]
    gen_del = list(m["views"][-1]["deleted_sessions"])
    extra = pick_extra_deletions(st, n_extra)          # from the generator ledger only (bridges never move deletions)
    deleted = gen_del + extra
    bridge = make_bridge(Path(stream_dir), st, deleted, n_per_class)
    events = _merge(st.events, bridge["events"])
    forgets = {e["forget_session"]: e["t"] for e in events if e["op"] == ledger.FORGET}
    for s in extra:
        forgets[s] = t_end
    v0 = ledger.compute_rows(events, keys, set())
    fin = ledger.compute_rows(events, keys, set(deleted))
    by_id = {r["fact_id"]: r for r in fin}
    by_id0 = {r["fact_id"]: r for r in v0}
    name = lambda k: keys[k]["subject_name"]
    touched = {e["key"] for e in events if e.get("session") in set(deleted) and e.get("key") and e["type"] != "DISTRACTOR"}

    def gold(rows, k):
        f = ledger.fact_at(rows, k, t_end)
        return f if (f and f["status"] == "active" and f["value"]) else None

    def last_t(k, v):
        """valid_from of the latest undeleted-ledger row holding outdated value v (dates the stale-note control)."""
        ts = [r["valid_from"] for r in v0 if r["key"] == k and r["value"] == v]
        return max(ts) if ts else None

    def del_touched(k):
        g0, g1 = gold(v0, k), gold(fin, k)
        if (g0 or {}).get("value") != (g1 or {}).get("value") or k in touched:
            return True
        if keys[k]["kind"] == "derived" and g0:
            return bool(_support(by_id0, g0) & set(deleted))
        return False

    used: set[str] = set()
    tasks: list[dict] = []

    def order(cands, tag, prio):
        rng = sub_rng(seed, tag)
        c = sorted(cands); rng.shuffle(c)
        return sorted(c, key=prio)

    def add(cls, k, q, value, truth_any, support, sensitive, extra_fields=None, wrong=()):
        used.add(k)
        row = {"task_id": f"{seed}:{cls}:{k}", "seed": seed, "cls": cls, "key": k, "slot": keys[k]["slot"],
               "subject": keys[k]["subject"], "question": q, "t_query": t_end, "gold": value, "truth_any": truth_any,
               "wrong_any": [value_regex(w) if not w.isdigit() else rf"\b{w}\b" for w in wrong if w and w != value],
               "wrong_t": [last_t(k, w) for w in wrong if w and w != value],
               "support_sessions": sorted(support), "n_support_sessions": len(support),
               "stratum": "distributed" if len(support) >= 2 else "single", "deletion_touched": bool(sensitive)}
        row.update(extra_fields or {})
        tasks.append(row)

    base = [k for k in keys if keys[k]["kind"] == "base"]
    derived = [k for k in keys if keys[k]["kind"] == "derived"]
    shortfall = {}

    # MULTIHOP first (scarcest), then DERIVED, AGG, CURRENT
    owners: dict[tuple[str, str], list[str]] = {}
    for k in base:
        sl = keys[k]["slot"]
        if sl in ("svc_owner", "proj_lead"):
            g = gold(fin, k)
            if g:
                owners.setdefault((sl, g["value"]), []).append(k)
    mh = []
    bridged = {(b["hop_key"], b["key"]) for b in bridge["tasks"]}
    for (sl, person), ks in owners.items():
        if len(ks) != 1:
            continue
        hop = ks[0]
        for (hs, asl), tmpl in HOP.items():
            if hs != sl:
                continue
            ak = next((x for x in base if keys[x]["subject"] == keys[hop]["subject"] and keys[x]["slot"] == asl), None)
            if ak and gold(fin, ak) and (hop, ak) in bridged:
                mh.append((hop, ak, person, tmpl))
    rng = sub_rng(seed, "MULTIHOP"); mh.sort(key=lambda x: (x[1], x[0])); rng.shuffle(mh)
    mh.sort(key=lambda x: 0 if (del_touched(x[0]) or del_touched(x[1])) else 1)
    seen_subj, got = set(), 0
    for pass_ in (0, 1):          # pass 0: one task per hop entity; pass 1: allow a second attribute of the same entity
      for hop, ak, person, tmpl in mh:
        if got == n_per_class:
            break
        if ak in used or (pass_ == 0 and keys[hop]["subject"] in seen_subj):
            continue
        g = gold(fin, ak)
        sup = _support(by_id, gold(fin, hop)) | _support(by_id, g)
        add("MULTIHOP", ak, tmpl.format(p=person), g["value"], [value_regex(g["value"])], sup,
            del_touched(hop) or del_touched(ak), {"hop_key": hop, "via": person, "hop_entity": name(hop),
                                                  "bridge_session": next(b["session"] for b in bridge["tasks"]
                                                                         if b["key"] == ak)},
            wrong=[v for v in _vals(v0, ak, t_end)])
        seen_subj.add(keys[hop]["subject"]); got += 1
    shortfall["MULTIHOP"] = n_per_class - got

    got = 0
    for k in order([k for k in derived if gold(fin, k) and k not in used], "DERIVED", lambda k: 0 if del_touched(k) else 1):
        if got == n_per_class:
            break
        g = gold(fin, k)
        add("DERIVED", k, DERIVED_Q[keys[k]["slot"]].format(s=name(k)), g["value"], [value_regex(g["value"])],
            _support(by_id, g), del_touched(k), wrong=_vals(v0, k, t_end)); got += 1
    shortfall["DERIVED"] = n_per_class - got

    got = 0
    # AGG (rev 5, Astra finding 1): cardinality-stratified so no constant answer is a class baseline. Eligible = base
    # keys with >=1 value ever recorded by t_end (undeleted ledger); stratum = surviving distinct count (0, 1, 2+),
    # strata interleaved 2,1,0,... (a short stratum is skipped, others fill); within a stratum the previous priority.
    agg = [k for k in base if k not in used and len(_vals(v0, k, t_end)) >= 1]
    strata = {}
    for k in order(agg, "AGG", lambda k: (0 if len(_vals(v0, k, t_end)) != len(_vals(fin, k, t_end)) else 1 if del_touched(k) else 2)):
        strata.setdefault(min(len(_vals(fin, k, t_end)), 2), []).append(k)
    picks, cyc = [], [2, 1, 0]
    while len(picks) < n_per_class and any(strata.get(c) for c in cyc):
        for c in cyc:
            if strata.get(c) and len(picks) < n_per_class:
                picks.append(strata[c].pop(0))
    for k in picks:
        cc, fc = len(_vals(fin, k, t_end)), len(_vals(v0, k, t_end))
        sup = set().union(set(), *[set(r["evidence_sessions"]) for r in fin if r["key"] == k and r["value"] and r["valid_from"] <= t_end])
        q = AGG_Q.format(s=name(k), p=SLOT_PHRASE[keys[k]['slot']])
        add("AGG", k, q, str(cc), [num_regex(cc)], sup, fc != cc or del_touched(k),
            {"count_undeleted": fc, "values_post_delete": _vals(fin, k, t_end)}, wrong=[str(fc)] if fc != cc else []); got += 1
    shortfall["AGG"] = n_per_class - got

    got = 0
    cur = [k for k in base if k not in used and gold(fin, k) and len(_vals(fin, k, t_end)) >= 2]
    for k in order(cur, "CURRENT", lambda k: 0 if del_touched(k) else 1):
        if got == n_per_class:
            break
        g = gold(fin, k)
        add("CURRENT", k, SLOT_Q[keys[k]["slot"]][0].format(s=name(k)), g["value"], [value_regex(g["value"])],
            _support(by_id, g), del_touched(k), wrong=[v for v in _vals(v0, k, t_end) if v != g["value"]]); got += 1
    shortfall["CURRENT"] = n_per_class - got

    # warm plan: before each deletion, use-in-task questions on keys that deletion touches (common A6 state, write-back on)
    warm = []
    rng = sub_rng(seed, "warm")
    per = {}
    for sd in deleted:
        ks = sorted({e["key"] for e in events if e.get("session") == sd and e.get("key") and e["type"] != "DISTRACTOR"
                     and keys[e["key"]]["kind"] == "base"})
        rng.shuffle(ks); per[sd] = ks
    i = 0
    while len(warm) < N_WARM and any(per.values()):
        sd = deleted[i % len(deleted)]; i += 1
        if per[sd]:
            k = per[sd].pop()
            warm.append({"warm_id": f"{seed}:W:{sd}:{k}", "before_forget": sd, "t": forgets[sd], "key": k,
                         "question": SLOT_Q[keys[k]["slot"]][2].format(s=name(k))})
    return {"seed": seed, "t_end": t_end, "deleted": deleted, "generator_deleted": gen_del, "extra_deleted": extra,
            "forgets": forgets, "tasks": tasks, "warm": warm, "shortfall": shortfall,
            "bridge_sha256": bridge["sha256"]}


def make_bridge(d: Path, st: LedgerOnlyStream, deleted: list[str], n: int = N_PER_CLASS) -> dict:
    """Select up to n MULTIHOP (hop, attribute) pairs on the generator ledger and bridge them (idempotent: an
    existing BRIDGE.json is reused, and session text is edited exactly once)."""
    bf = d / "BRIDGE.json"
    if bf.exists():
        b = json.loads(bf.read_text())
        return dict(b, sha256=hashlib.sha256(bf.read_bytes()).hexdigest())
    keys, events, seed, t_end = st.world["keys"], st.events, st.manifest["seed"], st.manifest["t_end"]
    v0 = ledger.compute_rows(events, keys, set())
    fin = ledger.compute_rows(events, keys, set(deleted))
    ev_by_id = {e["id"]: e for e in events}

    def gold(rows, k):
        f = ledger.fact_at(rows, k, t_end)
        return f if (f and f["status"] == "active" and f["value"]) else None

    base = [k for k in keys if keys[k]["kind"] == "base"]
    owners: dict[tuple[str, str], list[str]] = {}
    for k in base:
        if keys[k]["slot"] in ("svc_owner", "proj_lead") and gold(fin, k):
            owners.setdefault((keys[k]["slot"], gold(fin, k)["value"]), []).append(k)
    cands = []
    for (sl, person), ks in owners.items():
        if len(ks) != 1:
            continue
        hop = ks[0]
        for (hs, asl) in HOP:
            if hs != sl:
                continue
            ak = next((x for x in base if keys[x]["subject"] == keys[hop]["subject"] and keys[x]["slot"] == asl), None)
            g = gold(fin, ak) if ak else None
            gh = gold(fin, hop)
            if not g or g["created_in"] in deleted or gh["created_in"] in deleted:
                continue
            # anchor = the later of the two surviving gold assertions; the bridge restates the OTHER fact there,
            # which is active at that time in the post-delete ledger by construction; require it in the undeleted
            # ledger too, so the bridge is true in both worlds and never creates a new ledger fact.
            if g["valid_from"] >= gh["valid_from"]:
                anchor, bkey, bval = g, hop, person
            else:
                anchor, bkey, bval = gh, ak, g["value"]
            f0 = ledger.fact_at(v0, bkey, anchor["valid_from"])
            if not (f0 and f0["status"] == "active" and f0["value"] == bval):
                continue
            cands.append((hop, ak, person, (anchor, bkey, bval)))
    dset = set(deleted)
    touched = {e["key"] for e in events if e.get("session") in dset and e.get("key") and e["type"] != "DISTRACTOR"}

    def dt(k):   # deletion-touched (value changed under deletion, or the key has evidence in a deleted session)
        return (gold(v0, k) or {}).get("value") != (gold(fin, k) or {}).get("value") or k in touched
    rng = sub_rng(seed, "MULTIHOP"); cands.sort(key=lambda x: (x[1], x[0])); rng.shuffle(cands)
    cands.sort(key=lambda x: 0 if (dt(x[0]) or dt(x[1])) else 1)
    seen, picked, used = set(), [], set()
    for pass_ in (0, 1):
        for hop, ak, person, g in cands:
            if len(picked) == n:
                break
            if ak in used or (pass_ == 0 and keys[hop]["subject"] in seen):
                continue
            picked.append((hop, ak, person, g)); used.add(ak); seen.add(keys[hop]["subject"])
    trng = sub_rng(seed, "bridge")
    edits, new_ev, rows = {}, [], []
    for hop, ak, person, (anchor, bkey, bval) in picked:
        ev = ev_by_id[anchor["created_by"]]
        sid = ev["session"]
        j = _paragraph_index(d, sid, ev["id"], ev["value"])
        ent = keys[hop]["subject_name"]
        if bkey == hop:
            sent = BRIDGE_TPL[keys[hop]["slot"]][trng.randrange(2)].format(p=person, e=ent)
        else:
            sent = ATTR_TPL[keys[ak]["slot"]].format(e=ent, v=bval)
        edits.setdefault(sid, []).append((j, sent))
        new_ev.append({"after": ev["id"], "id": ev["id"] + "b", "key": bkey, "op": "observe", "seq": ev["seq"],
                       "session": sid, "slot": keys[bkey]["slot"], "subject": keys[bkey]["subject"],
                       "subject_name": keys[bkey]["subject_name"], "t": ev["t"], "type": "ASSERT", "value": bval,
                       "provenance": {"e2_bridge": True}, "rendered": True})
        rows.append({"hop_key": hop, "key": ak, "via": person, "session": sid, "paragraph": j, "sentence": sent,
                     "bridged_key": bkey})
    for sid, es in edits.items():
        f = d / "sessions" / f"{sid}.md"
        paras = f.read_text().rstrip("\n").split("\n\n")
        for j, sent in es:
            paras[j] = paras[j] + " " + sent
        f.write_text("\n\n".join(paras) + "\n")
    b = {"note": "E2 MULTIHOP bridges (tasks.make_bridge); session text edited once at generation", "tasks": rows,
         "events": new_ev}
    bf.write_text(json.dumps(b, indent=1))
    return dict(b, sha256=hashlib.sha256(bf.read_bytes()).hexdigest())


ABSTAIN_RX = re.compile(r"not found in memory", re.I)


def score(task: dict, answer: str | None) -> dict:
    """Exact controlled gold, same rule for every arm (DEFAULTS.md rev 4, #20-22).
    AGG: the answer must contain exactly one distinct number (digits or one..ten) and it must equal gold; zero or
    several distinct numbers score wrong. Other classes (PRIMARY, strict): gold regex hit AND no deleted/outdated
    value mentioned. `correct_lenient` (gold hit regardless of other mentions) is the prespecified sensitivity."""
    a = answer or ""
    if task["cls"] == "AGG":
        w2n = {v: k for k, v in NUM_WORDS.items()}
        w2n["none"] = 0
        vals = {int(t) if t.isdigit() else w2n[t.lower()] for t in re.findall(NUM_RX, a, re.I)}
        val = next(iter(vals)) if len(vals) == 1 else None          # 0 or >=2 distinct numbers: unparseable
        ok = val == int(task["gold"])
        return {"correct": ok, "correct_lenient": ok, "parsed": val, "n_numbers": len(vals), "mentions_wrong": False}
    if ABSTAIN_RX.search(a):                       # declared abstention override (prereg §6): an answer that says
        return {"correct": False, "correct_lenient": False, "parsed": None, "mentions_wrong": False, "abstained": True}
    hit = any(re.search(rx, a, re.I) for rx in task["truth_any"])
    wrong = any(re.search(rx, a, re.I) for rx in task.get("wrong_any", []))
    return {"correct": hit and not wrong, "correct_lenient": hit, "parsed": None, "mentions_wrong": wrong}
