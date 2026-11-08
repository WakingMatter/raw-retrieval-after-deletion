"""Ledger -> gold engine: validity intervals, views, deps and the deletion closure.

Gold is a pure function of ``events.jsonl`` plus the static key table in the
world. It never looks at rendered prose (prereg §5.1, ALLOC failure mode (a)).

Semantics (one rule per ``op``; every rule is state-independent except
``observe``, which only ever attaches evidence):

* ``set``      closes the key's current fact at the event time and opens a new
               active fact with the event's value. A set never merges with the
               previous fact, even when the value is the same (so a RETURN to A
               creates a new fact A').
* ``withdraw`` closes the current fact and opens a ``withdrawn`` fact (value
               None): a RETRACT. Abstaining is correct while it holds.
* ``observe``  (RESTATE, RE_READ, the ASSERT of a derived key) attaches the
               event's session as evidence to the current fact **iff** that fact
               is active and has the same value. Otherwise it is a no-op: an
               observation can never (re)activate a value. This is the
               no-resurrect rule; RE-READ of a retired value therefore leaves
               gold unchanged (prereg §5.1 RETURN row).
* ``none``     DISTRACTOR items: ignored by gold.
* ``forget``   DELETE: a harness event at time t_del naming a source session.
               From t_del on, gold is recomputed from the ledger with every
               event of the forgotten session removed (recompute-from-raw).

Views: view 0 has no deletions and holds for query times before the first
DELETE; view i applies the first i deletions and holds from the i-th DELETE
until the next one. Each view lists facts over the whole timeline.

Derived keys (DERIVED, "the lead's office"): value(t) = attr(ref(t), t). A
derived fact is one segment where one ref fact and one attr fact overlap. Its
row carries the parent fact ids and the parents' row digests, so any change to
a parent row changes the derived row (recompute on parent transition).
"""
from __future__ import annotations

from collections import defaultdict

from gen.common import canon, digest

SET, WITHDRAW, OBSERVE, NONE, FORGET = "set", "withdraw", "observe", "none", "forget"


def _lt(a: str | None, b: str | None) -> bool:
    """a < b where None means +infinity."""
    if a is None:
        return False
    if b is None:
        return True
    return a < b


def _min_t(a: str | None, b: str | None) -> str | None:
    if a is None:
        return b
    if b is None:
        return a
    return min(a, b)


def replay_base_key(key: str, events: list[dict], deleted: set[str]) -> list[dict]:
    """Replay one base key's events (already in ledger order)."""
    facts: list[dict] = []
    cur: dict | None = None
    for ev in events:
        if ev.get("session") in deleted:
            continue
        op = ev["op"]
        if op in (SET, WITHDRAW):
            if cur is not None:
                cur["valid_until"] = ev["t"]
                cur["closed_by"] = ev["id"]
                cur["closed_in"] = ev["session"]
            cur = {
                "fact_id": f"F:{key}:{ev['id']}",
                "key": key,
                "kind": "base",
                "value": ev["value"] if op == SET else None,
                "status": "active" if op == SET else "withdrawn",
                "valid_from": ev["t"],
                "valid_until": None,
                "created_by": ev["id"],
                "created_in": ev["session"],
                "created_type": ev["type"],
                "closed_by": None,
                "closed_in": None,
                "evidence_events": [ev["id"]],
                "evidence_sessions": [ev["session"]],
            }
            facts.append(cur)
        elif op == OBSERVE:
            if cur is not None and cur["status"] == "active" and cur["value"] == ev["value"]:
                cur["evidence_events"].append(ev["id"])
                if ev["session"] not in cur["evidence_sessions"]:
                    cur["evidence_sessions"].append(ev["session"])
    return facts


def _with_digest(row: dict) -> dict:
    row = dict(row)
    row.pop("digest", None)
    row["digest"] = digest(row)
    return row


def derive_key(dkey: str, spec: dict, base_rows: dict[str, list[dict]], observes: list[dict],
               deleted: set[str]) -> list[dict]:
    """Segments of a derived key. ``spec`` = {ref_key, attr_key_by_value}."""
    out: list[dict] = []
    obs = [o for o in observes if o.get("session") not in deleted]
    for R in base_rows.get(spec["ref_key"], []):
        if R["status"] != "active":
            segs = [(R, None, R["valid_from"], R["valid_until"], None, "withdrawn")]
        else:
            attr_key = spec["attr_key_by_value"].get(R["value"])
            segs = []
            for A in base_rows.get(attr_key, []) if attr_key else []:
                lo = max(R["valid_from"], A["valid_from"])
                hi = _min_t(R["valid_until"], A["valid_until"])
                if hi is None or lo < hi:
                    val = A["value"] if A["status"] == "active" else None
                    segs.append((R, A, lo, hi, val, A["status"]))
        for (Rf, Af, lo, hi, val, status) in segs:
            ev_events, ev_sessions = [], []
            for o in obs:
                if o["t"] >= lo and _lt(o["t"], hi) and status == "active" and o["value"] == val:
                    ev_events.append(o["id"])
                    if o["session"] not in ev_sessions:
                        ev_sessions.append(o["session"])
            parents = [Rf["fact_id"]] + ([Af["fact_id"]] if Af else [])
            parent_digests = [Rf["digest"]] + ([Af["digest"]] if Af else [])
            row = {
                "fact_id": f"D:{dkey}:{Rf['created_by']}:{Af['created_by'] if Af else '-'}",
                "key": dkey,
                "kind": "derived",
                "value": val,
                "status": status,
                "valid_from": lo,
                "valid_until": hi,
                "created_by": None,
                "created_in": None,
                "created_type": "DERIVED",
                "closed_by": None,
                "closed_in": None,
                "evidence_events": ev_events,
                "evidence_sessions": ev_sessions,
                "parents": parents,
                "parent_digests": parent_digests,
            }
            out.append(_with_digest(row))
    out.sort(key=lambda r: (r["valid_from"], r["fact_id"]))
    return out


def compute_rows(events: list[dict], keys: dict[str, dict], deleted: set[str]) -> list[dict]:
    """All fact rows (base then derived) for one deletion set."""
    by_key: dict[str, list[dict]] = defaultdict(list)
    for ev in events:
        if ev.get("key") and ev["op"] in (SET, WITHDRAW, OBSERVE):
            by_key[ev["key"]].append(ev)
    base_rows: dict[str, list[dict]] = {}
    rows: list[dict] = []
    for key in sorted(keys):
        if keys[key]["kind"] != "base":
            continue
        facts = [_with_digest(f) for f in replay_base_key(key, by_key.get(key, []), deleted)]
        base_rows[key] = facts
        rows.extend(facts)
    for key in sorted(keys):
        spec = keys[key]
        if spec["kind"] != "derived":
            continue
        rows.extend(derive_key(key, spec, base_rows, by_key.get(key, []), deleted))
    return rows


def compute_views(events: list[dict], keys: dict[str, dict]) -> list[dict]:
    forgets = sorted((e for e in events if e["op"] == FORGET), key=lambda e: (e["t"], e["id"]))
    bounds = [None] + [f["t"] for f in forgets] + [None]
    views = []
    deleted: set[str] = set()
    for i in range(len(forgets) + 1):
        if i > 0:
            deleted.add(forgets[i - 1]["forget_session"])
        views.append({
            "view": i,
            "view_from": bounds[i],
            "view_until": bounds[i + 1],
            "deleted_sessions": sorted(deleted),
            "forget_event": forgets[i - 1]["id"] if i > 0 else None,
            "rows": compute_rows(events, keys, set(deleted)),
        })
    return views


def gold_rows(views: list[dict]) -> list[dict]:
    out = []
    for v in views:
        for r in v["rows"]:
            row = dict(r)
            row["view"] = v["view"]
            out.append(row)
    return out


def views_from_gold(gold: list[dict], view_meta: list[dict]) -> list[dict]:
    views = []
    for m in view_meta:
        rows = [{k: v for k, v in r.items() if k != "view"} for r in gold if r["view"] == m["view"]]
        vv = dict(m)
        vv["rows"] = rows
        views.append(vv)
    return views


def view_at(views: list[dict], t: str) -> dict:
    for v in views:
        if (v["view_from"] is None or v["view_from"] <= t) and (v["view_until"] is None or t < v["view_until"]):
            return v
    raise ValueError(f"no view covers {t}")


def fact_at(rows: list[dict], key: str, t: str) -> dict | None:
    for r in rows:
        if r["key"] == key and r["valid_from"] <= t and _lt(t, r["valid_until"]):
            return r
    return None


def gold_at(views: list[dict], key: str, t: str) -> dict:
    """As-of gold for (key, t): {status: active|withdrawn|absent, value, fact_id, view}."""
    v = view_at(views, t)
    f = fact_at(v["rows"], key, t)
    if f is None:
        return {"status": "absent", "value": None, "fact_id": None, "view": v["view"]}
    return {"status": f["status"], "value": f["value"], "fact_id": f["fact_id"], "view": v["view"]}


# ---------------------------------------------------------------- deps / closure

def deps_for_rows(rows: list[dict]) -> dict:
    fact_sessions = {}
    fact_parents = {}
    for r in rows:
        fact_sessions[r["fact_id"]] = {
            "created_in": r["created_in"],
            "closed_in": r["closed_in"],
            "evidence": list(r["evidence_sessions"]),
        }
        if r["kind"] == "derived":
            fact_parents[r["fact_id"]] = list(r["parents"])
    return {"fact_sessions": fact_sessions, "derived_parents": fact_parents}


def closure(deps: dict, session: str) -> list[str]:
    """Facts that depend on ``session``: created, closed or evidenced there, plus
    every derived fact with a parent in the set (transitively)."""
    hit = set()
    for fid, s in deps["fact_sessions"].items():
        if s["created_in"] == session or s["closed_in"] == session or session in s["evidence"]:
            hit.add(fid)
    changed = True
    while changed:
        changed = False
        for fid, parents in deps["derived_parents"].items():
            if fid not in hit and any(p in hit for p in parents):
                hit.add(fid)
                changed = True
    return sorted(hit)


def row_diff(before: list[dict], after: list[dict]) -> tuple[set[str], set[str]]:
    """(ids changed or removed in ``before``, ids new in ``after``)."""
    b = {r["fact_id"]: r["digest"] for r in before}
    a = {r["fact_id"]: r["digest"] for r in after}
    changed = {fid for fid, d in b.items() if a.get(fid) != d}
    new = set(a) - set(b)
    return changed, new


def canon_rows(rows: list[dict]) -> str:
    return "\n".join(canon(r) for r in rows)
