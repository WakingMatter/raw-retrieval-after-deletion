"""Cost spent across all logged runs (real calls only; memo hits cost nothing)."""
import json, sys
from collections import Counter, defaultdict
from .common import ROOT
from .llm import in_tokens

def main():
    out = {}
    for d in sorted((ROOT / "runs").iterdir()):
        f = d / "calls.jsonl"
        if not f.exists():
            continue
        agg = defaultdict(lambda: Counter())
        for l in open(f):
            r = json.loads(l)
            if r.get("memo_hit"):
                agg["_memo"]["n"] += 1; continue
            m = r.get("model_requested") or "?"
            u = r.get("usage") or {}
            c = agg[m]; c["n_real"] += 1; c["failed"] += 0 if r.get("ok") else 1
            c["in_tok"] += in_tokens(u) or 0; c["out_tok"] += (u.get("output_tokens") or 0)
            c["lat_s"] += r.get("latency_s") or 0; c["usd_notional"] += r.get("cost_usd") or 0
        out[d.name] = {k: dict(v) for k, v in agg.items()}
    tot = Counter()
    for v in out.values():
        for k, c in v.items():
            if k != "_memo":
                for kk, x in c.items(): tot[kk] += x
    out["_TOTAL_real"] = dict(tot)
    (ROOT / "runs" / "COSTS.json").write_text(json.dumps(out, indent=1)); print(json.dumps(out, indent=1))

if __name__ == "__main__":
    main()
