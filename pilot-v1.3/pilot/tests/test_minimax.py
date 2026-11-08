"""Offline tests for the MiniMax answerer route (pilot/minimax.py, MINIMAX-ROUTE.md). No model calls: subprocess and
HTTP are faked. Also checks that the grok and astra paths of LLM are unchanged."""
import io, json, subprocess, urllib.error
from pathlib import Path
import pytest


def _exec_result(status="succeeded", output="Paris", error=None):
    return json.dumps({"status": status, "output": output, "sessionId": "mvs_test",
                       "model": {"providerId": "minimax", "modelId": "MiniMax-M3.1-Flash", "variant": "thinking"},
                       "usage": {"inputTokens": 1200, "outputTokens": 7, "cacheReadTokens": 256}, "durationMs": 4000,
                       "error": error})


class _P:
    def __init__(self, stdout, rc=0, stderr=""):
        self.stdout, self.returncode, self.stderr = stdout, rc, stderr


def test_cli_success_parses_exec_result(monkeypatch, tmp_path):
    from pilot import minimax as M
    seen = {}
    def fake_run(cmd, input=None, **kw):
        seen["cmd"], seen["input"] = cmd, input
        return _P("some log line\n" + _exec_result())
    monkeypatch.setattr(M.subprocess, "run", fake_run)
    r = M.call("Q?", "SYS", None, "low", tmp_path / "STOP", transport="cli")
    assert r["rc"] == 0 and r["stop"] == "completed" and r["text"] == "Paris"
    assert r["model_reported"] == "minimax/MiniMax-M3.1-Flash" and r["route"] == "minimax-mcode-cli-v1"
    assert r["usage"]["input_tokens"] == 1200 and r["usage"]["output_tokens"] == 7
    c = seen["cmd"]
    assert c[1] == "exec" and c[c.index("--mode") + 1] == "lightweight" and c[c.index("--permission") + 1] == "off"
    assert c[c.index("--model") + 1] == "minimax/MiniMax-M3.1-Flash" and c[c.index("--system-prompt") + 1] == "SYS"
    assert c[c.index("--effort") + 1] == "low" and c[c.index("--max-steps") + 1] == "1"
    assert seen["input"] == "Q?"          # system goes via --system-prompt, not into the prompt
    assert not (tmp_path / "STOP").exists()


def test_cli_schema_appended_and_fence_stripped(monkeypatch, tmp_path):
    from pilot import minimax as M
    seen = {}
    def fake_run(cmd, input=None, **kw):
        seen["input"] = input
        return _P(_exec_result(output='```json\n{"a": 1}\n```'))
    monkeypatch.setattr(M.subprocess, "run", fake_run)
    r = M.call("Q?", "SYS", '{"type":"object"}', "low", tmp_path / "STOP", transport="cli")
    assert "JSON Schema" in seen["input"] and r["text"] == '{"a": 1}'


def test_cli_rate_limit_writes_stop_and_short_circuits(monkeypatch, tmp_path):
    from pilot import minimax as M
    n = {"calls": 0}
    def fake_run(cmd, input=None, **kw):
        n["calls"] += 1
        return _P(_exec_result(status="failed", output="", error={"category": "rate_limit", "message": "429 Too Many Requests",
                                                                   "retryable": True}), rc=1)
    monkeypatch.setattr(M.subprocess, "run", fake_run)
    stop = tmp_path / "STOP"
    r = M.call("Q?", "SYS", None, "low", stop, transport="cli")
    assert r["stop"] == "quota_stop" and r["rc"] != 0 and stop.exists()
    r2 = M.call("Q?", "SYS", None, "low", stop, transport="cli")
    assert r2["stop"] == "quota_stop" and n["calls"] == 1


def test_cli_plain_failure_is_not_ok_and_no_stop(monkeypatch, tmp_path):
    from pilot import minimax as M
    monkeypatch.setattr(M.subprocess, "run", lambda cmd, input=None, **kw: _P(_exec_result(
        status="failed", output="", error={"category": "provider", "message": "upstream 500", "retryable": True}), rc=1))
    r = M.call("Q?", "SYS", None, "low", tmp_path / "STOP", transport="cli")
    assert r["stop"] == "failed" and r["rc"] != 0 and not (tmp_path / "STOP").exists()


def test_cli_timeout(monkeypatch, tmp_path):
    from pilot import minimax as M
    def boom(*a, **k):
        raise subprocess.TimeoutExpired("mcode", 1)
    monkeypatch.setattr(M.subprocess, "run", boom)
    r = M.call("Q?", "SYS", None, "low", tmp_path / "STOP", transport="cli")
    assert r["stop"] == "timeout" and r["rc"] == -9


class _Resp(io.BytesIO):
    status = 200
    def __enter__(self): return self
    def __exit__(self, *a): return False


def _anth(text="42", stop="end_turn", out=3):
    return json.dumps({"id": "msg_1", "model": "MiniMax-M3.1-Flash", "stop_reason": stop,
                       "content": [{"type": "thinking", "thinking": "hmm"}, {"type": "text", "text": text}],
                       "usage": {"input_tokens": 900, "output_tokens": out}}).encode()


def test_proxy_success_and_key_not_in_result(monkeypatch, tmp_path):
    from pilot import minimax as M
    monkeypatch.setenv("PV_MINIMAX_PROXY_TOS_OK", "1")
    kf = tmp_path / "launcher.sh"; kf.write_text('MM31_PROXY_KEY="local-test-key"\n')
    monkeypatch.setattr(M, "PROXY_KEY_FILE", kf)
    seen = {}
    def fake_open(req, timeout=None):
        seen["url"] = req.full_url; seen["key"] = req.get_header("X-api-key"); seen["body"] = json.loads(req.data)
        return _Resp(_anth())
    monkeypatch.setattr(M.urllib.request, "urlopen", fake_open)
    r = M.call("Q?", "SYS", None, "low", tmp_path / "STOP", transport="proxy")
    assert r["rc"] == 0 and r["stop"] == "completed" and r["text"] == "42" and r["route"] == "minimax-hermes-proxy-v1"
    assert seen["url"].endswith("/v1/messages") and seen["key"] == "local-test-key"
    assert seen["body"]["system"] == "SYS" and seen["body"]["messages"] == [{"role": "user", "content": "Q?"}]
    assert seen["body"]["thinking"]["budget_tokens"] == 1024
    assert "local-test-key" not in json.dumps(r)


def test_proxy_max_tokens_truncation_is_not_ok(monkeypatch, tmp_path):
    from pilot import minimax as M
    monkeypatch.setenv("PV_MINIMAX_PROXY_TOS_OK", "1")
    kf = tmp_path / "launcher.sh"; kf.write_text('MM31_PROXY_KEY="k"\n')
    monkeypatch.setattr(M, "PROXY_KEY_FILE", kf)
    monkeypatch.setattr(M.urllib.request, "urlopen", lambda req, timeout=None: _Resp(_anth(text="", stop="max_tokens", out=16384)))
    r = M.call("Q?", "SYS", None, "low", tmp_path / "STOP", transport="proxy")
    assert r["stop"] == "max_tokens" and r["rc"] != 0 and not (tmp_path / "STOP").exists()


def test_proxy_429_writes_stop(monkeypatch, tmp_path):
    from pilot import minimax as M
    monkeypatch.setenv("PV_MINIMAX_PROXY_TOS_OK", "1")
    kf = tmp_path / "launcher.sh"; kf.write_text('MM31_PROXY_KEY="k"\n')
    monkeypatch.setattr(M, "PROXY_KEY_FILE", kf)
    def fake_open(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests", {}, io.BytesIO(b'{"error":"rate limited"}'))
    monkeypatch.setattr(M.urllib.request, "urlopen", fake_open)
    r = M.call("Q?", "SYS", None, "low", tmp_path / "STOP", transport="proxy")
    assert r["stop"] == "quota_stop" and (tmp_path / "STOP").exists()


def test_proxy_disabled_by_default(monkeypatch, tmp_path):
    from pilot import minimax as M
    monkeypatch.delenv("PV_MINIMAX_PROXY_TOS_OK", raising=False)
    def boom(*a, **k): raise AssertionError("network must not be touched")
    monkeypatch.setattr(M.urllib.request, "urlopen", boom)
    with pytest.raises(PermissionError):
        M.call("Q?", "SYS", None, "low", tmp_path / "STOP", transport="proxy")


def test_unknown_transport_rejected(tmp_path):
    from pilot import minimax as M
    with pytest.raises(ValueError):
        M.call("Q?", "SYS", None, "low", tmp_path / "STOP", transport="nope")


def test_llm_answerer_minimax_routes_and_memo_namespace(monkeypatch, tmp_path):
    from pilot import llm as L, minimax as M
    calls = []
    def fake_call(prompt, system, schema, effort, stop_file, stop_at=0.0, transport=None):
        calls.append((prompt, system, effort))
        return {"rc": 0, "stop": "completed", "text": "an answer", "usage": {}, "latency_s": 0.1,
                "model_reported": "minimax/MiniMax-M3.1-Flash", "route": "minimax-mcode-cli-v1"}
    monkeypatch.setattr(M, "call", fake_call)
    llm = L.LLM(tmp_path / "calls", answerer="minimax", stop_file=tmp_path / "STOP")
    r = llm.call("answer", "P1")
    assert r["ok"] and r["model_requested"] == "MiniMax-M3.1-Flash" and calls == [("P1", L.SYSTEM, "low")]
    r2 = llm.call("answer", "P1")          # memo hit, no second call
    assert r2["memo_hit"] and len(calls) == 1
    key = L.sha(json.dumps(["call-v2-minimax", M.TRANSPORT, "answer", "MiniMax-M3.1-Flash", "low", L.SYSTEM, "", "P1"]))
    assert (tmp_path / "calls" / "memo" / f"{key}.json").exists()
    row = json.loads((tmp_path / "calls" / "calls.jsonl").read_text().splitlines()[0]) if (tmp_path / "calls" / "calls.jsonl").exists() else None
    if row:
        assert row["route"] == "minimax-mcode-cli-v1"


def test_llm_grok_and_astra_paths_unchanged(monkeypatch, tmp_path):
    from pilot import llm as L
    with pytest.raises(ValueError):
        L.LLM(tmp_path / "c", answerer="other")
    seen = []
    g = L.LLM(tmp_path / "g")
    monkeypatch.setattr(g, "_grok", lambda p, m, s: seen.append("grok") or {"rc": 0, "stop": "end_turn", "text": "x"})
    monkeypatch.setattr(g, "_minimax", lambda p, s: seen.append("minimax") or {})
    g.call("answer", "P")
    a = L.LLM(tmp_path / "a", answerer="astra", stop_file=tmp_path / "STOP")
    monkeypatch.setattr(a, "_astra", lambda p, s: seen.append("astra") or {"rc": 0, "stop": "completed", "text": "x"})
    monkeypatch.setattr(a, "_minimax", lambda p, s: seen.append("minimax") or {})
    a.call("answer", "P")
    assert seen == ["grok", "astra"]


def test_run2_refuses_pilot3_labels_for_minimax(monkeypatch):
    import sys
    from pilot2 import run2
    for label in ("PILOT3", "PILOT3-ASTRA", "PILOT3-MINIMAX"):
        monkeypatch.setattr(sys, "argv", ["run2", "--label", label, "--answerer", "minimax", "--fake"])
        with pytest.raises(SystemExit) as e:
            run2.main()
        assert "must not write into runs/PILOT3" in str(e.value)
