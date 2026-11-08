"""Measure gold support for gen_wide streams (model-free).   python3 -m t0r.wide_support SCALE seed[,seed...] [--out DIR]

Support is in answer-prompt tokens (pilot.common.item_cost on the arm-visible chunk "[sNN:SEG | t] text", the same
form long_support.py and the RR arm use). minimal = sum over paragraphs necessary to derive gold; union = minimal +
every distractor / superseded paragraph about the task's entities. Writes SUPPORT-{seed}.json beside the stream.
"""
from __future__ import annotations
import json, statistics, sys
from pathlib import Path
from e4.paths import DATA
from . import gen_wide
from pilot.common import item_cost

B_GRID = [500, 1000, 2000, 4000, 8000]


def stream_dir(seed, scale):
    return DATA / f"wide-x{scale:g}" / f"stream-{seed}"


def support(seed, scale):
    d = stream_dir(seed, scale)
    if not (d / "tasks.json").exists():
        gen_wide.generate(seed, d, scale)
    M = json.loads((d / "MANIFEST.json").read_text()); T = json.loads((d / "tasks.json").read_text())
    starts = {s["session"]: s["t_start"] for s in M["sessions"]}
    txt = {f.stem: f.read_text().rstrip("\n").split("\n\n") for f in (d / "sessions").glob("*.md")}
    cost = lambda r: item_cost(f"[{r[0]}:{r[1] + 1:03d} | {starts[r[0]][:16]}] {txt[r[0]][r[1]]}")  # noqa: E731
    stream_tok = sum(cost([s, i]) for s in txt for i in range(1, len(txt[s])))
    res = {tk["task_id"]: {"family": tk["family"], "n_entities": tk["n_entities"],
                           "n_min": len(tk["minimal_refs"]), "n_union": len(tk["union_refs"]),
                           "minimal": round(sum(cost(r) for r in tk["minimal_refs"])),
                           "union": round(sum(cost(r) for r in tk["union_refs"]))} for tk in T["tasks"]}
    out = {"seed": seed, "scale": scale, "stream_tokens": round(stream_tok),
           "n_paragraphs": sum(len(v) - 1 for v in txt.values()), "tasks": res}
    (d.parent / f"SUPPORT-{seed}.json").write_text(json.dumps(out, indent=1))
    return out


def summarize(outs):
    rows = [t for o in outs for t in o["tasks"].values()]
    fam = sorted({r["family"] for r in rows})
    lines = [f"streams={len(outs)} tasks={len(rows)} stream_tokens median={statistics.median(o['stream_tokens'] for o in outs):,.0f} "
             f"paragraphs median={statistics.median(o['n_paragraphs'] for o in outs):,.0f}"]
    for f in fam + ["ALL"]:
        rr = [r for r in rows if f in ("ALL", r["family"])]
        m = sorted(r["minimal"] for r in rr)
        q = lambda p: m[min(len(m) - 1, int(p * len(m)))]  # noqa: E731
        share = " ".join(f">{B}:{sum(x > B for x in m) / len(m):.2f}" for B in B_GRID)
        lines.append(f"{f:7s} n={len(rr):4d} minimal p10/p50/p90/max={q(.1)}/{q(.5)}/{q(.9)}/{m[-1]}  {share}")
    return "\n".join(lines)


if __name__ == "__main__":
    scale = float(sys.argv[1]); seeds = [int(x) for x in sys.argv[2].split(",")]
    print(f"scale={scale:g}"); print(summarize([support(s, scale) for s in seeds]))
