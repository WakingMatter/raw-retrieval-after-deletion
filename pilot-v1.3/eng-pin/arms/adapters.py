"""Model adapters: answerer, writers (A3 extractor, A4/A5 extraction + adjudication), embedders.

Every model sits behind one of these interfaces. Tests use the deterministic fakes. The real
adapters exist so M5 can switch them on, but in M2 they are **never called**. Every network adapter
first checks its endpoint and model against the frozen §3.1 routes (``gen/routes.py``) and refuses
anything else, then refuses unless ``CURRENCY_V0_ALLOW_REAL_CALLS=1`` is set. Since PREREG v1.1 §0.1a
(C1), INTERNAL (semi-real) payloads are allowed on those frozen routes only.

Frozen routes (prereg §3.1): answerer and writers ``xai/grok-4.7`` via the local OpenAI-compatible
proxy ``http://127.0.0.1:10100/v1``, temperature 0, ``MAX_OUTPUT_TOKENS = 512`` for every arm
(v1.1 §0.1c; holds if the M4 smoke shows truncation < 1%, see ``arms/metrics.py``).

Embedder (v1.1 §0.1d, C13): p3-mech's default ``gte-modernbert-base`` (768-d), HF revision
``e7f32e3c00f91d699e8c43b53106206bcc72bb22`` (recorded in ``protocol/FREEZE.json``), for A2
retrieval, A3 ranking and A5 ctx clustering; reranker ``gte-reranker-modernbert-base`` and
shortlister ``answerai-colbert-small-v1`` inside the A4 serve path. Local ONNX under
``EYWA_MODELS_DIR``; ``P3MechOnnxEmbedder`` wraps it.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
from dataclasses import dataclass, field

from gen.routes import ANSWERER, PROXY_BASE_URL, RouteRefused, check_route, post_frozen  # noqa: E402,F401

ANSWERER_MODEL = ANSWERER        # xai/grok-4.7 (v1.1 §0.1c)
WRITER_MODEL = ANSWERER
MAX_OUTPUT_TOKENS = 512          # every arm (v1.1 §0.1c); M4 smoke must show truncation < 1%
REAL_CALLS_ENV = "CURRENCY_V0_ALLOW_REAL_CALLS"


class RealCallRefused(RuntimeError):
    """A real model adapter was invoked without the env gate."""


REGISTERS = ("SYNTHETIC", "INTERNAL")


def _gate(register: str, role: str | None = None, base_url: str | None = None, model: str | None = None) -> str | None:
    """Route check first (every register), then the env gate. Returns the chat URL for network roles.

    ``role=None`` is a local adapter (ONNX embedder): no network, so no route, but still env-gated."""
    if register not in REGISTERS:
        raise RealCallRefused(f"unknown register {register!r}")
    url = check_route(role, base_url, model) if role is not None else None
    if os.environ.get(REAL_CALLS_ENV) != "1":
        raise RealCallRefused(f"real model calls are disabled (set {REAL_CALLS_ENV}=1 in M5+)")
    return url


# --------------------------------------------------------------------------- tokens (local)
_PIECE = re.compile(r"[A-Za-z]+|\d|[^\sA-Za-z\d]")


def local_tokens(text: str) -> int:
    """Conservative local token estimate (no grok tokenizer is available offline).

    Letters-runs cost ceil(len/4) (at least 1), every digit and every punctuation/symbol mark
    costs 1, and the result is never below ceil(utf8_bytes/4). Pre-call checks multiply this by
    1.15 (``common.SAFETY``); the binding check is post-call on the answerer's own usage."""
    if not text:
        return 0
    n = 0
    for m in _PIECE.finditer(text):
        s = m.group(0)
        n += max(1, math.ceil(len(s) / 4)) if s[0].isalpha() else 1
    return max(n, math.ceil(len(text.encode("utf-8")) / 4))


# --------------------------------------------------------------------------- answerer
@dataclass
class Completion:
    text: str
    prompt_tokens: int
    completion_tokens: int
    model: str
    raw: dict = field(default_factory=dict)
    finish_reason: str = "stop"           # "length" = hit max_tokens (truncated; C16 smoke metric)
    max_tokens: int = MAX_OUTPUT_TOKENS

    @property
    def truncated(self) -> bool:
        return self.finish_reason == "length"


class Answerer:
    model = "abstract"

    def complete(self, prompt: str, *, max_tokens: int = MAX_OUTPUT_TOKENS, register: str = "SYNTHETIC") -> Completion:
        raise NotImplementedError


class FakeAnswerer(Answerer):
    """Deterministic stand-in. Reports ``usage.prompt_tokens`` = local_tokens(prompt) + overhead,
    times ``inflate`` (the planted over-budget test sets inflate > 1). The answer is either a
    caller-supplied function of the prompt or a bare echo of the first excerpt line's value."""

    model = "fake-answerer"

    def __init__(self, *, overhead: int = 7, inflate: float = 1.0, respond=None):
        self.overhead, self.inflate, self.respond = overhead, inflate, respond
        self.calls: list[dict] = []

    def complete(self, prompt, *, max_tokens=MAX_OUTPUT_TOKENS, register="SYNTHETIC"):
        pt = int(math.ceil((local_tokens(prompt) + self.overhead) * self.inflate))
        text = self.respond(prompt) if self.respond else "not found in memory"
        ct = local_tokens(text)
        finish = "stop"
        if ct > max_tokens:                       # a fake can be told to overrun: it truncates like the API
            finish, ct = "length", max_tokens
        self.calls.append({"prompt_sha": hashlib.sha256(prompt.encode()).hexdigest()[:16], "prompt_tokens": pt,
                           "max_tokens": max_tokens})
        return Completion(text=text, prompt_tokens=pt, completion_tokens=ct, model=self.model, finish_reason=finish,
                          max_tokens=max_tokens)


class ProxyAnswerer(Answerer):
    """Real answerer: OpenAI-compatible chat completion on the frozen route. NOT CALLED IN M2."""

    model = ANSWERER_MODEL

    def __init__(self, base_url: str = PROXY_BASE_URL, api_key_env: str = "BENCH_API_KEY", model: str = ANSWERER_MODEL):
        self.base_url, self.api_key_env, self.model = base_url, api_key_env, model

    def complete(self, prompt, *, max_tokens=MAX_OUTPUT_TOKENS, register="SYNTHETIC"):
        url = _gate(register, "answerer", self.base_url, self.model)
        if max_tokens not in (MAX_OUTPUT_TOKENS, 1):      # 1 = template/question usage measurement only
            raise RealCallRefused(f"max_tokens must be {MAX_OUTPUT_TOKENS} for every arm (v1.1 §0.1c)")
        body = json.dumps({"model": self.model, "temperature": 0, "max_tokens": max_tokens,
                           "messages": [{"role": "user", "content": prompt}]}).encode()
        headers = {"Content-Type": "application/json",
                   "Authorization": f"Bearer {os.environ.get(self.api_key_env, 'x')}"}
        with post_frozen(url, body, headers, 180) as r:  # no env proxies, no redirects (C1)
            data = json.loads(r.read())
        u = data.get("usage") or {}
        if "prompt_tokens" not in u:
            raise RuntimeError("answerer returned no usage.prompt_tokens: the post-call budget check cannot run")
        ch = data["choices"][0]
        return Completion(text=ch["message"]["content"] or "", prompt_tokens=int(u["prompt_tokens"]),
                          completion_tokens=int(u.get("completion_tokens", 0)), model=data.get("model", self.model), raw=u,
                          finish_reason=ch.get("finish_reason") or "unknown", max_tokens=max_tokens)


# --------------------------------------------------------------------------- embedders
class Embedder:
    model_id = "abstract"

    def embed(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError


class HashEmbedder(Embedder):
    """Deterministic fake: hashed bag of lowercase word unigrams+bigrams, L2-normalised."""

    def __init__(self, dim: int = 256):
        self.dim = dim
        self.model_id = f"fake-hash-embedder-{dim}"

    def _one(self, text: str) -> list[float]:
        w = re.findall(r"[a-z0-9]+", text.lower())
        v = [0.0] * self.dim
        for g in w + [a + " " + b for a, b in zip(w, w[1:])]:
            h = int.from_bytes(hashlib.sha256(g.encode()).digest()[:8], "big")
            v[h % self.dim] += 1.0 if (h >> 63) == 0 else -1.0
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / n for x in v]

    def embed(self, texts):
        return [self._one(t) for t in texts]


class P3MechOnnxEmbedder(Embedder):
    """Real local embedder (p3-mech ``gte-modernbert-base`` via EYWA_MODELS_DIR). NOT CALLED IN M2.

    Local ONNX: no network. Kept behind the same gate so M2 tests cannot load it by accident."""

    model_id = "gte-modernbert-base"

    def embed(self, texts):
        # Released version: the vendored p3-mech package is not included and this class is not used by the
        # paper's experiments (they embed through pilot/embed.py -> pilot/gte_onnx.py). See RELEASE-NOTES.md.
        raise NotImplementedError("P3MechOnnxEmbedder is not part of the public release")


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


# --------------------------------------------------------------------------- writers
@dataclass
class WriteResult:
    rows: list[dict]
    prompt_tokens: int
    completion_tokens: int
    model: str


class Writer:
    """Extraction side: one call per session. ``rows`` are proposals (propose != commit)."""

    model = "abstract"

    def extract(self, session_id: str, paragraphs: list[str], t_start: str, *, context: list[dict] | None = None,
                register: str = "SYNTHETIC") -> WriteResult:
        raise NotImplementedError


class Adjudicator:
    """Write-side adjudication of the store's open cards (twin identity, rival pairs)."""

    model = "abstract"

    def twin(self, a: dict, b: dict, register: str = "SYNTHETIC") -> tuple[str, int, int]:
        raise NotImplementedError

    def rival(self, newer: dict, older: dict, register: str = "SYNTHETIC") -> tuple[str, int, int]:
        raise NotImplementedError


class ProxyWriter(Writer):
    """Real writer (grok-4.7). NOT CALLED IN M2. For A4 the real ingest path is the vendored p3-mech
    document door (``eywa.capture.capture_document``) with ``backend='openai:xai/grok-4.7'``; see
    arms/a4_store.py ``P3MechDoorIngest``. For A3 it is a thin generic extraction prompt."""

    model = WRITER_MODEL

    def __init__(self, base_url: str = PROXY_BASE_URL):
        self.base_url = base_url

    def extract(self, session_id, paragraphs, t_start, *, context=None, register="SYNTHETIC"):
        _gate(register, "writer", self.base_url, self.model)
        raise NotImplementedError("M5: wire the A3 extraction prompt (thin generic extractor, 2609.34227 §3)")


class ProxyAdjudicator(Adjudicator):
    """Real adjudicator (grok-4.7) for p3-mech twin/rival cards. NOT CALLED IN M2."""

    model = WRITER_MODEL

    def __init__(self, base_url: str = PROXY_BASE_URL):
        self.base_url = base_url

    def twin(self, a, b, register="SYNTHETIC"):
        _gate(register, "adjudicator", self.base_url, self.model)
        raise NotImplementedError("M5: wire the twin-card prompt")

    def rival(self, newer, older, register="SYNTHETIC"):
        _gate(register, "adjudicator", self.base_url, self.model)
        raise NotImplementedError("M5: wire the rival-card prompt")


_CHANGE_CUES = re.compile(r"\b(now|moved|changed|switched|instead|update[sd]?|correction|corrected|back to|reverted|"
                          r"no longer|replac\w*|from now on|going forward|new)\b", re.IGNORECASE)


class FakeRuleAdjudicator(Adjudicator):
    """Deterministic fake (tests only). Twins: 'same' iff the two names are identical after case
    folding. Rivals: 'newer' iff the newer quote carries a change cue word, else 'later' (leave
    open, both stay current). This is not the real adjudicator and makes no claim to its quality."""

    model = "fake-rule-adjudicator"

    def twin(self, a, b, register="SYNTHETIC"):
        same = (a.get("name") or "").casefold().strip() == (b.get("name") or "").casefold().strip()
        return ("same" if same else "different"), 0, 0

    def rival(self, newer, older, register="SYNTHETIC"):
        return ("newer" if _CHANGE_CUES.search(newer.get("quote") or "") else "later"), 0, 0
