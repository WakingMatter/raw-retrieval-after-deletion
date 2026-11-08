"""Pilot arms: A6 (lazy keyed recompute, code edges), A6-eager, A6m (model edges; ablation), A3n (notes, redact),
A3+DoT (notes, delete-on-touch), RS (Eng A2Rag over surviving raw user sessions)."""
from __future__ import annotations
import json, re, threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import numpy as np
from .common import (P_A3N_WRITE, P_CLUSTER, P_REDACT, P_A6_SYN, P_A6M_CITE, P_A6M_ANSWER_SUFFIX, SYNTH_PREFIX,
                     A3N_SCHEMA, SYN_CAP_TOKENS, REFRESH_AT, ANSWER_MODEL, sha, render_prompt, fill, item_cost,
                     local_tokens, is_non_answer, not_found)
from .store import Additive, quantize, input_set_hash, cache_key, DB, SCALE
from .llm import in_tokens


def paragraphs(sid, text):
    out = []
    for j, p in enumerate(text.rstrip("\n").split("\n\n"), 1):
        if p.startswith("# "):
            continue
        out.append((f"{sid}:{j:03d}", p))
    return out


def unit_vec(emb, text):
    v = np.asarray(emb.vec(text), dtype=np.float64)
    return v / np.linalg.norm(v)


class Base:
    name = "?"

    def __init__(self, name, world, workdir: Path, llm, emb):
        self.name, self.world, self.llm, self.emb = name, world, llm, emb
        self.dir = Path(workdir); self.dir.mkdir(parents=True, exist_ok=True)
        self.db = DB(self.dir / "store.sqlite")
        self.stats = {"calls": []}           # per-call cost rows: {phase, role, in, out, latency, memo}
        self.poison_log = []                 # cached non-answers (soft = 'not found'; hard never cached)
        self.serve_log = []
        self.lock = threading.Lock()

    def _llm(self, role, prompt, phase, schema=None, ctx=None):
        r = self.llm.call(role, prompt, model=ANSWER_MODEL, schema=schema,
                          ctx=dict(ctx or {}, arm=self.name, world=self.world, phase=phase))
        with self.lock:
            self.stats["calls"].append({"phase": phase, "role": role, "ok": r["ok"], "memo": r.get("memo_hit"),
                                        "in": in_tokens(r.get("usage")), "out": int((r.get("usage") or {}).get("output_tokens") or 0),
                                        "latency": r.get("latency_s"), "model_reported": r.get("model_reported"),
                                        # v1.3 F07: real attempts incl. failed retries; memo/in-flight hits own none
                                        "attempt_history": [] if r.get("memo_hit") else r.get("attempt_history", [r])})
        return r

    def answer(self, items, question, phase, prefix=SYNTH_PREFIX, ctx=None):
        prompt = render_prompt([it["text"] for it in items], question, prefix)
        r = self._llm("answer", prompt, phase, ctx=ctx)
        return r, prompt


# ====================================================================== A6 family
class A6(Base):
    def __init__(self, name, world, workdir, llm, emb, anchors, edges="code", recompute="lazy", syn=True,
                 audit_path: Path | None = None):
        super().__init__(name, world, workdir, llm, emb)
        self.edges, self.recompute, self.syn = edges, recompute, syn
        self.anchors = anchors
        self.add = Additive(anchors)
        self.units: dict[str, dict] = {}
        self.caches: dict[int, dict] = {}
        self.wb_n = 0
        self.audit_path = audit_path or (self.dir / "AUDIT-code-known.jsonl")   # sealed: arm only appends
        self.syn_prompt = P_A6_SYN if edges == "code" else P_A6_SYN + "\n" + P_A6M_CITE
        self.syn_prompt_sha = sha(self.syn_prompt)
        self.recompute_log = []

    def _audit(self, row):
        with open(self.audit_path, "a") as f:           # append-only; never read by the arm (T11)
            f.write(json.dumps(row) + "\n")

    # ---- write path
    def _add_unit(self, uid, kind, session, t, text, derived_from=(), edge_source=None):
        v = unit_vec(self.emb, text); q = quantize(v)
        u = {"kind": kind, "session": session, "t": t, "text": text, "vec": v, "q": q,
             "derived_from": sorted(set(derived_from)), "edge_source": edge_source}
        self.units[uid] = u
        n = self.add.add(uid, q); u["node"] = n
        self.db.put(kind, uid, {k: u[k] for k in ("session", "t", "text", "derived_from", "edge_source", "node")})

    def ingest(self, sid, text, t, idx=None):
        for uid, p in paragraphs(sid, text):
            self._add_unit(uid, "raw", sid, t, p)
        return {"session": sid}

    # ---- summaries
    def _input_set(self, n, t_query):
        live = sorted((self.units[u]["t"], u) for u in self.add.members[n] if self.units[u]["t"] <= t_query)
        chosen, tok = [], 0
        for t, u in reversed(live):
            c = local_tokens(self.units[u]["text"])
            if tok + c > SYN_CAP_TOKENS and chosen:
                break
            chosen.append(u); tok += c
        return sorted(chosen)

    def _syn_prompt(self, ids):
        if self.edges == "code":
            lines = [f"[{self.units[u]['t'][:16]}] {self.units[u]['text']}" for u in ids]
        else:
            lines = [f"[{u} | {self.units[u]['t'][:16]}] {self.units[u]['text']}" for u in ids]
        return self.syn_prompt + "\n\n" + "\n".join(lines)

    def _compute_summary(self, n, t_query, phase):
        ids = self._input_set(n, t_query)
        if len(ids) < 2:
            return None
        ish = input_set_hash(ids)
        key = cache_key(ish, self.syn_prompt_sha, ANSWER_MODEL)
        r = self._llm("synth", self._syn_prompt(ids), phase, ctx={"node": n})
        self.recompute_log.append({"node": n, "phase": phase, "t": t_query, "ok": r["ok"]})
        if not r["ok"]:
            return None                                   # never cache a non-answer (poisoning guard)
        text = r["text"].strip()
        if self.edges == "code":
            deps = ids
        else:
            cited = set()
            for grp in re.findall(r"\[([^\]]+)\]", text):
                for tok in re.split(r"[,\s;]+", grp):
                    if tok in self.units and tok in ids:
                        cited.add(tok)
            deps = sorted(cited)
            self._audit({"node": n, "code_known": ids, "cited": deps})
            key = cache_key(input_set_hash(deps), self.syn_prompt_sha, ANSWER_MODEL)
        c = {"node": n, "key": key, "ish": ish, "deps": deps, "text": text, "t": t_query,
             "inserts": int(self.add.inserts[n]), "model_reported": r.get("model_reported"),
             "soft_poison": not_found(text) or is_non_answer(text)}
        if c["soft_poison"]:
            self.poison_log.append({"kind": "summary", "node": n, "text": text[:200]})
        self.caches[n] = c
        self.db.put("summary", f"n{n:02d}", {k: c[k] for k in ("key", "deps", "text", "t")})
        return c

    def summary(self, n, t_query, phase):
        c = self.caches.get(n)
        if self.edges == "code":
            ids = self._input_set(n, t_query)
            if len(ids) < 2:
                return None
            key = cache_key(input_set_hash(ids), self.syn_prompt_sha, ANSWER_MODEL)
            if c is not None and c["key"] == key:        # T3: served only on exact key match
                return c
        else:   # A6m: valid while every cited id survives and no member was inserted since build
            if c is not None and c["inserts"] == int(self.add.inserts[n]) and all(d in self.units for d in c["deps"]):
                return c
        return self._compute_summary(n, t_query, phase)

    # ---- read path
    def read(self, question, t_query, B, phase):
        qv = unit_vec(self.emb, question)
        nodes = [n for n in range(self.add.k) if self.add.count[n] > 0]
        nodes.sort(key=lambda n: (-float(self.add.centroid(n) @ qv), n))
        top = nodes[:3]
        header, used = [], 0.0
        if self.syn:
            for n in top:
                c = self.summary(n, t_query, phase)
                if c is None:
                    continue
                label = f"summary:n{n:02d}"
                it = {"text": f"[{label}] {c['text']}", "kind": "summary", "ref": label, "node": n,
                      "deps": list(c["deps"]), "soft_poison": c["soft_poison"]}
                cost = item_cost(it["text"])
                if used + cost > B / 5:
                    break
                header.append(it); used += cost
        cands = [u for n in top for u in self.add.members[n] if self.units[u]["t"] <= t_query]
        cands.sort(key=lambda u: (-float(self.units[u]["vec"] @ qv), u))
        items = [{"text": f"[{u} | {self.units[u]['t'][:16]}] {self.units[u]['text']}", "kind": self.units[u]["kind"],
                  "ref": u} for u in cands]
        raw, used2 = fill(items, B - used)
        served = header + raw
        for it in served:
            if it["kind"] == "summary" and it["soft_poison"]:
                self.poison_log.append({"kind": "serve", "ref": it["ref"], "phase": phase})
        return served, {"top_nodes": top, "header_tokens_est": used, "raw_tokens_est": used2}

    def _closure(self, ids):
        out, stack = set(), list(ids)
        while stack:
            u = stack.pop()
            if u in out:
                continue
            out.add(u)
            if u in self.units:
                stack.extend(self.units[u]["derived_from"])
        return out

    def ask(self, question, t_query, B, phase, write_back=False, ctx=None):
        served, trace = self.read(question, t_query, B, phase)
        prefix = SYNTH_PREFIX + (P_A6M_ANSWER_SUFFIX if (write_back and self.edges == "model") else "")
        r, prompt = self.answer(served, question, phase, prefix, ctx)
        text = (r.get("text") or "").strip()
        code_known = set()
        for it in served:
            code_known |= set(it["deps"]) if it["kind"] == "summary" else {it["ref"]}
        code_known = self._closure(code_known)
        out = {"answer": text, "ok": r["ok"], "served": [it["ref"] for it in served], "trace": trace,
               "assembled_est": trace["header_tokens_est"] + trace["raw_tokens_est"],
               "served_text": "\n".join(it["text"] for it in served)}
        if self.edges == "model":
            m = re.search(r"^\s*SOURCES:\s*\[?([^\n\]]*)\]?\s*$", text, re.M)
            if m:
                text = (text[:m.start()] + text[m.end():]).strip(); out["answer"] = text
        if write_back and r["ok"]:
            if self.edges == "code":
                df = code_known
            else:
                cited = set(re.split(r"[,\s;]+", m.group(1).strip())) if m else set()
                served_map = {it["ref"]: it for it in served}
                df = set()
                for cid in cited:
                    cid = cid.strip("`'\"")
                    if cid in served_map:
                        it = served_map[cid]
                        df |= set(it["deps"]) if it["kind"] == "summary" else {cid}
                df = self._closure(df)
                self._audit({"wb": True, "code_known": sorted(code_known), "cited": sorted(df)})
            self.wb_n += 1
            wid = f"wb:{self.wb_n:03d}"
            if not_found(text):
                self.poison_log.append({"kind": "wb_soft", "id": wid, "text": text[:200]})
            self._add_unit(wid + ":001", "wb", wid, t_query, text, derived_from=df,
                           edge_source="code" if self.edges == "code" else "model")
            out["wb_id"] = wid + ":001"; out["wb_derived_from"] = sorted(df)
        return out

    # ---- forget
    def forget(self, sid, t, session_text=None):
        doomed = {u for u, x in self.units.items() if x["session"] == sid}
        changed = True
        while changed:
            changed = False
            for u, x in self.units.items():
                if u not in doomed and x["kind"] == "wb" and set(x["derived_from"]) & doomed:
                    doomed.add(u); changed = True
        wbs = sorted(u for u in doomed if self.units[u]["kind"] == "wb")
        for u in sorted(doomed):
            self.add.remove(u, self.units[u]["q"]); self.db.delete(self.units[u]["kind"], u); del self.units[u]
        inval = sorted(n for n, c in self.caches.items() if set(c["deps"]) & doomed)
        for n in inval:
            del self.caches[n]; self.db.delete("summary", f"n{n:02d}")
        eager = []
        if self.recompute == "eager":
            for n in inval:
                c = self._compute_summary(n, t, "forget_eager")
                eager.append(n)
        rebuilt = Additive.rebuild(self.anchors, {u: x["q"] for u, x in self.units.items()})
        kc1a = rebuilt.digest() == self.add.digest()
        return {"session": sid, "units_deleted": len(doomed), "writebacks_deleted": wbs, "caches_invalidated": inval,
                "eager_recomputed": eager, "kc1a_subtraction_equals_rebuild": kc1a}

    def derived_artifacts(self):
        out = [("summary", f"n{n:02d}", c["text"]) for n, c in self.caches.items()]
        out += [("wb", u, x["text"]) for u, x in self.units.items() if x["kind"] == "wb"]
        return out


# ====================================================================== A3 family
class A3(Base):
    def __init__(self, name, world, workdir, llm, emb, forget_mode="redact"):
        super().__init__(name, world, workdir, llm, emb)
        self.forget_mode = forget_mode
        self.notes: dict[str, dict] = {}
        self.clusters: dict[str, dict] = {}
        self.n_notes = 0; self.n_cl = 0; self.n_refresh = 0; self.wb_n = 0
        self.write_failures = []

    def _note_vec(self, nid):
        return unit_vec(self.emb, self.notes[nid]["text"])

    def _write(self, sid, text, t, phase):
        paras = [p for _, p in paragraphs(sid, text)] or [text]
        sv = np.mean([unit_vec(self.emb, p) for p in paras], axis=0); sv /= np.linalg.norm(sv)
        near = sorted(self.notes, key=lambda nid: (-float(self._note_vec(nid) @ sv), nid))[:8]
        shown = "\n".join(f"[{nid} | {self.notes[nid]['date']}] {self.notes[nid]['text']}" for nid in sorted(near)) or "(none)"
        prompt = f"{P_A3N_WRITE}\n\nEXISTING NOTES:\n{shown}\n\nNEW SESSION ({sid}, {t[:16]}):\n{text}"
        r = self._llm("a3_write", prompt, phase, schema=A3N_SCHEMA, ctx={"session": sid})
        ops, err = None, None
        try:
            ops = json.loads(r["text"])["ops"] if r["ok"] else None
            if ops is None:
                err = "no valid output"
        except Exception as e:
            err = f"invalid JSON: {e}"
        if ops is None:
            rp = prompt + f"\n\nYour previous output was invalid ({err}). Return the corrected JSON only."
            r2 = self._llm("a3_write_repair", rp, phase, schema=A3N_SCHEMA, ctx={"session": sid})
            try:
                ops = json.loads(r2["text"])["ops"] if r2["ok"] else None
            except Exception:
                ops = None
        if ops is None:
            self.write_failures.append(sid); return {"session": sid, "ops": 0, "failed": True}
        applied = {"ADD": 0, "UPDATE": 0, "DELETE": 0, "NOOP": 0, "invalid": 0}
        for op in ops:
            k = (op.get("op") or "").upper()
            if k == "ADD" and op.get("text"):
                self.n_notes += 1; nid = f"n{self.n_notes:04d}"
                self.notes[nid] = {"text": op["text"], "date": op.get("date") or t[:10], "sources": [sid], "version": 1, "t": t}
            elif k == "UPDATE" and op.get("id") in self.notes and op.get("text"):
                nt = self.notes[op["id"]]; nid = op["id"]
                nt.update(text=op["text"], date=op.get("date") or t[:10]); nt["version"] += 1
                if sid not in nt["sources"]:
                    nt["sources"].append(sid)
            elif k == "DELETE" and op.get("id") in self.notes:
                nid = op["id"]; del self.notes[nid]; self.db.delete("note", nid); applied[k] += 1; continue
            elif k == "NOOP":
                applied[k] += 1; continue
            else:
                applied["invalid"] += 1; continue
            applied[k] += 1
            self.db.put("note", nid, self.notes[nid])
        return {"session": sid, "applied": applied}

    def ingest(self, sid, text, t, idx=None):
        rec = self._write(sid, text, t, "ingest")
        if idx is not None and (idx + 1) in REFRESH_AT:
            self.refresh("ingest")
        return rec

    def _kmeans(self, ids, k, seed):
        X = np.stack([self._note_vec(i) for i in ids])
        rng = np.random.default_rng(seed)
        cent = [X[rng.integers(len(X))]]
        for _ in range(1, k):                       # k-means++ (deterministic seed)
            d = np.min([((X - c) ** 2).sum(1) for c in cent], axis=0)
            cent.append(X[rng.choice(len(X), p=d / d.sum())] if d.sum() > 0 else X[rng.integers(len(X))])
        C = np.stack(cent)
        for _ in range(25):
            lab = np.argmax(X @ C.T, axis=1)
            C2 = np.stack([X[lab == j].mean(0) if (lab == j).any() else C[j] for j in range(k)])
            C2 /= np.linalg.norm(C2, axis=1, keepdims=True)
            if np.allclose(C2, C):
                break
            C = C2
        groups = {}
        for i, l in zip(ids, lab):
            groups.setdefault(int(l), []).append(i)
        return [sorted(g) for g in groups.values()]

    def _cluster_call(self, prev_summary, notes, phase, cid):
        lines = "\n".join(f"[{nid} | {self.notes[nid]['date']}] {self.notes[nid]['text']}" for nid in notes)
        prompt = f"{P_CLUSTER}\n\nSUMMARY:\n{prev_summary or '(none)'}\n\nNOTES:\n{lines}"
        r = self._llm("a3_cluster", prompt, phase, ctx={"cluster": cid})
        return r["text"].strip() if r["ok"] else None

    def refresh(self, phase):
        self.n_refresh += 1
        ids = sorted(self.notes)
        if not ids:
            return
        groups = self._kmeans(ids, min(16, len(ids)), seed=1000 + self.n_refresh)
        old = list(self.clusters.values())
        jobs = []
        new = {}
        for g in groups:
            gs = set(g)
            prev = max(old, key=lambda c: (len(gs & set(c["members"])) / len(gs | set(c["members"])), c["id"]), default=None)
            if prev is not None and not (gs & set(prev["members"])):
                prev = None
            self.n_cl += 1; cid = f"c{self.n_cl:04d}"
            vers = {n: self.notes[n]["version"] for n in g}
            srcs = set().union(*[set(self.notes[n]["sources"]) for n in g])
            if prev is not None:
                srcs |= set(prev["sources"])
            c = {"id": cid, "members": g, "versions": vers, "sources": sorted(srcs), "summary": None}
            if prev is not None and set(prev["members"]) == gs and prev["versions"] == vers and prev["summary"]:
                c["summary"] = prev["summary"]
            else:
                changed = g if prev is None else [n for n in g if n not in prev["members"] or prev["versions"].get(n) != vers[n]]
                jobs.append((c, prev["summary"] if prev else None, changed or g))
            new[cid] = c
        with ThreadPoolExecutor(6) as ex:
            res = list(ex.map(lambda j: self._cluster_call(j[1], j[2], phase, j[0]["id"]), jobs))
        for (c, prev_s, _), s in zip(jobs, res):
            c["summary"] = s if s is not None else prev_s
        for c in old:
            self.db.delete("cluster", c["id"])
        self.clusters = new
        for c in new.values():
            self._cluster_soft(c)
            self.db.put("cluster", c["id"], c)

    def _cluster_soft(self, c):
        if c["summary"] is not None and (not_found(c["summary"]) or is_non_answer(c["summary"])):
            self.poison_log.append({"kind": "cluster", "id": c["id"], "text": (c["summary"] or "")[:200]})

    def read(self, question, t_query, B, phase):
        qv = unit_vec(self.emb, question)
        served, used = [], 0.0
        cl = [c for c in self.clusters.values() if c["summary"] and any(m in self.notes for m in c["members"])]
        if cl:
            def cen(c):
                v = np.mean([self._note_vec(m) for m in c["members"] if m in self.notes], axis=0)
                return v / np.linalg.norm(v)
            top = min(cl, key=lambda c: (-float(cen(c) @ qv), c["id"]))
            it = {"text": f"[cluster {top['id']} summary] {top['summary']}", "kind": "cluster", "ref": top["id"]}
            if item_cost(it["text"]) <= B:
                served.append(it); used = item_cost(it["text"])
        nids = sorted((n for n in self.notes if self.notes[n]["t"] <= t_query),
                      key=lambda n: (-float(self._note_vec(n) @ qv), n))
        items = [{"text": f"[{n} | {self.notes[n]['date']}] {self.notes[n]['text']}", "kind": "note", "ref": n} for n in nids]
        got, used2 = fill(items, B - used)
        return served + got, {"header_tokens_est": used, "raw_tokens_est": used2}

    def ask(self, question, t_query, B, phase, write_back=False, ctx=None):
        served, trace = self.read(question, t_query, B, phase)
        r, prompt = self.answer(served, question, phase, ctx=ctx)
        text = (r.get("text") or "").strip()
        out = {"answer": text, "ok": r["ok"], "served": [it["ref"] for it in served], "trace": trace,
               "assembled_est": trace["header_tokens_est"] + trace["raw_tokens_est"],
               "served_text": "\n".join(it["text"] for it in served)}
        if write_back and r["ok"]:
            self.wb_n += 1; wid = f"wb:{self.wb_n:03d}"
            if not_found(text):
                self.poison_log.append({"kind": "wb_soft", "id": wid, "text": text[:200]})
            before = set(self.notes)
            out["wb_write"] = self._write(wid, text, t_query, "writeback")
            out["wb_id"] = wid; out["wb_notes"] = sorted(set(self.notes) - before)
        return out

    def forget(self, sid, t, session_text=""):
        touched = [n for n, x in self.notes.items() if sid in x["sources"]]
        deleted, redacted, red_fail = [], [], []
        if self.forget_mode == "dot":
            for n in touched:
                del self.notes[n]; self.db.delete("note", n); deleted.append(n)
        else:
            def red(n):
                x = self.notes[n]
                prompt = f"{P_REDACT}\n\nNOTE:\n{x['text']}\n\nTEXT:\n{session_text}"
                r = self._llm("a3_redact", prompt, "forget", ctx={"note": n})
                return n, (r["text"].strip() if r["ok"] else None)
            sole = [n for n in touched if self.notes[n]["sources"] == [sid]]
            mixed = [n for n in touched if n not in sole]
            for n in sole:
                del self.notes[n]; self.db.delete("note", n); deleted.append(n)
            with ThreadPoolExecutor(6) as ex:
                res = list(ex.map(red, mixed))
            for n, txt in res:
                if txt is None:
                    del self.notes[n]; self.db.delete("note", n); red_fail.append(n); continue
                x = self.notes[n]; x["text"] = txt; x["sources"] = [s for s in x["sources"] if s != sid]; x["version"] += 1
                self.db.put("note", n, x); redacted.append(n)
        cl_touched = [c for c in self.clusters.values() if sid in c["sources"]]
        jobs, dropped = [], []
        for c in cl_touched:
            live = [m for m in c["members"] if m in self.notes]
            if not live:
                dropped.append(c["id"]); continue
            if self.forget_mode == "dot":
                jobs.append((c, None, live))
            else:
                changed = [m for m in live if m in redacted] or live
                jobs.append((c, c["summary"], changed))
        for cid in dropped:
            del self.clusters[cid]; self.db.delete("cluster", cid)
        with ThreadPoolExecutor(6) as ex:
            res = list(ex.map(lambda j: self._cluster_call(j[1], j[2], "forget", j[0]["id"]), jobs))
        rebuilt_fail = []
        for (c, prev, _), s in zip(jobs, res):
            c["members"] = [m for m in c["members"] if m in self.notes]
            c["versions"] = {m: self.notes[m]["version"] for m in c["members"]}
            if s is None:
                if self.forget_mode == "dot":     # cannot rebuild: drop the summary rather than keep touched text
                    c["summary"] = None
                rebuilt_fail.append(c["id"])
            else:
                c["summary"] = s
            srcs = set().union(*[set(self.notes[m]["sources"]) for m in c["members"]])
            if self.forget_mode == "redact":
                srcs |= set(c["sources"]) - {sid}
            c["sources"] = sorted(srcs)
            self._cluster_soft(c)
            self.db.put("cluster", c["id"], c)
        return {"session": sid, "notes_deleted": deleted, "notes_redacted": redacted, "redact_failed": red_fail,
                "clusters_rebuilt": [j[0]["id"] for j in jobs], "clusters_dropped": dropped, "cluster_fail": rebuilt_fail}

    def derived_artifacts(self):
        out = [("note", n, x["text"]) for n, x in self.notes.items()]
        out += [("cluster", c["id"], c["summary"]) for c in self.clusters.values() if c["summary"]]
        return out


# ====================================================================== RS
class RS(Base):
    """Eng A2Rag (pinned 863fb79) over surviving raw user sessions; write-backs excluded; no warm reads."""

    def __init__(self, name, world, workdir, llm, emb):
        super().__init__(name, world, workdir, llm, emb)
        from arms.a2_rag import A2Rag
        self.a2 = A2Rag(emb)

    def ingest(self, sid, text, t, idx=None):
        r = self.a2.ingest(sid, text, t)
        for c, x in self.a2.chunks.items():
            if x["session"] == sid:
                self.db.put("raw", c, {"text": x["text"], "t": x["t"]})
        return r

    def forget(self, sid, t, session_text=None):
        gone = [c for c, x in self.a2.chunks.items() if x["session"] == sid]
        for c in gone:
            self.db.delete("raw", c)
        return self.a2.forget(sid)

    def ask(self, question, t_query, B, phase, write_back=False, ctx=None):
        items = [{"text": it.text, "kind": "chunk", "ref": it.ref} for it in self.a2.candidates({"question": question}, t_query, B)]
        served, used = fill(items, B)
        r, prompt = self.answer(served, question, phase, ctx=ctx)
        return {"answer": (r.get("text") or "").strip(), "ok": r["ok"], "served": [it["ref"] for it in served],
                "trace": {}, "assembled_est": used, "served_text": "\n".join(it["text"] for it in served)}

    def derived_artifacts(self):
        return []
