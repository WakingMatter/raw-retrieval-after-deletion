"""v1.3 F12: fact-residue candidates for PILOT-2/3 scoring (importable; score2.py is a script)."""
import re


def cooccurrence_candidates(targets, artifacts, keys, ents):
    """Subject name + deleted value inside one derived artifact is a REVIEW CANDIDATE, not fact-level residue
    (SMOKE2 counted 'Meera Joshi' + an unrelated 'Dublin' in summary n09). Fact residue stays unknown (None) until
    subject-slot-value entailment is adjudicated."""
    out = []
    for t in targets:
        if t["cls"] not in ("R", "X", "S", "P", "W") or t["variant"] != "DIRECT":
            continue
        nm = keys[t["key"]]["subject_name"] if t.get("key") else ents[t["subject"]]["name"]
        rx = re.compile(t["deleted_any"][0])
        hits = [{"kind": k, "id": i, "text": x} for k, i, x in artifacts if x and nm in x and rx.search(x)]
        if hits:
            out.append({"probe": t["probe_id"], "subject": nm, "deleted_value": t.get("deleted_value"), "artifacts": hits})
    return out
