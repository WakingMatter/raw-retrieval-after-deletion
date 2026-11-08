"""Generate fresh-seed E4 streams with the pinned generator (model-free) and author E2-style tasks into e4 data/."""
from __future__ import annotations
import json, subprocess, sys
from .paths import DATA, ENG_PIN, MAIN, RESERVE, DEV
from e2.tasks import author_e2


def main(seeds=None):
    seeds = seeds or MAIN + DEV
    DATA.mkdir(parents=True, exist_ok=True)
    supply = json.loads((DATA / "SUPPLY.json").read_text()) if (DATA / "SUPPLY.json").exists() else {}
    for s in seeds:
        d = DATA / f"stream-{s}"
        if not (d / "MANIFEST.json").exists():
            subprocess.run([sys.executable, "-m", "gen.gen_stream", "--seed", str(s), "--out", str(d)], cwd=ENG_PIN,
                           check=True, capture_output=True)
        if not (DATA / f"tasks-{s}.json").exists():
            r = author_e2(d)
            (DATA / f"tasks-{s}.json").write_text(json.dumps(r, indent=1))
        r = json.loads((DATA / f"tasks-{s}.json").read_text())
        supply[str(s)] = {"n_tasks": len(r["tasks"]), "shortfall": r["shortfall"], "n_warm": len(r["warm"])}
    (DATA / "SUPPLY.json").write_text(json.dumps(supply, indent=1))
    return supply


if __name__ == "__main__":
    seeds = [int(x) for x in sys.argv[1].split(",")] if len(sys.argv) > 1 else None
    out = main(seeds)
    print(json.dumps({k: v for k, v in out.items() if any(v["shortfall"].values()) or v["n_tasks"] != 40}) or "all full")
    print("streams", len(out), "tasks", sum(v["n_tasks"] for v in out.values()))
