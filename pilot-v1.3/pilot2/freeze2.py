"""Write PILOT2-FREEZE.json (new file; PILOT-FREEZE.json untouched).  v1.3: LEGACY, disabled -- use pilot2.freeze3."""
raise SystemExit("pilot2.freeze2 is the v1.2 PILOT-2 freeze writer; in v1.3 use `python3 -m pilot2.freeze3`")
import hashlib, json, time
from pathlib import Path
from pilot.common import ROOT
from pilot2 import targets2 as T2
fsha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
code = sorted(p for d in ("pilot", "pilot2") for p in (ROOT / d).rglob("*.py") if "__pycache__" not in str(p) and not p.name.startswith("_"))
files = {str(p.relative_to(ROOT)): fsha(p) for p in code}
dig = hashlib.sha256("".join(f"{k}:{v}\n" for k, v in files.items()).encode()).hexdigest()
P1 = json.loads((ROOT / "PILOT-FREEZE.json").read_text())
txt = Path(T2.__file__).read_text()
prompts = {k: l.strip() for l in txt.splitlines() for k in ("HIST", "SUMM", "XHIST") if l.strip().startswith(f'"{k}"') or l.strip().startswith(f"{k} =")}
fz = {"frozen_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "label": "EXPLORATORY PILOT-2 (not confirmatory; post-hoc design after PILOT)",
      "code_digest": dig, "code_files": files, "pilot1_code_digest": P1["code_digest"],
      "pilot1_prompts_reused": {k: v["sha256"] for k, v in P1["prompts"].items()},
      "new_probe_prompt_lines": prompts, "models": P1["models"], "params": P1["params"], "eng_commit": P1["eng_commit"],
      "streams": [7240241, 7240242], "n_extra_deletions_per_stream": 6, "min_deletions_per_stream": 8,
      "arms": ["A6", "A6-eager", "A6m", "A3n", "A3+DoT(v2: A3DoT2)", "RS"],
      "memo": "runs/_calls/memo (prompt-keyed) reused where prompts identical",
      "deviations": {
        "D2-1": "A3+DoT uses pilot2/arms2.A3DoT2: provenance = own session + sources of the 8 near notes shown to the writer + served-note/cluster provenance on write-back; clusters inherit member provenance; forget deletes every note whose provenance contains sid. PILOT-1 DoT only tracked own-session sources, making it identical to A3n when all touched notes are sole-sourced.",
        "D2-2": "targets2.author2: PILOT-1 generator deletions kept + 6 extra deleted sessions per stream (forget at t_end, after all ingest); new class R (DIRECT/HIST/ENUM/SUMM) on facts whose value is absent from surviving raw co-mention; X canary HIST variant; MIX probes restricted to keys untouched by deletions; first R fact per deletion gets a write-back warm query.",
        "D2-3": "smoke = first 10 sessions, 2 extra deletions, 3 probes, forgets clamped to smoke t_end, refresh_at (4,8,10).",
        "D2-4": "scoring pilot2/score2.py: frozen score.py rows with LEAK_CLS+R, regex only (no J1 judge), fact-level residue = subject name + deleted value in same artifact."},
      "command": "cd /Users/a/Documents/Eywa/research/pilot-v1.2 && nohup sh -c 'python3 -m pilot2.run2 --label PILOT2 --streams 7240241,7240242 && python3 -m pilot2.score2 PILOT2' > runs/PILOT2.out 2>&1 &"}
(ROOT / "PILOT2-FREEZE.json").write_text(json.dumps(fz, indent=1)); print(dig, len(files), prompts.keys())
