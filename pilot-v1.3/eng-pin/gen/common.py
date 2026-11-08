"""Shared helpers for the currency-v0 generator (stdlib only).

Everything here is deterministic: no wall clock, no environment reads, no hash
randomisation (we never iterate over a ``set`` without sorting it first).
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

GENERATOR_VERSION = "currency-v0-gen 0.1.0"
PREREG_SHA256 = "3ef9010676fcfae9415121458d283cb7809e46e241a77b6fd35a8dfc2c909e66"  # PREREG v1.1 (v1 was 4af90303…37564d)
PREREG_FILE = "PREREG-currency-v1.1.md"

# Simulated calendar. Fixed (seed-independent) so that timestamps are comparable
# across streams; the year is deliberately in the future so it can never collide
# with real operator dates.
T0 = datetime(2030, 1, 7, tzinfo=timezone.utc)
N_SESSIONS = 60
HORIZON_DAYS = 90
TARGET_STREAM_TOKENS = 80_000


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def add_minutes(s: str, minutes: int) -> str:
    return iso(parse_iso(s) + timedelta(minutes=minutes))


def canon(obj) -> str:
    """Canonical JSON: sorted keys, no spaces, UTF-8 preserved."""
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def digest(obj) -> str:
    return hashlib.sha256(canon(obj).encode("utf-8")).hexdigest()


def sha256_file(path: os.PathLike | str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def sub_seed(seed: int, *parts: object) -> int:
    """Derive an independent, stable integer seed from (seed, parts)."""
    raw = "|".join([str(seed)] + [str(p) for p in parts]).encode("utf-8")
    return int.from_bytes(hashlib.sha256(raw).digest()[:8], "big")


def write_text(path: os.PathLike | str, text: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def write_json(path: os.PathLike | str, obj) -> None:
    write_text(path, json.dumps(obj, sort_keys=True, ensure_ascii=False, indent=1) + "\n")


def write_jsonl(path: os.PathLike | str, rows) -> None:
    write_text(path, "".join(canon(r) + "\n" for r in rows))


def read_jsonl(path: os.PathLike | str) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def read_json(path: os.PathLike | str):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def est_tokens(text: str) -> int:
    """Generator-side token estimate (chars/4, rounded up).

    Used only to size streams ("about 80k tokens") and to measure the
    DISTRACTOR token share. It is NOT the budget tokenizer: budget enforcement
    (M2) uses the answerer's reported usage per prereg §4.
    """
    return (len(text) + 3) // 4


def session_id(i: int) -> str:
    return f"s{i:02d}"


def session_start(i: int, hour: int, minute: int) -> str:
    day = (i * HORIZON_DAYS) // N_SESSIONS  # strictly increasing for 60 sessions / 90 days
    return iso(T0 + timedelta(days=day, hours=hour, minutes=minute))


def manifest_files(out_dir: Path, exclude: tuple[str, ...] = ("MANIFEST.json",)) -> dict[str, str]:
    files = {}
    for p in sorted(out_dir.rglob("*")):
        if p.is_file():
            rel = p.relative_to(out_dir).as_posix()
            if rel in exclude:
                continue
            files[rel] = sha256_file(p)
    return files
