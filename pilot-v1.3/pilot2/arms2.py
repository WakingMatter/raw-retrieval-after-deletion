"""PILOT-2 arm fix (DEVIATION D2-1). A3+DoT v2 = delete-on-touch with context-exposure provenance.
Frozen pilot/arms.py A3 'dot' only deleted notes whose `sources` contained the session; the writer ADDs
sole-sourced atomic notes (PILOT ops: ADD 1266 / UPDATE 21), so every touched note was sole-sourced and
DoT == redact (A3n). v2 also marks as touched every note ADDed/UPDATEd by a write call whose prompt SHOWED
a note sourced from the session (non-transitive), every write-back note derived from served notes/clusters
sourced from it, and every cluster whose members were touched. Prompts are unchanged (memo stays valid)."""
from __future__ import annotations
from pilot.arms import A3


class A3DoT2(A3):
    def __init__(self, name, world, workdir, llm, emb):
        super().__init__(name, world, workdir, llm, emb, forget_mode="dot")
        self._extra = set()

    def _prov(self, n):
        x = self.notes[n]; return set(x["sources"]) | set(x.get("touched", []))

    def _write(self, sid, text, t, phase):
        before = {n: x["version"] for n, x in self.notes.items()}
        import numpy as np
        from pilot.arms import paragraphs, unit_vec
        paras = [p for _, p in paragraphs(sid, text)] or [text]
        sv = np.mean([unit_vec(self.emb, p) for p in paras], axis=0); sv /= np.linalg.norm(sv)
        near = sorted(self.notes, key=lambda nid: (-float(self._note_vec(nid) @ sv), nid))[:8]   # same as frozen
        shown = set().union(*[set(self.notes[n]["sources"]) for n in near]) if near else set()
        shown |= self._extra
        rec = super()._write(sid, text, t, phase)
        for n, x in self.notes.items():
            if n not in before or before[n] != x["version"]:
                x["touched"] = sorted((set(x.get("touched", [])) | shown) - {sid}); self.db.put("note", n, x)
        return rec

    def ask(self, question, t_query, B, phase, write_back=False, ctx=None):
        if write_back:
            served, _ = self.read(question, t_query, B, phase)
            s = set()
            for it in served:
                if it["kind"] == "note" and it["ref"] in self.notes:
                    s |= self._prov(it["ref"])
                elif it["kind"] == "cluster" and it["ref"] in self.clusters:
                    s |= set(self.clusters[it["ref"]]["sources"])
            self._extra = s
        try:
            return super().ask(question, t_query, B, phase, write_back=write_back, ctx=ctx)
        finally:
            self._extra = set()

    def refresh(self, phase):
        super().refresh(phase)
        for c in self.clusters.values():
            c["sources"] = sorted(set(c["sources"]).union(*[self._prov(m) for m in c["members"] if m in self.notes]))
            self.db.put("cluster", c["id"], c)

    def forget(self, sid, t, session_text=""):
        hit = [n for n in self.notes if sid in self._prov(n)]
        for n in hit:                                   # make them 'sourced' so frozen DoT deletes them + rebuilds clusters
            if sid not in self.notes[n]["sources"]:
                self.notes[n]["sources"].append(sid)
        for c in self.clusters.values():
            if any(m in hit for m in c["members"]) and sid not in c["sources"]:
                c["sources"] = sorted(set(c["sources"]) | {sid})
        rec = super().forget(sid, t, session_text)
        rec["n_touched_v2"] = len(hit)
        return rec
