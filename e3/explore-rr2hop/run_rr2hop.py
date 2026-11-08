"""E3 explore: RR-2hop on the 320 E2 CONFIRM DERIVED tasks (exploratory, post hoc). Reuses E2's frozen RR store
(surviving chunks); hop 1 is asserted equal to E2 RR's served list for every task. Imports E2 code read-only; writes
only under e3/explore-rr2hop/. Usage: python3 run_rr2hop.py [--dry] [--parallel 6]"""
from __future__ import annotations
import argparse, json, threading, time
from concurrent.futures import ThreadPoolExecutor
from common import HERE, load_streams
from e3.rr2hop import RR2Hop, ranked
from e2.arms_e2 import Reranker, B_DEFAULT
from e2.minimax_api import MiniMaxAPI
from e2.paths import RUNS
from e2.tasks import score
from pilot.common import fill
from pilot.embed import Embedder


class Locked:
    """Serialize a model object across worker threads (reranker and embedder are single-locked, as in E2)."""
    def __init__(self, obj):
        self.o, self.l = obj, threading.Lock()

    def scores(self, q, texts):
        with self.l:
            return self.o.scores(q, texts)

    def vec(self, text):
        with self.l:
            return self.o.vec(text)


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--dry", action="store_true"); ap.add_argument("--parallel", type=int, default=6); ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    emb, rr = Locked(Embedder(RUNS / "_vec")), Locked(Reranker())
    S = load_streams(emb)
    jobs = [(s, tk) for s, st in S.items() for tk in st["tasks"].values()]
    jobs = jobs[:a.limit] if a.limit else jobs
    for s, tk in jobs:   # hop-1 reproduces E2 RR exactly
        assert [i["ref"] for i in fill(ranked(S[s]["chunks"], emb, rr, tk["question"], tk["t_query"]), B_DEFAULT)[0]] \
            == S[s]["rows"][tk["task_id"]]["RR"]["served"], tk["task_id"]
    print(f"jobs={len(jobs)} streams={len(S)} hop-1 == E2 RR served verified", flush=True)
    if a.dry:
        return
    api = MiniMaxAPI(HERE / "_cache", max_parallel=a.parallel, log_path=HERE / "api-events.jsonl")

    def one(job):
        s, tk = job
        r = RR2Hop(S[s]["chunks"], emb, rr, api).ask(tk["question"], tk["t_query"], B_DEFAULT,
                                                     ctx={"exp": "e3-rr2hop", "task": tk["task_id"]})
        return dict(task_id=tk["task_id"], seed=s, deletion_touched=tk["deletion_touched"], arm="RR-2hop",
                    score=score(tk, r["answer"] if r["ok"] else None), **r)

    out = HERE / "rr2hop_answers.jsonl"; t0 = time.time(); done = 0
    with ThreadPoolExecutor(a.parallel) as ex, open(out, "w") as f:
        for r in ex.map(one, jobs):
            f.write(json.dumps(r) + "\n"); f.flush(); done += 1
            if done % 40 == 0:
                print(f"{done}/{len(jobs)} {time.time()-t0:.0f}s", flush=True)
    print("done", round(time.time() - t0), flush=True)


if __name__ == "__main__":
    main()
