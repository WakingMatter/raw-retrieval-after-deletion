"""Zero-API diagnostic: (i) RR hop-1 reproduces E2 RR served lists; (ii) ORACLE-entity RR-2hop ceiling (bridge entity =
gold ref-leaf person from the ledger) -- an upper bound on what the bridge step can buy; (iii) RR-k (top-200) coverage.
Measures whether the attr (second-hop) leaf chunk reaches the served 2000-token context."""
from __future__ import annotations
import json, sys
from collections import Counter
from common import HERE, load_streams, leaves
from e3.rr2hop import ranked, interleave, hop2_query
from pilot.common import fill
from pilot.embed import Embedder
from e2.arms_e2 import Reranker, B_DEFAULT
from e2.paths import RUNS


def main():
    emb = Embedder(RUNS / "_vec"); rr = Reranker()
    S = load_streams(emb); L = leaves()
    res = []
    for s, st in S.items():
        for tid, tk in st["tasks"].items():
            lv = L[tid]
            h1 = ranked(st["chunks"], emb, rr, tk["question"], tk["t_query"])
            s1 = [i["ref"] for i in fill(h1, B_DEFAULT)[0]]
            assert s1 == st["rows"][tid]["RR"]["served"], tid
            h2 = ranked(st["chunks"], emb, rr, hop2_query(lv["ref"]["value"], tk["question"]), tk["t_query"])
            s2 = [i["ref"] for i in fill(interleave(h1, h2), B_DEFAULT)[0]]
            hk = ranked(st["chunks"], emb, rr, tk["question"], tk["t_query"], top_k=200)
            sk = [i["ref"] for i in fill(hk, B_DEFAULT)[0]]
            a, r = set(lv["attr"]["chunks_surviving"]), set(lv["ref"]["chunks_surviving"])
            res.append({"task_id": tid, "rr_attr": bool(a & set(s1)), "rr_ref": bool(r & set(s1)),
                        "oracle2hop_attr": bool(a & set(s2)), "oracle2hop_ref": bool(r & set(s2)),
                        "oracle2hop_attr_h2rank": min([i for i, x in enumerate(h2, 1) if x["ref"] in a] or [None]) if any(x["ref"] in a for x in h2) else None,
                        "rrk_attr": bool(a & set(sk)), "rrk_ref": bool(r & set(sk)),
                        "rrk_attr_in_pool": any(x["ref"] in a for x in hk)})
        print(s, len(res), flush=True)
    (HERE / "offline_diag.json").write_text(json.dumps(res, indent=0))
    n = len(res)
    for k in ("rr_attr", "rr_ref", "oracle2hop_attr", "oracle2hop_ref", "rrk_attr", "rrk_ref", "rrk_attr_in_pool"):
        print(k, sum(r[k] for r in res), "/", n)
    print("oracle h2 attr rank", Counter(min(r["oracle2hop_attr_h2rank"] or 99, 11) for r in res))


if __name__ == "__main__":
    main()
