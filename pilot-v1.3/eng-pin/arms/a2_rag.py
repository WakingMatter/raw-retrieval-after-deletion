"""A2 RAG-verbatim: raw chunks ranked by cosine and filled greedily to B, with timestamps.

As in 30 Aug ``_rag_context`` (runner.py L701-723), but each chunk is one session paragraph
(header line excluded) stamped with its session and start time. Embeddings go through the
``Embedder`` adapter (the fake hash embedder in tests). Ties break by chunk id. ``forget``
removes the session's chunks and their vectors."""
from arms.adapters import Embedder, cosine
from arms.base import Arm
from arms.common import Item


class A2Rag(Arm):
    name = "A2"

    def __init__(self, embedder: Embedder):
        super().__init__()
        self.emb = embedder
        self.chunks: dict[str, dict] = {}

    def ingest(self, session_id, text, t_start):
        paras = [p for p in text.rstrip("\n").split("\n\n")]
        new = []
        for j, p in enumerate(paras, 1):
            if p.startswith("# "):
                continue
            cid = f"{session_id}:{j:03d}"
            new.append((cid, p))
        vecs = self.emb.embed([p for _, p in new]) if new else []
        for (cid, p), v in zip(new, vecs):
            self.chunks[cid] = {"session": session_id, "t": t_start, "text": p, "vec": v}
        return {"session": session_id, "chunks": len(new)}

    def forget(self, session_id):
        gone = [c for c, x in self.chunks.items() if x["session"] == session_id]
        for c in gone:
            del self.chunks[c]
        return {"session": session_id, "removed": len(gone)}

    def candidates(self, task, t_query, B):
        qv = self.emb.embed([task["question"]])[0]
        live = [(c, x) for c, x in self.chunks.items() if x["t"] <= t_query]
        ranked = sorted(live, key=lambda cx: (-round(cosine(qv, cx[1]["vec"]), 12), cx[0]))
        return [Item(text=f"[{c} | {x['t'][:16]}] {x['text']}", kind="chunk", ref=c) for c, x in ranked]
