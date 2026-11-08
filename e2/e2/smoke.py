"""E2 API smoke (<= 20 live calls, hard-capped by budget_calls).
Part 1: 12 calibration items (pilot-v1.3/minimax-cal, seed 7240241) answered via the API, compared with the CLI-route
        MiniMax answers and the Astra answers recorded for the same prompts.
Part 2: one DEV stream (7269001; never a confirmatory seed) through the real E2 harness at t_end, no warm phase:
        A6 read (live synth for its top nodes) + 1 A6 answer, 1 A6-syn answer, 2 RR answers.
Writes runs/SMOKE/smoke.json. Prompts go through the shared per-call cache, so the full run will replay them."""
from __future__ import annotations
import json, random, re, time
from .paths import PILOT, RUNS
from .minimax_api import MiniMaxAPI, Quota
from .arms_e2 import A6E2, RerankedRaw, Reranker, LLMAdapter, B_DEFAULT
from .run_e2 import load, timeline
from .tasks import score

N_CAL = 12


def norm(s):
    return re.sub(r"[^a-z0-9 ]", "", (s or "").lower()).split()


def jacc(a, b):
    A, B = set(norm(a)), set(norm(b))
    return len(A & B) / len(A | B) if A | B else 1.0


def nf(s):
    return bool(re.search(r"not found", s or "", re.I))


def main():
    out = RUNS / "SMOKE"; out.mkdir(parents=True, exist_ok=True)
    q0 = Quota().read()
    api = MiniMaxAPI(RUNS / "_cache", max_parallel=4, log_path=out / "api-events.jsonl", budget_calls=20)
    prompts = [json.loads(l) for l in open(PILOT / "minimax-cal" / "prompts-7240241.jsonl")]
    cli = {(r["instance"], r["probe_id"]): r for r in map(json.loads, open(PILOT / "minimax-cal" / "cal-cli" / "answers.jsonl"))}
    rng = random.Random(7260000)
    pick = rng.sample(range(len(prompts)), N_CAL)
    rows = []
    for i in pick:
        p = prompts[i]
        r = api.call("answer", p["prompt"], ctx={"smoke": "cal", "instance": p["instance"], "probe": p["probe_id"]})
        c = cli.get((p["instance"], p["probe_id"]), {})
        rows.append({"part": "cal", "instance": p["instance"], "probe_id": p["probe_id"], "question": p["question"],
                     "api_answer": r["text"], "ok": r["ok"], "stop": r["stop"], "usage": r["usage"], "latency_s": r["latency_s"],
                     "thinking_chars": r.get("thinking_chars"), "memo_hit": r["memo_hit"], "prompt_chars": len(p["prompt"]),
                     "cli_answer": c.get("minimax_answer"), "astra_answer": p.get("astra_answer"),
                     "jacc_cli": jacc(r["text"], c.get("minimax_answer")), "jacc_astra": jacc(r["text"], p.get("astra_answer")),
                     "nf_agree_cli": nf(r["text"]) == nf(c.get("minimax_answer"))})
    # part 2: real E2 harness on DEV stream
    from pilot.embed import Embedder
    from pilot.anchors import load_or_fit
    emb = Embedder(RUNS / "_vec")
    anchors, _ = load_or_fit(emb, PILOT / "runs" / "anchors-7240240.npy")
    S = load(7269001)
    wd = out / "work"
    import shutil; shutil.rmtree(wd, ignore_errors=True)
    llm = LLMAdapter(api)
    a6 = A6E2("A6", "F", wd / "A6", llm, emb, anchors)
    rr = RerankedRaw("RR", "F", wd / "RR", llm, emb, Reranker())
    for t, _, kind, s in timeline(S):
        if kind == "ingest":
            a6.ingest(s, S["text"][s], t); rr.ingest(s, S["text"][s], t)
        else:
            a6.forget(s, t, S["text"][s]); rr.forget(s, t)
    by = {}
    for tk in S["tasks"]:
        by.setdefault(tk["cls"], tk)
    plan = [("A6", by["AGG"]), ("A6-syn", by["DERIVED"]), ("RR", by["MULTIHOP"]), ("RR", by["CURRENT"])]
    for arm, tk in plan:
        ctx = {"smoke": "e2", "probe": tk["task_id"], "variant": arm}
        r = rr.ask(tk["question"], tk["t_query"], B_DEFAULT, "probe", ctx=ctx) if arm == "RR" else \
            a6.ask(tk["question"], tk["t_query"], B_DEFAULT, "probe", ctx=ctx, syn=(arm == "A6"))
        rows.append({"part": "e2", "arm": arm, "task_id": tk["task_id"], "cls": tk["cls"], "question": tk["question"],
                     "gold": tk["gold"], "api_answer": r["answer"], "ok": r["ok"], "stop": r["stop"], "usage": r["usage"],
                     "assembled_est": r["assembled_est"], "prompt_chars": r["prompt_chars"], "trace": r["trace"],
                     "memo_hit": r["memo_hit"], **score(tk, r["answer"] if r["ok"] else None)})
    synth = [c for c in a6.stats["calls"] if c["role"] == "synth"]
    summ = {n: {k: c.get(k) for k in ("truncated", "cost_raw", "cost_served")} for n, c in a6.caches.items()}
    live = []
    for l in open(out / "api-events.jsonl"):
        e = json.loads(l)
        if e.get("kind") == "call":
            live.append(e)
    time.sleep(5)
    q1 = Quota().read()
    res = {"at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "live_calls": api.live_calls, "rows": rows, "synth_calls": synth,
           "summaries": summ, "events": live, "quota_before": q0,
           "quota_after": q1}
    (out / "smoke.json").write_text(json.dumps(res, indent=1, default=str))
    print(json.dumps({"live_calls": api.live_calls, "n_rows": len(rows), "n_synth": len(synth)}))


if __name__ == "__main__":
    main()
