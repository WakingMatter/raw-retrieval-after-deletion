"""E2 driver (DRAFT; the full run is NOT launched by this commit).

Per stream (all arms see the same post-delete world):
  1. time-ordered ingest of all 60 sessions into the A6E2 state and the RerankedRaw store;
  2. before each forget: the warm questions for that session are asked on the A6 state (write_back=True), so
     summaries/write-backs exist that the deletion must invalidate (RerankedRaw has no derived state; no warm);
  3. generator deletions forget at their scheduled times, the 6 E2 extra deletions at t_end after all ingest;
  4. 40 post-delete tasks x 3 arms at t_end: A6 (summaries served), A6-syn (same state, no header), RR.
Every probe writes its read trace. Resumable: every model call goes through the per-call file cache, so a rerun
replays cached calls (zero API cost) and continues where it stopped.

  python3 -m e2.run_e2 --tag DRY  --dry            # offline: fake answerer, exact call counts and prompt sizes
  python3 -m e2.run_e2 --tag DEV  --streams 7269001  # DEV only; confirmatory seeds need --confirm (after freeze)
"""
from __future__ import annotations
import argparse, json, threading, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from .paths import DATA, RUNS, PILOT
from pilot.common import render_prompt, SYNTH_PREFIX
from .arms_e2 import A6E2, RerankedRaw, Reranker, LLMAdapter, B_DEFAULT
from .tasks import score
from .make_data import CONFIRM, DEV
from .minimax_api import MiniMaxAPI

ARMS = ("A6", "A6-syn", "RR")


def load(seed):
    d = DATA / f"stream-{seed}"
    m = json.loads((d / "MANIFEST.json").read_text())
    sess = [(s["session"], s["t_start"]) for s in m["sessions"]]
    txt = {s: (d / "sessions" / f"{s}.md").read_text() for s, _ in sess}
    T = json.loads((DATA / f"tasks-{seed}.json").read_text())
    return dict(T, seed=seed, sessions=sess, text=txt)


def timeline(S):
    """(t, order, kind, session). Generator forgets precede a same-time ingest (pilot order);
    E2 extra deletions happen at t_end AFTER every ingest."""
    ev = [(t, 1, "ingest", s) for s, t in S["sessions"]]
    for s, t in S["forgets"].items():
        ev.append((t, 2 if s in S["extra_deleted"] else 0, "forget", s))
    return sorted(ev)


class FakeLLM:
    """Offline dry-run answerer: deterministic short answer, counts calls and prompt chars per role."""

    def __init__(self):
        self.rows, self.lock = [], threading.Lock()

    def call(self, role, prompt, model=None, schema=None, ctx=None):
        with self.lock:
            self.rows.append({"role": role, "prompt_chars": len(prompt), "ctx": {k: v for k, v in (ctx or {}).items()
                                                                                     if k in ("arm", "phase", "probe")}})
        text = ("Summary: " + prompt[-300:].replace("\n", " ")) if role == "synth" else "Not found."
        return {"ok": True, "text": text, "usage": {"input_tokens": 0, "output_tokens": 0}, "memo_hit": False,
                "latency_s": 0.0, "model_reported": "fake", "stop": "end_turn", "attempt_history": []}


def run_stream(seed, tag, llm, emb, anchors, reranker, B=B_DEFAULT, probe_threads=4):
    S = load(seed)
    out = RUNS / tag / f"stream-{seed}"
    done = out / "answers.jsonl"
    if done.exists():
        return {"seed": seed, "skipped": True}
    wd = out / "work"
    if wd.exists():                       # interrupted stream: rebuild state from scratch; model calls replay from cache
        import shutil; shutil.rmtree(wd)
    r0 = reranker.seconds if reranker else 0.0
    a6 = A6E2("A6", "F", wd / "A6", llm, emb, anchors)
    rr = RerankedRaw("RR", "F", wd / "RR", llm, emb, reranker)
    warm_by = {}
    for w in S["warm"]:
        warm_by.setdefault(w["before_forget"], []).append(w)
    log = {"warm": [], "forget": []}
    for t, _, kind, s in timeline(S):
        if kind == "ingest":
            a6.ingest(s, S["text"][s], t); rr.ingest(s, S["text"][s], t); continue
        for w in warm_by.get(s, []):
            r = a6.ask(w["question"], t, B, "warm", write_back=True, ctx={"probe": w["warm_id"], "seed": seed})
            log["warm"].append({"warm_id": w["warm_id"], "t": t, **{k: r.get(k) for k in ("answer", "ok", "wb_id", "trace")}})
        log["forget"].append({"session": s, "t": t, "A6": a6.forget(s, t, S["text"][s]), "RR": rr.forget(s, t)})
    # post-delete integrity: no surviving A6 unit/summary/write-back depends on a deleted session
    deleted = set(S["deleted"])
    dead_units = {u for u in a6.units if a6.units[u]["session"] in deleted}
    leak = sorted(dead_units) + [u for u, x in a6.units.items()
                                 if x["kind"] == "wb" and any(d.split(":")[0] in deleted for d in (x.get("derived_from") or ()))]
    leak += [f"summary:n{n:02d}" for n, c in a6.caches.items() if any(d.split(":")[0] in deleted for d in c["deps"])]
    leak += [c for c, x in rr.chunks.items() if x["session"] in deleted]
    if leak:                              # rev 5: deletion integrity is a hard precondition, not a log line
        raise RuntimeError(f"deletion integrity failed for {seed}: {leak[:5]}")
    jobs = [(tk, arm) for tk in S["tasks"] for arm in ARMS]

    def one(job):
        tk, arm = job
        ctx = {"probe": tk["task_id"], "seed": seed, "variant": arm}
        if arm == "RR":
            r = rr.ask(tk["question"], tk["t_query"], B, "probe", ctx=ctx)
        else:
            r = a6.ask(tk["question"], tk["t_query"], B, "probe", ctx=ctx, syn=(arm == "A6"))
        sc = score(tk, r["answer"] if (r["ok"] or r.get("stop") == "max_tokens") else None)   # prereg §6: truncations scored as returned, flagged
        return {"task_id": tk["task_id"], "cls": tk["cls"], "stratum": tk["stratum"], "deletion_touched": tk["deletion_touched"],
                "arm": arm, **{k: r.get(k) for k in ("answer", "ok", "served", "assembled_est", "trace", "usage", "stop",
                                                       "memo_hit", "cache_key", "prompt_chars")}, **sc}
    with ThreadPoolExecutor(probe_threads) as ex:
        rows = list(ex.map(one, jobs))
    out.mkdir(parents=True, exist_ok=True)
    stats = {"A6_calls": a6.stats["calls"], "RR_calls": rr.stats["calls"], "recompute": a6.recompute_log,
             "poison": a6.poison_log, "summaries": {f"n{n:02d}": {k: c.get(k) for k in ("key", "truncated", "cost_raw",
                                                                                     "cost_served", "t")}
                                                    for n, c in a6.caches.items()},
             "leak_units": leak, "reranker_seconds": reranker.seconds if reranker else None,
             "reranker_seconds_stream": round(reranker.seconds - r0, 3) if reranker else None,
             "reranker_seconds_note": "per-stream delta; exact when stream-threads=1 (enforced with --confirm)"}
    (out / "log.json").write_text(json.dumps(log, default=str, indent=1))
    (out / "stats.json").write_text(json.dumps(stats, default=str, indent=1))
    tmp = done.with_suffix(".tmp")
    tmp.write_text("".join(json.dumps(r, default=str) + "\n" for r in rows)); tmp.replace(done)   # completion marker
    return {"seed": seed, "n": len(rows)}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--streams", default="")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--confirm", action="store_true", help="allow confirmatory seeds (only after PREREG-E2 is frozen)")
    ap.add_argument("--stream-threads", type=int, default=4)
    ap.add_argument("--max-parallel", type=int, default=6)
    ap.add_argument("--B", type=int, default=B_DEFAULT)
    a = ap.parse_args(argv)
    seeds = [int(x) for x in a.streams.split(",") if x] or (CONFIRM if a.confirm else DEV)
    if not a.dry and any(s in CONFIRM for s in seeds):
        frozen = (Path(__file__).resolve().parents[2] / "prereg-E2" / "PREREG-E2.md")
        if not a.confirm or not frozen.exists():
            raise SystemExit("confirmatory E2 seeds require --confirm AND a frozen prereg-E2/PREREG-E2.md")
    if a.confirm:                         # rev 5 launch gates (Astra finding 3)
        from .make_freeze import verify_frozen
        bad = verify_frozen()
        if bad:
            raise SystemExit(f"freeze verification failed: {bad}")
        fr = json.loads((Path(__file__).resolve().parents[1] / "E2-FREEZE.json").read_text())
        allowed = set(fr["seeds"]["confirmatory_run"])
        if not set(seeds) <= allowed:
            raise SystemExit(f"--confirm seeds outside the frozen set: {sorted(set(seeds) - allowed)}")
        if a.B != B_DEFAULT or a.stream_threads != 1 or a.dry:
            raise SystemExit("--confirm requires B=B_DEFAULT, --stream-threads 1, no --dry")
        if json.loads((RUNS / fr["qualification_receipt"]).read_text()).get("verdict") != "PASS":
            raise SystemExit("qualification receipt is not PASS")
    from pilot.embed import Embedder
    from pilot.anchors import load_or_fit
    emb = Embedder(RUNS / "_vec")
    anchors_path = PILOT / "runs" / "anchors-7240240.npy"
    assert anchors_path.exists(), "frozen pilot anchors missing (E2 reuses them read-only)"
    anchors, _ = load_or_fit(emb, anchors_path)
    rr = Reranker()
    if a.dry:
        llm, api = FakeLLM(), None
    else:
        (RUNS / a.tag).mkdir(parents=True, exist_ok=True)
        api = MiniMaxAPI(RUNS / "_cache", max_parallel=a.max_parallel, log_path=RUNS / a.tag / "api-events.jsonl")
        llm = LLMAdapter(api)
    t0 = time.time()
    with ThreadPoolExecutor(a.stream_threads) as ex:
        res = list(ex.map(lambda s: run_stream(s, a.tag, llm, emb, anchors, rr, a.B), seeds))
    summ = {"tag": a.tag, "seeds": seeds, "wall_s": round(time.time() - t0, 1), "results": res}
    if a.dry:
        summ["dry_calls"] = llm.rows
    (RUNS / a.tag).mkdir(parents=True, exist_ok=True)
    (RUNS / a.tag / "summary.json").write_text(json.dumps(summ, indent=1, default=str))
    print(json.dumps({k: v for k, v in summ.items() if k != "dry_calls"}, default=str)[:2000])


if __name__ == "__main__":
    main()
