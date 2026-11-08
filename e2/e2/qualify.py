"""E2 stage-0 answerer qualification on DEV streams (prereg §4). 30 calls per DEV stream, 120 over 4 streams.

Groups (built from the stream's post-delete RR store at t_end; same answer prompt as every arm):
  no_evidence   10 non-AGG tasks, EMPTY context -> contaminated if the answer states the gold or a deleted/outdated
                value (truth_any | wrong_any).
  gold_evidence 10 CURRENT tasks, context = the surviving support sessions' paragraphs, reranked, filled to B
                -> scored with the task's gold. RESPONSIVE POSITIVE CONTROL: accuracy must reach GOLD_MIN, so an
                always-abstaining (or always-wrong) answerer FAILS.
  stale_derived 10 tasks with an outdated value: RR context plus a stale note asserting that value, placed first,
                dated at the time that outdated value was recorded
                -> repeat rate REPORTED, not a pass criterion.
  gold_evidence_cls (rev 5, Astra finding 7) 3 AGG (gold > 0) + 3 DERIVED + 3 MULTIHOP tasks per stream with the same
                sufficient-evidence context -> per-class accuracy REPORTED (descriptive, not a pass criterion).
                The stale_derived rows also record endorses_stale (stale value without gold) vs mentions_both.
  (summary delivery is measured on the DEV pass traces, K-delivery, not here.)
PASS = 0 contaminated (no_evidence) AND 0 failed calls AND gold_evidence accuracy >= GOLD_MIN."""
from __future__ import annotations
import argparse, json, re, time
from concurrent.futures import ThreadPoolExecutor
from .paths import RUNS
from .tasks import score
from .arms_e2 import RerankedRaw, Reranker, LLMAdapter, B_DEFAULT, E2_PREFIX
from .make_data import DEV

GOLD_MIN = 0.70           # freeze item: minimum accuracy with sufficient gold evidence
N_GROUP = 10


def literal(rx: str) -> str:
    return re.sub(r"\\b", "", rx).replace("\\", "")


def jobs_for(S):
    t = S["tasks"]
    non_agg = [x for x in t if x["cls"] != "AGG"][::3][:N_GROUP]          # spread over CURRENT/DERIVED/MULTIHOP
    cur = [x for x in t if x["cls"] == "CURRENT"][:N_GROUP]
    stale = [x for x in t if x["cls"] != "AGG" and x.get("wrong_any")][1::2][:N_GROUP]
    desc = []
    for c in ("AGG", "DERIVED", "MULTIHOP"):
        desc += [x for x in t if x["cls"] == c and x.get("support_sessions") and str(x.get("gold")) != "0"][:3]
    return ([("no_evidence", x) for x in non_agg] + [("gold_evidence", x) for x in cur] +
            [("stale_derived", x) for x in stale] + [("gold_evidence_cls", x) for x in desc])


def run_job(rr: RerankedRaw, kind, tk, B=B_DEFAULT):
    ctx = {"ctl": kind, "probe": tk["task_id"]}
    q = tk["question"]
    if kind == "no_evidence":
        served = []
    elif kind in ("gold_evidence", "gold_evidence_cls"):
        from pilot.common import fill
        sup = set(tk["support_sessions"])
        ch = [(c, x) for c, x in rr.chunks.items() if x["session"] in sup and x["t"] <= tk["t_query"]]
        sc = rr.rr.scores(q, [x["text"] for _, x in ch]) if ch else []
        ranked = [cx for cx, _ in sorted(zip(ch, sc), key=lambda z: (-round(z[1], 9), z[0][0]))]
        served, _ = fill([{"text": f"[{c} | {x['t'][:16]}] {x['text']}", "kind": "chunk", "ref": c} for c, x in ranked], B)
    else:
        from pilot.common import fill
        base, _ = rr.read(q, tk["t_query"], B)
        stale_val = literal(tk["wrong_any"][0])
        # dated when the outdated value was recorded (DEFAULTS #23), not at query time: the note is a stale record,
        # and newer evidence in the context legitimately supersedes it
        when = ((tk.get("wrong_t") or [None])[0] or tk["t_query"])[:16]
        note = {"text": f"[note | {when}] Note: the answer to \"{q}\" is {stale_val}.", "kind": "note", "ref": "note"}
        served, _ = fill([note] + base, B)
    r, prompt = rr.answer(served, q, "qual", prefix=E2_PREFIX, ctx=ctx)
    ans = (r.get("text") or "").strip()
    hit_truth = any(re.search(x, ans, re.I) for x in tk.get("truth_any", []))
    hit_wrong = any(re.search(x, ans, re.I) for x in tk.get("wrong_any", []))
    row = {"control": kind, "task_id": tk["task_id"], "cls": tk["cls"], "ok": bool(r.get("ok")), "answer": ans[:400],
           "usage": r.get("usage"), "stop": r.get("stop"), "n_served": len(served)}
    if kind == "no_evidence":
        row["contaminated"] = bool(r.get("ok")) and (hit_truth or hit_wrong)
    elif kind in ("gold_evidence", "gold_evidence_cls"):
        row["correct"] = score(tk, ans if (r.get("ok") or r.get("stop") == "max_tokens") else None)["correct"]
    else:
        row["repeated_stale"] = hit_wrong
        row["endorses_stale"] = hit_wrong and not hit_truth
        row["mentions_both"] = hit_wrong and hit_truth
    return row


def verdict(rows, gold_min=GOLD_MIN):
    ne = [r for r in rows if r["control"] == "no_evidence"]
    ge = [r for r in rows if r["control"] == "gold_evidence"]
    sd = [r for r in rows if r["control"] == "stale_derived"]
    gc = [r for r in rows if r["control"] == "gold_evidence_cls"]
    by_cls = {}
    for r in gc:
        by_cls.setdefault(r["cls"], []).append(r["correct"])
    contaminated = sum(r["contaminated"] for r in ne)
    failed = sum(not r["ok"] for r in rows if r["control"] != "gold_evidence_cls")   # descriptive rows don't gate
    gold_acc = (sum(r["correct"] for r in ge) / len(ge)) if ge else 0.0
    ok = contaminated == 0 and failed == 0 and bool(ge) and gold_acc >= gold_min
    return {"verdict": "PASS" if ok else "FAIL", "n": len(rows), "contaminated": contaminated, "failed": failed,
            "gold_evidence_acc": gold_acc, "gold_min": gold_min,
            "stale_repeat_rate": (sum(r["repeated_stale"] for r in sd) / len(sd)) if sd else None,
            "stale_endorse_rate": (sum(r.get("endorses_stale", False) for r in sd) / len(sd)) if sd else None,
            "stale_mentions_both_rate": (sum(r.get("mentions_both", False) for r in sd) / len(sd)) if sd else None,
            "gold_evidence_by_class_desc": {c: {"n": len(v), "acc": sum(v) / len(v)} for c, v in sorted(by_cls.items())},
            "desc_failed_calls": sum(not r["ok"] for r in gc),
            "reasons": [m for m, bad in (("contaminated", contaminated > 0), ("failed_calls", failed > 0),
                                         (f"gold_evidence_acc<{gold_min}", gold_acc < gold_min)) if bad]}


def build_rr(S, llm, emb, reranker, wd):
    from .run_e2 import timeline
    rr = RerankedRaw("Q-RR", "F", wd, llm, emb, reranker)
    for t, _, kind, s in timeline(S):
        rr.ingest(s, S["text"][s], t) if kind == "ingest" else rr.forget(s, t)
    return rr


def main(argv=None):
    from .run_e2 import load, FakeLLM
    from .minimax_api import MiniMaxAPI
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="QUAL")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--max-parallel", type=int, default=6)
    a = ap.parse_args(argv)
    from pilot.embed import Embedder
    emb = Embedder(RUNS / "_vec"); rer = Reranker()
    out = RUNS / a.tag; out.mkdir(parents=True, exist_ok=True)
    llm = FakeLLM() if a.dry else LLMAdapter(MiniMaxAPI(RUNS / "_cache", max_parallel=a.max_parallel,
                                                         log_path=out / "api-events.jsonl"))
    rows = []
    for seed in DEV:
        S = load(seed)
        rr = build_rr(S, llm, emb, rer, out / f"stream-{seed}" / "work")
        with ThreadPoolExecutor(4) as ex:
            rows += [dict(r, seed=seed) for r in ex.map(lambda j: run_job(rr, *j), jobs_for(S))]
    res = dict(verdict(rows), finished=time.strftime("%Y-%m-%dT%H:%M:%S%z"), dry=a.dry)
    (out / "answers.jsonl").write_text("".join(json.dumps(r, default=str) + "\n" for r in rows))
    (out / "QUALIFY.json").write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
