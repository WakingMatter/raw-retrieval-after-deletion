"""Shared paths, frozen prompts (v1.2 §2.2-§2.3 verbatim; v1.1 answer template from Eng's pinned arms/common.py)."""
from __future__ import annotations
import hashlib, json, math, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]            # research/pilot-v1.2
ENG_PIN = ROOT / "eng-pin"                            # git archive of Eng commit 863fb79 (read-only copy)
DATA = ROOT / "data"
if str(ENG_PIN) not in sys.path:
    sys.path.insert(0, str(ENG_PIN))
from arms.common import SYNTH_PREFIX, NO_EXCERPTS, SEP, SAFETY  # noqa: E402  (verbatim v1.1 template)
from arms.adapters import local_tokens  # noqa: E402

ENG_COMMIT = "863fb794257e22f615c8be82801bd4398a21d78e"
PREREG_V12_SHA = "329023498ddc109f7924098145f4f80f8d816156be2b8c4dc04f333d6c02dad6"

# ---- frozen prompts (v1.2 §2.2, §2.3) ----
P_A3N_WRITE = ("You maintain a long-term memory of atomic notes about a user's world. Each note states ONE fact about "
               "one subject, in ≤ 40 words, with the date it became true. Read the new session and the existing notes. "
               "Return JSON {\"ops\":[...]} using only: ADD {text, date}; UPDATE {id, text, date} (an existing note is "
               "changed, corrected or superseded; rewrite it to state the current fact; keep at most one clause about the "
               "prior value); DELETE {id} (no longer true, no replacement); NOOP. Prefer UPDATE over ADD for the same "
               "subject and attribute. Never invent facts. Do not copy chit-chat.")
P_CLUSTER = "Update this ≤ 120-word summary so it reflects the notes below. State current values with dates."
P_REDACT = "Rewrite the note so it contains nothing that came only from the text below; keep facts supported elsewhere."
P_A6_SYN = ("Summarise the dated excerpts below in ≤ 120 words. For each subject and attribute, state the latest value "
            "and its date. If a value changed, say so in one clause. Use only the excerpts.")
P_A6M_CITE = ("After each sentence, cite in brackets the ids of EVERY excerpt the sentence relies on, including excerpts "
              "you combined, compared or counted. Cite nothing you did not use.")
P_A6M_ANSWER_SUFFIX = " End with a line `SOURCES: [ids]` listing every excerpt id your answer relied on."
P_JUDGE = None  # defined in judge.py

ANSWER_MODEL = "grok-4.7"
JUDGE_MODEL = "gpt-6.1-sol"
SYN_CAP_TOKENS = 3000
K_ANCHORS = 16
REFRESH_AT = (10, 20, 30, 40, 50, 60)

A3N_SCHEMA = json.dumps({
    "type": "object", "required": ["ops"],
    "properties": {"ops": {"type": "array", "items": {
        "type": "object", "required": ["op"],
        "properties": {"op": {"type": "string", "enum": ["ADD", "UPDATE", "DELETE", "NOOP"]},
                       "id": {"type": "string"}, "text": {"type": "string"}, "date": {"type": "string"}}}}}})


def sha(s: str | bytes) -> str:
    return hashlib.sha256(s.encode() if isinstance(s, str) else s).hexdigest()


def render_prompt(excerpts: list[str], question: str, prefix: str = SYNTH_PREFIX) -> str:
    body = SEP.join(excerpts) if excerpts else NO_EXCERPTS
    return f"{prefix}\n\n{body}\n\n{question}"


def item_cost(text: str) -> float:
    return local_tokens(text + SEP) * SAFETY


def fill(items: list[dict], B: float) -> tuple[list[dict], float]:
    """Eng budget law: prefix-fill in rank order, stop at the first item that would cross B."""
    out, used = [], 0.0
    for it in items:
        c = item_cost(it["text"])
        if used + c > B:
            break
        out.append(it)
        used += c
    return out, used


NON_ANSWER = re.compile(r"(rate limit (exceeded|reached)|rate-?limited\b|you('ve| have) (hit|reached|exceeded)|exceeded your (current )?quota|quota exceeded|usage limit|too many requests|"
                        r"try again later|unauthori[sz]ed|internal server error|service unavailable|^\s*error\b|"
                        r"i can(?:no|')t (help|assist)|i'm unable to (help|assist)|as an ai\b)", re.I | re.M)


def is_non_answer(text: str | None) -> bool:
    """Cache-poisoning guard (§3.3a(ii)): empty, banner, error or refusal text. Patterns are checked only on the
    first line / first 200 chars (a banner or refusal leads), so stream content such as 'quota-guard' never trips it."""
    if text is None or not text.strip():
        return True
    head = text.strip()[:200]
    return bool(NON_ANSWER.search(head.splitlines()[0])) or (len(text.strip()) < 200 and bool(NON_ANSWER.search(head)))


def not_found(text: str) -> bool:
    return bool(re.search(r"not found in memory", text or "", re.I))


def jdump(o) -> str:
    return json.dumps(o, sort_keys=True, ensure_ascii=False)
