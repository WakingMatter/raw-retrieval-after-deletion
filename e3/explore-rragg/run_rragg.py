"""E3 explore: RR-agg on E2 CONFIRM DERIVED tasks (exploratory). Reuses E2's frozen RR retrieval outputs (served ids
from runs/CONFIRM answers + RR store text). Imports E2 code read-only; writes only under e3/explore-rragg/.
Usage: python3 run_rragg.py [--dry] [--parallel 6]"""
from __future__ import annotations
import argparse, glob, json, sqlite3, sys, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
HERE = Path(__file__).resolve().parent
E2D = HERE.parents[1] / "e2"
sys.path.insert(0, str(E2D))
from e2 import paths  # noqa: F401,E402
from e2.arms_e2 import E2_PREFIX, SYN_WORDS, B_DEFAULT, cap_summary  # noqa: E402
from e2.minimax_api import MiniMaxAPI, cache_key  # noqa: E402
from e2.tasks import score  # noqa: E402
from pilot.common import P_A6_SYN, render_prompt, fill, item_cost  # noqa: E402

SYN_INSTR = P_A6_SYN.replace("≤ 120 words", f"≤ {SYN_WORDS} words")   # exactly A6's E2 synth instruction
LABEL = "summary:rr"
RUN = E2D / "runs" / "CONFIRM"


def load():
    jobs = []
    for f in sorted(glob.glob(str(RUN / "stream-*/answers.jsonl"))):
        s = int(f.split("stream-")[1].split("/")[0])
        db = sqlite3.connect(RUN / f"stream-{s}/work/RR/store.sqlite")
        raw = {i: json.loads(b) for i, b in db.execute("select id, body from obj where kind='raw'")}
        tasks = {t["task_id"]: t for t in json.load(open(E2D / f"data/tasks-{s}.json"))["tasks"]}
        for l in open(f):
            r = json.loads(l)
            if r["arm"] == "RR" and r["cls"] == "DERIVED":
                t = tasks[r["task_id"]]
                items = [{"text": f"[{c} | {raw[c]['t'][:16]}] {raw[c]['text']}", "ref": c} for c in r["served"]]
                assert cache_key("answer", render_prompt([i["text"] for i in items], t["question"], E2_PREFIX)) == r["cache_key"]
                lines = [f"[{raw[c]['t'][:16]}] {raw[c]['text']}" for c in r["served"]]
                note_prompt = (SYN_INSTR + "\n\nQuestion the excerpts were retrieved for: " + t["question"] + "\n\n"
                               + "\n".join(lines))
                jobs.append({"seed": s, "task": t, "items": items, "note_prompt": note_prompt})
    return jobs


def run_one(api, j):
    t = j["task"]
    rn = api.call("note", j["note_prompt"], ctx={"exp": "e3-rragg", "task": t["task_id"]})
    header, used, note_txt, trunc = [], 0.0, None, None
    if rn["ok"]:
        note_txt, trunc = cap_summary(rn["text"].strip(), LABEL)
        it = {"text": f"[{LABEL}] {note_txt}"}
        c = item_cost(it["text"])
        if c <= B_DEFAULT / 5:
            header, used = [it], c
    raw, used2 = fill(j["items"], B_DEFAULT - used)
    prompt = render_prompt([i["text"] for i in header + raw], t["question"], E2_PREFIX)
    ra = api.call("answer", prompt, ctx={"exp": "e3-rragg", "task": t["task_id"]})
    ans = (ra.get("text") or "").strip() if ra["ok"] else None
    sc = score(t, ans)
    return {"task_id": t["task_id"], "seed": j["seed"], "deletion_touched": t["deletion_touched"], "arm": "RR-agg",
            "note_ok": rn["ok"], "note": note_txt, "note_truncated": trunc, "header_tokens_est": used,
            "raw_tokens_est": used2, "n_raw": len(raw), "answer": ans, "ok": ra["ok"], "score": sc,
            "note_usage": rn.get("usage"), "note_memo": rn.get("memo_hit"), "answer_usage": ra.get("usage"),
            "answer_memo": ra.get("memo_hit"), "note_attempts": len(rn.get("attempt_history") or []),
            "answer_attempts": len(ra.get("attempt_history") or [])}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--dry", action="store_true"); ap.add_argument("--parallel", type=int, default=6)
    a = ap.parse_args()
    jobs = load()
    print(f"jobs={len(jobs)} streams={len({j['seed'] for j in jobs})} RR prompt keys verified", flush=True)
    if a.dry:
        import statistics as S
        print("note prompt est tokens mean", round(S.mean(item_cost(j["note_prompt"]) for j in jobs)))
        print(jobs[0]["note_prompt"][:600]); return
    api = MiniMaxAPI(HERE / "_cache", max_parallel=a.parallel, log_path=HERE / "api-events.jsonl")
    out = HERE / "rragg_answers.jsonl"; t0 = time.time(); done = 0
    with ThreadPoolExecutor(a.parallel) as ex, open(out, "w") as f:
        for r in ex.map(lambda j: run_one(api, j), jobs):
            f.write(json.dumps(r) + "\n"); f.flush(); done += 1
            if done % 40 == 0:
                print(f"{done}/{len(jobs)} {time.time()-t0:.0f}s", flush=True)
    print("done", time.time() - t0, flush=True)


if __name__ == "__main__":
    main()
