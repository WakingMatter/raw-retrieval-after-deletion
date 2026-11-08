#!/usr/bin/env python3
"""Probe author (prereg §5.3; brief §3).

    python3 gen/probe_author.py --stream DIR [--out DIR/probes.jsonl]

30 probes per stream, authored from the LEDGER ONLY. It opens exactly these
files of a stream directory and nothing else: MANIFEST.json, world.json,
events.jsonl, gold.jsonl, deps.json. It never opens sessions/, render traces,
or anything under runs/ (arm outputs), and refuses a stream path inside runs/.

Mix: 10 current, 4 premise-bait, 4 use-in-task, 4 multi-hop/derived,
4 deleted/retracted/absent, 4 unaffected controls.

Source cap (ALLOC failure mode (b)): no stream session, no source group (for
semi-real streams: corpus file + source day) and no topic (subject entity)
supplies more than 10% of the probes (3 of 30). Infeasible caps raise.

Per prereg §5.3, probes for dev/main seeds are authored after the instrument
freeze; this module is part of the instrument.
"""
from __future__ import annotations

import argparse
import random
import re
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gen import ledger  # noqa: E402
from gen.common import read_json, read_jsonl, sub_seed, write_json, write_jsonl  # noqa: E402

MIX = {"current": 10, "premise_bait": 4, "use_in_task": 4, "multi_hop": 4, "deleted_retracted_absent": 4,
       "unaffected_control": 4}
N_PROBES = sum(MIX.values())
CAP = int(N_PROBES * 0.10)  # 3
ALLOWED_FILES = ("MANIFEST.json", "world.json", "events.jsonl", "gold.jsonl", "deps.json")

# Question bank: (current, premise-bait, use-in-task). Disjoint wording from warmup_author.WARM_TEMPLATES.
SLOT_Q = {
    "office_city": ("Which city is {s}'s office in?",
                    "Since {s} still works out of {old}, which city should a visitor travel to in order to meet {s} in person?",
                    "Write a one-sentence note telling a new colleague which city to fly to for an in-person meeting with {s}."),
    "team_name": ("Which team is {s} on?",
                  "Given that {s} is still on the {old} team, which team's channel should {s}'s access request go to?",
                  "Draft a one-line message routing a question to {s}'s team, naming the team."),
    "job_role": ("What is {s}'s role?",
                 "As {s} is still a {old}, what title should go on {s}'s conference badge?",
                 "Write the one-line speaker bio for {s}, including the role {s} holds."),
    "proj_lead": ("Who leads {s}?",
                  "Since {old} still leads {s}, who should sign off on the {s} design?",
                  "Draft a one-line email asking the lead of {s} for a review, addressed to them by name."),
    "proj_status": ("What is the status of {s}?",
                    "Given that {s} is still {old}, what status should the roadmap slide show for {s}?",
                    "Write a one-line roadmap entry for {s} that states its status."),
    "proj_deadline": ("When is {s} due?",
                      "Since {s} is still due on {old}, what date should go in the launch calendar for {s}?",
                      "Write a one-line calendar entry for the {s} deadline with the date."),
    "repo_name": ("Which repository holds the {s} code?",
                  "Given that {s} code still lives in {old}, which repository should a new contributor clone?",
                  "Write the one-line clone instruction for {s}, naming the repository."),
    "svc_owner": ("Who owns {s}?",
                  "Since {old} still owns {s}, who should be paged first for an {s} outage?",
                  "Draft a one-line escalation note naming the person to page for {s}."),
    "host_region": ("Which region is {s} hosted in?",
                    "Given that {s} still runs in {old}, which region should the failover drill target for {s}?",
                    "Write a one-line runbook step naming the region where {s} runs."),
    "listen_port": ("Which port does {s} listen on?",
                    "Since {s} still listens on port {old}, which port should the firewall rule for {s} open?",
                    "Write the one-line health-check command for {s}, including its port."),
    "db_engine": ("Which database does {s} use?",
                  "Given that {s} still uses {old}, which database client should the {s} on-call install?",
                  "Write a one-line backup instruction for {s} that names its database."),
    "cfg_max_rps": ("What request-per-second ceiling does the {s} set?",
                    "Since the {s} still caps traffic at {old} rps, what rate should the load test for it target?",
                    "Write the one-line load-test setting that matches the ceiling of the {s}."),
    "cfg_timeout_ms": ("What timeout does the {s} use?",
                       "Given that the {s} still times out at {old} ms, what timeout should the client library be configured with?",
                       "Write the one-line client setting that matches the timeout of the {s}."),
}
DERIVED_Q = {
    "lead_office_city": "In which city does the person leading {s} have their office?",
    "lead_team_name": "Which team is the person leading {s} on?",
    "owner_office_city": "In which city does the person who owns {s} have their office?",
    "owner_team_name": "Which team is the person who owns {s} on?",
}
PROBE_TEMPLATES = [q for t in SLOT_Q.values() for q in t] + list(DERIVED_Q.values())


def value_regex(v: str) -> str:
    pre = r"\b" if re.match(r"\w", v) else ""
    post = r"\b" if re.search(r"\w$", v) else ""
    return pre + re.escape(v) + post


class LedgerOnlyStream:
    """Read-only view of the ledger files of one stream directory."""

    def __init__(self, stream_dir: str | Path):
        d = Path(stream_dir).resolve()
        if "runs" in d.parts:
            raise PermissionError("probe author never reads arm outputs (refusing a path under runs/)")
        self.dir = d
        self.opened: list[str] = []
        self.manifest = self._json("MANIFEST.json")
        self.world = self._json("world.json")
        self.events = self._jsonl("events.jsonl")
        self.gold = self._jsonl("gold.jsonl")
        self.deps = self._json("deps.json")
        self.views = ledger.views_from_gold(self.gold, self.manifest["views"])

    def _path(self, name: str) -> Path:
        assert name in ALLOWED_FILES, name
        self.opened.append(name)
        return self.dir / name

    def _json(self, name):
        return read_json(self._path(name))

    def _jsonl(self, name):
        return read_jsonl(self._path(name))


def _facts(view: dict, key: str, t: str) -> list[dict]:
    return sorted((r for r in view["rows"] if r["key"] == key and r["valid_from"] <= t),
                  key=lambda r: (r["valid_from"], r["fact_id"]))


def author_probes(stream: LedgerOnlyStream, seed: int | None = None) -> list[dict]:
    m, world, events, views = stream.manifest, stream.world, stream.events, stream.views
    seed = m["seed"] if seed is None else seed
    rng = random.Random(sub_seed(seed, "probes", m.get("kind", "synthetic")))
    t_q = m["t_end"]
    final = ledger.view_at(views, t_q)
    v0 = views[0]
    keys = world["keys"]
    group_of = {s["session"]: s["source_group"] for s in m["sessions"]}
    day_of = {s["session"]: s.get("source_day") for s in m["sessions"]}
    deleted = set(final["deleted_sessions"])

    etypes = {}
    distract = {}
    for e in events:
        if not e.get("key"):
            continue
        if e["type"] == "DISTRACTOR":
            distract.setdefault(e["key"], set()).add(e["value"])
        else:
            tag = e["type"]
            if tag == "SUPERSEDE_EXPLICIT" and e["provenance"].get("return_leg"):
                tag = "RETURN_OUT"
            etypes.setdefault(e["key"], set()).add(tag)
    touched_deleted = {e["key"] for e in events if e.get("session") in deleted and e.get("key")
                       and e["type"] != "DISTRACTOR"}

    info = {}
    for k in sorted(keys):
        g = ledger.gold_at(views, k, t_q)
        hist = _facts(final, k, t_q)
        cur = ledger.fact_at(final["rows"], k, t_q)
        retired = []
        for f in hist:
            if f["value"] is not None and f["value"] != g["value"] and f["value"] not in retired:
                retired.append(f["value"])
        final_ids = {f["fact_id"] for f in final["rows"] if f["key"] == k}
        deleted_vals = []
        for f in _facts(v0, k, t_q):
            if f["fact_id"] not in final_ids and f["value"] is not None and f["value"] != g["value"] \
                    and f["value"] not in deleted_vals:
                deleted_vals.append(f["value"])
        src = []
        if cur is not None:
            src = list(cur["evidence_sessions"])
            if cur.get("created_in") and cur["created_in"] not in src:
                src.append(cur["created_in"])
            if cur["kind"] == "derived":
                for pid in cur["parents"]:
                    p = next(r for r in final["rows"] if r["fact_id"] == pid)
                    for s in p["evidence_sessions"]:
                        if s not in src:
                            src.append(s)
        elif deleted_vals:
            src = sorted({e["session"] for e in events if e.get("key") == k and e.get("session") in deleted})
        info[k] = {"g": g, "hist": hist, "retired": retired, "deleted_vals": deleted_vals, "src": sorted(src),
                   "types": etypes.get(k, set())}

    def is_changed(k):
        i = info[k]
        return keys[k]["kind"] == "base" and i["g"]["status"] == "active" and len(i["hist"]) >= 2 and i["retired"]

    def is_control(k):
        i = info[k]
        return (keys[k]["kind"] == "base" and i["g"]["status"] == "active" and len(i["hist"]) == 1
                and k not in touched_deleted and i["types"] <= {"ASSERT", "RESTATE"})

    counts = {"session": {}, "group": {}, "topic": {}}
    chosen: list[dict] = []
    used_keys: set[str] = set()

    def fits(srcs, topic):
        for s in srcs:
            if counts["session"].get(s, 0) >= CAP:
                return False
        for gname in {group_of.get(s, s) for s in srcs}:
            if counts["group"].get(gname, 0) >= CAP:
                return False
        return counts["topic"].get(topic, 0) < CAP

    def take(cat, k, question, gold, premise=None, src=None, topic=None, slot=None, subject=None):
        i = info.get(k)
        srcs = src if src is not None else i["src"]
        topic = topic or keys[k]["subject"]
        if (k in used_keys) or not fits(srcs, topic):
            return False
        for s in srcs:
            counts["session"][s] = counts["session"].get(s, 0) + 1
        for gname in {group_of.get(s, s) for s in srcs}:
            counts["group"][gname] = counts["group"].get(gname, 0) + 1
        counts["topic"][topic] = counts["topic"].get(topic, 0) + 1
        used_keys.add(k)
        outdated = list(i["retired"]) if i else []
        deleted_vals = list(i["deleted_vals"]) if i else []
        never = sorted(distract.get(k, set()) - set(outdated) - set(deleted_vals) - {gold["value"]})
        wrong_any = [value_regex(v) for v in outdated + deleted_vals + never]
        chosen.append({
            "category": cat, "key": k, "subject": subject or keys[k]["subject"], "slot": slot or keys[k]["slot"],
            "question": question, "t_query": t_q, "view": final["view"],
            "gold": gold, "truth_any": [value_regex(gold["value"])] if gold["value"] else [],
            "expect": "value" if gold["status"] == "active" else "abstain",
            "premise_value": premise, "outdated_values": outdated, "deleted_values": deleted_vals,
            "never_valid_values": never, "wrong_any": wrong_any,
            "source_sessions": list(srcs), "source_groups": sorted({group_of.get(s, s) for s in srcs}),
            "topic": topic,
        })
        return True

    def gold_of(k):
        g = info[k]["g"]
        return {"status": g["status"], "value": g["value"], "fact_id": g["fact_id"]}

    def fill(cat, cands, make, need):
        got = 0
        for k in cands:
            if got == need:
                break
            if make(k):
                got += 1
        if got < need:
            raise RuntimeError(f"probe author: only {got}/{need} feasible '{cat}' probes under the 10% caps")

    base_sorted = sorted(k for k in keys if keys[k]["kind"] == "base")
    derived_sorted = sorted(k for k in keys if keys[k]["kind"] == "derived")

    # multi-hop first (scarcest): derived keys with an active value; changed ones first
    mh = [k for k in derived_sorted if info[k]["g"]["status"] == "active"]
    rng.shuffle(mh)
    mh.sort(key=lambda k: 0 if info[k]["retired"] else 1)
    fill("multi_hop", mh, lambda k: take("multi_hop", k, DERIVED_Q[keys[k]["slot"]].format(s=keys[k]["subject_name"]),
                                         gold_of(k)), MIX["multi_hop"])

    # deleted / retracted / absent: 2 retracted, 1 deleted, 1 never-asserted (fallbacks fill from the others)
    retracted = [k for k in base_sorted if info[k]["g"]["status"] == "withdrawn"]
    dels = [k for k in base_sorted if info[k]["deleted_vals"] and info[k]["g"]["status"] == "absent"]
    rng.shuffle(retracted)
    rng.shuffle(dels)
    absent = [tuple(p) for p in world["absent_pairs"]]
    rng.shuffle(absent)
    plan = ["retracted", "retracted", "deleted", "absent"]
    got = 0
    pools = {"retracted": retracted, "deleted": dels, "absent": absent}

    def make_dra(kind, item):
        if kind == "absent":
            eid, slot = item
            name = world["entities"][eid]["name"]
            akey = f"absent:{eid}:{slot}"
            if akey in used_keys or not fits([], eid):
                return False
            used_keys.add(akey)
            counts["topic"][eid] = counts["topic"].get(eid, 0) + 1
            chosen.append({"category": "deleted_retracted_absent", "key": None, "subject": eid, "slot": slot,
                           "question": SLOT_Q[slot][0].format(s=name), "t_query": t_q, "view": final["view"],
                           "gold": {"status": "absent", "value": None, "fact_id": None}, "truth_any": [],
                           "expect": "abstain", "premise_value": None, "outdated_values": [], "deleted_values": [],
                           "never_valid_values": [], "wrong_any": [], "source_sessions": [], "source_groups": [],
                           "topic": eid, "absent_reason": "never-asserted"})
            return True
        k = item
        ok = take("deleted_retracted_absent", k, SLOT_Q[keys[k]["slot"]][0].format(s=keys[k]["subject_name"]),
                  gold_of(k))
        if ok:
            chosen[-1]["absent_reason"] = "retracted" if kind == "retracted" else "deleted"
        return ok

    for kind in plan:
        for item in pools[kind]:
            if make_dra(kind, item):
                got += 1
                break
    for kind in ("retracted", "deleted", "absent"):
        for item in pools[kind]:
            if got >= MIX["deleted_retracted_absent"]:
                break
            if make_dra(kind, item):
                got += 1
    if got < MIX["deleted_retracted_absent"]:
        raise RuntimeError("probe author: not enough deleted/retracted/absent probes")

    changed = [k for k in base_sorted if is_changed(k)]
    rng.shuffle(changed)

    def premise(k):
        old = info[k]["retired"][-1]
        s = keys[k]["subject_name"]
        return take("premise_bait", k, SLOT_Q[keys[k]["slot"]][1].format(s=s, old=old), gold_of(k), premise=old)

    fill("premise_bait", changed, premise, MIX["premise_bait"])
    fill("use_in_task", changed, lambda k: take("use_in_task", k, SLOT_Q[keys[k]["slot"]][2].format(
        s=keys[k]["subject_name"]), gold_of(k)), MIX["use_in_task"])

    # current: round-robin over change kinds so every kind is represented
    buckets = {"RE_READ": [], "RETURN": [], "TRANSIENT_SET": [], "SUPERSEDE_IMPLICIT": [], "SUPERSEDE_EXPLICIT": [],
               "OTHER": []}
    for k in changed:
        t = info[k]["types"]
        b = next((x for x in ("RE_READ", "RETURN", "TRANSIENT_SET", "SUPERSEDE_IMPLICIT", "SUPERSEDE_EXPLICIT")
                  if x in t), "OTHER")
        buckets[b].append(k)
    order = []
    while any(buckets.values()):
        for b in list(buckets):
            if buckets[b]:
                order.append(buckets[b].pop(0))
    fill("current", order, lambda k: take("current", k, SLOT_Q[keys[k]["slot"]][0].format(
        s=keys[k]["subject_name"]), gold_of(k)), MIX["current"])

    controls = [k for k in base_sorted if is_control(k)]
    rng.shuffle(controls)
    fill("unaffected_control", controls, lambda k: take("unaffected_control", k, SLOT_Q[keys[k]["slot"]][0].format(
        s=keys[k]["subject_name"]), gold_of(k)), MIX["unaffected_control"])

    assert len(chosen) == N_PROBES
    files_of = {s["session"]: s.get("source_files") or [] for s in m["sessions"]}
    win_of = {s["session"]: s["source_window"] for s in m["sessions"] if s.get("source_window")}
    for p in chosen:  # reported, not capped (CONFLICTS C4 ruling)
        p["source_days"] = sorted({day_of[s] for s in p["source_sessions"] if day_of.get(s)})
        p["source_files"] = sorted({f for s in p["source_sessions"] for f in files_of.get(s, [])})
        if win_of:  # semi-real only (C9): corpus-window cluster for the window-clustered bootstrap
            p["source_windows"] = sorted({win_of[s] for s in p["source_sessions"] if s in win_of})
            last = sorted(s for s in p["source_sessions"] if s in win_of)
            p["primary_window"] = win_of[last[-1]] if last else None
        k = p["key"]
        if k is None:
            p["event_types"], p["event_class"] = [], "ABSENT"
        else:  # CONFLICTS C8 ruling: results must split by event type
            ts = set(info[k]["types"])
            if keys[k]["kind"] == "derived":
                ts.add("DERIVED")
                for pk in [keys[k]["ref_key"]] + sorted(set(keys[k]["attr_key_by_value"].values())):
                    if pk in info and "TRANSIENT_SET" in info[pk]["types"]:
                        ts.add("PARENT_TRANSIENT")
            if k in touched_deleted or info[k]["deleted_vals"]:
                ts.add("DELETE")
            p["event_types"] = sorted(ts)
            p["event_class"] = next(c for c in EVENT_CLASS_ORDER if c in ts)
    cat_order = list(MIX)
    chosen.sort(key=lambda p: (cat_order.index(p["category"]), p["key"] or "", p["subject"], p["slot"]))
    for i, p in enumerate(chosen):
        p["id"] = f"p{i:02d}"
        p["stream_seed"] = m["seed"]
        p["stream_kind"] = m.get("kind", "synthetic")
    return chosen


EVENT_CLASS_ORDER = ("DELETE", "RE_READ", "RETURN", "TRANSIENT_SET", "RETRACT", "DERIVED", "SUPERSEDE_IMPLICIT",
                     "SUPERSEDE_EXPLICIT", "RETURN_OUT", "ASSERT", "RESTATE")


def probe_shares(probes: list[dict]) -> dict:
    """Per-day and per-file probe shares (reported for the threats section; CONFLICTS C4 ruling),
    the capped units' maxima, and probe counts per event class (C8 ruling)."""
    n = len(probes)
    out = {"n_probes": n, "cap_per_unit": CAP, "capped_units": ["window(stream session)", "topic", "source_group"],
           "max_per_unit": cap_report(probes), "per_source_day": {}, "per_source_file": {}, "per_event_class": {}}
    for p in probes:
        for d in p.get("source_days", []):
            out["per_source_day"][d] = out["per_source_day"].get(d, 0) + 1
        for f in p.get("source_files", []):
            out["per_source_file"][f] = out["per_source_file"].get(f, 0) + 1
        c = p.get("event_class", "?")
        out["per_event_class"][c] = out["per_event_class"].get(c, 0) + 1
    for k in ("per_source_day", "per_source_file", "per_event_class"):
        out[k] = {x: {"probes": v, "share": round(v / n, 4)} for x, v in sorted(out[k].items())}
    return out


def cap_report(probes: list[dict]) -> dict:
    rep = {"session": {}, "group": {}, "topic": {}, "source_day_reported_only": {}}
    for p in probes:
        for d in p.get("source_days", []):
            rep["source_day_reported_only"][d] = rep["source_day_reported_only"].get(d, 0) + 1
        for s in p["source_sessions"]:
            rep["session"][s] = rep["session"].get(s, 0) + 1
        for g in p["source_groups"]:
            rep["group"][g] = rep["group"].get(g, 0) + 1
        rep["topic"][p["topic"]] = rep["topic"].get(p["topic"], 0) + 1
    return {k: max(v.values()) if v else 0 for k, v in rep.items()}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stream", required=True)
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    s = LedgerOnlyStream(a.stream)
    probes = author_probes(s)
    out = Path(a.out) if a.out else Path(a.stream) / "probes.jsonl"
    write_jsonl(out, probes)
    write_json(out.with_name(out.stem + "-MANIFEST.json"), probe_shares(probes))
    print(f"probes={len(probes)} max_per={cap_report(probes)} opened={s.opened} -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
