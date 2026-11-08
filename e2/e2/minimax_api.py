"""MiniMax Token Plan answerer over the official Anthropic-compatible Messages API (NOT the mcode CLI, NOT the
Hermes proxy).

Key: env var MINIMAX_API_KEY, else ~/.mmx/config.json field `api_key`. The value is never logged, printed,
hashed into a cache key or written to disk by this module.

Determinism: MiniMax documents `temperature` and `top_p` as ignored on this endpoint (server-fixed 1.0 / 0.95)
and thinking cannot be disabled (thinking:disabled -> 400/2013). We send no temperature and record that in the
freeze file. `output_config.effort` = "low" (matches the CLI calibration's --effort low).

Robustness:
* retry with exponential backoff + jitter on network errors, HTTP 408/429/5xx, MiniMax 1000/1001/1002/1024/
  1033/1039/1041/2045/2046/2047/2062;
* window exhaustion (2056 "usage limit exceeded", 1008/2053 credit errors) -> shared pause gate: poll
  token_plan/remains and sleep until the 5-hour window (or weekly window) end + margin, then resume;
* proactive guard: every `guard_every_s` the remaining % of the 5-hour and weekly windows is read; below
  `floor_pct` all workers pause until reset (so overflow never silently spills into purchased Credits);
* content-addressed per-call cache (one JSON file per call) -> idempotent resume. Non-answers and truncated
  (stop_reason=max_tokens with no text) outputs are never cached.
"""
from __future__ import annotations
import hashlib, json, os, random, re, threading, time, urllib.error, urllib.request
from pathlib import Path

ENDPOINT = "https://api.minimax.io/anthropic/v1/messages"
QUOTA_URL = "https://www.minimax.io/v1/token_plan/remains"
MODEL = "MiniMax-M3.1-Flash"
EFFORT = "low"
MAX_TOKENS = 8192                     # includes thinking tokens; generous so answers are not truncated
ROUTE = "minimax-anthropic-api-v1"
SYSTEM = ("You are a careful assistant. Follow the user's instructions exactly. You have NO tools, skills, memory or brain "
          "access in this session: never attempt a tool or skill call or a lookup. Use only the text in the prompt. Reply with text only.")
RETRY_CODES = {1000, 1001, 1002, 1024, 1033, 1039, 1041, 2045, 2046, 2047, 2062}
WINDOW_CODES = {2056, 1008, 2053}
FATAL_CODES = {1004, 2049, 2057, 2061, 2022, 2013, 1026, 1027}
WINDOW_RX = re.compile(r"usage limit exceeded|insufficient (balance|credit)|5-hour|weekly", re.I)


def load_key() -> str:
    k = os.environ.get("MINIMAX_API_KEY", "").strip()
    if k:
        return k
    p = Path.home() / ".mmx" / "config.json"
    if p.exists():
        k = (json.load(open(p)).get("api_key") or "").strip()
    if not k:
        raise RuntimeError("no MiniMax key: set MINIMAX_API_KEY or ~/.mmx/config.json api_key")
    return k


def cache_key(role: str, prompt: str, system: str = SYSTEM, model: str = MODEL, effort: str = EFFORT,
              max_tokens: int = MAX_TOKENS) -> str:
    blob = json.dumps({"route": ROUTE, "role": role, "model": model, "effort": effort, "max_tokens": max_tokens,
                       "system": system, "prompt": prompt}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()


def parse_response(body: dict) -> dict:
    """Anthropic-format body -> {text, thinking_chars, stop, usage, model_reported}. Text = concatenated text blocks."""
    blocks = body.get("content") or []
    text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
    thinking = sum(len(b.get("thinking", "") or "") for b in blocks if b.get("type") == "thinking")
    u = body.get("usage") or {}
    return {"text": text, "thinking_chars": thinking, "stop": body.get("stop_reason"), "model_reported": body.get("model"),
            "usage": {"input_tokens": int(u.get("input_tokens") or 0), "output_tokens": int(u.get("output_tokens") or 0),
                      "cache_read_input_tokens": int(u.get("cache_read_input_tokens") or 0),
                      "cache_creation_input_tokens": int(u.get("cache_creation_input_tokens") or 0)}}


def is_error_body(body_text: str) -> bool:
    """MiniMax can return HTTP 200 with an error envelope (type=error or base_resp.status_code != 0)."""
    try:
        j = json.loads(body_text)
    except Exception:
        return False
    br = j.get("base_resp") or {}
    return j.get("type") == "error" or bool(br.get("status_code")) and not j.get("content")


def classify_error(status: int | None, body_text: str) -> tuple[str, int | None]:
    """-> (kind, minimax_code); kind in retry|window|fatal."""
    code = None
    try:
        j = json.loads(body_text)
        br = j.get("base_resp") or {}
        code = br.get("status_code")
        if code is None and isinstance(j.get("error"), dict):
            m = re.search(r"\((\d{4,5})\)", json.dumps(j["error"]))
            code = int(m.group(1)) if m else None
    except Exception:
        m = re.search(r"\b(1\d{3}|2\d{3})\b", body_text or "")
        code = int(m.group(1)) if m else None
    if code in WINDOW_CODES or WINDOW_RX.search(body_text or ""):
        return "window", code
    if code in FATAL_CODES or status in (400, 401, 403, 404):
        return "fatal", code
    if code in RETRY_CODES or status in (None, 408, 409, 425, 429, 500, 502, 503, 504, 529):
        return "retry", code
    return ("retry" if (status or 0) >= 500 else "fatal"), code


class Quota:
    """Reads the Token Plan windows (GET token_plan/remains; HTTP 200 always -> check base_resp.status_code)."""

    def __init__(self, key_fn=load_key, opener=None):
        self.key_fn, self.opener = key_fn, opener or urllib.request.urlopen

    def read(self) -> dict | None:
        req = urllib.request.Request(QUOTA_URL, headers={"Authorization": f"Bearer {self.key_fn()}",
                                                         "Content-Type": "application/json"})
        try:
            with self.opener(req, timeout=30) as r:
                j = json.loads(r.read().decode())
        except Exception:
            return None
        if (j.get("base_resp") or {}).get("status_code", 0) != 0:
            return None
        return summarize_quota(j)


def summarize_quota(j: dict) -> dict:
    """Pick the text-model row (`general`, else MiniMax-M*) of model_remains; fall back to the first row."""
    rows = j.get("model_remains") or []
    row = next((r for r in rows if r.get("model_name") == "general"), None) or \
        next((r for r in rows if str(r.get("model_name", "")).startswith("MiniMax-M")), rows[0] if rows else {})
    return {"interval_remaining_pct": row.get("current_interval_remaining_percent"),
            "interval_end_ms": row.get("end_time"), "interval_remains_ms": row.get("remains_time"),
            "weekly_remaining_pct": row.get("current_weekly_remaining_percent"),
            "weekly_end_ms": row.get("weekly_end_time"), "model_name": row.get("model_name"),
            "read_at_ms": int(time.time() * 1000)}


class PauseGate:
    """Shared across worker threads: one thread waits out the window; the rest block on the event."""

    def __init__(self, quota: Quota, log, floor_pct=2.0, guard_every_s=120, margin_s=90, sleep=time.sleep):
        self.quota, self.log, self.floor, self.every, self.margin, self.sleep = quota, log, floor_pct, guard_every_s, margin_s, sleep
        self.lock = threading.Lock(); self.open = threading.Event(); self.open.set()
        self.last_check = 0.0
        self.pauses: list[dict] = []

    def _resume_at(self, q: dict | None, why: str) -> float:
        now = time.time()
        if not q:
            return now + 600                              # quota unreadable: re-check in 10 min
        ends = []
        if q.get("interval_remaining_pct") is not None and q["interval_remaining_pct"] <= self.floor and q.get("interval_end_ms"):
            ends.append(q["interval_end_ms"] / 1000)
        if q.get("weekly_remaining_pct") is not None and q["weekly_remaining_pct"] <= self.floor and q.get("weekly_end_ms"):
            ends.append(q["weekly_end_ms"] / 1000)
        if not ends:
            return now + (60 if why == "window_error" else 0)   # error but windows look fine: RPM-type, 1 min
        return max(ends) + self.margin

    def pause(self, why: str):
        if not self.lock.acquire(blocking=False):
            self.open.wait(); return                      # someone else is already waiting out the window
        try:
            self.open.clear()
            while True:
                q = self.quota.read()
                until = self._resume_at(q, why)
                if until <= time.time():
                    break
                rec = {"why": why, "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "quota": q,
                       "resume_at": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(until))}
                self.pauses.append(rec); self.log(rec)
                self.sleep(max(1.0, until - time.time()))
                why = "recheck"
        finally:
            self.open.set(); self.lock.release()

    def guard(self):
        self.open.wait()
        if time.time() - self.last_check < self.every:
            return
        self.last_check = time.time()
        q = self.quota.read()
        if q and ((q.get("interval_remaining_pct") is not None and q["interval_remaining_pct"] <= self.floor) or
                  (q.get("weekly_remaining_pct") is not None and q["weekly_remaining_pct"] <= self.floor)):
            self.pause("guard_floor")


class MiniMaxAPI:
    """call(role, prompt) -> {ok, text, stop, usage, latency_s, model_reported, memo_hit, attempt_history, cache_key}."""

    def __init__(self, cache_dir: Path, *, model=MODEL, effort=EFFORT, max_tokens=MAX_TOKENS, system=SYSTEM,
                 max_attempts=8, max_parallel=6, transport=None, gate: PauseGate | None = None, log_path: Path | None = None,
                 sleep=time.sleep, budget_calls: int | None = None, max_window_pauses: int = 50,
                 max_rate_limit_retries: int = 60):
        self.model, self.effort, self.max_tokens, self.system = model, effort, max_tokens, system
        self.cache_dir = Path(cache_dir); self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.max_attempts, self.sleep, self.max_window_pauses = max_attempts, sleep, max_window_pauses
        # rev 5: HTTP 429 "Token Plan rate limit" (2062) is throttling, not a fault; it gets its own retry budget so
        # concurrency never turns into failed calls (DEV3 lost 1 answer after 8 consecutive 2062s)
        self.max_rate_limit_retries = max_rate_limit_retries
        self.transport = transport or self._http
        self.sem = threading.Semaphore(max_parallel)
        self.log_path = Path(log_path) if log_path else self.cache_dir.parent / "api-events.jsonl"
        self.gate = gate or PauseGate(Quota(), self._event)
        self.inflight: dict[str, threading.Event] = {}
        self.ilock = threading.Lock()
        self.budget_calls, self.live_calls = budget_calls, 0
        self.block = threading.Lock()

    def _event(self, rec: dict):
        with open(self.log_path, "a") as f:
            f.write(json.dumps(rec, default=str) + "\n")

    # -- transport (replaceable in tests)
    def _http(self, payload: dict) -> tuple[int | None, str]:
        req = urllib.request.Request(ENDPOINT, data=json.dumps(payload).encode(), method="POST",
                                     headers={"Authorization": f"Bearer {load_key()}", "Content-Type": "application/json",
                                              "anthropic-version": "2023-06-01"})
        try:
            with urllib.request.urlopen(req, timeout=600) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode(errors="replace")
        except Exception as e:                          # network / timeout
            return None, f"{type(e).__name__}: {e}"

    def payload(self, prompt: str) -> dict:
        return {"model": self.model, "max_tokens": self.max_tokens, "system": self.system,
                "messages": [{"role": "user", "content": prompt}], "output_config": {"effort": self.effort}}

    def _path(self, k):
        return self.cache_dir / k[:2] / f"{k}.json"

    def call(self, role: str, prompt: str, ctx: dict | None = None) -> dict:
        k = cache_key(role, prompt, self.system, self.model, self.effort, self.max_tokens)
        p = self._path(k)
        while True:
            if p.exists():
                r = json.load(open(p)); r.update(memo_hit=True, attempt_history=[]); return r
            with self.ilock:
                ev = self.inflight.get(k)
                if ev is None:
                    self.inflight[k] = threading.Event(); mine = True
                else:
                    mine = False
            if not mine:
                ev.wait()
                if p.exists():
                    continue
                # owner failed: fall through and try ourselves
                with self.ilock:
                    if k in self.inflight:
                        continue
                    self.inflight[k] = threading.Event()
            try:
                r = self._live(role, prompt, k, ctx)
            finally:
                with self.ilock:
                    self.inflight.pop(k).set()
            return r

    def _live(self, role, prompt, k, ctx):
        hist = []
        with self.block:
            if self.budget_calls is not None and self.live_calls >= self.budget_calls:
                raise RuntimeError(f"live-call budget {self.budget_calls} reached")
            self.live_calls += 1
        attempt, windows, rl = 0, 0, 0
        while attempt < self.max_attempts and windows < self.max_window_pauses:
            attempt += 1
            self.gate.guard()
            with self.sem:
                t0 = time.time()
                status, text = self.transport(self.payload(prompt))
                dt = time.time() - t0
            if status == 200 and not is_error_body(text):    # HTTP 200 + error envelope falls through to classify
                try:
                    out = parse_response(json.loads(text))
                except Exception as e:
                    hist.append({"attempt": attempt, "status": status, "err": f"parse: {e}"}); self.sleep(min(60, 2 ** attempt)); continue
                trunc = out["stop"] == "max_tokens"
                ok = bool(out["text"].strip()) and not trunc
                rec = dict(out, ok=ok, truncated=trunc, latency_s=round(dt, 3), cache_key=k, role=role, route=ROUTE,
                           model=self.model, effort=self.effort, max_tokens=self.max_tokens,
                           ctx=ctx or {}, at=time.strftime("%Y-%m-%dT%H:%M:%S%z"))
                hist.append({"attempt": attempt, "status": 200, "stop": out["stop"], "usage": out["usage"], "latency_s": rec["latency_s"]})
                rec["attempt_history"] = hist
                self._event({"kind": "call", "role": role, "ok": ok, "stop": out["stop"], "usage": out["usage"],
                             "latency_s": rec["latency_s"], "cache_key": k, "ctx": ctx or {}})
                if ok or trunc:                           # rev 5: first terminal sample persisted, incl. truncations
                    p = self._path(k); p.parent.mkdir(parents=True, exist_ok=True)
                    tmp = p.with_suffix(".tmp"); tmp.write_text(json.dumps(rec)); tmp.replace(p)
                rec["memo_hit"] = False
                return rec                                # truncated: returned not-ok, cached; empty: not cached
            kind, code = classify_error(status, text)
            hist.append({"attempt": attempt, "status": status, "code": code, "kind": kind, "err": (text or "")[:300]})
            self._event({"kind": "error", "status": status, "code": code, "class": kind, "err": (text or "")[:300], "ctx": ctx or {}})
            if kind == "fatal":
                break
            if kind == "window":                         # window/limit pauses do not consume retry attempts
                windows += 1; attempt -= 1
                self.gate.pause("window_error")
                continue
            if status == 429 and rl < self.max_rate_limit_retries:   # throttling: own budget, jittered 5-35 s
                rl += 1; attempt -= 1
                self.sleep(5 + random.random() * 30)
                continue
            self.sleep(min(120.0, (2 ** attempt) + random.random() * 2))
        self._event({"kind": "call_failed", "role": role, "cache_key": k, "attempts": len(hist), "ctx": ctx or {},
                     "last": hist[-1] if hist else None})
        return {"ok": False, "text": "", "stop": None, "usage": {"input_tokens": 0, "output_tokens": 0}, "latency_s": None,
                "model_reported": None, "memo_hit": False, "attempt_history": hist, "cache_key": k, "error": hist[-1] if hist else None}
