"""Int64 fixed-point additive store (v1.2 §2.1 A6), input-set-keyed summary cache, SQLite persistence.

Vectors are L2-normalised float64 then quantised to int64 at SCALE = 2**30. A node holds the exact int64 sum and the
member count, so remove(x) after add(x) restores the node bit-exactly (T1) and subtraction == rebuild from the
survivors (T1/KC1(a)). Routing = argmax over k = 16 frozen anchors (ties -> lowest index)."""
from __future__ import annotations
import json, sqlite3, threading
from pathlib import Path
import numpy as np
from .common import sha

SCALE = 2 ** 30


def quantize(v) -> np.ndarray:
    x = np.asarray(v, dtype=np.float64)
    x = x / np.linalg.norm(x)
    return np.round(x * SCALE).astype(np.int64)


class Additive:
    def __init__(self, anchors: np.ndarray):
        a = np.asarray(anchors, dtype=np.float64)
        self.anchors = a / np.linalg.norm(a, axis=1, keepdims=True)
        self.k = len(a)
        self.dim = a.shape[1]
        self.sum = np.zeros((self.k, self.dim), dtype=np.int64)
        self.count = np.zeros(self.k, dtype=np.int64)
        self.members: list[set[str]] = [set() for _ in range(self.k)]
        self.inserts = np.zeros(self.k, dtype=np.int64)     # A6m refresh trigger (deletion never touches it)
        self.where: dict[str, int] = {}

    def route(self, q: np.ndarray) -> int:
        return int(np.argmax(self.anchors @ (q.astype(np.float64) / SCALE)))

    def add(self, uid: str, q: np.ndarray) -> int:
        assert uid not in self.where, uid
        n = self.route(q)
        self.sum[n] += q; self.count[n] += 1; self.members[n].add(uid); self.inserts[n] += 1
        self.where[uid] = n
        return n

    def remove(self, uid: str, q: np.ndarray) -> int:
        n = self.where.pop(uid)
        self.sum[n] -= q; self.count[n] -= 1; self.members[n].discard(uid)
        return n

    def centroid(self, n: int) -> np.ndarray:
        if self.count[n] == 0:
            return np.zeros(self.dim)
        c = self.sum[n].astype(np.float64) / float(self.count[n])
        nn = np.linalg.norm(c)
        return c / nn if nn else c

    def node_digest(self, n: int) -> str:
        return sha(self.sum[n].astype("<i8").tobytes() + int(self.count[n]).to_bytes(8, "little") +
                   json.dumps(sorted(self.members[n])).encode())

    def digest(self) -> str:
        return sha("".join(self.node_digest(n) for n in range(self.k)))

    @classmethod
    def rebuild(cls, anchors, units: dict[str, np.ndarray]) -> "Additive":
        a = cls(anchors)
        for uid in sorted(units):
            a.add(uid, units[uid])
        return a


def input_set_hash(ids) -> str:
    return sha("\n".join(sorted(ids)))


def cache_key(ish: str, prompt_sha: str, model_id: str) -> str:
    return sha(ish + "|" + prompt_sha + "|" + model_id)


class DB:
    """Per arm-world SQLite: secure_delete=ON, WAL, write-through. close_for_scan() checkpoints(TRUNCATE) and closes
    (mirrors Eng a4_store L266-300) before a byte-level residue scan."""

    def __init__(self, path: Path):
        self.path = Path(path); self.path.parent.mkdir(parents=True, exist_ok=True)
        for suf in ("", "-wal", "-shm"):
            p = Path(str(self.path) + suf)
            if p.exists():                                  # v1.3 F03: never destroy an existing store
                raise FileExistsError(f"Existing store {p}; preserve it and use a fresh run label")
        self.lock = threading.Lock()
        self.c = sqlite3.connect(str(self.path), check_same_thread=False, isolation_level=None)
        self.c.execute("PRAGMA secure_delete=ON"); self.c.execute("PRAGMA journal_mode=WAL")
        self.c.execute("CREATE TABLE obj(kind TEXT, id TEXT, body TEXT, PRIMARY KEY(kind,id))")

    def put(self, kind, oid, body: dict):
        with self.lock:
            self.c.execute("INSERT OR REPLACE INTO obj VALUES(?,?,?)", (kind, oid, json.dumps(body, ensure_ascii=False)))

    def delete(self, kind, oid):
        with self.lock:
            self.c.execute("DELETE FROM obj WHERE kind=? AND id=?", (kind, oid))

    def checkpoint(self):
        with self.lock:
            self.c.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    def close_for_scan(self):
        with self.lock:
            if self.c is not None:
                self.c.execute("PRAGMA wal_checkpoint(TRUNCATE)"); self.c.close(); self.c = None

    def files(self):
        return [p for p in (self.path, Path(str(self.path) + "-wal"), Path(str(self.path) + "-shm")) if p.exists()]
