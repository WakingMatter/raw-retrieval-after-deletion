"""Arm interface. Arms see session prose and timestamps only, never ledger files. The two
oracle arms are the exception, by definition. ``candidates`` returns the arm's own ordering, and
``arms.common.assemble`` trims it at B."""
from __future__ import annotations

import re

from arms.common import Item


class Arm:
    name = "abstract"
    capped = True
    stateful = True

    def __init__(self):
        self.last_trace: dict = {}

    def ingest(self, session_id: str, text: str, t_start: str) -> dict:
        return {}

    def forget(self, session_id: str) -> dict:
        return {"session": session_id, "removed": 0}

    def candidates(self, task: dict, t_query: str, B: int | None) -> list[Item]:
        raise NotImplementedError


def fold_key(subject: str, slot: str) -> str:
    s = " ".join((subject or "").casefold().split())
    t = re.sub(r"[_\-\s]+", " ", (slot or "").casefold()).strip()
    return f"{s}|{t}"


def short_id(fact_id: str) -> str:
    return fact_id[:10]


def read_jsonl(p) -> list[dict]:
    import json
    with open(p, encoding="utf-8") as fh:
        return [json.loads(x) for x in fh]


def read_json(p):
    import json
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)
