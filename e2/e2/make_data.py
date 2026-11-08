"""Generate E2 streams (model-free, deterministic) and author E2 tasks. Confirmatory seeds 7260001-7260032;
DEV seeds 7269001-7269004 (qualification, K-delivery, nuisance variance). Writes data/stream-S/ and data/tasks-S.json."""
from __future__ import annotations
import json, subprocess, sys
from .paths import DATA, ENG_PIN
from .tasks import author_e2

CONFIRM = list(range(7260001, 7260033))
DEV = list(range(7269001, 7269005))
EXTRA = list(range(7260033, 7260048)) + [7260049]   # stream-addition reserve (prereg §7), used in this order only if
# the rule fires; 7260048 skipped (generator yields 39 tasks, short 1 DERIVED), replaced by the next full seed


def main(seeds=None):
    seeds = seeds or CONFIRM + DEV + EXTRA
    DATA.mkdir(parents=True, exist_ok=True)
    summary = {}
    for s in seeds:
        d = DATA / f"stream-{s}"
        if not (d / "MANIFEST.json").exists():
            subprocess.run([sys.executable, "-m", "gen.gen_stream", "--seed", str(s), "--out", str(d)], cwd=ENG_PIN,
                           check=True, capture_output=True)
        r = author_e2(d)
        (DATA / f"tasks-{s}.json").write_text(json.dumps(r, indent=1))
        summary[s] = {"n_tasks": len(r["tasks"]), "shortfall": r["shortfall"], "n_warm": len(r["warm"]),
                      "deleted": r["deleted"]}
    (DATA / "SUPPLY.json").write_text(json.dumps(summary, indent=1))
    return summary


if __name__ == "__main__":
    out = main()
    short = {s: v["shortfall"] for s, v in out.items() if any(v["shortfall"].values())}
    print(f"streams={len(out)} tasks={sum(v['n_tasks'] for v in out.values())} short={short}")
