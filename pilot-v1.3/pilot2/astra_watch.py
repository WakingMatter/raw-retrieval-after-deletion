"""PILOT3-ASTRA watchdog: every 120 s log weekly used_percent (read like queue2.sh: newest astra rollout's 10080-min
primary window) and recent failure rate; write runs/<label>/STOP when used_percent >= cap or >= 30% of the last 40
calls failed. Exits when the run PID is gone."""
import glob, json, os, re, sys, time
from pathlib import Path


def used_pct():
    for f in sorted(glob.glob(os.path.expanduser("~/.codex/sessions/2026/1*/*/rollout-*.jsonl")), key=os.path.getmtime, reverse=True)[:30]:
        s = Path(f).read_text(errors="ignore")
        if '"model":"gpt-6-astra"' not in s:
            continue
        v = re.findall(r'"primary":\{"used_percent":([0-9.]+),"window_minutes":10080', s)
        if v:
            return float(v[-1])
    return None


def main(run_dir, pid, cap):
    run_dir = Path(run_dir); log = run_dir / "WATCHDOG.log"; stop = run_dir / "STOP"
    while True:
        alive = os.system(f"kill -0 {pid} 2>/dev/null") == 0
        rows = []
        if (run_dir / "calls.jsonl").exists():
            rows = [json.loads(l) for l in open(run_dir / "calls.jsonl") if l.strip()]
        real = [r for r in rows if not r.get("memo_hit")]
        recent = real[-40:]
        fail = sum(1 for r in recent if not r.get("ok"))
        u = used_pct()
        msg = (f"{time.strftime('%Y-%m-%d %H:%M:%S IST')} used_pct={u} calls_logged={len(rows)} real={len(real)} "
               f"ok={sum(1 for r in real if r.get('ok'))} recent_fail={fail}/{len(recent)} alive={alive} stop={stop.exists()}")
        with open(log, "a") as f:
            f.write(msg + "\n")
        if not stop.exists():
            if u is not None and u >= cap:
                stop.write_text(f"{msg}\nwatchdog: used_percent {u} >= cap {cap}\n")
            elif len(recent) >= 20 and fail / len(recent) >= 0.3:
                stop.write_text(f"{msg}\nwatchdog: failure rate {fail}/{len(recent)}\n")
        if not alive:
            return
        time.sleep(120)


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]), float(sys.argv[3]))
