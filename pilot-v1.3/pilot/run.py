"""Pilot driver.  python3 -m pilot.run --label SMOKE|PILOT [--smoke] [--streams 7240241,7240242] [--B 2000]"""
from __future__ import annotations
import argparse, json, re, threading, time, traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from .common import ROOT, DATA, ANSWER_MODEL, render_prompt, jdump
from . import common, targets as T
from .llm import LLM, in_tokens
from .embed import Embedder
from .anchors import load_or_fit
from .arms import A6, A3, RS

ARMS = [  # (name, cls, kwargs, worlds)  -- A6-eager C == A6 C and A3+DoT C == A3n C (no forget in C): aliased
    ("A6", A6, {"edges": "code", "recompute": "lazy"}, ("F", "C")),
    ("A6-eager", A6, {"edges": "code", "recompute": "eager"}, ("F",)),
    ("A6m", A6, {"edges": "model", "recompute": "lazy"}, ("F", "C")),
    ("A3n", A3, {"forget_mode": "redact"}, ("F", "C")),
    ("A3+DoT", A3, {"forget_mode": "dot"}, ("F",)),
    ("RS", RS, {}, ("F", "C")),
]
ALIAS_C = {"A6-eager": "A6", "A3+DoT": "A3n"}


def load_stream(seed, smoke):
    d = DATA / f"stream-{seed}"
    m = json.load(open(d / "MANIFEST.json"))
    sess = [(s["session"], s["t_start"]) for s in m["sessions"]]
    txt = {s: (d / "sessions" / f"{s}.md").read_text() for s, _ in sess}
    tg = T.author(d, txt)
    probes = [json.loads(l) for l in open(DATA / f"stream-{seed}-probes" / "probes.jsonl")]
    deleted, forgets = tg["deleted"], tg["forgets"]
    if smoke:
        sess = sess[:8]; deleted = [s for s in deleted if s in dict(sess)][:1]
        forgets = {s: forgets[s] for s in deleted}
        tg["targets"] = [t for t in tg["targets"] if t["deleted_session"] in deleted]
        probes = probes[:3]
    t_end = sess[-1][1] if smoke else m["t_end"]
    for t in tg["targets"]:
        t["t_query"] = t_end
    for p in probes:
        p["t_query"] = t_end if smoke else p["t_query"]
    return dict(seed=seed, sessions=sess, text=txt, targets=tg["targets"], canaries=tg["canaries"], deleted=deleted,
                forgets=forgets, probes=probes, t_end=t_end, manifest=m)


def timeline(S, world):
    ev = []
    for i, (s, t) in enumerate(S["sessions"]):
        if world == "C" and s in S["deleted"]:
            continue
        ev.append((t, 1, "ingest", s, i))
    for s, t in S["forgets"].items():
        ev.append((t, 0, "warm+forget" if world == "F" else "warm", s, None))
    return sorted(ev)


def run_instance(arm, world, S, B, out: Path, refresh_at):
    log = {"warm": [], "forget": [], "ingest": []}
    for t, _, kind, s, i in timeline(S, world):
        if kind == "ingest":
            text = S["text"][s]
            if world == "F" and s in S["canaries"]:
                text = T.inject(text, S["canaries"][s])
            if isinstance(arm, A3):
                rec = arm._write(s, text, t, "ingest")
                if (i + 1) in refresh_at:
                    arm.refresh("ingest")
            else:
                rec = arm.ingest(s, text, t, i)
            log["ingest"].append(rec)
            continue
        if not isinstance(arm, RS):
            for tg in S["targets"]:
                if tg["deleted_session"] != s or tg["cls"] not in ("P", "W") or tg["variant"] != "DIRECT":
                    continue
                r = arm.ask(tg["warm_question"], t, B, f"warm_{tg['cls']}", write_back=tg["cls"] == "W",
                            ctx={"probe": tg["probe_id"], "seed": S["seed"]})
                log["warm"].append({"probe_id": tg["probe_id"], "cls": tg["cls"], "t": t, **{k: r.get(k) for k in (
                    "answer", "served", "served_text", "wb_id", "wb_derived_from", "wb_notes")}})
        if world == "F":
            st = S["text"][s] + ("\n\n" + S["canaries"][s]["paragraph"] if s in S["canaries"] else "")
            t0 = time.time(); rec = arm.forget(s, t, st); rec["wall_s"] = time.time() - t0
            log["forget"].append(rec)
    # final probes
    qs = [dict(probe_id=tg["probe_id"], question=tg["question"], t_query=tg["t_query"], kind="deletion") for tg in S["targets"]]
    qs += [dict(probe_id=f"mix:{i:02d}:{p['category']}", question=p["question"], t_query=p["t_query"], kind="mix")
           for i, p in enumerate(S["probes"])]

    def one(q):
        n0 = len(arm.stats["calls"])
        r = arm.ask(q["question"], q["t_query"], B, "probe", ctx={"probe": q["probe_id"], "seed": S["seed"]})
        return dict(q, **{k: r.get(k) for k in ("answer", "ok", "served", "assembled_est")})
    with ThreadPoolExecutor(4) as ex:
        answers = list(ex.map(one, qs))
    out.mkdir(parents=True, exist_ok=True)
    arts = arm.derived_artifacts()
    (out / "answers.jsonl").write_text("".join(json.dumps(a) + "\n" for a in answers))
    (out / "log.json").write_text(json.dumps(log, default=str, indent=1))
    (out / "artifacts.json").write_text(json.dumps(arts))
    (out / "stats.json").write_text(json.dumps({"calls": arm.stats["calls"], "poison": arm.poison_log,
                                                "recompute": getattr(arm, "recompute_log", []),
                                                "write_failures": getattr(arm, "write_failures", [])}, default=str))
    arm.db.close_for_scan()
    canaries = [c["code"] for c in S["canaries"].values()]
    hits = {}
    for f in arm.db.files():
        b = f.read_bytes()
        hits[f.name] = {c: b.count(c.encode()) for c in canaries}
    (out / "residue_bytes.json").write_text(json.dumps(hits))
    return out


_plock = __import__("threading").Lock()


def progress(msg):
    """Append a checkpoint line to pilot-v1.2/PROGRESS.md (box-local = IST)."""
    with _plock:
        with open(ROOT / "PROGRESS.md", "a") as f:
            f.write(f"- {time.strftime('%Y-%m-%d %H:%M:%S IST')} — {msg}\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True)
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--streams", default="7240241,7240242")
    ap.add_argument("--B", type=int, default=2000)
    ap.add_argument("--arms", default="")
    ap.add_argument("--fake", action="store_true")
    a = ap.parse_args()
    freeze_digest = None
    if not a.fake and not a.smoke:      # v1.3 F10: a real full run must match the freeze (fake/smoke are dev-only)
        from pilot.freeze import verify_frozen
        sel_names = [x[0] for x in ARMS if not a.arms or x[0] in a.arms.split(",")]
        freeze_digest = verify_frozen("PILOT-FREEZE.json", a.B, [int(s) for s in a.streams.split(",")], arms=sel_names)
    run_dir = ROOT / "runs" / a.label
    run_dir.mkdir(parents=True, exist_ok=True)
    fake = None
    if a.fake:
        fake = lambda role, p: '{"ops":[{"op":"ADD","text":"x note","date":"2030-01-01"}]}' if role.startswith("a3_write") else "fake summary text"
    llm = LLM(ROOT / "runs" / ("_calls_fake" if a.fake else "_calls"), fake=fake)   # shared memo across labels (disclosed)
    llm.log_path = run_dir / "calls.jsonl"
    emb = Embedder(ROOT / "runs" / "_vec")
    anchors, anchors_sha = load_or_fit(emb, ROOT / "runs" / "anchors-7240240.npy")
    refresh_at = (4, 8) if a.smoke else common.REFRESH_AT
    # template overhead (Eng post-call law): one call with empty excerpts + empty question
    tmpl = llm.call("template", render_prompt([], ""), ctx={"phase": "template"})
    meta = {"freeze_digest": freeze_digest, "label": a.label, "smoke": a.smoke, "B": a.B, "anchors_sha": anchors_sha, "embedder": emb.model_id,
            "template_in_tokens": in_tokens(tmpl.get("usage")), "template_model_reported": tmpl.get("model_reported"),
            "started": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    sel = [x for x in ARMS if not a.arms or x[0] in a.arms.split(",")]
    jobs = []
    for seed in [int(s) for s in a.streams.split(",")]:
        S = load_stream(seed, a.smoke)
        sd = run_dir / f"stream-{seed}"; sd.mkdir(exist_ok=True)
        (sd / "targets.json").write_text(json.dumps({"targets": S["targets"], "canaries": S["canaries"],
                                                     "deleted": S["deleted"], "forgets": S["forgets"], "t_end": S["t_end"],
                                                     "probes": S["probes"]}, indent=1))
        for name, cls, kw, worlds in sel:
            for w in worlds:
                wd = sd / f"{name}-{w}"
                if (wd / "DONE").exists():      # v1.3 F03: resume check BEFORE constructing (DB() refuses existing stores)
                    print(f"skip (DONE) {S['seed']} {name}-{w}", flush=True)
                    continue
                kwargs = dict(kw)
                if cls is A6:
                    kwargs["anchors"] = anchors
                arm = cls(f"{name}", w, wd / "db", llm, emb, **kwargs)
                jobs.append((arm, w, S, wd))
    if not jobs:
        print("nothing to do: every selected instance is DONE", flush=True); return
    errs = []

    def go(j):
        arm, w, S, wd = j
        try:
            t0 = time.time(); run_instance(arm, w, S, a.B, wd, refresh_at)
            (wd / "DONE").write_text(time.strftime("%Y-%m-%dT%H:%M:%S%z"))
            print(f"done {S['seed']} {arm.name}-{w} {time.time()-t0:.0f}s", flush=True)
            progress(f"{a.label}: instance {S['seed']}:{arm.name}-{w} finished in {time.time()-t0:.0f}s")
        except Exception:
            errs.append((arm.name, w, S["seed"], traceback.format_exc())); print(errs[-1][3], flush=True)
    with ThreadPoolExecutor(len(jobs)) as ex:
        list(ex.map(go, jobs))
    meta["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S%z"); meta["errors"] = errs; meta["alias_C"] = ALIAS_C
    meta["arms"] = [x[0] for x in sel]; meta["streams"] = [int(s) for s in a.streams.split(",")]   # v1.3 F04: declared coverage
    (run_dir / "RUN-META.json").write_text(json.dumps(meta, indent=1))
    print("ERRORS" if errs else "OK", len(errs))
    progress(f"{a.label}: run finished, errors={len(errs)}")
    if errs:                                # v1.3 F04: an incomplete run must fail the shell chain (no scorer after it)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
