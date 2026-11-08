"""Renderer interface: event script -> session prose.

Two implementations, deliberately separate:

* ``TemplateRenderer`` - deterministic, stdlib-only, used by every test and by
  any stream generated in M1. Same (stream seed, session script) -> same bytes.
* ``ProxyChatRenderer`` - the *real* renderer adapter (prereg §3.1: synthetic
  session renderer = ``google-antigravity/gemini-3.8-flash`` via the local
  OpenAI-compatible proxy). It is NOT called in M1/M2. It refuses to run unless
  ``CURRENCY_V0_ALLOW_REAL_RENDER=1`` is set, and it refuses any endpoint or model
  outside the frozen §3.1 routes (``gen/routes.py``). Since PREREG v1.1 §0.1a (C1),
  semi-real scripts are allowed, but only on that frozen route.

Gold never depends on the renderer: gold is computed from ``events.jsonl`` only.
The renderer returns ``segments`` (kind, event ids, tokens) so the DISTRACTOR
token share can be measured; segments are written to ``render_trace.jsonl``,
which is generator-side metadata and is never shown to an arm.
"""
from __future__ import annotations

import json
import os
import random
import re

from gen.common import est_tokens, parse_iso, sub_seed
from gen.routes import PROXY_BASE_URL, RENDERER, check_route, post_frozen
from gen.vocab import ALL_SLOT_LABELS, FILLER_TEMPLATES, FILLER_TOPICS, T

ETYPE_TO_TEMPLATE = {
    "ASSERT": "assert", "SUPERSEDE_EXPLICIT": "se", "SUPERSEDE_IMPLICIT": "si", "RESTATE": "restate",
    "RE_READ": "reread", "TRANSIENT_SET": "tset", "TRANSIENT_VOID": "tvoid", "RETURN": "return",
    "RETRACT": "retract",
}
DISTRACTOR_TOKEN_SHARE = 0.30  # prereg §5.1 DISTRACTOR "about 30% of tokens"


def fmt_day(t: str) -> str:
    d = parse_iso(t)
    return f"{d.day} {d.strftime('%b')}"


def fact_sentence(item: dict, rng: random.Random) -> str:
    evs = item["events"]
    if item["kind"] == "distractor":
        ev = evs[0]
        return T[ev["slot"]][ev["distractor_kind"]].format(s=ev["subject_name"], v=ev["value"])
    if len(evs) == 2:  # misattribution-bait pair, one sentence
        a, b = evs
        return T[a["slot"]]["bait"].format(s=a["subject_name"], v=a["value"], s2=b["subject_name"], v2=b["value"])
    ev = evs[0]
    variants = T[ev["slot"]][ETYPE_TO_TEMPLATE[ev["type"]]]
    tpl = variants[rng.randrange(len(variants))]
    d = fmt_day(ev["provenance"]["reverts_change_t"]) if ev["type"] == "RETURN" else ""
    return tpl.format(s=ev["subject_name"], v=ev["value"] if ev["value"] is not None else "", d=d)


def filler_paragraph(rng: random.Random, people: list[str], n_sent: int) -> str:
    out = []
    for _ in range(n_sent):
        tpl = FILLER_TEMPLATES[rng.randrange(len(FILLER_TEMPLATES))]
        p = people[rng.randrange(len(people))]
        q = people[rng.randrange(len(people))]
        x = FILLER_TOPICS[rng.randrange(len(FILLER_TOPICS))]
        out.append(tpl.format(p=p, q=q, x=x))
    return " ".join(out)


class TemplateRenderer:
    name = "template-v1"

    def __init__(self, stream_seed: int):
        self.stream_seed = stream_seed

    def render_session(self, script: dict) -> dict:
        rng = random.Random(sub_seed(self.stream_seed, "render", script["session"]))
        d = parse_iso(script["t_start"])
        header = f"# Session {script['index']:02d} - {d.strftime('%a')} {d.strftime('%Y-%m-%d')}"
        items = []
        for it in script["items"]:
            text = fact_sentence(it, rng)
            items.append({"kind": it["kind"], "event_ids": [e["id"] for e in it["events"]], "text": text,
                          "tokens": est_tokens(text)})
        dis = sum(i["tokens"] for i in items if i["kind"] == "distractor")
        fixed = est_tokens(header) + sum(i["tokens"] for i in items)
        total_target = int(round(dis / DISTRACTOR_TOKEN_SHARE)) if dis else script.get("target_tokens", 1300)
        filler_needed = max(0, total_target - fixed)
        fillers: list[str] = []
        got = 0
        while got < filler_needed:
            para = filler_paragraph(rng, script["people"], 2 + rng.randrange(3))
            fillers.append(para)
            got += est_tokens(para)
        # interleave: filler paragraphs spread evenly between items
        segments = [{"kind": "header", "event_ids": [], "text": header}]
        slots = len(items) + 1
        per = [len(fillers) // slots + (1 if k < len(fillers) % slots else 0) for k in range(slots)]
        fi = 0
        for k in range(slots):
            for _ in range(per[k]):
                segments.append({"kind": "filler", "event_ids": [], "text": fillers[fi]})
                fi += 1
            if k < len(items):
                segments.append({"kind": items[k]["kind"], "event_ids": items[k]["event_ids"],
                                 "text": items[k]["text"]})
        text = "\n\n".join(s["text"] for s in segments) + "\n"
        for s in segments:
            s["tokens"] = est_tokens(s["text"])
            s["chars"] = len(s["text"])
        return {"text": text, "segments": segments, "renderer": self.name}


# ------------------------------------------------------------------ lint

_ID_PATTERNS = [re.compile(r"\bK\d{3}\b"), re.compile(r"\bE\d{2}\b"), re.compile(r"\be\d{4}\b"),
                re.compile(r"\b[FD]:K\d{3}")]


def find_label_leaks(text: str, allowed: set[str] | None = None) -> list[str]:
    """Internal identifiers that appear verbatim in prose (key ids, entity ids,
    event ids, fact ids, slot labels). ``allowed`` = literals the event script
    explicitly put in the prose."""
    allowed = allowed or set()
    found = []
    for pat in _ID_PATTERNS:
        for m in pat.finditer(text):
            if m.group(0) not in allowed:
                found.append(m.group(0))
    low = text.lower()
    for lab in ALL_SLOT_LABELS:
        if lab in low and lab not in allowed:
            found.append(lab)
    return sorted(set(found))


# ------------------------------------------------------------------ real renderer (not called in M1)

class RealRendererDisabled(RuntimeError):
    pass


class ProxyChatRenderer:
    """Adapter for the frozen renderer route. Not exercised in M1 (no model calls)."""

    name = "proxy-chat:google-antigravity/gemini-3.8-flash"
    ENV_GATE = "CURRENCY_V0_ALLOW_REAL_RENDER"

    def __init__(self, stream_seed: int, base_url: str = PROXY_BASE_URL,
                 model: str = RENDERER, max_tokens: int = 6000,
                 timeout_s: int = 180, api_key_env: str = "BENCH_API_KEY"):
        self.stream_seed = stream_seed
        self.base_url = base_url
        self.model = model
        self.max_tokens = max_tokens
        self.timeout_s = timeout_s
        self.api_key_env = api_key_env
        self._templates = TemplateRenderer(stream_seed)

    def build_prompt(self, script: dict) -> str:
        rng = random.Random(sub_seed(self.stream_seed, "render", script["session"]))
        lines = []
        for it in script["items"]:
            lines.append({"item": it["item_id"], "kind": it["kind"], "say": fact_sentence(it, rng)})
        return (
            "You are writing one day's working notes for a small software organisation.\n"
            "Rewrite each item below as one natural paragraph, in order, keeping every name, number, "
            "date and value EXACTLY as given and keeping the meaning exactly (if an item signals a change, "
            "a correction, a revert or a retraction, keep that signal; if it does not, do not add one). "
            "Do not add any other facts about these people, projects, services or policies. Between items, "
            "add short neutral paragraphs about everyday team work (no numbers, no dates, no places) so the "
            f"whole note is about {script.get('target_tokens', 1300)} tokens long.\n"
            "Return JSON only: {\"paragraphs\": [{\"item\": <item id or \"filler\">, \"text\": \"...\"}]}.\n\n"
            + json.dumps(lines, ensure_ascii=False, indent=1)
        )

    def render_session(self, script: dict) -> dict:
        # Route first, for every register: semi-real text may go to the frozen route only (v1.1 §0.1a).
        url = check_route("renderer", self.base_url, self.model)
        if os.environ.get(self.ENV_GATE) != "1":
            raise RealRendererDisabled(f"set {self.ENV_GATE}=1 to call the real renderer (not allowed before M4)")
        body = json.dumps({
            "model": self.model, "temperature": 0, "max_tokens": self.max_tokens,
            "messages": [{"role": "user", "content": self.build_prompt(script)}],
            "response_format": {"type": "json_object"},
        }).encode("utf-8")
        headers = {"Content-Type": "application/json",
                   "Authorization": f"Bearer {os.environ.get(self.api_key_env, 'none')}"}
        with post_frozen(url, body, headers, self.timeout_s) as resp:  # no env proxies, no redirects (C1)
            payload = json.loads(resp.read().decode("utf-8"))
        content = payload["choices"][0]["message"]["content"]
        paras = json.loads(content)["paragraphs"]
        return self._assemble(script, paras, payload.get("usage"))

    def _assemble(self, script: dict, paras: list[dict], usage) -> dict:
        by_id = {it["item_id"]: it for it in script["items"]}
        d = parse_iso(script["t_start"])
        header = f"# Session {script['index']:02d} - {d.strftime('%a')} {d.strftime('%Y-%m-%d')}"
        segments = [{"kind": "header", "event_ids": [], "text": header}]
        for p in paras:
            it = by_id.get(p.get("item"))
            if it is None:
                segments.append({"kind": "filler", "event_ids": [], "text": p["text"]})
            else:
                segments.append({"kind": it["kind"], "event_ids": [e["id"] for e in it["events"]], "text": p["text"]})
        problems = lint_rendered(script, segments)
        if problems:
            raise ValueError(f"real render failed lint: {problems}")
        text = "\n\n".join(s["text"] for s in segments) + "\n"
        for s in segments:
            s["tokens"] = est_tokens(s["text"])
            s["chars"] = len(s["text"])
        return {"text": text, "segments": segments, "renderer": self.name, "usage": usage}


def lint_rendered(script: dict, segments: list[dict]) -> list[str]:
    """Post-render checks any renderer must pass: every scripted item present
    once with its exact values, and no internal labels in prose."""
    problems = []
    seen = {}
    for s in segments:
        for eid in s["event_ids"]:
            seen[eid] = s["text"]
    for it in script["items"]:
        for ev in it["events"]:
            txt = seen.get(ev["id"])
            if txt is None:
                problems.append(f"missing item {it['item_id']}")
                continue
            if ev.get("value") is not None and str(ev["value"]) not in txt:
                problems.append(f"value not verbatim for {ev['id']}")
            if ev.get("subject_name") and ev["subject_name"] not in txt:
                problems.append(f"subject not verbatim for {ev['id']}")
    allowed = set()
    for it in script["items"]:
        for ev in it["events"]:
            allowed.update(ev.get("scripted_literals", []))
    for s in segments:
        leaks = find_label_leaks(s["text"], allowed)
        if leaks:
            problems.append(f"label leak {leaks}")
    return problems
