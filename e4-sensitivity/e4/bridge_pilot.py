"""Step 3: pilot the GENERIC RR-2hop bridge prompt on the 2 DEV seeds only (7289001, 7289002). Real MiniMax calls.

Per task and B in PILOT_B: RR (hop 1 only), the generic bridge call on RR's served text, and RR-2hop's answer.
Bridge scoring (gold-side, offline): the expected bridge entity is
  MULTIHOP -> the hop entity (the service/project owned/led by the named person: task['hop_entity']),
  DERIVED  -> the current value of the derived key's reference slot (the lead/owner person),
  AGG / CURRENT -> NONE (the question already names everything).
Reported: bridge exact/contains rate per class, NONE rate, and RR vs RR-2hop accuracy per class (E2 score()).
    python3 -m e4.bridge_pilot --prompt v1 [--B 500,2000,8000]
"""
from __future__ import annotations
import argparse, json, time
from collections import defaultdict
from .paths import DATA, RUNS, PILOT, DEV
from . import arms_e4
from .dry_run import load
from e2.arms_e2 import RerankedRaw, Reranker, LLMAdapter, E2_PREFIX
from e2.run_e2 import timeline
from e2.tasks import score, ledger, _merge
from e2.minimax_api import MiniMaxAPI
from e3.rr2hop import ranked, interleave, parse_entity, hop2_query
from pilot.common import fill, render_prompt

PROMPTS = {"v1": arms_e4.BRIDGE_PROMPT_GENERIC_V1, "v2": arms_e4.BRIDGE_PROMPT_GENERIC_V2, "v3": arms_e4.BRIDGE_PROMPT_GENERIC_V3}


def expected_entity(seed, tk):
    if tk["cls"] == "MULTIHOP":
        return tk["hop_entity"]
    if tk["cls"] != "DERIVED":
        return None
    d = DATA / f"stream-{seed}"
    W = json.loads((d / "world.json").read_text())
    E = [json.loads(l) for l in (d / "events.jsonl").read_text().splitlines() if l.strip()]
    T = json.loads((DATA / f"tasks-{seed}.json").read_text())
    Br = json.loads((d / "BRIDGE.json").read_text())
    F = ledger.compute_rows(_merge(E, Br["events"]), W["keys"], set(T["deleted"]))
    f = ledger.fact_at(F, W["keys"][tk["key"]]["ref_key"], T["t_end"])
    return f["value"] if f and f["status"] == "active" else None


def ask2(rr_chunks, emb, rer, llm, prompt_head, q, tq, B, ctx):
    h1 = ranked(rr_chunks, emb, rer, q, tq)
    s1, _ = fill(h1, B)
    a1 = llm.call("answer", render_prompt([it["text"] for it in s1], q, E2_PREFIX), ctx=dict(ctx, arm="RR"))
    rb = llm.call("bridge", prompt_head + "\n\nQuestion: " + q + "\n\nExcerpts:\n" + "\n".join(it["text"] for it in s1),
                  ctx=dict(ctx, arm="RR-2hop"))
    ent = parse_entity(rb.get("text")) if rb.get("ok") else None
    if ent:
        served, _ = fill(interleave(h1, ranked(rr_chunks, emb, rer, hop2_query(ent, q), tq)), B)
    else:
        served = s1
    a2 = llm.call("answer", render_prompt([it["text"] for it in served], q, E2_PREFIX), ctx=dict(ctx, arm="RR-2hop"))
    return a1, rb, ent, a2


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt", default="v1")
    ap.add_argument("--B", default="500,2000,8000")
    ap.add_argument("--max-parallel", type=int, default=6)
    a = ap.parse_args(argv)
    Bs = [int(x) for x in a.B.split(",")]
    from concurrent.futures import ThreadPoolExecutor
    from pilot.embed import Embedder
    out = RUNS / f"BRIDGE-PILOT-{a.prompt}"; out.mkdir(parents=True, exist_ok=True)
    api = MiniMaxAPI(RUNS / "_cache", max_parallel=a.max_parallel, log_path=out / "api-events.jsonl")
    llm = LLMAdapter(api)
    emb = Embedder(RUNS / "_vec-dev"); rer = Reranker(threads=4)
    rows = []
    for seed in DEV:
        S = load(seed)
        rr = RerankedRaw("RR", "F", out / f"work-{seed}", llm, emb, rer)
        for t, _, kind, s in timeline(S):
            rr.ingest(s, S["text"][s], t) if kind == "ingest" else rr.forget(s, t)
        jobs = [(tk, B) for tk in S["tasks"] for B in Bs]
        exp = {tk["task_id"]: expected_entity(seed, tk) for tk in S["tasks"]}

        def one(job):
            tk, B = job
            ctx = {"probe": tk["task_id"], "cell": f"B{B}", "pilot": a.prompt}
            a1, rb, ent, a2 = ask2(rr.chunks, emb, rer, llm, PROMPTS[a.prompt], tk["question"], tk["t_query"], B, ctx)
            e = exp[tk["task_id"]]
            return {"task_id": tk["task_id"], "cls": tk["cls"], "B": B, "expected": e, "entity": ent,
                    "bridge_raw": (rb.get("text") or "")[:200], "bridge_ok": rb.get("ok"),
                    "bridge_right": (ent is None) if e is None else bool(ent and (e.lower() in ent.lower() or ent.lower() in e.lower())),
                    "rr_correct": score(tk, a1.get("text") if a1.get("ok") else None)["correct"],
                    "rr2_correct": score(tk, a2.get("text") if a2.get("ok") else None)["correct"],
                    "usage": [x.get("usage") for x in (a1, rb, a2)], "memo": [x.get("memo_hit") for x in (a1, rb, a2)]}
        with ThreadPoolExecutor(6) as ex:
            rows += list(ex.map(one, jobs))
    (out / "rows.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    agg = defaultdict(lambda: defaultdict(list))
    for r in rows:
        for k in ("bridge_right", "rr_correct", "rr2_correct"):
            agg[(r["cls"], r["B"])][k].append(r[k])
            agg[("ALL", r["B"])][k].append(r[k])
    summ = {f"{c}|B{B}": {k: round(sum(v) / len(v), 3) for k, v in d.items()} | {"n": len(d["rr_correct"])}
            for (c, B), d in sorted(agg.items())}
    tok = {"input": sum((u or {}).get("input_tokens", 0) for r in rows for u, m in zip(r["usage"], r["memo"]) if not m),
           "output": sum((u or {}).get("output_tokens", 0) for r in rows for u, m in zip(r["usage"], r["memo"]) if not m)}
    res = {"prompt": a.prompt, "seeds": DEV, "B": Bs, "summary": summ, "metered_tokens_live": tok,
           "live_calls": api.live_calls, "at": time.strftime("%Y-%m-%d %H:%M:%S %Z")}
    (out / "SUMMARY.json").write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
