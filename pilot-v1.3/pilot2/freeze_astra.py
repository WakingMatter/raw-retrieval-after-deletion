"""Write PILOT3-ASTRA-FREEZE.json (DEVIATION-ASTRA.md). Never touches PILOT3-FREEZE.json (frozen)."""
import json, time
from pilot.common import ROOT
from pilot2 import freeze3


def main():
    fz = freeze3.build("FROZEN")
    old = json.loads((ROOT / "PILOT3-FREEZE.json").read_text())
    fz["label"] = "EXPLORATORY PILOT3-ASTRA (logged deviation of PILOT-3: answerer grok-4.7 -> gpt-6-astra for the remaining instances; never pooled)"
    fz["deviation_doc"] = "DEVIATION-ASTRA.md"
    fz["parent_freeze"] = {"file": "PILOT3-FREEZE.json", "code_digest": old["code_digest"], "frozen_at": old["frozen_at"]}
    fz["code_files_changed_vs_parent"] = sorted(k for k in set(fz["code_files"]) | set(old["code_files"])
                                                if fz["code_files"].get(k) != old["code_files"].get(k))
    fz["inputs_unchanged_vs_parent"] = {k: fz[k] == old[k] for k in ("probe_files", "stream_manifests", "anchors", "streams", "arms", "params")}
    fz["models"] = dict(old["models"], **{"answer/synth/write/redact/cluster": "gpt-6-astra (codex CLI 0.153.3, isolated closed-book route pilot/astra.py; effort low)"})
    fz["command"] = ("cd /Users/a/Documents/Eywa/research/pilot-v1.3 && PYTHONPATH=.:eng-pin nohup python3 -m pilot2.run2 --label PILOT3-ASTRA "
                     "--answerer astra --streams <all 10 frozen streams> --instances <phase list> --stop-at <cap> --stream-par 1 --llm-par 8")
    (ROOT / "PILOT3-ASTRA-FREEZE.json").write_text(json.dumps(fz, indent=1))
    print(fz["code_digest"], fz["code_files_changed_vs_parent"], fz["inputs_unchanged_vs_parent"])


if __name__ == "__main__":
    main()
