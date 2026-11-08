"""PILOT-2 driver (EXPLORATORY; copy of frozen pilot/run.py with deviations D2-1..D2-3).  python3 -m pilot.run --label SMOKE|PILOT [--smoke] [--streams 7240241,7240242] [--B 2000]"""
from __future__ import annotations
import argparse, hashlib, json, random, re, threading, time, traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from pilot.common import ROOT, DATA, ANSWER_MODEL, render_prompt, jdump
from pilot import common, targets as T
from pilot2.targets2 import author2
from pilot2.arms2 import A3DoT2
from pilot.llm import LLM, in_tokens
from pilot.embed import Embedder
from pilot.anchors import load_or_fit
from pilot.arms import A6, A3, RS

ARMS = [  # (name, cls, kwargs, worlds)  -- A6-eager C == A6 C and A3+DoT C == A3n C (no forget in C): aliased
    ("A6", A6, {"edges": "code", "recompute": "lazy"}, ("F", "C")),
    ("A6-eager", A6, {"edges": "code", "recompute": "eager"}, ("F",)),
    ("A6m", A6, {"edges": "model", "recompute": "lazy"}, ("F", "C")),
    ("A3n", A3, {"forget_mode": "redact"}, ("F", "C")),
    ("A3+DoT", A3DoT2, {}, ("F",)),
    # v1.3 narrow DoT (J2-17): delete-on-touch with A3n's touch-only attribution -- forget deletes exactly the notes
    # whose `sources` contain the session, i.e. notes the writer ADDed/UPDATEd from it (no context-exposure provenance).
    # Same writer/clusters/retrieval as A3n; only delete-vs-redact differs. Distinct name; not pooled with A3+DoT.
    ("A3+DoTn", A3, {"forget_mode": "dot"}, ("F",)),
    ("RS", RS, {}, ("F", "C")),
]
ALIAS_C = {"A6-eager": "A6", "A3+DoT": "A3n", "A3+DoTn": "A3n"}
# v1.3 J2-13 (Research decision 4): terminal probe order is a frozen seeded shuffle per (stream, arm, world).
PROBE_ORDER_SEED = 7240300
PROBE_WORKERS = 4            # concurrency inside an instance stays; answers are keyed by probe id, not completion order


def probe_order(qs, stream, arm, world, seed=PROBE_ORDER_SEED):
    """Deterministic order: sort by probe id, then shuffle with RNG seeded by sha256(seed|stream|arm|world)."""
    ids = sorted(q["probe_id"] for q in qs)
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate probe ids")
    rs = int(hashlib.sha256(f"probe-order|{seed}|{stream}|{arm}|{world}".encode()).hexdigest()[:16], 16)
    random.Random(rs).shuffle(ids)
    return ids, rs


def load_stream(seed, smoke):
    d = DATA / f"stream-{seed}"
    m = json.load(open(d / "MANIFEST.json"))
    sess = [(s["session"], s["t_start"]) for s in m["sessions"]]
    txt = {s: (d / "sessions" / f"{s}.md").read_text() for s, _ in sess}
    probes = [json.loads(l) for l in open(DATA / f"stream-{seed}-probes" / "probes.jsonl")]
    if smoke:
        sess = sess[:10]
    tg = author2(d, txt, probes, n_extra=(2 if smoke else 6), sessions=[s for s, _ in sess])
    probes = tg["probes"]; deleted, forgets = tg["deleted"], tg["forgets"]
    t_end = sess[-1][1] if smoke else m["t_end"]
    if smoke:
        probes = probes[:3]
        forgets = {s: (t if t <= t_end else t_end) for s, t in forgets.items()}
        for t in tg["targets"]:
            t["t_forget"] = forgets[t["deleted_session"]]
    for t in tg["targets"]:
        t["t_query"] = t_end
    for p in probes:
        p["t_query"] = t_end if smoke else p["t_query"]
    return dict(seed=seed, sessions=sess, text=txt, targets=tg["targets"], canaries=tg["canaries"], deleted=deleted,
                forgets=forgets, probes=probes, t_end=t_end, manifest=m, extra=tg["extra"], dropped=tg.get("dropped", []))


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
                if tg["deleted_session"] != s or not tg.get("warm_question") or tg["variant"] != "DIRECT":
                    continue
                wb = tg["cls"] == "W" or bool(tg.get("warm_wb"))
                r = arm.ask(tg["warm_question"], t, B, f"warm_{tg['cls']}", write_back=wb,
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

    order, order_rs = probe_order(qs, S["seed"], arm.name, world)
    byid = {q["probe_id"]: q for q in qs}

    def one(i, q):
        r = arm.ask(q["question"], q["t_query"], B, "probe", ctx={"probe": q["probe_id"], "seed": S["seed"]})
        return dict(q, order_index=i, **{k: r.get(k) for k in ("answer", "ok", "served", "assembled_est")})
    got, completion = {}, []
    with ThreadPoolExecutor(PROBE_WORKERS) as ex:      # submitted strictly in the frozen order
        futs = [ex.submit(one, i, byid[pid]) for i, pid in enumerate(order)]
        for fu in as_completed(futs):
            a_ = fu.result()
            if a_["probe_id"] in got:
                raise ValueError(f"duplicate answer for {a_['probe_id']}")
            got[a_["probe_id"]] = a_; completion.append(a_["probe_id"])
    answers = [got[pid] for pid in sorted(got)]            # keyed by probe id; file order independent of completion
    out.mkdir(parents=True, exist_ok=True)
    (out / "probe_order.json").write_text(json.dumps({"seed": PROBE_ORDER_SEED, "rng_seed": order_rs, "stream": S["seed"],
                                                      "arm": arm.name, "world": world, "workers": PROBE_WORKERS,
                                                      "order": order, "completion_order_diagnostic": completion}, indent=1))
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
    """Append a checkpoint line to <ROOT>/PROGRESS.md (box-local = IST)."""
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
    ap.add_argument("--stream-par", type=int, default=0, help="streams run concurrently (0 = all); instances of a stream run together")
    ap.add_argument("--llm-par", type=int, default=8, help="global cap on concurrent model calls (PILOT-2: 8)")
    # PILOT3-ASTRA deviation (DEVIATION-ASTRA.md); defaults leave the grok run byte-for-byte unchanged in behaviour
    ap.add_argument("--answerer", choices=["grok", "astra", "minimax"], default="grok")
    ap.add_argument("--instances", default="", help="astra: comma list seed:ARM-W (e.g. 7240241:A3n-C); empty = all")
    ap.add_argument("--stop-at", type=float, default=94.0, help="astra: weekly used_percent at which STOP is written")
    a = ap.parse_args()
    astra = a.answerer == "astra"
    if astra and a.label == "PILOT3":
        raise SystemExit("astra runs must not write into runs/PILOT3")
    minimax = a.answerer == "minimax"     # MiniMax route (MINIMAX-ROUTE.md)
    if minimax and a.label.startswith("PILOT3"):
        raise SystemExit("minimax runs must not write into runs/PILOT3*")
    want = set(x for x in a.instances.split(",") if x)
    freeze_digest = None
    if not a.fake and not a.smoke:      # v1.3 F10: a real full run must match the freeze (fake/smoke are dev-only)
        from pilot.freeze import verify_frozen
        sel_names = [x[0] for x in ARMS if not a.arms or x[0] in a.arms.split(",")]
        if minimax:  # needs its own freeze + deviation doc (not created by the route work)
            freeze_digest = verify_frozen("MINIMAX-FREEZE.json", a.B, [int(s) for s in a.streams.split(",")], arms=sel_names)
        elif astra:   # deviation freeze; the frozen PILOT3-FREEZE.json is never edited
            freeze_digest = verify_frozen("PILOT3-ASTRA-FREEZE.json", a.B, [int(s) for s in a.streams.split(",")], arms=sel_names)
        else:
            freeze_digest = verify_frozen("PILOT3-FREEZE.json", a.B, [int(s) for s in a.streams.split(",")], arms=sel_names)
    run_dir = ROOT / "runs" / a.label
    run_dir.mkdir(parents=True, exist_ok=True)
    fake = None
    if a.fake:
        fake = lambda role, p: '{"ops":[{"op":"ADD","text":"x note","date":"2030-01-01"}]}' if role.startswith("a3_write") else "fake summary text"
    stop_file = run_dir / "STOP"
    if minimax:
        llm = LLM(ROOT / "runs" / ("_calls_fake" if a.fake else "_calls"), fake=fake, max_parallel=a.llm_par,
                  answerer="minimax", stop_file=stop_file)
    elif astra:
        llm = LLM(ROOT / "runs" / ("_calls_fake" if a.fake else "_calls"), fake=fake, max_parallel=a.llm_par,
                  answerer="astra", stop_file=stop_file, stop_at=a.stop_at)
    else:
        llm = LLM(ROOT / "runs" / ("_calls_fake" if a.fake else "_calls"), fake=fake, max_parallel=a.llm_par)   # shared memo across labels (disclosed)
    llm.log_path = run_dir / "calls.jsonl"
    emb = Embedder(ROOT / "runs" / "_vec")
    anchors, anchors_sha = load_or_fit(emb, ROOT / "runs" / "anchors-7240240.npy")
    refresh_at = (4, 8, 10) if a.smoke else common.REFRESH_AT
    # template overhead (Eng post-call law): one call with empty excerpts + empty question
    tmpl = llm.call("template", render_prompt([], ""), ctx={"phase": "template"})
    meta = {"freeze_digest": freeze_digest, "label": a.label, "smoke": a.smoke, "B": a.B, "anchors_sha": anchors_sha, "embedder": emb.model_id,
            "template_in_tokens": in_tokens(tmpl.get("usage")), "template_model_reported": tmpl.get("model_reported"),
            "started": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    if minimax:
        from pilot import minimax as _mm
        meta.update(answerer=f"minimax ({_mm.MINIMAX_MODEL}, {_mm.ROUTES[_mm.TRANSPORT]}; MINIMAX-ROUTE.md)", instances=sorted(want))
    if astra:
        meta.update(answerer="astra (gpt-6-astra, isolated codex route; DEVIATION-ASTRA.md)", instances=sorted(want), stop_at=a.stop_at)
    sel = [x for x in ARMS if not a.arms or x[0] in a.arms.split(",")]
    jobs = []
    streams_sel = [int(s) for s in a.streams.split(",")]
    meta["stream_par"] = a.stream_par or len(streams_sel); meta["probe_order_seed"] = PROBE_ORDER_SEED; meta["llm_par"] = a.llm_par
    for seed in streams_sel:
        S = load_stream(seed, a.smoke)
        sd = run_dir / f"stream-{seed}"; sd.mkdir(exist_ok=True)
        (sd / "targets.json").write_text(json.dumps({"targets": S["targets"], "canaries": S["canaries"],
                                                     "deleted": S["deleted"], "extra": S.get("extra"), "dropped": S.get("dropped", []), "forgets": S["forgets"], "t_end": S["t_end"],
                                                     "probes": S["probes"]}, indent=1))
        for name, cls, kw, worlds in sel:
            for w in worlds:
                wd = sd / f"{name}-{w}"
                if want and f"{seed}:{name}-{w}" not in want:
                    continue
                if (wd / "DONE").exists():      # v1.3 F03: resume check BEFORE constructing (DB() refuses existing stores)
                    print(f"skip (DONE) {S['seed']} {name}-{w}", flush=True)
                    continue
                jobs.append((name, cls, kw, w, S, wd))     # constructed lazily when its stream starts
    if not jobs:
        print("nothing to do: every selected instance is DONE", flush=True); return
    errs = []

    def go(j):
        name, cls, kw, w, S, wd = j
        kwargs = dict(kw)
        if cls is A6:
            kwargs["anchors"] = anchors
        arm = None
        if (astra or minimax) and stop_file.exists():
            errs.append((name, w, S["seed"], "not started: STOP present")); print(f"not started (STOP) {S['seed']} {name}-{w}", flush=True)
            return
        try:
            arm = cls(f"{name}", w, wd / "db", llm, emb, **kwargs)
            t0 = time.time(); run_instance(arm, w, S, a.B, wd, refresh_at)
            if astra or minimax:   # DONE only for a complete instance: no failed/voided call and no STOP (fixes the PILOT3 partial-DONE issue)
                bad = [c for c in arm.stats["calls"] if not c["ok"]]
                if bad or stop_file.exists():
                    (wd / "INCOMPLETE").write_text(json.dumps({"failed_calls": len(bad), "stop": stop_file.exists(),
                                                               "at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}))
                    errs.append((name, w, S["seed"], f"INCOMPLETE failed_calls={len(bad)} stop={stop_file.exists()}"))
                    progress(f"{a.label}: instance {S['seed']}:{arm.name}-{w} INCOMPLETE (failed={len(bad)}, stop={stop_file.exists()})")
                    return
            (wd / "DONE").write_text(time.strftime("%Y-%m-%dT%H:%M:%S%z"))
            print(f"done {S['seed']} {arm.name}-{w} {time.time()-t0:.0f}s", flush=True)
            progress(f"{a.label}: instance {S['seed']}:{arm.name}-{w} finished in {time.time()-t0:.0f}s")
        except Exception:
            errs.append((name, w, S["seed"], traceback.format_exc())); print(errs[-1][3], flush=True)

    by_stream = {}
    for j in jobs:
        by_stream.setdefault(j[4]["seed"], []).append(j)

    def go_stream(seed):
        js = by_stream[seed]; t0 = time.time()
        progress(f"{a.label}: stream {seed} started ({len(js)} instances)")
        with ThreadPoolExecutor(len(js)) as ex:
            list(ex.map(go, js))
        progress(f"{a.label}: stream {seed} finished in {time.time()-t0:.0f}s; errors so far={len(errs)}")
    with ThreadPoolExecutor(max(1, min(a.stream_par or len(by_stream), len(by_stream)))) as ex:
        list(ex.map(go_stream, [s for s in streams_sel if s in by_stream]))
    meta["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S%z"); meta["errors"] = errs; meta["alias_C"] = ALIAS_C
    meta["arms"] = [x[0] for x in sel]; meta["streams"] = [int(s) for s in a.streams.split(",")]   # v1.3 F04: declared coverage
    (run_dir / "RUN-META.json").write_text(json.dumps(meta, indent=1))
    print("ERRORS" if errs else "OK", len(errs))
    progress(f"{a.label}: run finished, errors={len(errs)}")
    if errs:                                # v1.3 F04: an incomplete run must fail the shell chain (no scorer after it)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
