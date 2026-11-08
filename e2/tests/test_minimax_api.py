import json, threading
from e2 import minimax_api as M


def ok_body(text="Paris.", stop="end_turn", out=12):
    return json.dumps({"model": M.MODEL, "stop_reason": stop, "content": [
        {"type": "thinking", "thinking": "hmm"}, {"type": "text", "text": text}],
        "usage": {"input_tokens": 100, "output_tokens": out}})


def err(code, status=200):
    return status, json.dumps({"type": "error", "error": {"type": "x", "message": f"({code}) boom"},
                               "base_resp": {"status_code": code, "status_msg": "boom"}})


class FakeQuota:
    def __init__(self, rows): self.rows = list(rows)
    def read(self): return self.rows.pop(0) if len(self.rows) > 1 else self.rows[0]


def api(tmp_path, transport, quota=None, **kw):
    sleeps = []
    gate = M.PauseGate(quota or FakeQuota([{"interval_remaining_pct": 90, "weekly_remaining_pct": 90}]),
                       lambda r: None, sleep=sleeps.append, guard_every_s=0)
    a = M.MiniMaxAPI(tmp_path / "cache", transport=transport, gate=gate, sleep=sleeps.append,
                     log_path=tmp_path / "ev.jsonl", **kw)
    return a, sleeps


def test_parse_response_joins_text_and_counts_thinking():
    r = M.parse_response(json.loads(ok_body("A")))
    assert r["text"] == "A" and r["thinking_chars"] == 3 and r["usage"]["output_tokens"] == 12


def test_cache_hit_makes_no_second_call(tmp_path):
    n = []
    a, _ = api(tmp_path, lambda p: (n.append(1), (200, ok_body()))[1])
    r1 = a.call("answer", "q?"); r2 = a.call("answer", "q?")
    assert r1["ok"] and not r1["memo_hit"] and r2["memo_hit"] and r2["text"] == "Paris." and len(n) == 1
    # resume: a fresh client over the same cache dir replays without calling
    b, _ = api(tmp_path, lambda p: (_ for _ in ()).throw(AssertionError("live call on resume")))
    assert b.call("answer", "q?")["memo_hit"]


def test_key_value_not_in_cache_key_or_payload(tmp_path, monkeypatch):
    monkeypatch.setenv("MINIMAX_API_KEY", "SECRET-TEST-VALUE")
    seen = []
    a, _ = api(tmp_path, lambda p: (seen.append(json.dumps(p)), (200, ok_body()))[1])
    r = a.call("answer", "q?")
    assert "SECRET-TEST-VALUE" not in seen[0] and "SECRET-TEST-VALUE" not in json.dumps(r)
    assert "SECRET-TEST-VALUE" not in (tmp_path / "ev.jsonl").read_text()


def test_truncated_is_not_ok_but_cached_first_sample(tmp_path):
    """rev 5: the first terminal (truncated) sample is persisted, so a resume replays it instead of resampling."""
    calls = []
    a, _ = api(tmp_path, lambda p: (calls.append(1), (200, ok_body("partial", stop="max_tokens")))[1])
    r = a.call("answer", "q?")
    assert not r["ok"] and r["truncated"] and r["text"] == "partial"
    r2 = a.call("answer", "q?")
    assert r2["memo_hit"] and r2["text"] == "partial" and len(calls) == 1


def test_empty_is_not_cached(tmp_path):
    a, _ = api(tmp_path, lambda p: (200, ok_body("", stop="end_turn")))
    r = a.call("answer", "q?")
    assert not r["ok"]
    assert not list((tmp_path / "cache").rglob("*.json"))


def test_retry_then_success_with_backoff(tmp_path):
    seq = [(500, "oops"), err(1002), (None, "TimeoutError"), (200, ok_body())]
    a, sleeps = api(tmp_path, lambda p: seq.pop(0))
    r = a.call("answer", "q?")
    assert r["ok"] and len(r["attempt_history"]) == 4 and len(sleeps) == 3


def test_window_error_pauses_until_reset_and_resumes(tmp_path):
    import time
    end = (time.time() + 3600) * 1000
    q = FakeQuota([{"interval_remaining_pct": 90, "weekly_remaining_pct": 90},   # guard
                   {"interval_remaining_pct": 0, "interval_end_ms": end, "weekly_remaining_pct": 50},  # pause read
                   {"interval_remaining_pct": 100, "weekly_remaining_pct": 50}])
    seq = [err(2056), (200, ok_body())]
    a, sleeps = api(tmp_path, lambda p: seq.pop(0), quota=q, max_attempts=1)
    r = a.call("answer", "q?")
    assert r["ok"]                                         # window pause did not consume the single attempt
    assert any(3500 < s < 3800 for s in sleeps)            # slept until interval end + margin
    assert a.gate.pauses and a.gate.pauses[0]["why"] == "window_error"


def test_guard_pauses_proactively_at_floor(tmp_path):
    import time
    end = (time.time() + 600) * 1000
    q = FakeQuota([{"interval_remaining_pct": 1, "interval_end_ms": end, "weekly_remaining_pct": 50},
                   {"interval_remaining_pct": 1, "interval_end_ms": end, "weekly_remaining_pct": 50},
                   {"interval_remaining_pct": 100, "weekly_remaining_pct": 50}])
    a, sleeps = api(tmp_path, lambda p: (200, ok_body()), quota=q)
    assert a.call("answer", "q?")["ok"] and any(500 < s < 800 for s in sleeps)


def test_fatal_error_stops(tmp_path):
    n = []
    a, _ = api(tmp_path, lambda p: (n.append(1), err(1004, 401))[1])
    r = a.call("answer", "q?")
    assert not r["ok"] and len(n) == 1


def test_budget_cap(tmp_path):
    a, _ = api(tmp_path, lambda p: (200, ok_body()), budget_calls=1)
    a.call("answer", "a"); a.call("answer", "a")            # second is a cache hit, not a live call
    try:
        a.call("answer", "b"); assert False
    except RuntimeError:
        pass


def test_inflight_coalescing(tmp_path):
    n, gate = [], threading.Event()

    def slow(p):
        n.append(1); gate.wait(2); return 200, ok_body()
    a, _ = api(tmp_path, slow)
    out = []
    th = [threading.Thread(target=lambda: out.append(a.call("answer", "same"))) for _ in range(4)]
    [t.start() for t in th]; gate.set(); [t.join() for t in th]
    assert len(n) == 1 and all(r["ok"] for r in out)


def test_payload_route():
    a = M.MiniMaxAPI.__new__(M.MiniMaxAPI); a.model, a.max_tokens, a.system, a.effort = M.MODEL, 8192, "s", "low"
    p = a.payload("hi")
    assert p["model"] == "MiniMax-M3.1-Flash" and p["output_config"] == {"effort": "low"} and "temperature" not in p
    assert M.ENDPOINT == "https://api.minimax.io/anthropic/v1/messages"


def test_rate_limit_2062_has_own_budget_and_failure_is_logged(tmp_path):
    seq = [err(2062, 429)] * 20 + [(200, ok_body())]
    a, sleeps = api(tmp_path, lambda p: seq.pop(0))
    assert a.call("answer", "q?")["ok"] and len(sleeps) == 20
    b, _ = api(tmp_path / "b", lambda p: err(2062, 429), max_rate_limit_retries=3, max_attempts=2)
    r = b.call("answer", "q?")
    assert not r["ok"]
    ev = [json.loads(l) for l in (tmp_path / "b" / "ev.jsonl").read_text().splitlines()]
    assert ev[-1]["kind"] == "call_failed" and ev[-1]["attempts"] == 5
