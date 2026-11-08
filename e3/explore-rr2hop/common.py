"""Shared loaders for the RR-2hop exploration (read-only over E2 CONFIRM)."""
from __future__ import annotations
import glob, json, sqlite3, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from e3 import paths  # noqa: E402,F401
from e3.paths import E2  # noqa: E402
from pilot.arms import unit_vec  # noqa: E402

RUN = E2 / "runs" / "CONFIRM"
AUDIT = HERE.parent / "explore-rragg" / "AUDIT.json"


def load_streams(emb):
    """{seed: {"chunks": {...surviving RR chunks with vec}, "tasks": {task_id: task}, "rows": {task_id: {arm: row}}}}"""
    out = {}
    for f in sorted(glob.glob(str(RUN / "stream-*/answers.jsonl"))):
        s = int(f.split("stream-")[1].split("/")[0])
        db = sqlite3.connect(RUN / f"stream-{s}/work/RR/store.sqlite")
        raw = {i: json.loads(b) for i, b in db.execute("select id, body from obj where kind='raw'")}
        db.close()
        chunks = {c: {"t": x["t"], "text": x["text"], "vec": unit_vec(emb, x["text"])} for c, x in raw.items()}
        tasks = {t["task_id"]: t for t in json.load(open(E2 / f"data/tasks-{s}.json"))["tasks"] if t["cls"] == "DERIVED"}
        rows = {}
        for l in open(f):
            r = json.loads(l)
            if r["cls"] == "DERIVED":
                rows.setdefault(r["task_id"], {})[r["arm"]] = r
        out[s] = {"chunks": chunks, "tasks": tasks, "rows": rows}
    return out


def leaves():
    A = json.load(open(AUDIT))["tasks"]
    return {t["task_id"]: {("ref" if l["slot"] in ("svc_owner", "proj_lead") else "attr"): l for l in t["leaves"]} | {"_t": t}
            for t in A}
