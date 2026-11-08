"""E4 arms. A6E4 = E2's A6E2 with the header share and the per-summary cap as read-time parameters.

Design choice (PREDICTION-AND-DESIGN.md §3): the warm phase runs once per stream at the E2 reference config
(B=2000, header 1/5, cap 200), so every cell reads the SAME post-delete memory state. The synth prompt (<= 50 words)
does not depend on B, cap or share, so every summary is one cached synth call shared by all cells; the cap is applied
at read time to the stored raw summary with E2's cap_summary (sentence truncation)."""
from __future__ import annotations
import math
from e2.arms_e2 import A6E2, cap_summary, label_of, E2_PREFIX
from pilot.arms import unit_vec
from pilot.common import fill, item_cost

# Generic bridge, v1 (DEV pilot 25 Oct: failed DEFAULTS D01 criteria 1 and 2; kept for the record).
BRIDGE_PROMPT_GENERIC_V1 = (
    "Do not answer the question. Using only the dated excerpts, decide whether answering the question needs one more "
    "lookup about a person, service, project or configuration that the question refers to without naming it (for "
    "example 'the service owned by X' or 'the project's lead'). If so, reply with that thing's full name only, on one "
    "line, preferring the most recent statement when excerpts disagree. If the question already names everything "
    "needed, or the excerpts do not say, reply NONE."
)
# v2 (DEFAULTS D13): an explicit relation-vs-named test, and a most-recent best guess instead of NONE when the
# excerpts link the relation to any name.
BRIDGE_PROMPT_GENERIC_V2 = (
    "Do not answer the question. First decide whether the question identifies the thing it asks about only through "
    "a relation instead of by name, such as 'the service owned by <person>', 'the project led by <person>', 'the "
    "person who owns <service>' or 'the person leading <project>'. If the question names the thing it asks about "
    "directly (including questions that ask who owns or leads something, or how many values something has had), "
    "reply NONE. Otherwise reply with the full name of the unnamed thing, on one line and nothing else, using only "
    "the dated excerpts. When excerpts disagree or the relation changed over time, give the most recently stated "
    "one. Give your best reading of the excerpts rather than NONE; reply NONE only if no excerpt links the relation "
    "to any name."
)
# v3 (DEFAULTS D14, last revision allowed by D01): v2 answered the final question (a city or team) instead of naming
# the intermediate. v3 asks for the intermediate explicitly, says what type it must be, and gives four shapes.
BRIDGE_PROMPT_GENERIC_V3 = (
    "Do not answer the question. Your job is only to name an intermediate entity for a second lookup.\n"
    "Some questions refer to their subject through a relation instead of by name. Four shapes:\n"
    "- 'the person who owns <service>' or 'the person leading <project>': reply with that PERSON's full name.\n"
    "- 'the service owned by <person>': reply with that SERVICE's name.\n"
    "- 'the project led by <person>': reply with that PROJECT's name.\n"
    "The reply is the person, service or project in the relation, never the thing the question finally asks for "
    "(never a team, city, region, date, number or other attribute).\n"
    "If the question has no such relation because it names its subject directly (for example it asks who owns or "
    "leads a named thing, which team or city a named person has, or how many values something has had), reply NONE.\n"
    "Otherwise use only the dated excerpts. If the relation changed over time, give the most recently stated holder. "
    "Give your best reading rather than NONE; reply NONE only if no excerpt links the relation to any name.\n"
    "Reply with the name only, on one line, nothing else."
)
BRIDGE_PROMPT_GENERIC = BRIDGE_PROMPT_GENERIC_V3   # D16: v3 passed all three D01 criteria


def bridge_prompt_generic(question: str, served_texts: list[str]) -> str:
    return BRIDGE_PROMPT_GENERIC + "\n\nQuestion: " + question + "\n\nExcerpts:\n" + "\n".join(served_texts)


def eff_cap(B: float, cap: float | None, share: float) -> float:
    """A served summary can never exceed the header, so cap > header == uncapped-within-header."""
    return min(math.inf if cap is None else cap, B * share)


class A6E4(A6E2):
    def _compute_summary(self, n, t_query, phase):
        c = super()._compute_summary(n, t_query, phase)
        if c is not None:                                  # keep the uncapped text so any cap can be applied later
            c["raw"] = self._last_raw.pop(n, None)
        return c

    def _llm(self, role, prompt, phase, ctx=None, **kw):
        # cost attribution only (ctx is not part of the cache key). pilot Base._llm overwrites ctx['arm'] with
        # self.name, so the intended arm (A6, A6-syn, A6-T4) is carried as ctx['e4_arm'].
        ctx = dict(ctx or {})
        if role == "synth":
            ctx.update(self.ctx_extra)
        ctx["e4_arm"] = ctx.get("arm", self.name)
        r = super()._llm(role, prompt, phase, ctx=ctx, **kw)
        if role == "synth" and ctx and "node" in ctx and r.get("ok"):
            self._last_raw[ctx["node"]] = (r.get("text") or "").strip()
        return r

    def __init__(self, *a, **kw):
        self._last_raw, self.ctx_extra = {}, {}
        super().__init__(*a, **kw)

    def read_cell(self, question, t_query, B, share, cap, phase, syn=True):
        """A6E2.read with header = share*B and each summary re-capped to eff_cap(B, cap, share)."""
        qv = unit_vec(self.emb, question)
        nodes = [n for n in range(self.add.k) if self.add.count[n] > 0]
        nodes.sort(key=lambda n: (-float(self.add.centroid(n) @ qv), n))
        top = nodes[:3]
        hcap, ecap = B * share, eff_cap(B, cap, share)
        header, used, node_trace = [], 0.0, []
        if syn:
            for n in top:
                c = self.summary(n, t_query, phase)
                if c is None:
                    node_trace.append({"node": n, "status": "none"}); continue
                label = label_of(n)
                text, trunc = cap_summary(c.get("raw") or c["text"], label, ecap)
                it = {"text": f"[{label}] {text}", "kind": "summary", "ref": label, "node": n, "deps": list(c["deps"]),
                      "soft_poison": c["soft_poison"]}
                cost = item_cost(it["text"])
                if used + cost > hcap:
                    node_trace.append({"node": n, "status": "skipped_no_fit", "cost": cost}); continue
                header.append(it); used += cost
                node_trace.append({"node": n, "status": "served", "cost": cost, "truncated": trunc})
        cands = [u for n in top for u in self.add.members[n] if self.units[u]["t"] <= t_query]
        cands.sort(key=lambda u: (-float(self.units[u]["vec"] @ qv), u))
        items = [{"text": f"[{u} | {self.units[u]['t'][:16]}] {self.units[u]['text']}", "kind": self.units[u]["kind"],
                  "ref": u} for u in cands]
        pool = sum(item_cost(it["text"]) for it in items)
        raw, used2 = fill(items, B - used)
        trace = {"top_nodes": top, "nodes": node_trace, "header_tokens_est": used, "raw_tokens_est": used2,
                 "n_raw": len(raw), "raw_pool_est": pool, "pool_exhausted": len(raw) == len(items)}
        return header + raw, trace

    def ask_cell(self, question, t_query, B, share, cap, phase, ctx=None, syn=True):
        served, trace = self.read_cell(question, t_query, B, share, cap, phase, syn=syn)
        r, prompt = self.answer(served, question, phase, E2_PREFIX, ctx)
        return {"answer": (r.get("text") or "").strip(), "ok": r["ok"], "served": [it["ref"] for it in served],
                "trace": trace, "prompt_chars": len(prompt), "usage": r.get("usage"), "stop": r.get("stop")}
