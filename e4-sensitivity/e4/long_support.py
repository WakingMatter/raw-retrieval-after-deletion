"""Generate gen_long streams, author E2 tasks on them, and measure gold support (model-free).

    python3 -m e4.long_support L CHAIN seed[,seed...]

Support (two measures, both in answer-prompt tokens via pilot.common.item_cost on the arm-visible chunk text):
  union   -- Astra E2 audit method (dry_run.support_costs): union of every ledger evidence paragraph of the gold
             fact(s) (restatements included). Upper bound on what an arm must hold.
  minimal -- one cheapest evidence paragraph per needed leaf fact (AGG: per surviving value; DERIVED: per parent
             chain; MULTIHOP: hop + attribute). Lower bound: below this the evidence cannot fit in B in raw form.
Output: DATA/long-L{L}C{CHAIN}/SUPPORT-{seed}.json and a printed summary.
"""
from __future__ import annotations
import json, statistics, sys
from .paths import DATA
from . import gen_long
from e2.tasks import author_e2, _merge
from gen import ledger
from pilot.common import item_cost


def gen_dir(L, chain):
    return DATA / ("" if (L, chain) == (1, 1) else f"long-L{L}C{chain}")


def ensure(seed, L, chain):
    root = gen_dir(L, chain); d = root / f"stream-{seed}"
    if not (d / "MANIFEST.json").exists():
        gen_long.generate(seed, d, L, chain)
    tf = root / f"tasks-{seed}.json"
    if not tf.exists():
        tf.write_text(json.dumps(author_e2(d), indent=1))
    return root, d, json.loads(tf.read_text())


def support(seed, L, chain):
    root, d, T = ensure(seed, L, chain)
    rd = lambda p: json.loads(p.read_text())  # noqa: E731
    rows = lambda p: [json.loads(l) for l in p.read_text().splitlines() if l.strip()]  # noqa: E731
    W, M, E, Br = rd(d / "world.json"), rd(d / "MANIFEST.json"), rows(d / "events.jsonl"), rd(d / "BRIDGE.json")
    F = ledger.compute_rows(_merge(E, Br["events"]), W["keys"], set(T["deleted"]))
    byid = {f["fact_id"]: f for f in F}; map_p = {}
    for rt in rows(d / "render_trace.jsonl"):
        for eid in rt["event_ids"]:
            map_p[eid] = (rt["session"], rt["seg"])
    for e in Br["events"]:
        map_p[e["id"]] = map_p[e["after"]]
    txt = {f.stem: f.read_text().rstrip("\n").split("\n\n") for f in (d / "sessions").glob("*.md")}
    starts = {s["session"]: s["t_start"] for s in M["sessions"]}
    cost = lambda r: item_cost(f"[{r[0]}:{r[1] + 1:03d} | {starts[r[0]][:16]}] {txt[r[0]][r[1]]}")  # noqa: E731

    def leaves(f):          # list of evidence-ref sets, one per leaf fact
        own = {map_p[e] for e in f["evidence_events"] if e in map_p}
        out = [own] if own else []
        for pid in f.get("parents", []):
            out += leaves(byid[pid])
        return out
    res = {}
    for tk in T["tasks"]:
        facts = ([f for f in F if f["key"] == tk["key"] and f["value"] and f["valid_from"] <= T["t_end"]]
                 if tk["cls"] == "AGG" else [ledger.fact_at(F, tk["key"], T["t_end"])])
        if tk["cls"] == "MULTIHOP":
            facts.append(ledger.fact_at(F, tk["hop_key"], T["t_end"]))
        ls = [l for f in facts for l in leaves(f)]
        union = set().union(*ls) if ls else set()
        res[tk["task_id"]] = {"cls": tk["cls"], "gold": tk["gold"], "union": sum(cost(r) for r in union),
                              "minimal": sum(min(cost(r) for r in l) for l in ls), "n_paragraphs": len(union)}
    out = {"seed": seed, "L": L, "chain": chain, "tokens": M["tokens"]["total"], "sessions": len(M["sessions"]),
           "n_tasks": len(T["tasks"]), "shortfall": T["shortfall"], "tasks": res}
    (root / f"SUPPORT-{seed}.json").write_text(json.dumps(out, indent=1))
    return out


def summarize(outs, Bs=(500, 1000, 2000)):
    allt = [t for o in outs for t in o["tasks"].values()]
    s = {"n_streams": len(outs), "n_tasks": len(allt), "stream_tokens_median": statistics.median(o["tokens"] for o in outs),
         "shortfall": {c: sum(o["shortfall"][c] for o in outs) for c in outs[0]["shortfall"]}}
    for m in ("union", "minimal"):
        for B in Bs:
            s[f"{m}>{B}"] = round(sum(t[m] > B for t in allt) / len(allt), 3)
        for c in ("AGG", "CURRENT", "DERIVED", "MULTIHOP", "ALL"):
            v = [t[m] for t in allt if c == "ALL" or t["cls"] == c]
            if v:
                s[f"{m}:{c}"] = {"median": statistics.median(v), "max": max(v),
                                 **{f">{B}": round(sum(x > B for x in v) / len(v), 3) for B in Bs}}
    return s


if __name__ == "__main__":
    L, chain = int(sys.argv[1]), int(sys.argv[2])
    seeds = [int(x) for x in sys.argv[3].split(",")]
    print(json.dumps(summarize([support(s, L, chain) for s in seeds]), indent=1))
