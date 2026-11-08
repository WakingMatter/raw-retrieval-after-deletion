"""E4 real driver (MiniMax-M3.1-Flash, Token Plan). Frozen by e4/make_freeze.py; see PREREG-E4.md and DEFAULTS.md.

    python3 -m e4.run_e4 --phase main --streams 7280001,... --vec _vec-p0 --tag CONFIRM [--confirm]
    python3 -m e4.run_e4 --phase t4   --streams ...         --vec _vec-p0 --tag CONFIRM [--confirm]

phase main: one pass per stream over T1 (B ladder), F0 (B=125), T5 (RR-K) and T2/T3 (cap x share) cells.
phase t4:   rebuild the same post-delete state (warm replayed from the response cache), then re-synthesize the
            probe-time summaries with the length-instructed prompts and answer at the matching serving cells.
Per stream the order is fixed and staged so the reranker runs only on the main thread (exact compute accounting):
  build+warm+forget -> integrity -> materialize summaries (threads) -> hop-1 / RR-K ranking (main)
  -> bridge calls (threads) -> hop-2 ranking (main) -> all answer calls (threads).
Every row is written; a failed call scores as wrong (never dropped)."""
from __future__ import annotations
import argparse, json, math, threading, time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from .paths import DATA, RUNS, PILOT
from .arms_e4 import A6E4, bridge_prompt_generic
from .dry_run import load, a6_cells, B_LADDER, SHARES, REF
from e2.arms_e2 import RerankedRaw, Reranker, LLMAdapter, E2_PREFIX, SYN_WORDS, sha, cache_key, input_set_hash, MODEL
from e2.run_e2 import timeline
from e2.tasks import score
from e2.minimax_api import MiniMaxAPI
from e3.rr2hop import ranked, interleave, parse_entity, hop2_query
from pilot.common import fill, item_cost, render_prompt

B_CAP = [125]                                   # F0 capacity rung (DEFAULTS D04)
B_ALL = B_CAP + B_LADDER                        # [125, 500, 1000, 2000, 4000, 8000]
F0_CELLS = [(125, "1/5", 25.0), (125, "2/5", 50.0)]
RRK_B = [4000, 8000]
K_MIN, K_MAX = 50, 600
T4_VARIANTS = {"len100": (100, 50), "len400": (400, 200)}   # serving cap -> requested words (DEFAULTS D10)
WORKERS = 6


def rrk_K(B, cbar):
    return int(min(K_MAX, max(K_MIN, math.ceil(2 * B / cbar))))


class A6Run(A6E4):
    """A6E4 whose summaries are materialized once per (input set) and then frozen: a failed synth is retried once
    during materialization and is otherwise served as 'none' in every cell (no order-dependent later retries)."""
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.store, self.frozen, self.misses, self.slock = {}, False, [], threading.Lock()
        self.force_none = set()          # keys that failed in an earlier pass of the same stream stay 'none' (D07)

    def summary(self, n, t_query, phase):
        with self._node_lock(n):
            ids = self._input_set(n, t_query)
            if len(ids) < 2:
                return None
            key = self._key(ids)
            if key in self.store:
                return self.store[key]
            if key in self.force_none:
                self.store[key] = None; return None
            if self.frozen:
                self.misses.append({"node": n, "key": key}); return None
            c = self._compute_summary(n, t_query, phase) or self._compute_summary(n, t_query, phase)
            self.store[key] = c
            return c


def integrity(seed, S, a6, rr):
    """E2 run_e2 post-delete check (units, write-back provenance, summary deps, RR chunks)."""
    deleted = set(S["deleted"])
    leak = sorted(u for u in a6.units if a6.units[u]["session"] in deleted)
    leak += [u for u, x in a6.units.items()
             if x["kind"] == "wb" and any(d.split(":")[0] in deleted for d in (x.get("derived_from") or ()))]
    leak += [f"summary:n{n:02d}" for n, c in a6.caches.items() if any(d.split(":")[0] in deleted for d in c["deps"])]
    leak += [c for c, x in rr.chunks.items() if x["session"] in deleted]
    if leak:
        raise RuntimeError(f"deletion integrity failed for {seed}: {leak[:5]}")


def build(seed, llm, emb, anchors, rer, wd):
    S = load(seed)
    a6 = A6Run("A6", "F", wd / "A6", llm, emb, anchors)
    a6.ctx_extra = {"arm": "A6", "seed": seed}
    rr = RerankedRaw("RR", "F", wd / "RR", llm, emb, rer)
    warm_by = {}
    for w in S["warm"]:
        warm_by.setdefault(w["before_forget"], []).append(w)
    for t, _, kind, s in timeline(S):
        if kind == "ingest":
            a6.ingest(s, S["text"][s], t); rr.ingest(s, S["text"][s], t); continue
        for w in warm_by.get(s, []):
            a6.ask(w["question"], t, REF[0], "warm", write_back=True,
                   ctx={"probe": w["warm_id"], "seed": seed, "arm": "A6", "cell": "warm"})
        a6.forget(s, t, S["text"][s]); rr.forget(s, t)
    integrity(seed, S, a6, rr)
    return S, a6, rr


def top_nodes(a6, q):
    from pilot.arms import unit_vec
    qv = unit_vec(a6.emb, q)
    nodes = [n for n in range(a6.add.k) if a6.add.count[n] > 0]
    nodes.sort(key=lambda n: (-float(a6.add.centroid(n) @ qv), n))
    return nodes[:3]


def materialize(a6, S, ex):
    jobs = sorted({(n, tk["t_query"]) for tk in S["tasks"] for n in top_nodes(a6, tk["question"])})
    list(ex.map(lambda j: a6.summary(j[0], j[1], "probe"), jobs))
    a6.frozen = True
    return [{"node": n, "key": c["key"], "deps": c["deps"], "raw": c.get("raw"), "raw_sha": sha(c.get("raw") or ""),
             "cost_raw": c["cost_raw"], "soft_poison": c["soft_poison"]} if c else
            {"node": n, "failed": True, "key": a6._key(a6._input_set(*j)) if len(a6._input_set(*j)) >= 2 else None}
            for j, c in ((j, a6.store.get(a6._key(a6._input_set(*j)))) for j in jobs) for n in (j[0],)]


def timed_rank(rer, *a, **kw):
    r0, c0 = rer.seconds, time.process_time()
    out = ranked(*a, **kw)
    return out, rer.seconds - r0, time.process_time() - c0


def answer_row(llm, texts, tk, ctx):
    t0 = time.time()
    r = llm.call("answer", render_prompt(texts, tk["question"], E2_PREFIX), ctx=ctx)
    return r, time.time() - t0


def run_main(seed, llm, emb, anchors, rer, out, tiers, wd_name=None, force_none=()):
    """tiers: T1 (also runs F0 and every comparator at every B, incl. bridge), T5 (RR-K), T2, T3. A later pass of the
    same stream (e.g. T2,T3 after T1,F0,T5) passes the earlier pass's failed summary keys in force_none."""
    t_start = time.time()
    S, a6, rr = build(seed, llm, emb, anchors, rer, out / (wd_name or f"work-{seed}"))
    a6.force_none = set(force_none)
    t_built = time.time()
    ex = ThreadPoolExecutor(WORKERS)
    summaries = materialize(a6, S, ex)
    t_mat = time.time()
    live = [x for x in rr.chunks.values() if x["t"] <= S["tasks"][0]["t_query"]]
    cbar = sum(item_cost(f"[c | {x['t'][:16]}] {x['text']}") for x in live) / len(live)
    Ks = {B: rrk_K(B, cbar) for B in RRK_B}
    rank_acct = defaultdict(lambda: [0.0, 0.0])          # arm -> [reranker wall-s, process CPU-s]
    h1, hk = {}, {}
    for tk in S["tasks"]:
        if "T1" in tiers:
            h1[tk["task_id"]], w, c = timed_rank(rer, rr.chunks, emb, rer, tk["question"], tk["t_query"])
            rank_acct["RR"][0] += w; rank_acct["RR"][1] += c
        if "T5" in tiers:
            for B, K in Ks.items():
                hk[(tk["task_id"], B)], w, c = timed_rank(rer, rr.chunks, emb, rer, tk["question"], tk["t_query"], top_k=K)
                rank_acct["RR-K"][0] += w; rank_acct["RR-K"][1] += c
    t_rank1 = time.time()
    by_id = {tk["task_id"]: tk for tk in S["tasks"]}
    # bridge calls (threads)
    def bridge(j):
        tid, B = j; tk = by_id[tid]
        served, _ = fill(h1[tid], B)
        t0 = time.time()
        r = llm.call("bridge", bridge_prompt_generic(tk["question"], [it["text"] for it in served]),
                     ctx={"probe": tid, "seed": seed, "arm": "RR-2hop", "cell": f"B{B}"})
        return j, r, time.time() - t0
    bjobs = [(tid, B) for tid in by_id for B in B_ALL] if "T1" in tiers else []
    bres = {j: (r, dt) for j, r, dt in ex.map(bridge, bjobs)}
    ents = {j: (parse_entity(r.get("text")) if r.get("ok") else None) for j, (r, _) in bres.items()}
    t_bridge = time.time()
    h2 = {}
    for (tid, B), e in sorted(ents.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        if e and (tid, e) not in h2:
            h2[(tid, e)], w, c = timed_rank(rer, rr.chunks, emb, rer, hop2_query(e, by_id[tid]["question"]),
                                            by_id[tid]["t_query"])
            rank_acct["RR-2hop"][0] += w; rank_acct["RR-2hop"][1] += c
    t_rank2 = time.time()
    # answer jobs
    cells = a6_cells()
    jobs = []
    for tid in by_id:
        if "T1" in tiers:
            for B in B_ALL:
                jobs += [("RR", tid, B, None), ("RR-2hop", tid, B, None), ("A6-syn", tid, B, None)]
            for B in B_LADDER:
                jobs.append(("A6", tid, B, (B, "1/5", min(200.0, B * 0.2))))
            for c in F0_CELLS:
                jobs.append(("A6", tid, 125, c))
        if "T5" in tiers:
            jobs += [("RR-K", tid, B, None) for B in RRK_B]
        for (B, sh, ec), meta in cells.items():
            if meta["tier"] in (2, 3) and f"T{meta['tier']}" in tiers:
                jobs.append(("A6", tid, B, (B, sh, ec)))
    def one(j):
        arm, tid, B, cell = j; tk = by_id[tid]
        cname = f"B{B}" if cell is None else f"B{B}|{cell[1]}|{cell[2]:g}"
        ctx = {"probe": tid, "seed": seed, "arm": arm, "cell": cname}
        t0 = time.time(); extra = {}
        if arm == "RR":
            served, _ = fill(h1[tid], B); r, _ = answer_row(llm, [it["text"] for it in served], tk, ctx)
        elif arm == "RR-K":
            served, _ = fill(hk[(tid, B)], B); r, _ = answer_row(llm, [it["text"] for it in served], tk, ctx)
            extra = {"K": Ks[B], "pool_exhausted": len(served) == len(hk[(tid, B)])}
        elif arm == "RR-2hop":
            e = ents[(tid, B)]
            pool = interleave(h1[tid], h2[(tid, e)]) if e else h1[tid]
            served, _ = fill(pool, B); r, _ = answer_row(llm, [it["text"] for it in served], tk, ctx)
            extra = {"entity": e, "bridge_raw": (bres[(tid, B)][0].get("text") or "")[:160],
                     "bridge_usage": bres[(tid, B)][0].get("usage"), "bridge_memo": bres[(tid, B)][0].get("memo_hit"),
                     "bridge_s": round(bres[(tid, B)][1], 3)}
        else:
            syn = arm == "A6"
            Bc, sh, ec = cell if syn else (B, "1/5", min(200.0, B * 0.2))
            res = a6.ask_cell(tk["question"], tk["t_query"], Bc, SHARES[sh], ec, "probe", ctx=ctx, syn=syn)
            r = {"text": res["answer"], "ok": res["ok"], "usage": res["usage"], "memo_hit": None}
            tr = res["trace"]
            extra = {"header_est": tr["header_tokens_est"], "raw_est": tr["raw_tokens_est"],
                     "n_sum_served": sum(1 for x in tr["nodes"] if x["status"] == "served"),
                     "pool_exhausted": tr["pool_exhausted"]}
        dt = time.time() - t0
        ans = (r.get("text") or "").strip() if r.get("ok") else None
        return {"seed": seed, "task_id": tid, "cls": tk["cls"], "arm": arm, "B": B, "cell": cname,
                "ok": bool(r.get("ok")), "correct": score(tk, ans)["correct"], "answer": (ans or "")[:300],
                "usage": r.get("usage"), "memo_hit": r.get("memo_hit"), "elapsed_s": round(dt, 3), **extra}
    rows = list(ex.map(one, jobs))
    ex.shutdown()
    t_end = time.time()
    return {"seed": seed, "phase": "main", "tiers": sorted(tiers), "rows": rows, "summaries": summaries,
            "summary_misses": a6.misses, "cbar": cbar, "K": Ks, "rerank": {k: [round(v[0], 2), round(v[1], 2)] for k, v in rank_acct.items()},
            "rerank_total_s": round(rer.seconds, 2),
            "wall": {"build_warm": round(t_built - t_start, 1), "materialize": round(t_mat - t_built, 1),
                     "rank_hop1_K": round(t_rank1 - t_mat, 1), "bridge": round(t_bridge - t_rank1, 1),
                     "rank_hop2": round(t_rank2 - t_bridge, 1), "answers": round(t_end - t_rank2, 1),
                     "total": round(t_end - t_start, 1)},
            "a6_warm_wb": a6.wb_n, "n_units": len(a6.units)}


def run_t4(seed, llm, emb, anchors, rer, out, wd_name=None):
    t_start = time.time()
    S, a6, rr = build(seed, llm, emb, anchors, rer, out / (wd_name or f"work-t4-{seed}"))
    ref_prompt = a6.syn_prompt
    phrase = f"≤ {SYN_WORDS} words"
    assert phrase in ref_prompt
    rows, comp = [], {}
    for name, (cap, words) in T4_VARIANTS.items():
        a6.syn_prompt = ref_prompt.replace(phrase, f"≤ {words} words, and keep your whole reply under {cap} tokens")
        a6.syn_prompt_sha = sha(a6.syn_prompt)
        a6.store, a6.frozen, a6.caches = {}, False, {}
        a6.ctx_extra = {"arm": "A6-T4", "seed": seed, "cell": name}
        ex = ThreadPoolExecutor(WORKERS)
        t0 = time.time()
        sums = materialize(a6, S, ex)
        comp[name] = {"n": len(sums), "failed": sum(1 for s in sums if s.get("failed")),
                      "within_cap": sum(1 for s in sums if not s.get("failed") and s["cost_raw"] <= cap),
                      "cost_raw": [s.get("cost_raw") for s in sums], "summaries": sums,
                      "materialize_s": round(time.time() - t0, 1)}
        def one(tk):
            ctx = {"probe": tk["task_id"], "seed": seed, "arm": "A6-T4", "cell": f"{name}|B2000|1/5|{cap}"}
            t1 = time.time()
            res = a6.ask_cell(tk["question"], tk["t_query"], 2000, 0.2, float(cap), "probe", ctx=ctx)
            ans = res["answer"] if res["ok"] else None
            return {"seed": seed, "task_id": tk["task_id"], "cls": tk["cls"], "arm": "A6-T4", "B": 2000,
                    "cell": f"{name}|B2000|1/5|{cap}", "ok": bool(res["ok"]), "correct": score(tk, ans)["correct"],
                    "answer": (ans or "")[:300], "usage": res["usage"], "elapsed_s": round(time.time() - t1, 3),
                    "header_est": res["trace"]["header_tokens_est"]}
        rows += list(ex.map(one, S["tasks"])); ex.shutdown()
    return {"seed": seed, "phase": "t4", "rows": rows, "compliance": comp, "summary_misses": a6.misses,
            "wall": {"total": round(time.time() - t_start, 1)}}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", choices=["main", "t4"], default="main")
    ap.add_argument("--tiers", default="T1,F0,T5,T2,T3")
    ap.add_argument("--streams", required=True)
    ap.add_argument("--vec", default="_vec")
    ap.add_argument("--tag", default="CONFIRM")
    ap.add_argument("--max-parallel", type=int, default=3)
    ap.add_argument("--confirm", action="store_true")
    a = ap.parse_args(argv)
    seeds = [int(x) for x in a.streams.split(",") if x]
    if a.confirm:
        from .make_freeze import verify_frozen, frozen_streams
        bad = verify_frozen()
        assert not bad, f"freeze mismatch: {bad}"
        assert set(seeds) <= set(frozen_streams()), "confirmatory seeds must be the frozen planned streams"
    from pilot.embed import Embedder
    from pilot.anchors import load_or_fit
    out = RUNS / a.tag; out.mkdir(parents=True, exist_ok=True)
    api = MiniMaxAPI(RUNS / "_cache", max_parallel=a.max_parallel, log_path=out / f"api-events-{a.vec}.jsonl")
    llm = LLMAdapter(api)
    emb = Embedder(RUNS / a.vec)
    anchors, _ = load_or_fit(emb, PILOT / "runs" / "anchors-7240240.npy")
    rer = Reranker(threads=4)
    tiers = set(a.tiers.split(","))
    label = a.phase if a.phase == "t4" else "main" + ("" if "T1" in tiers else "-" + "_".join(sorted(tiers)))
    for s in seeds:
        f = out / f"{label}-{s}.json"
        if f.exists():
            print("skip (done)", f.name, flush=True); continue
        wd = out / (f"work-{label}-{s}")
        if wd.exists():                         # resume after a crash: keep the partial store, start the stream fresh
            wd.rename(wd.with_name(f"{wd.name}.partial-{int(time.time())}"))
        if a.phase == "main":
            prev = out / f"main-{s}.json"
            fn = [x["key"] for x in json.loads(prev.read_text())["summaries"] if x.get("failed") and x.get("key")] \
                if label != "main" and prev.exists() else []
            assert label == "main" or prev.exists(), "run the T1 pass of a stream before its later passes"
            r = run_main(s, llm, emb, anchors, rer, out, tiers, wd_name=f"work-{label}-{s}", force_none=fn)
        else:
            assert (out / f"main-{s}.json").exists(), "T4 replays the main pass's warm state from the cache"
            r = run_t4(s, llm, emb, anchors, rer, out, wd_name=f"work-{label}-{s}")
        r["live_calls_process"] = api.live_calls; r["pauses"] = api.gate.pauses
        tmp = f.with_suffix(".tmp"); tmp.write_text(json.dumps(r, default=str)); tmp.replace(f)
        print(json.dumps({"seed": s, "phase": a.phase, "wall": r["wall"], "n_rows": len(r["rows"]),
                          "acc": round(sum(x["correct"] for x in r["rows"]) / len(r["rows"]), 3)}), flush=True)


if __name__ == "__main__":
    main()
