"""PILOT3-ASTRA 3-call real smoke (DEVIATION-ASTRA.md): one answer, one a3_write (schema), one synth call on real
stream-7240241 text through the isolated Astra route. Writes runs/PILOT3-ASTRA-SMOKE/SMOKE.json. Not part of results."""
import json, re, time
from pathlib import Path
from pilot.common import ROOT, DATA, render_prompt, P_A3N_WRITE, P_A6_SYN, A3N_SCHEMA
from pilot.llm import LLM, in_tokens

d = DATA / "stream-7240241"
m = json.load(open(d / "MANIFEST.json"))
sess = [s["session"] for s in m["sessions"]]
txt = {s: (d / "sessions" / f"{s}.md").read_text() for s in sess}
probe = json.loads(open(DATA / "stream-7240241-probes" / "probes.jsonl").readline())
paras = [p for s in sess[:6] for p in re.split(r"\n\s*\n", txt[s]) if len(p) > 80]
answer_p = render_prompt(paras[:14], probe["question"])
write_p = f"{P_A3N_WRITE}\n\nEXISTING NOTES:\n(none)\n\nNEW SESSION ({sess[0]}, {m['sessions'][0]['t_start'][:16]}):\n{txt[sess[0]]}"
synth_p = P_A6_SYN + "\n\n" + "\n".join(f"[{m['sessions'][i]['t_start'][:16]}] {p}" for i, p in enumerate(paras[:12]))
run = ROOT / "runs" / "PILOT3-ASTRA-SMOKE"; run.mkdir(parents=True, exist_ok=True)
llm = LLM(run / "_memo", max_parallel=1, answerer="astra", stop_file=run / "STOP", stop_at=94.0)
llm.log_path = run / "calls.jsonl"
out = []
for role, p, sch in (("answer", answer_p, None), ("a3_write", write_p, A3N_SCHEMA), ("synth", synth_p, None)):
    r = llm.call(role, p, model="grok-4.7", schema=sch, ctx={"phase": "smoke"})
    row = {"role": role, "ok": r["ok"], "stop": r.get("stop"), "latency_s": round(r.get("latency_s") or 0, 1),
           "usage": r.get("usage"), "in_tokens": in_tokens(r.get("usage")), "model_reported": r.get("model_reported"),
           "used_percent_after": r.get("used_percent"), "tool_calls": r.get("tool_calls"), "prompt_chars": len(p),
           "text_head": (r.get("text") or "")[:300]}
    if sch:
        try:
            row["json_ops"] = len(json.loads(r["text"])["ops"])
        except Exception as e:
            row["json_error"] = str(e)
    out.append(row); print(json.dumps(row), flush=True)
(run / "SMOKE.json").write_text(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "calls": out}, indent=1))
