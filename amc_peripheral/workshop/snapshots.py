"""Snapshot cache keys, queue state and artifact bookkeeping."""

from __future__ import annotations

import hashlib
import sqlite3
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

RENDERER_VERSION = "viewer-21"
PRIORITY_POPULAR = -10
PRIORITY_VISIBLE = 50
PRIORITY_DIRECT = 100
SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshot_jobs (
    cache_key TEXT PRIMARY KEY,
    source_kind TEXT NOT NULL,
    source_id INTEGER NOT NULL,
    config_hash TEXT NOT NULL,
    asset_version TEXT NOT NULL,
    renderer_version TEXT NOT NULL,
    camera TEXT NOT NULL,
    status TEXT NOT NULL,
    priority INTEGER NOT NULL DEFAULT 0,
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt REAL,
    lease_owner TEXT,
    lease_until REAL,
    artifact_path TEXT,
    width INTEGER,
    height INTEGER,
    bytes INTEGER,
    sha256 TEXT,
    error_code TEXT,
    error_message TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_snapshot_ready
    ON snapshot_jobs(source_kind, source_id, config_hash, status);
CREATE INDEX IF NOT EXISTS ix_snapshot_due
    ON snapshot_jobs(status, next_attempt, priority, created_at);
CREATE TABLE IF NOT EXISTS snapshot_worker_heartbeat (
    worker_id TEXT PRIMARY KEY,
    updated_at REAL NOT NULL
);
"""


def render_key(
    *,
    source_kind: str,
    source_id: int,
    config_hash: str,
    asset_version: str,
    camera: str = "default",
    renderer_version: str = RENDERER_VERSION,
) -> str:
    body = "|".join(
        (
            "v1",
            source_kind,
            str(int(source_id)),
            config_hash,
            asset_version,
            renderer_version,
            camera,
        )
    )
    return hashlib.sha256(body.encode()).hexdigest()


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_schema(path: Path) -> None:
    with connect(path) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(SCHEMA)


@dataclass(frozen=True)
class SnapshotJob:
    cache_key: str
    source_kind: str
    source_id: int
    config_hash: str
    asset_version: str
    camera: str
    priority: int = 0

    def as_fields(self) -> dict[str, Any]:
        return asdict(self)


class SnapshotStore:
    def __init__(self, site_db: Path):
        self.site_db = site_db
        self._initialized = False
        self._init_lock = threading.Lock()

    def _conn(self) -> sqlite3.Connection:
        if not self._initialized:
            with self._init_lock:
                if not self._initialized:
                    ensure_schema(self.site_db)
                    self._initialized = True
        return connect(self.site_db)

    def enqueue(self, job: SnapshotJob) -> dict[str, Any]:
        now = time.time()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO snapshot_jobs
                  (cache_key,source_kind,source_id,config_hash,asset_version,
                   renderer_version,camera,status,priority,next_attempt,
                   created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,'pending',?,?,?,?)
                ON CONFLICT(cache_key) DO UPDATE SET
                  priority=MAX(snapshot_jobs.priority,excluded.priority),
                  next_attempt=CASE
                    WHEN excluded.priority>snapshot_jobs.priority THEN excluded.next_attempt
                    ELSE snapshot_jobs.next_attempt END,
                  updated_at=excluded.updated_at
                WHERE snapshot_jobs.status IN ('pending','retry_pending')
                """,
                (
                    job.cache_key,
                    job.source_kind,
                    job.source_id,
                    job.config_hash,
                    job.asset_version,
                    RENDERER_VERSION,
                    job.camera,
                    job.priority,
                    now,
                    now,
                    now,
                ),
            )
        return self.status(job.cache_key) or {"status": "pending"}

    def status(self, cache_key: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM snapshot_jobs WHERE cache_key=?", (cache_key,)
            ).fetchone()
        if not row:
            return None
        return self._public(row, include_error=True)

    def queue_depth(self) -> int:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM snapshot_jobs "
                "WHERE status IN ('pending','retry_pending','rendering')"
            ).fetchone()
        return int(row["n"] if row else 0)

    def statuses(self, cache_keys: list[str]) -> dict[str, dict[str, Any]]:
        if not cache_keys:
            return {}
        marks = ",".join("?" for _ in cache_keys)
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM snapshot_jobs WHERE cache_key IN ({marks})",
                tuple(cache_keys),
            ).fetchall()
        return {row["cache_key"]: self._public(row) for row in rows}

    def heartbeat(self, worker_id: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO snapshot_worker_heartbeat(worker_id,updated_at) "
                "VALUES(?,?) ON CONFLICT(worker_id) DO UPDATE SET updated_at=excluded.updated_at",
                (worker_id, time.time()),
            )

    def health(self) -> dict[str, Any]:
        now = time.time()
        with self._conn() as conn:
            counts = {
                row["status"]: int(row["n"])
                for row in conn.execute(
                    "SELECT status, COUNT(*) AS n FROM snapshot_jobs GROUP BY status"
                )
            }
            oldest = conn.execute(
                "SELECT MIN(created_at) AS at FROM snapshot_jobs "
                "WHERE status IN ('pending','retry_pending')"
            ).fetchone()
            heartbeat = conn.execute(
                "SELECT MAX(updated_at) AS at FROM snapshot_worker_heartbeat"
            ).fetchone()
            ready = conn.execute(
                "SELECT COALESCE(SUM(bytes),0) AS bytes FROM snapshot_jobs "
                "WHERE status='ready'"
            ).fetchone()
        depth = sum(
            counts.get(status, 0)
            for status in ("pending", "retry_pending", "rendering")
        )
        return {
            "queueDepth": depth,
            "oldestQueuedSeconds": (
                round(now - float(oldest["at"]), 1) if oldest and oldest["at"] else None
            ),
            "workerHeartbeatAgeSeconds": (
                round(now - float(heartbeat["at"]), 1)
                if heartbeat and heartbeat["at"]
                else None
            ),
            "artifactBytes": int(ready["bytes"] if ready else 0),
            "statusCounts": counts,
        }

    def ready_map(
        self, source_kind: str, pairs: list[tuple[int, str]]
    ) -> dict[int, dict[str, Any]]:
        if not pairs:
            return {}
        found: dict[int, dict[str, Any]] = {}
        with self._conn() as conn:
            for source_id, config_hash in pairs:
                row = conn.execute(
                    "SELECT * FROM snapshot_jobs WHERE source_kind=? "
                    "AND source_id=? AND config_hash=? AND status='ready' "
                    "ORDER BY updated_at DESC LIMIT 1",
                    (source_kind, source_id, config_hash),
                ).fetchone()
                if row:
                    found[source_id] = self._public(row)
        return found

    def claim(self, owner: str, lease_seconds: float) -> sqlite3.Row | None:
        now = time.time()
        with self._conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "UPDATE snapshot_jobs SET status='pending', lease_owner=NULL, "
                "lease_until=NULL, updated_at=? "
                "WHERE status='rendering' AND lease_until < ?",
                (now, now),
            )
            row = conn.execute(
                """
                SELECT * FROM snapshot_jobs
                WHERE status IN ('pending','retry_pending')
                  AND (next_attempt IS NULL OR next_attempt <= ?)
                ORDER BY priority DESC, created_at ASC LIMIT 1
                """,
                (now,),
            ).fetchone()
            if row is None:
                conn.commit()
                return None
            conn.execute(
                "UPDATE snapshot_jobs SET status='rendering', lease_owner=?, "
                "lease_until=?, updated_at=? WHERE cache_key=?",
                (owner, now + lease_seconds, now, row["cache_key"]),
            )
            claimed = conn.execute(
                "SELECT * FROM snapshot_jobs WHERE cache_key=?",
                (row["cache_key"],),
            ).fetchone()
            conn.commit()
        return claimed

    def complete(
        self,
        cache_key: str,
        *,
        artifact_path: str,
        width: int,
        height: int,
        size: int,
        sha256: str,
    ) -> None:
        now = time.time()
        with self._conn() as conn:
            conn.execute(
                "UPDATE snapshot_jobs SET status='ready', artifact_path=?, "
                "width=?, height=?, bytes=?, sha256=?, lease_owner=NULL, "
                "lease_until=NULL, error_code=NULL, error_message=NULL, "
                "updated_at=? WHERE cache_key=?",
                (
                    artifact_path,
                    width,
                    height,
                    size,
                    sha256,
                    now,
                    cache_key,
                ),
            )

    def fail(
        self,
        cache_key: str,
        *,
        code: str,
        message: str,
        permanent: bool,
        max_attempts: int = 3,
    ) -> None:
        now = time.time()
        with self._conn() as conn:
            row = conn.execute(
                "SELECT attempts FROM snapshot_jobs WHERE cache_key=?",
                (cache_key,),
            ).fetchone()
            attempts = int(row["attempts"] or 0) + 1 if row else 1
            if permanent or attempts >= max_attempts:
                status = "unsupported" if permanent else "failed_permanent"
                next_attempt = None
            else:
                status = "retry_pending"
                next_attempt = now + min(300, 15 * (2 ** (attempts - 1)))
            conn.execute(
                "UPDATE snapshot_jobs SET status=?, attempts=?, next_attempt=?, "
                "lease_owner=NULL, lease_until=NULL, error_code=?, "
                "error_message=?, updated_at=? WHERE cache_key=?",
                (status, attempts, next_attempt, code, message[:300], now,
                 cache_key),
            )

    def supersede_missing(self, live_keys: set[str]) -> int:
        """Retire ready artifacts whose source/config no longer exists."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT cache_key FROM snapshot_jobs WHERE status='ready'"
            ).fetchall()
            stale = [row["cache_key"] for row in rows if row["cache_key"] not in live_keys]
            for key in stale:
                conn.execute(
                    "UPDATE snapshot_jobs SET status='superseded', updated_at=? "
                    "WHERE cache_key=?",
                    (time.time(), key),
                )
        return len(stale)

    @staticmethod
    def _public(row: sqlite3.Row, *, include_error: bool = True) -> dict[str, Any]:
        value = {
            "key": row["cache_key"],
            "status": row["status"],
            "sourceKind": row["source_kind"],
            "sourceId": row["source_id"],
            "configHash": row["config_hash"],
            "priority": row["priority"],
            "width": row["width"],
            "height": row["height"],
            "bytes": row["bytes"],
            "sha256": row["sha256"],
            "url": (
                f"/workshop/snapshots/{row['artifact_path']}"
                if row["status"] == "ready" and row["artifact_path"]
                else None
            ),
        }
        if include_error:
            value["error"] = (
                {"code": row["error_code"], "message": row["error_message"]}
                if row["error_code"]
                else None
            )
        return value
