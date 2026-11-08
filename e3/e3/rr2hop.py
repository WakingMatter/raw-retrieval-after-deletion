"""RR-2hop: two-step reranked raw retrieval (E3 fair comparator for A6 on DERIVED).

  hop 1  cosine top-K -> cross-encoder rerank on the question            (identical to E2 RerankedRaw)
  bridge one call to the answer model on the hop-1 served text: name the bridging person the question refers to
         only indirectly (the current owner/lead of the named service/project); reply with the name or NONE
  hop 2  cosine top-K -> rerank on  f"{entity} {question}"
  merge  interleave hop-1 and hop-2 ranked lists (h1[0], h2[0], h1[1], h2[1], ...), drop duplicates, prefix-fill to
         the same B with the E2 budget law (stop at the first item that would cross B)
  answer E2 answer prompt (render_prompt(texts, question, E2_PREFIX)), same model
If the bridge call fails or returns NONE/unparseable, RR-2hop serves hop 1 only (identical to RR's context).
The bridge call sees only surviving retrieved raw text and the question: never gold, ledger or deletion metadata."""
from __future__ import annotations
import re
from . import paths  # noqa: F401
from pilot.arms import unit_vec
from pilot.common import fill, render_prompt
from e2.arms_e2 import E2_PREFIX, TOP_K

BRIDGE_PROMPT = (
    "Do not answer the question. The question below names a service or project and asks about a person connected to "
    "it (for example its owner or its lead) without naming that person. Using only the dated excerpts, and preferring "
    "the most recent statement when they disagree, give the full name of that person. Reply with the person's name "
    "only, on one line. If the excerpts do not say who it is, reply NONE."
)
MAX_ENTITY_WORDS = 6


def bridge_prompt(question: str, served_texts: list[str]) -> str:
    return BRIDGE_PROMPT + "\n\nQuestion: " + question + "\n\nExcerpts:\n" + "\n".join(served_texts)


def parse_entity(text: str | None) -> str | None:
    """First non-empty line, stripped of markup/quotes/trailing punctuation; None for NONE, empty or over-long."""
    if not text:
        return None
    line = next((l for l in text.strip().splitlines() if l.strip()), "")
    line = re.sub(r"^(answer|name|entity)\s*:\s*", "", line.strip(), flags=re.I)
    line = line.strip(" *`\"'“”‘’").rstrip(".;:,!").strip()
    if not line or re.fullmatch(r"none|unknown|not found.*|n/?a", line, re.I):
        return None
    if len(line.split()) > MAX_ENTITY_WORDS:
        return None
    return line


def hop2_query(entity: str, question: str) -> str:
    return f"{entity} {question}"


def ranked(chunks: dict, emb, reranker, query: str, t_query: str, top_k: int = TOP_K) -> list[dict]:
    """Full reranked candidate list exactly as E2 RerankedRaw.read orders it (before fill)."""
    qv = unit_vec(emb, query)
    live = [(c, x) for c, x in chunks.items() if x["t"] <= t_query]
    cos = sorted(live, key=lambda cx: (-round(float(cx[1]["vec"] @ qv), 12), cx[0]))[:top_k]
    sc = reranker.scores(query, [x["text"] for _, x in cos])
    rk = sorted(zip(cos, sc), key=lambda z: (-round(z[1], 9), z[0][0]))
    return [{"text": f"[{c} | {x['t'][:16]}] {x['text']}", "kind": "chunk", "ref": c} for (c, x), _ in rk]


def interleave(a: list[dict], b: list[dict]) -> list[dict]:
    out, seen = [], set()
    for i in range(max(len(a), len(b))):
        for lst in (a, b):
            if i < len(lst) and lst[i]["ref"] not in seen:
                seen.add(lst[i]["ref"]); out.append(lst[i])
    return out


class RR2Hop:
    """chunks: {chunk_id: {"t", "text", "vec"}} of SURVIVING raw paragraphs (E2 RerankedRaw state)."""

    def __init__(self, chunks, emb, reranker, llm, top_k=TOP_K):
        self.chunks, self.emb, self.rr, self.llm, self.top_k = chunks, emb, reranker, llm, top_k

    def ask(self, question: str, t_query: str, B: float, ctx=None) -> dict:
        h1 = ranked(self.chunks, self.emb, self.rr, question, t_query, self.top_k)
        s1, _ = fill(h1, B)
        rb = self.llm.call("bridge", bridge_prompt(question, [it["text"] for it in s1]), ctx=ctx)
        entity = parse_entity(rb.get("text")) if rb.get("ok") else None
        if entity:
            h2 = ranked(self.chunks, self.emb, self.rr, hop2_query(entity, question), t_query, self.top_k)
            served, used = fill(interleave(h1, h2), B)
        else:
            h2 = []
            served, used = fill(h1, B)
        ra = self.llm.call("answer", render_prompt([it["text"] for it in served], question, E2_PREFIX), ctx=ctx)
        return {"answer": (ra.get("text") or "").strip(), "ok": ra.get("ok"), "stop": ra.get("stop"),
                "entity": entity, "bridge_ok": rb.get("ok"), "bridge_raw": (rb.get("text") or "")[:200],
                "served": [it["ref"] for it in served], "hop1_served": [it["ref"] for it in s1],
                "hop2_top": [it["ref"] for it in h2[:10]], "raw_tokens_est": used,
                "bridge_usage": rb.get("usage"), "answer_usage": ra.get("usage"),
                "bridge_memo": rb.get("memo_hit"), "answer_memo": ra.get("memo_hit"),
                "bridge_attempts": len(rb.get("attempt_history") or []),
                "answer_attempts": len(ra.get("attempt_history") or [])}
