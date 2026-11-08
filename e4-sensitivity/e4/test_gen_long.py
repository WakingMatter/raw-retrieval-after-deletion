"""Regression: gen_long at L=1, CHAIN_LEN=1 is byte-identical to the pinned eng-pin generator (3+ seeds)."""
from __future__ import annotations
import filecmp, subprocess, sys, tempfile
from pathlib import Path
from .paths import ENG_PIN

SEEDS = (7280001, 7280005, 7289001)


def tree(d: Path) -> dict:
    return {p.relative_to(d).as_posix(): p.read_bytes() for p in sorted(d.rglob("*")) if p.is_file()}


def check(seed: int) -> tuple[bool, int]:
    with tempfile.TemporaryDirectory() as td:
        a, b = Path(td) / "pin", Path(td) / "long"
        subprocess.run([sys.executable, "-m", "gen.gen_stream", "--seed", str(seed), "--out", str(a)], cwd=ENG_PIN,
                       check=True, capture_output=True)
        subprocess.run([sys.executable, "-m", "e4.gen_long", "--seed", str(seed), "--out", str(b), "--L", "1",
                        "--chain", "1"], cwd=Path(__file__).resolve().parents[1], check=True, capture_output=True,
                       env={"PYTHONDONTWRITEBYTECODE": "1", "PATH": "/usr/bin:/bin"})
        ta, tb = tree(a), tree(b)
        return ta == tb, len(ta)




def check_forked_schedule(seed: int) -> bool:
    """Stronger check: the re-written schedule (make_schedule(1, 1)) itself reproduces eng-pin's ledger."""
    import json
    from . import gen_long as GL
    G = GL.G
    ref = G.build_ledger(seed)
    G.schedule = GL.make_schedule(1, 1)
    try:
        new = G.build_ledger(seed)
    finally:
        GL.configure(1, 1)
    dump = lambda x: json.dumps([x[1], x[2]], sort_keys=True, default=str)  # noqa: E731
    return dump(ref) == dump(new)


if __name__ == "__main__":
    ok = True
    for s in [int(x) for x in sys.argv[1:]] or SEEDS:
        same, n = check(s)
        fork = check_forked_schedule(s)
        print(f"seed={s} files={n} byte_identical={same} forked_schedule_identical={fork}")
        ok &= same and fork
    sys.exit(0 if ok else 1)
