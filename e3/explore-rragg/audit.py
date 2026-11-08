"""Offline provenance audit of the E2 CONFIRM DERIVED tasks (zero API calls).

Reads E2 data and run outputs read-only: ledger (events + BRIDGE), tasks, answers.jsonl, A6/RR stores, stats.json,
log.json, render_trace. Local embedder/reranker only (pinned E2 models), used to rebuild RR's cosine top-50 and
reranked order, which is checked against E2's served list. Writes AUDIT.json here."""
from __future__ import annotations
import json, re, sqlite3, sys
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
RESEARCH = HERE.parents[1]
sys.path.insert(0, str(RESEARCH / "e2"))
from e2 import paths  # noqa: E402,F401
from e2.paths import DATA, RUNS  # noqa: E402
from e2.tasks import _merge  # noqa: E402
from e2.make_data import CONFIRM  # noqa: E402
from gen import ledger  # noqa: E402
from gen.probe_author import LedgerOnlyStream, value_regex  # noqa: E402
from pilot.arms import unit_vec  # noqa: E402

BASE = RUNS / "CONFIRM"
DO_RERANK = "--no-rerank" not in sys.argv


def rows_of(db, kind):
    con = sqlite3.connect(db)
    try:
        return {i: json.loads(b) for i, b in con.execute("select id, body from obj where kind=?", (kind,))}
    finally:
        con.close()


def leaves(by_id, fid):
    r = by_id[fid]
    if r["kind"] == "base":
        return [r]
    out = []
    for p in r.get("parents") or []:
        out += leaves(by_id, p)
    return out


def min_cover(sets):
    sets = [set(s) for s in sets]
    uni = sorted(set().union(*sets)) if sets else []
    for k in range(1, len(uni) + 1):
        for c in combinations(uni, k):
            if all(s & set(c) for s in sets):
                return k, list(c)
    return None, []


def main():
    from pilot.embed import Embedder
    emb = Embedder(RUNS / "_vec")
    rr_model = None
    if DO_RERANK:
        from e2.arms_e2 import Reranker
        rr_model = Reranker()
    out, leak_scan = [], []
    for seed in CONFIRM:
        d = DATA / f"stream-{seed}"
        st = LedgerOnlyStream(d)
        keys = st.world["keys"]
        T = json.loads((DATA / f"tasks-{seed}.json").read_text())
        deleted = set(T["deleted"])
        ev = _merge(st.events, json.loads((d / "BRIDGE.json").read_text())["events"])
        fin = ledger.compute_rows(ev, keys, deleted)
        v0 = ledger.compute_rows(ev, keys, set())
        by_id = {r["fact_id"]: r for r in fin}
        by_id0 = {r["fact_id"]: r for r in v0}
        ev_by_id = {e["id"]: e for e in ev}
        seg = {}
        for l in open(d / "render_trace.jsonl"):
            x = json.loads(l)
            for eid in x["event_ids"]:
                seg.setdefault(eid, []).append(f"{x['session']}:{x['seg'] + 1:03d}")
        for b in json.loads((d / "BRIDGE.json").read_text())["events"]:      # bridge sentences ride the anchor paragraph
            seg.setdefault(b["id"], seg.get(b["id"][:-1], []))
        sess_text = {p.stem: p.read_text() for p in (d / "sessions").glob("*.md")}
        wd = BASE / f"stream-{seed}" / "work"
        a6_raw = rows_of(wd / "A6" / "store.sqlite", "raw")
        a6_sum = rows_of(wd / "A6" / "store.sqlite", "summary")
        a6_wb = rows_of(wd / "A6" / "store.sqlite", "wb")
        rr_raw = rows_of(wd / "RR" / "store.sqlite", "raw")
        stats = json.loads((BASE / f"stream-{seed}" / "stats.json").read_text())
        log = json.loads((BASE / f"stream-{seed}" / "log.json").read_text())
        last_phase = {}
        for r in stats["recompute"]:
            if r["ok"]:
                last_phase[r["node"]] = (r["phase"], r["t"])
        forget_t = sorted(T["forgets"].values())
        ans = defaultdict(dict)
        for l in open(BASE / f"stream-{seed}" / "answers.jsonl"):
            r = json.loads(l)
            ans[r["task_id"]][r["arm"]] = r

        def lineage(dep_ids, seen=None):
            seen = set() if seen is None else seen
            s = set()
            for u in dep_ids:
                if u in seen:
                    continue
                seen.add(u)
                if u.startswith("wb:"):
                    w = a6_wb.get(u)
                    s |= {"<wb-missing>"} if w is None else lineage(w.get("derived_from") or [], seen)
                else:
                    s.add(u.split(":")[0])
            return s

        # residue scan: every final summary text vs value literals that survive nowhere but exist in deleted sessions
        values = sorted({e["value"] for e in ev if e.get("value") and len(str(e["value"])) >= 3}, key=len, reverse=True)
        surv_text = "\n".join(x["text"] for x in a6_raw.values())
        del_text = "\n".join(sess_text[s] for s in deleted if s in sess_text)
        for sid, sm in a6_sum.items():
            lin = lineage(sm["deps"])
            dep_text = "\n".join(a6_raw[u]["text"] for u in sm["deps"] if u in a6_raw)
            suspicious = []
            for v in values:
                rx = value_regex(v)
                if re.search(rx, sm["text"]) and not re.search(rx, dep_text):
                    suspicious.append({"value": v, "in_surviving_raw": bool(re.search(rx, surv_text)),
                                       "in_deleted_sessions": bool(re.search(rx, del_text))})
            leak_scan.append({"seed": seed, "summary": sid, "n_deps": len(sm["deps"]),
                              "deps_missing_from_store": sum(u not in a6_raw and not u.startswith("wb:") for u in sm["deps"]),
                              "lineage_deleted": sorted(lin & deleted), "last_phase": last_phase.get(int(sid[1:])),
                              "summary_t": sm.get("t"), "literals_not_in_deps": suspicious})

        chunk_ids = sorted(rr_raw)
        for tk in T["tasks"]:
            if tk["cls"] != "DERIVED":
                continue
            g = ledger.fact_at(fin, tk["key"], T["t_end"])
            g0 = ledger.fact_at(v0, tk["key"], T["t_end"])
            lv = leaves(by_id, g["fact_id"])
            leaf_info = []
            for f in lv:
                ch = sorted({c for e in f["evidence_events"] for c in seg.get(e, [])})
                leaf_info.append({"fact_id": f["fact_id"], "key": f["key"], "slot": keys[f["key"]]["slot"],
                                  "value": f["value"], "evidence_sessions": f["evidence_sessions"],
                                  "chunks": ch, "chunks_surviving": [c for c in ch if c in rr_raw],
                                  "value_in_chunk": [c for c in ch if c in rr_raw and re.search(value_regex(f["value"]), rr_raw[c]["text"])]})
            ev_sess = [set(l["evidence_sessions"]) for l in leaf_info]
            n_min, cover = min_cover(ev_sess)
            gold_rx = tk["truth_any"]
            sup_del = sorted(set(tk["support_sessions"]) & deleted)
            leaf_del = sorted(set().union(*ev_sess) & deleted)
            # explicit inference statements of this derived key
            inf = [{"session": e["session"], "value": e["value"], "deleted": e["session"] in deleted, "t": e["t"],
                    "chunks": seg.get(e["id"], [])} for e in ev if e.get("key") == tk["key"] and e.get("session")]
            # deletion-touched reasons
            reasons = []
            if (g0 or {}).get("value") != g["value"]:
                reasons.append("value_changed")
            if any(e.get("session") in deleted and e.get("key") == tk["key"] and e["type"] != "DISTRACTOR" for e in ev):
                reasons.append("key_event_in_deleted_session")
            if g0 and {s for x in leaves(by_id0, g0["fact_id"]) for s in x["evidence_sessions"]} & deleted:
                reasons.append("undeleted_gold_support_in_deleted")
            A6, RR = ans[tk["task_id"]]["A6"], ans[tk["task_id"]]["RR"]
            served_sum = []
            for ref in A6["trace"]["served_summaries"]:
                sid = ref.split(":", 1)[1]
                sm = a6_sum.get(sid, {})
                lin = lineage(sm.get("deps", []))
                served_sum.append({"ref": ref, "node": int(sid[1:]), "lineage_sessions": sorted(lin),
                                   "lineage_deleted": sorted(lin & deleted),
                                   "computed": last_phase.get(int(sid[1:])), "summary_t": sm.get("t"),
                                   "post_all_forgets": last_phase.get(int(sid[1:]), ("", ""))[0] == "probe",
                                   "gold_literal": any(re.search(x, sm.get("text", ""), re.I) for x in gold_rx),
                                   "leaf_chunks_in_deps": [c for l in leaf_info for c in l["chunks_surviving"] if c in set(sm.get("deps", []))],
                                   "text": sm.get("text")})
            hdr_gold = any(s["gold_literal"] for s in served_sum)
            # RR: rebuild cosine top-50 and reranked order; check against E2's served list
            qv = unit_vec(emb, tk["question"])
            cos = sorted(((c, float(unit_vec(emb, rr_raw[c]["text"]) @ qv)) for c in chunk_ids),
                         key=lambda z: (-round(z[1], 12), z[0]))
            cos_rank = {c: i + 1 for i, (c, _) in enumerate(cos)}
            top50 = [c for c, _ in cos[:50]]
            rr_rank, rr_repro = {}, None
            if rr_model:
                sc = rr_model.scores(tk["question"], [rr_raw[c]["text"] for c in top50])
                rk = [c for c, _ in sorted(zip(top50, sc), key=lambda z: (-round(z[1], 9), z[0]))]
                rr_rank = {c: i + 1 for i, c in enumerate(rk)}
                rr_repro = rk[:len(RR["served"])] == RR["served"]
            rr_served, a6_served = set(RR["served"]), set(A6["served"])
            for l in leaf_info:
                l["rr"] = [{"chunk": c, "cos_rank": cos_rank.get(c), "in_top50": c in top50,
                            "rerank_rank": rr_rank.get(c), "served": c in rr_served} for c in l["chunks_surviving"]]
                l["rr_any_served"] = any(x["served"] for x in l["rr"])
                l["rr_any_top50"] = any(x["in_top50"] for x in l["rr"])
                l["a6_raw_any_served"] = any(c in a6_served for c in l["chunks_surviving"])
                l["a6_header_dep"] = any(c in s["leaf_chunks_in_deps"] for s in served_sum for c in l["chunks_surviving"])
            inf_surv_gold = [x for x in inf if not x["deleted"] and x["value"] == g["value"]]
            out.append({"task_id": tk["task_id"], "seed": seed, "question": tk["question"], "gold": tk["gold"],
                        "deletion_touched": tk["deletion_touched"], "touched_reasons": reasons,
                        "gold_undeleted": (g0 or {}).get("value"), "hdr_gold": hdr_gold,
                        "A6": A6["correct"], "RR": RR["correct"], "A6syn": ans[tk["task_id"]]["A6-syn"]["correct"],
                        "A6_answer": A6["answer"][:200], "RR_answer": RR["answer"][:200],
                        "support_sessions": tk["support_sessions"], "support_deleted": sup_del, "leaf_sessions_deleted": leaf_del,
                        "leaves": leaf_info, "min_sessions_needed": n_min, "min_cover": cover,
                        "inference_statements": inf, "surviving_inference_states_gold": bool(inf_surv_gold),
                        "served_summaries": served_sum, "rr_rerank_reproduced": rr_repro,
                        "rr_n_served": len(RR["served"]), "integrity_leak_units_E2": stats["leak_units"]})
        print(seed, len(out), flush=True)
    (HERE / "AUDIT.json").write_text(json.dumps({"tasks": out, "summary_scan": leak_scan}, indent=1, default=str))


if __name__ == "__main__":
    main()
