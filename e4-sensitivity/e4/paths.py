"""E4 paths. e2, e3, pilot-v1.3 and eng-pin are imported read-only; nothing outside e4-sensitivity/ is written."""
from __future__ import annotations
import sys
from pathlib import Path

E4 = Path(__file__).resolve().parents[1]          # research/e4-sensitivity
RESEARCH = E4.parent
for p in (RESEARCH / "e2", RESEARCH / "e3"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
from e2 import paths as _e2paths  # noqa: E402  (adds pilot-v1.3 and eng-pin to sys.path)

PILOT, ENG_PIN = _e2paths.PILOT, _e2paths.ENG_PIN
E2_RUNS = _e2paths.RUNS                              # read-only: CONFIRM stats for the fake-synth length model
DATA = E4 / "data"                                   # gitignored; regenerable from seeds
RUNS = E4 / "runs"

# Fresh seeds. E2 used 7260001-7260049 and 7269001-7269004; no 728xxxx seed appears anywhere in the repo (checked
# 2026-10-25 with a word-bounded search over *.py/*.md/*.json).
MAIN = list(range(7280001, 7280017))      # 16 planned streams
RESERVE = list(range(7280017, 7280033))   # replacements, used in order, only for generator shortfall
DEV = [7289001, 7289002]                  # smoke / generic-bridge prompt check only, never scored with MAIN


def planned_streams(n=16):
    """First n seeds from MAIN then RESERVE (in order) whose authored task set is full (40 tasks, no shortfall)."""
    import json
    out = []
    for s in MAIN + RESERVE:
        f = DATA / f"tasks-{s}.json"
        if not f.exists():
            continue
        r = json.loads(f.read_text())
        if len(r["tasks"]) == 40 and not any(r["shortfall"].values()):
            out.append(s)
        if len(out) == n:
            break
    return out
