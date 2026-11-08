"""Grok CLI / Codex CLI wrappers with a content-addressed call memo and a JSONL call log (C41: reported model ids).

Memo key = sha256(role | requested model | system | schema | prompt). A memo hit re-serves an earlier VALID
output (identical prompt -> identical output across arms/worlds; disclosed in the REPORT). Invalid outputs
(non-zero exit, stopReason != end_turn, empty text, banner/error/refusal) are NEVER memoised or returned as ok
(cache-poisoning guard, v1.2.1 §3.3a(ii)). Concurrent identical requests are coalesced (in-flight futures)."""
from __future__ import annotations
import json, os, subprocess, tempfile, threading, time, glob
from concurrent.futures import Future
from pathlib import Path
from .common import sha, is_non_answer, ANSWER_MODEL, JUDGE_MODEL

GROK_BIN = os.environ.get("PV_GROK_BIN", "grok")
CODEX_BIN = os.environ.get("PV_CODEX_BIN", "/opt/homebrew/lib/node_modules/@openai/codex/node_modules/@openai/codex-"
                           "darwin-arm64/vendor/aarch64-apple-darwin/bin/codex")
SYSTEM = ("You are a careful assistant. Follow the user's instructions exactly. You have NO tools, skills, memory or brain "
          "access in this session: never attempt a tool or skill call or a lookup. Use only the text in the prompt. Reply with text only.")
EMPTY_CWD = Path(tempfile.gettempdir()) / "pv12empty"


class LLM:
    def __init__(self, run_dir: Path, fake=None, reasoning_effort: str = "low", max_parallel: int = 8,
                 answerer: str = "grok", stop_file: Path | None = None, stop_at: float = 94.0):
        self.dir = Path(run_dir); self.dir.mkdir(parents=True, exist_ok=True)
        self.memo_dir = self.dir / "memo"; self.memo_dir.mkdir(exist_ok=True)
        self.log_path = self.dir / "calls.jsonl"
        self.fake = fake                      # callable(role, prompt) -> text, for tests only
        self.effort = reasoning_effort
        self.lock = threading.Lock()
        self.inflight: dict[str, Future] = {}
        self.sem = threading.Semaphore(max_parallel)
        EMPTY_CWD.mkdir(exist_ok=True)
        # PILOT3-ASTRA deviation (DEVIATION-ASTRA.md): answerer route selected by flag; default grok path unchanged
        # MiniMax route (MINIMAX-ROUTE.md): answerer="minimax" sends answerer calls to pilot/minimax.py
        if answerer not in ("grok", "astra", "minimax"):
            raise ValueError(answerer)
        self.answerer, self.stop_file, self.stop_at = answerer, stop_file, stop_at

    # ------------------------------------------------------------------ public
    def call(self, role: str, prompt: str, *, model: str = ANSWER_MODEL, schema: str | None = None,
             ctx: dict | None = None) -> dict:
        provider = "codex" if model == JUDGE_MODEL else "grok"
        if provider == "grok" and self.answerer == "astra":
            provider = "astra"
        if provider == "grok" and self.answerer == "minimax":
            provider = "minimax"
        # v1.3 F08: versioned structured key incl. reasoning effort (v1.2 key omitted decoding config)
        if provider == "astra":     # distinct namespace: astra outputs never collide with grok memo entries
            from .astra import ASTRA_MODEL
            key = sha(json.dumps(["call-v2-astra", role, ASTRA_MODEL, self.effort, SYSTEM, schema or "", prompt]))
        elif provider == "minimax":  # distinct namespace again (never collides with grok or astra entries)
            from .minimax import MINIMAX_MODEL, TRANSPORT     # transport in the key: cli and proxy differ in overhead
            key = sha(json.dumps(["call-v2-minimax", TRANSPORT, role, MINIMAX_MODEL, self.effort, SYSTEM, schema or "", prompt]))
        else:
            key = sha(json.dumps(["call-v2", role, model, self.effort, SYSTEM if provider == "grok" else "", schema or "", prompt]))
        mpath = self.memo_dir / f"{key}.json"
        with self.lock:
            fut = self.inflight.get(key)
            owner = fut is None
            if owner:
                fut = Future(); self.inflight[key] = fut
        if not owner:
            r = dict(fut.result()); r["memo_hit"] = True
            self._log(r, role, ctx, key, memo=True); return r
        try:
            if mpath.exists():
                r = json.loads(mpath.read_text()); r["memo_hit"] = True
                self._log(r, role, ctx, key, memo=True)
            else:
                r = None
                attempt_history = []          # v1.3 F07: every real attempt, billed to the initiating caller
                for attempt in range(3):
                    with self.sem:
                        r = self._fake(role, prompt, model) if self.fake else (
                            self._astra(prompt, schema) if provider == "astra" else
                            self._minimax(prompt, schema) if provider == "minimax" else
                            self._grok(prompt, model, schema) if provider == "grok" else self._codex(prompt, model))
                    r.update(role=role, model_requested=("gpt-6-astra" if provider == "astra" else
                             "MiniMax-M3.1-Flash" if provider == "minimax" else model), prompt_sha=sha(prompt), attempt=attempt,
                             prompt_chars=len(prompt))
                    r["ok"] = r.get("rc") == 0 and r.get("stop") in ("end_turn", "completed") and not is_non_answer(r.get("text"))
                    self._log(r, role, ctx, key, memo=False)
                    attempt_history.append({k: r.get(k) for k in ("ok", "usage", "latency_s", "model_reported", "cost_usd")})
                    if r["ok"] or r.get("stop") == "quota_stop":     # astra: never retry after a quota stop
                        break
                    time.sleep(3 * (attempt + 1))
                r["memo_hit"] = False
                r["attempt_history"] = attempt_history
                if r["ok"]:
                    mpath.write_text(json.dumps(r))
            fut.set_result(r)
            return r
        except BaseException as e:
            fut.set_exception(e); raise
        finally:
            with self.lock:
                self.inflight.pop(key, None)

    # ------------------------------------------------------------------ backends
    def _fake(self, role, prompt, model):
        t0 = time.time(); text = self.fake(role, prompt)
        return {"rc": 0, "stop": "end_turn", "text": text, "model_reported": "fake", "usage": {"input_tokens": len(prompt) // 4,
                "output_tokens": len(text) // 4}, "cost_usd": 0.0, "latency_s": time.time() - t0}

    def _minimax(self, prompt, schema):
        from . import minimax
        return minimax.call(prompt, SYSTEM, schema, self.effort, self.stop_file, self.stop_at)

    def _astra(self, prompt, schema):
        from . import astra
        return astra.call(prompt, SYSTEM, schema, self.effort, self.stop_file, self.stop_at)

    def _grok(self, prompt, model, schema):
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
            f.write(prompt); pf = f.name
        cmd = [GROK_BIN, "--prompt-file", pf, "-m", model, "--output-format", "json", "--max-turns", "1",
               "--disable-web-search", "--no-subagents", "--tools", "", "--system-prompt-override", SYSTEM,
               "--reasoning-effort", self.effort, "--cwd", str(EMPTY_CWD)]
        if schema:
            cmd += ["--json-schema", schema]
        t0 = time.time()
        try:
            p = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=600,
                               env=dict(os.environ, GROK_MEMORY="0"))
        except subprocess.TimeoutExpired:
            os.unlink(pf); return {"rc": -9, "stop": "timeout", "text": "", "latency_s": time.time() - t0}
        os.unlink(pf)
        lat = time.time() - t0
        try:
            out = p.stdout.strip()
            j = json.loads(out[out.index("{"):])
        except Exception:
            return {"rc": p.returncode or -1, "stop": "parse_error", "text": "", "latency_s": lat,
                    "stderr": p.stderr[-500:], "stdout": p.stdout[-500:]}
        text = j.get("text") or j.get("result") or ""
        if schema and j.get("structuredOutput") is not None:
            text = json.dumps(j["structuredOutput"])
        mu = j.get("modelUsage") or {}
        return {"rc": p.returncode, "stop": j.get("stopReason"), "text": text,
                "model_reported": ",".join(sorted(mu.keys())) or None, "usage": j.get("usage") or {},
                "cost_usd": j.get("total_cost_usd"), "latency_s": lat}

    def _codex(self, prompt, model):
        t0 = time.time()
        try:
            p = subprocess.run([CODEX_BIN, "exec", "-m", model, "--skip-git-repo-check", "--json", prompt],
                               stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=900,
                               cwd=str(Path.home()))
        except subprocess.TimeoutExpired:
            return {"rc": -9, "stop": "timeout", "text": "", "latency_s": time.time() - t0}
        lat = time.time() - t0
        text, usage, tid, stop = "", {}, None, None
        for line in p.stdout.splitlines():
            try:
                e = json.loads(line)
            except Exception:
                continue
            if e.get("type") == "thread.started":
                tid = e.get("thread_id")
            it = e.get("item") or {}
            if e.get("type") == "item.completed" and it.get("type") in ("agent_message", "assistant_message"):
                text = it.get("text") or text
            if e.get("type") == "turn.completed":
                usage = e.get("usage") or {}; stop = "completed"
        reported = None
        if tid:
            for f in glob.glob(str(Path.home() / ".codex/sessions") + "/*/*/*/*" + tid + ".jsonl"):
                for line in open(f):
                    if '"model":"' in line:
                        reported = line.split('"model":"', 1)[1].split('"', 1)[0]; break
        return {"rc": p.returncode, "stop": stop, "text": text, "model_reported": reported, "usage": usage,
                "cost_usd": None, "latency_s": lat, "thread_id": tid}

    def _log(self, r, role, ctx, key, memo):
        row = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "role": role, "key": key, "memo_hit": memo,
               "ok": r.get("ok"), "rc": r.get("rc"), "stop": r.get("stop"), "model_requested": r.get("model_requested"),
               "model_reported": r.get("model_reported"), "usage": r.get("usage"), "cost_usd": r.get("cost_usd"),
               "latency_s": None if memo else r.get("latency_s"), "prompt_sha": r.get("prompt_sha"),
               "attempt": r.get("attempt"), "non_answer": is_non_answer(r.get("text")), "ctx": ctx or {}}
        if r.get("route"):                    # astra deviation fields (absent on the grok route)
            row.update(route=r["route"], used_percent=r.get("used_percent"), tool_calls=r.get("tool_calls"),
                       thread_id=r.get("thread_id"))
        if not r.get("ok"):
            row["text_head"] = (r.get("text") or "")[:300]; row["stderr"] = r.get("stderr")
        with self.lock, open(self.log_path, "a") as f:
            f.write(json.dumps(row) + "\n")


def in_tokens(usage: dict) -> int:
    u = usage or {}
    return int(u.get("input_tokens") or 0) + int(u.get("cache_read_input_tokens") or 0) + \
        int(u.get("cache_creation_input_tokens") or 0) + int(u.get("cached_input_tokens") or 0) * 0
