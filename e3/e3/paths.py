"""E3 paths. E2 (and through it pilot-v1.3/eng-pin) is imported read-only; nothing under e2/ is modified."""
from __future__ import annotations
import sys
from pathlib import Path

E3 = Path(__file__).resolve().parents[1]          # research/e3
RESEARCH = E3.parent
E2 = RESEARCH / "e2"
if str(E2) not in sys.path:
    sys.path.insert(0, str(E2))
from e2 import paths as _e2paths  # noqa: E402,F401  (adds pilot-v1.3 and eng-pin to sys.path)
