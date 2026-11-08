"""Shared assembler and token-budget enforcement (brief §4, §5; prereg §3.2, §4).

``assemble(arm, task, B, t_query) -> Pack{items, trace}`` is the one entry every arm goes through.
The prompt template is ``SYNTH_PREFIX``, copied verbatim from ``runner.py`` (L40-44), and
``render_prompt`` is ``runner._synthesize``'s layout:
``f"{SYNTH_PREFIX}\\n\\n{excerpts}\\n\\n{question}"``, with ``"(no excerpts)"`` when the pack is empty.

Budget law:
- **Pre-call:** each item costs ``local_tokens(item + separator) x SAFETY`` (1.15). The arm's own
  ranking is filled in order and trimmed at the first item that would cross B. No item is
  admitted over B, not even the first.
- **Post-call:** ``assembled = usage.prompt_tokens - template_tokens - question_tokens``, from the
  answerer's own usage. ``template_tokens`` is measured **once per run** with a call whose excerpts and
  question are empty. ``question_tokens`` is measured once per distinct question with a call whose
  excerpts are empty. If ``assembled > B``, the call is logged invalid and ``BudgetAbort`` is raised.
  The harness then stops the run.
- **Natural size** (B=None): no trimming and no abort. Logged with ``mode='natural'`` and labelled
  descriptive. A1 is always natural (uncapped, prereg §4).
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

from arms.adapters import Answerer, Completion, local_tokens

SYNTH_PREFIX = (
    "Answer the question using ONLY the excerpts below. "
    "If the excerpts do not contain the answer, say 'not found in memory'. "
    "Be direct and specific."
)
NO_EXCERPTS = "(no excerpts)"
SEP = "\n\n"
SAFETY = 1.15
BUDGETS = (2000, 8000)
A5_EXTRA_BUDGET = 1000


SERVED_FIELDS = ("ref", "kind", "session", "key", "tier", "exploration", "propensity", "ctx_id")


class BudgetAbort(RuntimeError):
    """A post-call check found assembled tokens > B. The run must stop."""

    def __init__(self, row: dict):
        super().__init__(f"BUDGET ABORT: arm={row['arm']} B={row['B']} task={row['task_id']} "
                         f"assembled={row['assembled_tokens']} > B (usage={row['prompt_tokens']}, "
                         f"template={row['template_tokens']}, question={row['question_tokens']})")
        self.row = row


@dataclass
class Item:
    text: str
    kind: str                     # session | chunk | record | fact | ledger | filler
    ref: str = ""                 # session id / chunk id / record id / fact id
    meta: dict = field(default_factory=dict)

    def cost(self) -> int:
        return local_tokens(self.text + SEP)


@dataclass
class Pack:
    items: list[dict]
    trace: dict

    def excerpts(self) -> str:
        return SEP.join(i["text"] for i in self.items) if self.items else NO_EXCERPTS


def render_prompt(excerpts: str, question: str) -> str:
    return f"{SYNTH_PREFIX}\n\n{excerpts}\n\n{question}"


def fill(candidates: list[Item], B: int | None) -> tuple[list[Item], dict]:
    """Prefix-fill in the arm's own order; stop at the first item whose safety-scaled cost crosses B."""
    kept, used_est = [], 0.0
    for it in candidates:
        c = it.cost() * SAFETY
        if B is not None and used_est + c > B:
            break
        kept.append(it)
        used_est += c
    return kept, {"n_candidates": len(candidates), "n_items": len(kept), "trimmed": len(candidates) - len(kept),
                  "est_tokens_x1.15": math.ceil(used_est), "est_tokens_raw": sum(i.cost() for i in kept)}


def assemble(arm, task: dict, B: int | None, t_query: str) -> Pack:
    """The shared assembler. ``arm`` is an arm instance exposing ``name``, ``capped`` and
    ``candidates(task, t_query, B)``. Capped arms are trimmed at B; uncapped arms (A1) are not."""
    eff_B = B if arm.capped else None
    cands = arm.candidates(task, t_query, eff_B)
    kept, tr = fill(cands, eff_B)
    trace = {"arm": arm.name, "B": B, "mode": "natural" if eff_B is None else "capped", "t_query": t_query,
             "task_id": task.get("id"), **tr, **getattr(arm, "last_trace", {})}
    items = [{"text": it.text, "kind": it.kind, "ref": it.ref, **it.meta} for it in kept]
    return Pack(items=items, trace=trace)


class CallLog:
    """Append-only per-call log (JSONL). Every answer, write, adjudication, measurement and
    leave-one-out call lands here with its input and output tokens."""

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else None
        self.rows: list[dict] = []
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)

    def add(self, **row) -> dict:
        row = {"seq": len(self.rows), **row}
        self.rows.append(row)
        if self.path:
            with open(self.path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, sort_keys=True) + "\n")
        return row

    def cost(self, **row) -> dict:
        return self.add(**row)


class Meter:
    """Template and question tokens, measured with the answerer's own usage."""

    def __init__(self, answerer: Answerer, log: CallLog, run_id: str = ""):
        self.answerer, self.log, self.run_id = answerer, log, run_id
        self.template_tokens: int | None = None
        self._q: dict[str, int] = {}

    def template(self, register: str = "SYNTHETIC") -> int:
        if self.template_tokens is None:
            c = self.answerer.complete(render_prompt("", ""), max_tokens=1, register=register)
            self.template_tokens = c.prompt_tokens
            self.log.add(kind="measure", what="template", run=self.run_id, model=c.model,
                         prompt_tokens=c.prompt_tokens, completion_tokens=c.completion_tokens)
        return self.template_tokens

    def question(self, q: str, register: str = "SYNTHETIC") -> int:
        if q not in self._q:
            t = self.template(register)
            c = self.answerer.complete(render_prompt("", q), max_tokens=1, register=register)
            self._q[q] = c.prompt_tokens - t
            self.log.add(kind="measure", what="question", run=self.run_id, model=c.model, question=q,
                         prompt_tokens=c.prompt_tokens, completion_tokens=c.completion_tokens, question_tokens=self._q[q])
        return self._q[q]


def answer(arm, task: dict, B: int | None, t_query: str, answerer: Answerer, meter: Meter, log: CallLog,
           *, register: str = "SYNTHETIC", pack: Pack | None = None) -> tuple[Completion, Pack, dict]:
    """Assemble, call the answerer once, verify the budget post-call, log. Raises BudgetAbort."""
    pack = pack or assemble(arm, task, B, t_query)
    q = task["question"]
    tmpl, qt = meter.template(register), meter.question(q, register)
    prompt = render_prompt(pack.excerpts(), q)
    c = answerer.complete(prompt, register=register)
    assembled = c.prompt_tokens - tmpl - qt
    capped = pack.trace["mode"] == "capped"
    valid = (assembled <= B) if capped else True
    row = log.add(kind="answer", run=meter.run_id, arm=arm.name, B=B, mode=pack.trace["mode"], task_id=task.get("id"),
                  task_kind=task.get("kind", "probe"), model=c.model, prompt_tokens=c.prompt_tokens,
                  completion_tokens=c.completion_tokens, template_tokens=tmpl, question_tokens=qt,
                  assembled_tokens=assembled, est_tokens_x115=pack.trace["est_tokens_x1.15"],
                  n_items=pack.trace["n_items"], valid=valid, answer=c.text,
                  max_tokens=getattr(c, "max_tokens", None), finish_reason=getattr(c, "finish_reason", None),
                  truncated=bool(getattr(c, "truncated", False)),
                  served=[{k: i.get(k) for k in SERVED_FIELDS if k in i} for i in pack.items],
                  trace={k: v for k, v in pack.trace.items() if k not in ("arm", "B", "task_id")})
    if not valid:
        raise BudgetAbort(row)
    return c, pack, row
