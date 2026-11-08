"""E4 offline dry run: ZERO model API calls. Replays every planned cell with a fake LLM and counts the calls the real run
would make after response-cache de-duplication (identical role+prompt => one call), per tier/arm/cell.

Fake synth text has a realistic LENGTH: its est. token cost is drawn (by prompt hash) from the 401 real E2 CONFIRM
summary costs, so the cap/header truncation and cell collapsing behave as they would with real summaries. Fake
answers are "Not found."; so fake write-backs and the fake bridge (always NONE) differ from a real run -- RR-2hop
answer calls and hop-2 reranks are therefore reported as upper bounds, not dry-run counts.

Also measures, per task: gold-support cost (ledger evidence paragraphs, Astra audit method), RR top-50 pool cost and
A6 raw pool cost (does a bigger B add anything?), reranker and embedder seconds (4 torch threads, 1 process)."""
from __future__ import annotations
import argparse, glob, hashlib, json, threading, time
from bisect import bisect_left
from .paths import DATA, RUNS, PILOT, E2_RUNS, planned_streams
from .arms_e4 import A6E4, eff_cap, bridge_prompt_generic
from e2.arms_e2 import RerankedRaw, Reranker, E2_PREFIX
from e2.run_e2 import timeline
from e2.tasks import ledger, _merge
from e3.rr2hop import ranked
from pilot.common import fill, item_cost

B_LADDER = [500, 1000, 2000, 4000, 8000]
CAPS = [100, 200, 400, None]              # None = uncapped-within-header
SHARES = {"1/5": 0.2, "2/5": 0.4}
REF = (2000, "1/5", 200)                  # E2 reference config: warm phase + tier-1 cap/share


def a6_cells():
    """Unique A6 cells (B, share, eff_cap) with the nominal cells that collapse onto each, and their tier."""
    cells = {}
    for B in B_LADDER:
        for sh, f in SHARES.items():
            for cap in CAPS:
                k = (B, sh, eff_cap(B, cap, f))
                cells.setdefault(k, []).append(cap)
    def tier(k):
        B, sh, ec = k
        if sh == "1/5" and ec == eff_cap(B, 200, 0.2):
            return 1
        return 2 if B in (1000, 2000, 4000) else 3
    return {k: {"nominal_caps": v, "tier": tier(k)} for k, v in cells.items()}


class FakeLLM:
    def __init__(self):
        self.rows, self.lock = [], threading.Lock()
        costs = sorted(v["cost_raw"] for f in glob.glob(str(E2_RUNS / "CONFIRM" / "stream-*" / "stats.json"))
                       for v in json.load(open(f))["summaries"].values() if v.get("cost_raw"))
        assert len(costs) == 401, len(costs)
        self.costs = costs

    def _fake_summary(self, prompt):
        h = int(hashlib.sha256(prompt.encode()).hexdigest()[:12], 16)
        target = self.costs[h % len(self.costs)]
        words = [w for w in prompt[-4000:].split() if w.isalpha()] or ["fact"]
        out, i = [], h
        while item_cost("[summary:n00] " + " ".join(out)) < target:
            sent = [words[(i + j) % len(words)] for j in range(12)]
            out.append(" ".join(sent).capitalize() + "."); i = i * 6364136223846793005 % (1 << 61) + 7
        return " ".join(out)

    def call(self, role, prompt, model=None, schema=None, ctx=None):
        with self.lock:
            self.rows.append({"role": role, "h": hashlib.sha256((role + "\x00" + prompt).encode()).hexdigest()[:20],
                              "chars": len(prompt), "ctx": {k: v for k, v in (ctx or {}).items()
                                                           if k in ("arm", "variant", "phase", "cell", "tier", "probe")}})
        text = self._fake_summary(prompt) if role == "synth" else ("NONE" if role == "bridge" else "Not found.")
        return {"ok": True, "text": text, "usage": {"input_tokens": 0, "output_tokens": 0}, "memo_hit": False,
                "latency_s": 0.0, "model_reported": "fake", "stop": "end_turn", "attempt_history": []}


def load(seed):
    d = DATA / f"stream-{seed}"
    m = json.loads((d / "MANIFEST.json").read_text())
    sess = [(s["session"], s["t_start"]) for s in m["sessions"]]
    txt = {s: (d / "sessions" / f"{s}.md").read_text() for s, _ in sess}
    T = json.loads((DATA / f"tasks-{seed}.json").read_text())
    return dict(T, seed=seed, sessions=sess, text=txt)


def support_costs(seed):
    """Astra E2 audit method (audit_semantics.py:17-34): union of ledger evidence paragraphs for the gold fact(s)."""
    d = DATA / f"stream-{seed}"
    rd = lambda p: json.loads(p.read_text())
    rows = lambda p: [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
    T, W, M, E, Br = rd(DATA / f"tasks-{seed}.json"), rd(d / "world.json"), rd(d / "MANIFEST.json"), \
        rows(d / "events.jsonl"), rd(d / "BRIDGE.json")
    merged = _merge(E, Br["events"]); F = ledger.compute_rows(merged, W["keys"], set(T["deleted"]))
    byid = {f["fact_id"]: f for f in F}; map_p = {}
    for rt in rows(d / "render_trace.jsonl"):
        for eid in rt["event_ids"]:
            map_p[eid] = (rt["session"], rt["seg"])
    for e in Br["events"]:
        map_p[e["id"]] = map_p[e["after"]]
    txt = {f.stem: f.read_text().rstrip("\n").split("\n\n") for f in (d / "sessions").glob("*.md")}
    starts = {s["session"]: s["t_start"] for s in M["sessions"]}

    def refs_for(f):
        out = set(map_p[e] for e in f["evidence_events"] if e in map_p)
        for pid in f.get("parents", []):
            out |= refs_for(byid[pid])
        return out
    res = {}
    for tk in T["tasks"]:
        facts = ([f for f in F if f["key"] == tk["key"] and f["value"] and f["valid_from"] <= T["t_end"]]
                 if tk["cls"] == "AGG" else [ledger.fact_at(F, tk["key"], T["t_end"])])
        if tk["cls"] == "MULTIHOP":
            facts.append(ledger.fact_at(F, tk["hop_key"], T["t_end"]))
        refs = set().union(*(refs_for(f) for f in facts))
        res[tk["task_id"]] = sum(item_cost(f"[{sid}:{seg + 1:03d} | {starts[sid][:16]}] {txt[sid][seg]}")
                                 for sid, seg in refs)
    return res


def run_stream(seed, llm, emb, anchors, rer, out):
    from pathlib import Path
    S = load(seed)
    wd = out / f"stream-{seed}" / "work"
    if wd.exists():
        import shutil; shutil.rmtree(wd)
    t0, r0 = time.time(), rer.seconds
    a6 = A6E4("A6", "F", wd / "A6", llm, emb, anchors)
    rr = RerankedRaw("RR", "F", wd / "RR", llm, emb, rer)
    warm_by = {}
    for w in S["warm"]:
        warm_by.setdefault(w["before_forget"], []).append(w)
    for t, _, kind, s in timeline(S):
        if kind == "ingest":
            a6.ingest(s, S["text"][s], t); rr.ingest(s, S["text"][s], t); continue
        for w in warm_by.get(s, []):     # warm ONCE at the reference config (B=2000, 1/5, cap 200 == A6E2.read)
            a6.ask(w["question"], t, REF[0], "warm", write_back=True, ctx={"probe": w["warm_id"]})
        a6.forget(s, t, S["text"][s]); rr.forget(s, t)
    t_ingest = time.time() - t0
    deleted = set(S["deleted"])
    assert not [u for u in a6.units if a6.units[u]["session"] in deleted], "deletion integrity"
    assert not [c for c, x in rr.chunks.items() if x["session"] in deleted], "deletion integrity"
    cells = a6_cells(); sup = support_costs(seed); per_task = []
    r_probe0 = rer.seconds
    for tk in S["tasks"]:
        q, tq, tid = tk["question"], tk["t_query"], tk["task_id"]
        row = {"task_id": tid, "cls": tk["cls"], "support_est": sup[tid], "a6_pool": None, "rr_pool": None}
        h1 = ranked(rr.chunks, emb, rer, q, tq)                  # rerank once per task; B only changes the fill
        row["rr_pool"] = sum(item_cost(it["text"]) for it in h1)
        for B in B_LADDER:
            served, _ = fill(h1, B)
            rr.answer(served, q, "probe", E2_PREFIX, ctx={"probe": tid, "cell": f"B{B}", "tier": 1})
            llm.call("bridge", bridge_prompt_generic(q, [it["text"] for it in served]),
                     ctx={"arm": "RR-2hop", "probe": tid, "cell": f"B{B}", "tier": 1})
            r = a6.ask_cell(q, tq, B, 0.2, None, "probe", ctx={"probe": tid, "cell": f"B{B}", "tier": 1, "variant": "A6-syn"},
                            syn=False)                           # A6-syn (no header) diagnostic: depends on B only
        for (B, sh, ec), meta in sorted(cells.items(), key=lambda kv: (kv[1]["tier"], kv[0][0], kv[0][1], kv[0][2])):
            r = a6.ask_cell(q, tq, B, SHARES[sh], ec, "probe",
                            ctx={"probe": tid, "cell": f"B{B}|{sh}|{ec:g}", "tier": meta["tier"]})
            if (B, sh, ec) == (2000, "1/5", 200):
                row["a6_pool"] = r["trace"]["raw_pool_est"]
        per_task.append(row)
    return {"seed": seed, "wall_s": round(time.time() - t0, 1), "ingest_warm_s": round(t_ingest, 1),
            "rerank_s_total": round(rer.seconds - r0, 2), "rerank_s_probe_hop1": round(rer.seconds - r_probe0, 2),
            "n_tasks": len(S["tasks"]), "tasks": per_task, "n_summaries": len(a6.caches),
            "a6_warm_wb": a6.wb_n}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="DRY")
    ap.add_argument("--streams", default="")
    ap.add_argument("--vec", default="_vec")
    a = ap.parse_args(argv)
    seeds = [int(x) for x in a.streams.split(",") if x] or planned_streams()
    from pilot.embed import Embedder
    from pilot.anchors import load_or_fit
    emb = Embedder(RUNS / a.vec)
    anchors, _ = load_or_fit(emb, PILOT / "runs" / "anchors-7240240.npy")
    rer = Reranker(threads=4)                       # <= 4 reranker threads, one process
    out = RUNS / a.tag; out.mkdir(parents=True, exist_ok=True)
    res = []
    for s in seeds:                                 # streams serial: one process, one reranker
        llm = FakeLLM()
        r = run_stream(s, llm, emb, anchors, rer, out)
        r["calls"] = llm.rows
        (out / f"stream-{s}.json").write_text(json.dumps(r, default=str))
        print(json.dumps({k: v for k, v in r.items() if k not in ("calls", "tasks")}), flush=True)
        res.append(s)
    print("done", res)


if __name__ == "__main__":
    main()
