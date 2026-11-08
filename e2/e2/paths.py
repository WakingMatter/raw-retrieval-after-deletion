"""Paths. pilot-v1.3 and its eng-pin are imported read-only (never modified by E2)."""
from __future__ import annotations
import sys
from pathlib import Path

E2 = Path(__file__).resolve().parents[1]          # research/e2
RESEARCH = E2.parent
PILOT = RESEARCH / "pilot-v1.3"
ENG_PIN = PILOT / "eng-pin"
DATA = E2 / "data"
RUNS = E2 / "runs"
for p in (PILOT, ENG_PIN):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
