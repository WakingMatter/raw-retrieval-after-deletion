"""MiniMax M3.1 Flash answerer route (MINIMAX-ROUTE.md). The grok and astra routes are untouched.

Two transports, same model, same call() interface as pilot/astra.py:

  cli   (default, official) `mcode exec` from the npm package @minimax-ai/code, signed in through the MiniMax Code
        managed login that the desktop app and CLI share (dataDir ~/.minimax, region en). Lightweight mode (no tools,
        no file access), permission off, one assistant step, an empty cwd, JSON ExecResult on stdout. The pilot SYSTEM
        text replaces the identity prompt via --system-prompt (MiniMax runtime rules stay, ~1k tokens overhead).
        NOTE: every exec creates a visible Session in the MiniMax Code app unless PV_MINIMAX_DATA_DIR points at an
        isolated dataDir that has its own `mcode login`.
  proxy DISABLED (2026-10-24, Aditya's ToS rule): refused unless PV_MINIMAX_PROXY_TOS_OK=1. MiniMax's Agent/App ToS bars
        "any robot, spider, or other automatic device, process, or means to access the Services"; scripting the
        Code-app lane through an unofficial proxy is prohibited or at best unclear. Kept only for reference: the local Hermes proxy at 127.0.0.1:8771 (OpenAI chat-completions in,
        Anthropic Messages to the MiniMax Code managed endpoint out). Uses the proxy's native /v1/messages passthrough. Fast, but unofficial and it
        rotates the app's
        OAuth refresh token (see MINIMAX-ROUTE.md caveats). The local proxy key is read from the proxy's launcher
        script at call time and never logged.

Rate-limit / quota / auth errors write a STOP file; every later call then returns stop="quota_stop" at once."""
from __future__ import annotations
import json, os, re, subprocess, tempfile, time, urllib.error, urllib.request
from pathlib import Path

MINIMAX_MODEL = "MiniMax-M3.1-Flash"
CLI_MODEL = os.environ.get("PV_MINIMAX_MODEL", f"minimax/{MINIMAX_MODEL}")
MCODE_BIN = os.environ.get("PV_MINIMAX_BIN", str(Path.home() / ".local/mcode-cli/node_modules/.bin/mcode"))
TRANSPORT = os.environ.get("PV_MINIMAX_TRANSPORT", "cli")
PROXY_URL = os.environ.get("PV_MINIMAX_PROXY_URL", "http://127.0.0.1:8771")
PROXY_KEY_FILE = Path(os.environ.get("PV_MINIMAX_PROXY_KEY_FILE", str(Path.home() / ".hermes/scripts/mm31-proxy.sh")))
TIMEOUT_S = int(os.environ.get("PV_MINIMAX_TIMEOUT", "300"))
QUOTA_ERR = re.compile(r"rate.?limit|too many requests|\b429\b|quota|usage limit|insufficient|exceeded|credits|"
                       r"unauthori[sz]ed|\b401\b|\b403\b|not logged in|log ?in again|re-?login|refresh_token", re.I)
EMPTY = Path(tempfile.gettempdir()) / "pv13-minimax-empty"
ROUTES = {"cli": "minimax-mcode-cli-v1", "proxy": "minimax-hermes-proxy-v1"}
PROXY_DISABLED_MSG = ("minimax proxy transport is disabled: MiniMax ToS bars automated access to the MiniMax Code/Agent "
                      "Services; use PV_MINIMAX_TRANSPORT=cli (see MINIMAX-ROUTE.md). Override only with written consent: "
                      "PV_MINIMAX_PROXY_TOS_OK=1")


def full_prompt(prompt, schema):
    if not schema:
        return prompt
    return (prompt + "\n\nOutput ONLY a single JSON object (no prose, no code fences) that validates against this JSON Schema:\n"
            + (schema if isinstance(schema, str) else json.dumps(schema)))


def strip_fence(text, schema):
    if schema and text.strip().startswith("```"):
        return re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", text.strip())
    return text


def cli_command(system, effort="low"):
    EMPTY.mkdir(exist_ok=True)
    if any(EMPTY.iterdir()):
        raise RuntimeError(f"{EMPTY} must be empty")
    cmd = [MCODE_BIN, "exec", "--input", "-", "--mode", "lightweight", "--permission", "off", "--max-steps", "1",
           "--cwd", str(EMPTY), "--output-format", "json", "--timeout", f"{TIMEOUT_S}s", "--model", CLI_MODEL]
    if effort:
        cmd += ["--effort", effort]
    if system:
        cmd += ["--system-prompt", system]
    return cmd


def parse_exec(stdout):
    """mcode exec --output-format json prints one ExecResult object (last JSON object on stdout)."""
    for line in reversed([l for l in stdout.strip().splitlines() if l.strip()] or [""]):
        try:
            d = json.loads(line)
            if isinstance(d, dict):
                return d
        except ValueError:
            continue
    try:
        return json.loads(stdout)
    except ValueError:
        return {}


def _cli(prompt, system, schema, effort):
    env = dict(os.environ)
    if os.environ.get("PV_MINIMAX_DATA_DIR"):
        env["MINIMAX_DATA_DIR"] = os.environ["PV_MINIMAX_DATA_DIR"]
    t0 = time.time()
    try:
        p = subprocess.run(cli_command(system, effort), input=full_prompt(prompt, schema), capture_output=True, text=True,
                           timeout=TIMEOUT_S + 60, env=env)
    except subprocess.TimeoutExpired:
        return {"rc": -9, "stop": "timeout", "text": "", "latency_s": time.time() - t0}, ""
    lat = time.time() - t0
    d = parse_exec(p.stdout)
    st, err = d.get("status"), d.get("error") or {}
    u = d.get("usage") or {}
    m = d.get("model") or {}
    out = {"rc": p.returncode if st == "succeeded" else (p.returncode or 1),
           "stop": "completed" if st == "succeeded" else (st or "no_result"),
           "text": strip_fence(d.get("output") or "", schema),
           "usage": {"input_tokens": u.get("inputTokens"), "output_tokens": u.get("outputTokens"),
                     "cache_read_tokens": u.get("cacheReadTokens")},
           "cost_usd": None, "latency_s": lat, "duration_ms": d.get("durationMs"), "thread_id": d.get("sessionId"),
           "model_reported": f"{m.get('providerId')}/{m.get('modelId')}" if m.get("modelId") else None,
           "model_variant": m.get("variant"), "route": ROUTES["cli"]}
    blob = f"{err.get('category', '')} {err.get('message', '')} " + p.stderr[-2000:]
    if st != "succeeded":
        out["stderr"] = blob[-600:]; out["retryable"] = err.get("retryable")
    return out, blob


def _proxy_key():
    m = re.search(r'MM31_PROXY_KEY="([^"]+)"', PROXY_KEY_FILE.read_text())
    if not m:
        raise RuntimeError(f"no local proxy key in {PROXY_KEY_FILE}")
    return m.group(1)


THINK_BUDGET = {"low": 1024, "medium": 4096, "high": 16384}
MAX_TOKENS = int(os.environ.get("PV_MINIMAX_MAX_TOKENS", "16384"))


def _proxy(prompt, system, schema, effort, max_tokens=MAX_TOKENS):
    """Native Anthropic Messages passthrough of the proxy (/v1/messages): keeps stop_reason (the proxy's OpenAI
    translation reports finish_reason "stop" even when max_tokens truncated the reply) and separates thinking."""
    body = {"model": MINIMAX_MODEL, "max_tokens": max_tokens, "stream": False,
            "messages": [{"role": "user", "content": full_prompt(prompt, schema)}]}
    if system:
        body["system"] = system
    if effort in THINK_BUDGET:      # M3.1 Flash thinks regardless; the budget is a hint upstream may exceed
        body["thinking"] = {"type": "enabled", "budget_tokens": min(THINK_BUDGET[effort], max_tokens - 512)}
    req = urllib.request.Request(PROXY_URL + "/v1/messages", data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "x-api-key": _proxy_key(),
                                          "anthropic-version": "2023-06-01"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            code, raw = resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        code, raw = e.code, e.read().decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return {"rc": -9, "stop": "transport_error", "text": "", "latency_s": time.time() - t0,
                "stderr": str(e)[:300], "route": ROUTES["proxy"]}, str(e)
    lat = time.time() - t0
    try:
        d = json.loads(raw)
    except ValueError:
        d = {}
    blocks = d.get("content") or []
    text = "".join(b.get("text") or "" for b in blocks if isinstance(b, dict) and b.get("type") == "text")
    think = sum(len(b.get("thinking") or "") for b in blocks if isinstance(b, dict) and b.get("type") == "thinking")
    u = d.get("usage") or {}
    sr = d.get("stop_reason")
    good = code == 200 and sr in ("end_turn", "stop_sequence")
    out = {"rc": 0 if good else (code if code != 200 else 1), "stop": "completed" if good else (sr or f"http_{code}"),
           "text": strip_fence(text, schema),
           "usage": {"input_tokens": u.get("input_tokens"), "output_tokens": u.get("output_tokens"),
                     "cache_read_tokens": u.get("cache_read_input_tokens")},
           "cost_usd": None, "latency_s": lat, "http_status": code, "thread_id": d.get("id"), "thinking_chars": think,
           "model_reported": d.get("model"), "route": ROUTES["proxy"]}
    blob = f"http {code} " + ("" if good else raw[:1500])
    if not good:
        out["stderr"] = blob[:600]
    return out, blob


def call(prompt, system, schema, effort, stop_file: Path, stop_at: float = 0.0, transport: str | None = None):
    """Same contract as astra.call. stop_at is accepted for interface parity (MiniMax reports no used_percent)."""
    if stop_file is not None and stop_file.exists():
        return {"rc": -2, "stop": "quota_stop", "text": "", "latency_s": 0.0, "route": ROUTES.get(transport or TRANSPORT)}
    tr = transport or TRANSPORT
    if tr not in ROUTES:
        raise ValueError(f"unknown PV_MINIMAX_TRANSPORT {tr!r}")
    if tr == "proxy" and os.environ.get("PV_MINIMAX_PROXY_TOS_OK") != "1":
        raise PermissionError(PROXY_DISABLED_MSG)
    out, blob = (_cli if tr == "cli" else _proxy)(prompt, system, schema, effort)
    if out.get("stop") != "completed" and QUOTA_ERR.search(blob or ""):
        if stop_file is not None:
            stop_file.write_text(f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} minimax {tr} limit/auth error: "
                                 f"{(blob or '')[-600:]}\n")
        out.update(stop="quota_stop", rc=out.get("rc") or -2)
    return out
