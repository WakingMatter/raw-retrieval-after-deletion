#!/usr/bin/env python3
"""SPARK warm-up tasks (prereg §5.4; brief §3).

60 tasks per stream, each timestamped inside the stream (after a session's
events and before the next session), drawn from the same key population as the
probes, worded disjointly from the probe bank, and each carrying an exact-match
gold taken from the ledger as of its timestamp (``gen.ledger.gold_at``).
Warm-ups are graded by exact ledger match only, never by an LLM judge.

    python3 gen/warmup_author.py --stream DIR   # re-derive warmup.jsonl from a stream's ledger and compare
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
from gen.common import add_minutes, canon, read_json, read_jsonl, sub_seed  # noqa: E402
from gen.vocab import SLOT_NOUN  # noqa: E402

N_WARMUPS = 60
FIRST_WARMUP_SESSION = 8
WARMUP_OFFSET_MIN = 90  # minutes after a session starts; sessions' events end well before this

# Wording bank. Kept disjoint from gen/probe_author.py PROBE_TEMPLATES (tested: no shared 4-gram).
WARM_TEMPLATES = [
    "Lookup task. Give only the {noun} currently on record for {s}. If nothing is on record, give the single word unknown.",
    "Fill the blank with one value only: {s} | {noun} | ____ (write unknown if not on record).",
    "Exact-match drill: {s} -> {noun}? Reply with just the value, or unknown.",
    "Record check for {s}: state the {noun} as a bare value, nothing else; unknown if withdrawn.",
]
UNKNOWN = "unknown"
CHANGE_TYPES = {"SUPERSEDE_EXPLICIT", "SUPERSEDE_IMPLICIT", "RETRACT", "TRANSIENT_SET", "TRANSIENT_VOID", "RETURN"}


def normalize(v: str) -> str:
    v = v.casefold().strip()
    v = re.sub(r"\s+", " ", v)
    return v.rstrip(".")


def transient_windows(events: list[dict]) -> dict:
    """key -> [(t_set, t_void, set_event_id)]: the TRANSIENT mistaken windows (CONFLICTS C7 ruling)."""
    sets = {e["id"]: e for e in events if e["type"] == "TRANSIENT_SET"}
    out: dict = {}
    for e in events:
        if e["type"] == "TRANSIENT_VOID":
            s = sets[e["provenance"]["voids"]]
            out.setdefault(s["key"], []).append((s["t"], e["t"], s["id"]))
    for k in out:
        out[k].sort()
    return out


def transient_tag(keys: dict, views: list[dict], windows: dict, k: str, t: str) -> dict | None:
    """The mistaken window that ``(k, t)`` falls inside, directly or via a derived key's parents, else None.
    Gold stays as-of-ledger (ruling on C7); this tag only lets results be reported separately."""
    spec = keys[k]
    cand = [k]
    if spec["kind"] == "derived":
        cand.append(spec["ref_key"])
        ref = ledger.gold_at(views, spec["ref_key"], t)
        ak = spec["attr_key_by_value"].get(ref["value"]) if ref["status"] == "active" else None
        if ak:
            cand.append(ak)
    for ck in cand:
        for t_set, t_void, sid in windows.get(ck, []):
            if t_set <= t < t_void:
                return {"key": ck, "set_event": sid, "t_set": t_set, "t_void": t_void, "via_parent": ck != k}
    return None


def author_warmups(seed: int, keys: dict, events: list[dict], views: list[dict], scripts: list[dict],
                   n: int = N_WARMUPS) -> list[dict]:
    rng = random.Random(sub_seed(seed, "warmup"))
    sess = [sc for sc in scripts if sc["index"] >= FIRST_WARMUP_SESSION]
    last_event_t = {}
    for e in events:
        if e.get("session"):
            last_event_t[e["session"]] = max(last_event_t.get(e["session"], ""), e["t"])
    change_t = {}
    for e in events:
        if e["type"] in CHANGE_TYPES and e.get("key"):
            change_t.setdefault(e["key"], []).append(e["t"])
    windows = transient_windows(events)
    out = []
    used = set()
    key_list = sorted(keys)
    guard = 0
    while len(out) < n:
        guard += 1
        if guard > 100_000:
            raise RuntimeError("could not author enough warm-ups")
        sc = sess[rng.randrange(len(sess))]
        t = add_minutes(sc["t_start"], WARMUP_OFFSET_MIN)
        assert last_event_t.get(sc["session"], "") < t, "warm-up must come after the session's events"
        weights = []
        for k in key_list:
            g = ledger.gold_at(views, k, t)
            if g["status"] == "absent":
                weights.append(0)
            else:
                changed = any(ct <= t for ct in change_t.get(k, []))
                weights.append(3 if changed else 1)
        if not any(weights):
            continue
        k = rng.choices(key_list, weights=weights, k=1)[0]
        if (k, sc["session"]) in used:
            continue
        used.add((k, sc["session"]))
        g = ledger.gold_at(views, k, t)
        spec = keys[k]
        tpl = WARM_TEMPLATES[rng.randrange(len(WARM_TEMPLATES))]
        gold = g["value"] if g["status"] == "active" else UNKNOWN
        out.append({
            "t": t, "after_session": sc["session"], "key": k, "subject": spec["subject"], "slot": spec["slot"],
            "task": tpl.format(s=spec["subject_name"], noun=SLOT_NOUN[spec["slot"]]),
            "gold_status": g["status"], "gold_exact": gold, "accept_exact": [normalize(gold)],
            "gold_fact_id": g["fact_id"], "view": g["view"], "grading": "exact-ledger-match",
        })
        tw = transient_tag(keys, views, windows, k, t)
        out[-1]["in_transient_window"] = tw is not None
        out[-1]["transient_window"] = tw
    out.sort(key=lambda r: (r["t"], r["key"]))
    for i, r in enumerate(out):
        r["id"] = f"w{i:02d}"
    return out


def grade_exact(row: dict, answer: str) -> bool:
    return normalize(answer) in row["accept_exact"]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stream", required=True)
    a = ap.parse_args(argv)
    d = Path(a.stream)
    m = read_json(d / "MANIFEST.json")
    world = read_json(d / "world.json")
    events = read_jsonl(d / "events.jsonl")
    views = ledger.views_from_gold(read_jsonl(d / "gold.jsonl"), m["views"])
    scripts = [{"session": s["session"], "index": i, "t_start": s["t_start"]} for i, s in enumerate(m["sessions"])]
    rows = author_warmups(m["seed"], world["keys"], events, views, scripts)
    same = [canon(r) for r in rows] == [canon(r) for r in read_jsonl(d / "warmup.jsonl")]
    print(f"warmups={len(rows)} identical_to_stream={same}")
    return 0 if same else 1


if __name__ == "__main__":
    sys.exit(main())
