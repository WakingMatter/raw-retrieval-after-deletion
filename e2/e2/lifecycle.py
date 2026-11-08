"""Per-stream lifecycle metering and A6 header gold coverage (rev 5, Astra findings 5 and 8). Model-free; reads
stats.json, answers.jsonl and the call cache only."""
from __future__ import annotations
import json, re
from collections import defaultdict
from .paths import RUNS

CLASSES = ("AGG", "DERIVED", "MULTIHOP", "CURRENT")


def stream_cost(st: dict) -> dict:
    """Nominal lifecycle cost of one stream, cache hits counted at their recorded usage (a cache hit is not free work,
    it is a replay). A6 covers warm state + synthesis + both A6 arms' answers (the shared warm state is charged to both
    A6 arms, never to RR); RR covers RR answers plus local reranker seconds."""
    def tok(calls):
        return sum((c.get("in") or 0) + (c.get("out") or 0) for c in calls)
    a6, rr = st.get("A6_calls", []), st.get("RR_calls", [])
    return {"A6_tokens": tok(a6), "A6_calls": len(a6),
            "A6_synth_calls": sum(c.get("role") == "synth" for c in a6),
            "RR_tokens": tok(rr), "RR_calls": len(rr),
            "reranker_seconds": round(st.get("reranker_seconds") or 0, 1)}


def _final_summaries(work) -> dict:
    import sqlite3
    f = work / "A6" / "store.sqlite"
    if not f.exists():
        return {}
    con = sqlite3.connect(f)
    try:
        return {i: json.loads(b).get("text") or "" for i, b in con.execute("select id, body from obj where kind='summary'")}
    finally:
        con.close()


def header_gold_coverage(rows: list[dict], base) -> dict:
    """Share of A6 probes whose served summaries contain the gold literal (truth_any regex), reconstructed from the
    FINAL served (post-cap) summary text of each node in the stream's A6 store (probes run after deletion, so this
    approximates what was served). AGG gold is a count, so AGG is excluded. Literal presence is not entailment;
    descriptive only."""
    tasks, summ = {}, {}
    for seed in {r["seed"] for r in rows}:
        f = RUNS.parent / "data" / f"tasks-{seed}.json"
        tasks.update({t["task_id"]: t for t in json.loads(f.read_text())["tasks"]})
        summ[seed] = _final_summaries(base / f"stream-{seed}" / "work")
    out = defaultdict(lambda: {"n": 0, "gold_in_header": 0})
    for r in rows:
        if r["arm"] != "A6" or r["cls"] == "AGG":
            continue
        tk = tasks[r["task_id"]]
        texts = [summ[r["seed"]].get(sid.split(":", 1)[-1], "") for sid in (r.get("trace") or {}).get("served_summaries") or []]
        hit = any(re.search(x, t, re.I) for t in texts for x in tk["truth_any"])
        o = out[r["cls"]]; o["n"] += 1; o["gold_in_header"] += hit
    return dict(out)
