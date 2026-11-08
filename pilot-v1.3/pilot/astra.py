"""PILOT3-ASTRA deviation: isolated Codex/Astra answerer route (DEVIATION-ASTRA.md). The grok route is untouched.

Route (same isolation as cm-bench cmbench/route.py, J14 #8): `codex exec -m gpt-6-astra` with reasoning effort low,
read-only sandbox, web search DISABLED, every MCP server disabled (verified via `codex mcp list --json`), memories /
plugins / hooks / multi-agent / goals disabled, approval never, empty cwd, --json events. The grok SYSTEM text is
prepended to the prompt (codex exec has no system-prompt override). Each call's session rollout is audited: any tool /
web / shell / MCP item VOIDS the call (ok=False, never memoised). The rollout's weekly used_percent is recorded per
call; at or above the stop threshold a STOP file is written and every later call returns stop="quota_stop" at once.
Quota/limit errors also write STOP. No retries after a stop."""
from __future__ import annotations
import glob, json, os, re, subprocess, tempfile, time
from pathlib import Path

ASTRA_MODEL = "gpt-6-astra"
CODEX_BIN = os.environ.get("PV_ASTRA_BIN", "/Users/a/.hermes/node/bin/codex")
ISOLATION = [
    "-s", "read-only", "-c", 'approval_policy="never"', "-c", 'web_search="disabled"',
    "-c", "features.multi_agent_v2.enabled=false",
    "-c", "memories.use_memories=false", "-c", "memories.generate_memories=false",
    "--disable", "memories", "--disable", "plugins", "--disable", "hooks", "--disable", "plugin_hooks",
    "--disable", "multi_agent", "--disable", "goals", "--disable", "chronicle",
    "--ignore-rules", "--skip-git-repo-check", "--json",
    # prompt-overhead trims (measured with `codex debug prompt-input`, no model call): skills catalogue, context-window
    # guidance, permission/environment/collaboration blocks, and tool-adding features a closed-book answerer never needs
    "-c", "skills.include_instructions=false", "-c", "include_permissions_instructions=false",
    "-c", "include_environment_context=false", "-c", "include_collaboration_mode_instructions=false",
    "--disable", "context_management", "--disable", "image_generation", "--disable", "browser_use",
    "--disable", "browser_use_external", "--disable", "computer_use", "--disable", "apps", "--disable", "code_mode_host",
    "--disable", "view_image", "--disable", "sleep_tool", "--disable", "skill_search", "--disable", "tool_suggest",
    "--disable", "in_app_browser", "--disable", "shell_tool", "--disable", "unified_exec",
]
QUOTA_ERR = re.compile(r"usage limit|rate limit|quota|insufficient|exceeded|credits", re.I)
EMPTY = Path(tempfile.gettempdir()) / "pv13-astra-empty"
_MCP_ARGS = None


def _mcp_list(extra):
    p = subprocess.run([CODEX_BIN, *extra, "--disable", "plugins", "mcp", "list", "--json"], capture_output=True, text=True,
                       timeout=60, stdin=subprocess.DEVNULL)
    if p.returncode:
        raise RuntimeError(f"codex mcp list failed: {p.stderr[-300:]}")
    return json.loads(p.stdout)


def mcp_args():
    global _MCP_ARGS
    if _MCP_ARGS is None:
        names = [x["name"] for x in _mcp_list([]) if x.get("enabled")]
        args = [a for n in names for a in ("-c", f"mcp_servers.{n}.enabled=false")]
        still = [x["name"] for x in _mcp_list(args) if x.get("enabled")]
        if still:
            raise RuntimeError(f"MCP servers still enabled: {still}")
        _MCP_ARGS = args
    return _MCP_ARGS


def command(effort="low", schema_file=None):
    EMPTY.mkdir(exist_ok=True)
    if any(EMPTY.iterdir()):
        raise RuntimeError(f"{EMPTY} must be empty")
    cmd = [CODEX_BIN, "exec", "-m", ASTRA_MODEL, "-c", f'model_reasoning_effort="{effort}"', *ISOLATION, *mcp_args(),
           "-C", str(EMPTY)]
    if schema_file:
        cmd += ["--output-schema", schema_file]
    return cmd


def audit_rollout(path):
    calls, model, used = [], None, None
    for line in Path(path).read_text().splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        p = e.get("payload") or {}
        if not isinstance(p, dict):
            continue
        if model is None and p.get("model"):
            model = p["model"]
        if e.get("type") == "response_item" and str(p.get("type", "")).endswith("_call"):
            calls.append(str(p.get("type")) + ":" + str(p.get("name") or ""))
        m = re.search(r'"primary":\{"used_percent":([0-9.]+),"window_minutes":10080', line)
        if m:
            used = float(m.group(1))
    return {"tool_calls": calls, "model": model, "used_percent": used}


def call(prompt, system, schema, effort, stop_file: Path, stop_at: float):
    if stop_file.exists():
        return {"rc": -2, "stop": "quota_stop", "text": "", "latency_s": 0.0}
    # A3N_SCHEMA is not OpenAI-strict (optional fields, no additionalProperties:false), which `--output-schema`
    # requires, so the schema is appended as text instead of grok's native --json-schema (disclosed deviation).
    sf = None
    full = f"{system}\n\n{prompt}"
    if schema:
        full += ("\n\nOutput ONLY a single JSON object (no prose, no code fences) that validates against this JSON Schema:\n"
                 + (schema if isinstance(schema, str) else json.dumps(schema)))
    t0 = time.time()
    try:
        p = subprocess.run(command(effort, sf), input=full, capture_output=True, text=True, timeout=900)
    except subprocess.TimeoutExpired:
        return {"rc": -9, "stop": "timeout", "text": "", "latency_s": time.time() - t0}
    finally:
        if sf:
            os.unlink(sf)
    lat = time.time() - t0
    text, usage, tid, stop, errs = "", {}, None, None, []
    for line in p.stdout.splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if e.get("type") == "thread.started":
            tid = e.get("thread_id")
        it = e.get("item") or {}
        if e.get("type") == "item.completed" and it.get("type") in ("agent_message", "assistant_message"):
            text = it.get("text") or text
        if e.get("type") == "turn.completed":
            usage = e.get("usage") or {}; stop = "completed"
        if e.get("type") in ("error", "turn.failed"):
            errs.append(json.dumps(e)[:400])
    if schema and text.strip().startswith("```"):     # strip a code fence around the JSON (disclosed)
        text = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", text.strip())
    out = {"rc": p.returncode, "stop": stop, "text": text, "usage": usage, "cost_usd": None, "latency_s": lat,
           "thread_id": tid, "model_reported": None, "route": "astra-isolated-v1"}
    blob = " ".join(errs) + " " + p.stderr[-2000:]
    if stop != "completed" and QUOTA_ERR.search(blob):
        stop_file.write_text(f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} quota/limit error: {blob[-600:]}\n")
        out.update(stop="quota_stop", rc=p.returncode or -2, stderr=blob[-600:])
        return out
    files = glob.glob(str(Path.home() / ".codex/sessions") + f"/*/*/*/*{tid}.jsonl") if tid else []
    if not files:
        out.update(stop="no_rollout", stderr=blob[-600:]); return out
    au = audit_rollout(files[0])
    out.update(model_reported=au["model"], used_percent=au["used_percent"], tool_calls=au["tool_calls"])
    if au["tool_calls"]:
        out.update(stop="void_tool_call")
    if au["used_percent"] is not None and au["used_percent"] >= stop_at:
        stop_file.write_text(f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} used_percent {au['used_percent']} >= {stop_at}\n")
    if stop != "completed":
        out["stderr"] = blob[-600:]
    return out
