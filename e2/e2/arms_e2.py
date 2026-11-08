"""E2 arms (DRAFT). Subclass / wrap pilot-v1.3 arms without editing them.

* A6E2 -- pilot A6 (code edges, lazy keyed recompute) with the E1/A6-SERVING fixes:
    (a) synth output hard-capped at SYN_OUT_CAP (= B/5 = 400 estimated tokens under pilot `item_cost`, label
        included) by deterministic sentence-boundary truncation (word-boundary if one sentence is too long);
        the cache entry records `truncated` and pre/post costs;
    (b) header packing is skip-and-continue (a summary that does not fit is skipped, later ones still tried);
    (c) read() takes syn=True/False so A6 and A6-syn (no summary header) read the SAME warm state;
    (d) per-probe read trace: top_nodes, per-node summary status, served summary ids, header/raw token estimates.
  Summary cache keys use the E2 answer model id (pilot's ANSWER_MODEL constant is not used by E2).
* RerankedRaw -- surviving raw paragraphs (same chunking as RS/A2Rag), cosine top-K with the pilot embedder,
  cross-encoder rerank (gte-reranker-modernbert-base, fp32 torch CPU, pinned revision), prefix-fill to B. Zero generative calls.
"""
from __future__ import annotations
import glob, os, re, threading, time
from pathlib import Path
import numpy as np
from . import paths  # noqa: F401
from pilot.arms import A6, Base, paragraphs, unit_vec
from pilot.common import SYNTH_PREFIX, sha, fill, item_cost, is_non_answer, not_found
from pilot.store import input_set_hash, cache_key
from .minimax_api import MODEL

B_DEFAULT = 2000
HEADER_CAP = B_DEFAULT / 5           # 400 est. tokens: the preregistered 1/5 B header rule (unchanged)
SYN_OUT_CAP = B_DEFAULT / 10         # 200 est. tokens per served summary (label included), so >=2 fit in the header
SYN_WORDS = 50                       # synth instruction (was <=120 words); ~3-4 est. tokens/word under common.py costing
TOP_K = 50
# Answer prompt for EVERY arm and the qualification controls (rev 5, Astra finding 2): the pilot prefix plus the
# generator's evidence-precedence rule (eng-pin ledger: an inferred/derived statement that conflicts with the
# underlying base facts is superseded by them), so the oracle's semantics are told to the answerer symmetrically.
E2_PREFIX = SYNTH_PREFIX + (
    " Some statements are inferences about one thing from another (for example, which team a service's owner is on,"
    " or where a project's lead sits). If such a statement conflicts with the underlying facts (who currently owns or"
    " leads the thing, and that person's own current team or office), answer from the underlying facts. When"
    " excerpts disagree, prefer the most recent one."
)
RERANKER_REPO = "Alibaba-NLP/gte-reranker-modernbert-base"
RERANKER_REV = "f7481e6055501a30fb19d090657df9ec1f79ab2c"
RERANKER_ID = f"{RERANKER_REPO}@{RERANKER_REV} model.safetensors fp32 torch-cpu"


def label_of(n):
    return f"summary:n{n:02d}"


def cap_summary(text: str, label: str, cap: float = SYN_OUT_CAP) -> tuple[str, bool]:
    """Longest sentence-prefix of `text` whose served item fits `cap`; word-prefix if even one sentence does not."""
    full = f"[{label}] {text}"
    if item_cost(full) <= cap:
        return text, False
    sents = re.split(r"(?<=[.!?])\s+", text.strip())
    out = ""
    for s in sents:
        cand = (out + " " + s).strip()
        if item_cost(f"[{label}] {cand}") > cap:
            break
        out = cand
    if not out:
        words = text.split()
        lo, hi = 0, len(words)
        while lo < hi:                                     # largest word prefix that fits
            mid = (lo + hi + 1) // 2
            if item_cost(f"[{label}] {' '.join(words[:mid])} …") <= cap:
                lo = mid
            else:
                hi = mid - 1
        out = " ".join(words[:lo]) + " …"
    return out, True


class A6E2(A6):
    def __init__(self, *a, syn_cap=SYN_OUT_CAP, **kw):
        kw.setdefault("edges", "code"); kw.setdefault("recompute", "lazy")
        super().__init__(*a, **kw)
        assert self.edges == "code", "E2 uses code edges only"
        self.syn_cap = syn_cap
        assert "≤ 120 words" in self.syn_prompt
        self.syn_prompt = self.syn_prompt.replace("≤ 120 words", f"≤ {SYN_WORDS} words")   # E2: ask for what fits
        self.syn_prompt_sha = sha(self.syn_prompt)
        self.node_locks: dict[int, threading.Lock] = {}
        self.nl = threading.Lock()

    def _key(self, ids):
        return cache_key(input_set_hash(ids), self.syn_prompt_sha, MODEL)

    def _node_lock(self, n):
        with self.nl:
            return self.node_locks.setdefault(n, threading.Lock())

    def _compute_summary(self, n, t_query, phase):
        ids = self._input_set(n, t_query)
        if len(ids) < 2:
            return None
        key = self._key(ids)
        r = self._llm("synth", self._syn_prompt(ids), phase, ctx={"node": n})
        self.recompute_log.append({"node": n, "phase": phase, "t": t_query, "ok": r["ok"]})
        if not r["ok"]:
            return None                                    # never cache a non-answer
        raw = r["text"].strip()
        text, trunc = cap_summary(raw, label_of(n), self.syn_cap)
        c = {"node": n, "key": key, "ish": input_set_hash(ids), "deps": ids, "text": text, "t": t_query,
             "inserts": int(self.add.inserts[n]), "model_reported": r.get("model_reported"),
             "soft_poison": not_found(raw) or is_non_answer(raw), "truncated": trunc,
             "cost_raw": item_cost(f"[{label_of(n)}] {raw}"), "cost_served": item_cost(f"[{label_of(n)}] {text}")}
        if c["soft_poison"]:
            self.poison_log.append({"kind": "summary", "node": n, "text": raw[:200]})
        self.caches[n] = c
        self.db.put("summary", f"n{n:02d}", {k: c[k] for k in ("key", "deps", "text", "t", "truncated")})
        return c

    def summary(self, n, t_query, phase):
        with self._node_lock(n):                           # one synth per (node, key) even under parallel reads
            ids = self._input_set(n, t_query)
            if len(ids) < 2:
                return None
            c = self.caches.get(n)
            if c is not None and c["key"] == self._key(ids):   # served only on exact key match
                return c
            return self._compute_summary(n, t_query, phase)

    def read(self, question, t_query, B, phase, syn=True):
        qv = unit_vec(self.emb, question)
        nodes = [n for n in range(self.add.k) if self.add.count[n] > 0]
        nodes.sort(key=lambda n: (-float(self.add.centroid(n) @ qv), n))
        top = nodes[:3]
        header, used, node_trace = [], 0.0, []
        if syn:
            for n in top:
                c = self.summary(n, t_query, phase)
                if c is None:
                    node_trace.append({"node": n, "status": "none"}); continue
                label = label_of(n)
                it = {"text": f"[{label}] {c['text']}", "kind": "summary", "ref": label, "node": n,
                      "deps": list(c["deps"]), "soft_poison": c["soft_poison"]}
                cost = item_cost(it["text"])
                if used + cost > B / 5:                       # HEADER_CAP at B=2k
                    node_trace.append({"node": n, "status": "skipped_no_fit", "cost": cost}); continue   # FIX: skip, not break
                header.append(it); used += cost
                node_trace.append({"node": n, "status": "served", "cost": cost, "truncated": c.get("truncated", False)})
        cands = [u for n in top for u in self.add.members[n] if self.units[u]["t"] <= t_query]
        cands.sort(key=lambda u: (-float(self.units[u]["vec"] @ qv), u))
        items = [{"text": f"[{u} | {self.units[u]['t'][:16]}] {self.units[u]['text']}", "kind": self.units[u]["kind"],
                  "ref": u} for u in cands]
        raw, used2 = fill(items, B - used)
        served = header + raw
        for it in served:
            if it["kind"] == "summary" and it["soft_poison"]:
                self.poison_log.append({"kind": "serve", "ref": it["ref"], "phase": phase})
        trace = {"top_nodes": top, "nodes": node_trace, "served_summaries": [it["ref"] for it in header],
                 "header_tokens_est": used, "raw_tokens_est": used2, "n_raw": len(raw),
                 "n_wb_served": sum(1 for it in raw if it["kind"] == "wb"), "syn": syn}
        return served, trace

    def ask(self, question, t_query, B, phase, write_back=False, ctx=None, syn=True):
        served, trace = self.read(question, t_query, B, phase, syn=syn)
        r, prompt = self.answer(served, question, phase, E2_PREFIX, ctx)
        text = (r.get("text") or "").strip()
        out = {"answer": text, "ok": r["ok"], "served": [it["ref"] for it in served], "trace": trace,
               "assembled_est": trace["header_tokens_est"] + trace["raw_tokens_est"],
               "usage": r.get("usage"), "stop": r.get("stop"), "memo_hit": r.get("memo_hit"),
               "cache_key": r.get("cache_key"), "prompt_chars": len(prompt)}
        if write_back and r["ok"]:
            known = set()
            for it in served:
                known |= set(it["deps"]) if it["kind"] == "summary" else {it["ref"]}
            df = self._closure(known)
            self.wb_n += 1
            wid = f"wb:{self.wb_n:03d}"
            if not_found(text):
                self.poison_log.append({"kind": "wb_soft", "id": wid, "text": text[:200]})
            self._add_unit(wid + ":001", "wb", wid, t_query, text, derived_from=df, edge_source="code")
            out["wb_id"] = wid + ":001"; out["wb_derived_from"] = sorted(df)
        return out


class Reranker:
    """gte-reranker-modernbert-base cross-encoder, fp32 safetensors via torch on CPU (pinned revision).
    The cached ONNX int8 export ran ~16 s/pair on this machine (onnxruntime 1.28) and was rejected for wall-time.
    Determinism: fixed thread count, eval/no_grad, candidates scored in their (deterministic) cosine order."""

    def __init__(self, max_len=512, threads=4):
        import torch
        from huggingface_hub import snapshot_download
        from transformers import AutoModelForSequenceClassification, AutoTokenizer
        kw = dict(revision=RERANKER_REV, allow_patterns=["*.json", "model.safetensors", "*.txt"])
        try:
            self.path = snapshot_download(RERANKER_REPO, local_files_only=True, **kw)
        except Exception:
            self.path = snapshot_download(RERANKER_REPO, **kw)
        self.torch = torch
        torch.set_num_threads(threads)
        self.tok = AutoTokenizer.from_pretrained(self.path)
        self.model = AutoModelForSequenceClassification.from_pretrained(self.path, dtype=torch.float32).eval()
        self.max_len = max_len
        self.lock = threading.Lock()
        self.seconds = 0.0; self.pairs = 0

    def scores(self, query: str, docs: list[str], batch=16) -> list[float]:
        out = []
        with self.lock, self.torch.no_grad():
            t0 = time.time()
            for i in range(0, len(docs), batch):
                d = docs[i:i + batch]
                x = self.tok([query] * len(d), d, padding=True, truncation=True, max_length=self.max_len,
                             return_tensors="pt")
                out += [float(v) for v in self.model(**x).logits.view(-1).tolist()]
            self.seconds += time.time() - t0; self.pairs += len(docs)
        return out


class RerankedRaw(Base):
    """Surviving raw paragraphs only; cosine top-K -> cross-encoder rerank -> prefix-fill to B."""

    def __init__(self, name, world, workdir, llm, emb, reranker: Reranker, top_k=TOP_K):
        super().__init__(name, world, workdir, llm, emb)
        self.rr, self.top_k = reranker, top_k
        self.chunks: dict[str, dict] = {}

    def ingest(self, sid, text, t, idx=None):
        for cid, p in paragraphs(sid, text):
            self.chunks[cid] = {"session": sid, "t": t, "text": p, "vec": unit_vec(self.emb, p)}
            self.db.put("raw", cid, {"text": p, "t": t})
        return {"session": sid}

    def forget(self, sid, t=None, session_text=None):
        gone = [c for c, x in self.chunks.items() if x["session"] == sid]
        for c in gone:
            del self.chunks[c]; self.db.delete("raw", c)
        return {"session": sid, "removed": len(gone)}

    def read(self, question, t_query, B):
        qv = unit_vec(self.emb, question)
        live = [(c, x) for c, x in self.chunks.items() if x["t"] <= t_query]
        cos = sorted(live, key=lambda cx: (-round(float(cx[1]["vec"] @ qv), 12), cx[0]))[: self.top_k]
        sc = self.rr.scores(question, [x["text"] for _, x in cos])
        ranked = sorted(zip(cos, sc), key=lambda z: (-round(z[1], 9), z[0][0]))
        items = [{"text": f"[{c} | {x['t'][:16]}] {x['text']}", "kind": "chunk", "ref": c} for (c, x), _ in ranked]
        served, used = fill(items, B)
        return served, {"n_candidates": len(cos), "raw_tokens_est": used, "header_tokens_est": 0.0, "n_raw": len(served),
                        "rerank_top": [c for (c, _), _ in ranked[:5]]}

    def ask(self, question, t_query, B, phase, write_back=False, ctx=None):
        served, trace = self.read(question, t_query, B)
        r, prompt = self.answer(served, question, phase, E2_PREFIX, ctx=ctx)
        return {"answer": (r.get("text") or "").strip(), "ok": r["ok"], "served": [it["ref"] for it in served],
                "trace": trace, "assembled_est": trace["raw_tokens_est"], "usage": r.get("usage"), "stop": r.get("stop"),
                "memo_hit": r.get("memo_hit"), "cache_key": r.get("cache_key"), "prompt_chars": len(prompt)}

    def derived_artifacts(self):
        return []


class LLMAdapter:
    """pilot Base._llm calls llm.call(role, prompt, model=, schema=, ctx=); route every role to MiniMaxAPI."""

    def __init__(self, api):
        self.api = api

    def call(self, role, prompt, model=None, schema=None, ctx=None):
        assert schema is None, "E2 arms never request JSON schemas"
        return self.api.call(role, prompt, ctx=ctx)
