"""Queue idempotency: many visitors asking for the same item at once."""

from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path

from amc_peripheral.workshop.snapshots import (
    PRIORITY_DIRECT,
    PRIORITY_POPULAR,
    PRIORITY_VISIBLE,
    SnapshotJob,
    SnapshotStore,
    render_key,
)

KEY = "k" * 64


def job(priority: int = PRIORITY_POPULAR) -> SnapshotJob:
    return SnapshotJob(
        cache_key=KEY,
        source_kind="workshop",
        source_id=7,
        config_hash="c" * 64,
        asset_version="manifest-1",
        camera="default",
        priority=priority,
    )


def _rows(db: Path) -> list[sqlite3.Row]:
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute("SELECT * FROM snapshot_jobs").fetchall()


def test_concurrent_visitors_create_exactly_one_job(tmp_path: Path) -> None:
    store = SnapshotStore(tmp_path / "site.db")
    store.enqueue(job())  # create the schema before the race
    barrier = threading.Barrier(32)
    errors: list[BaseException] = []

    def visitor() -> None:
        try:
            barrier.wait(timeout=10)
            store.enqueue(job(PRIORITY_VISIBLE))
        except BaseException as exc:  # noqa: BLE001 - surfaced by the assert below
            errors.append(exc)

    threads = [threading.Thread(target=visitor) for _ in range(32)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert not errors, errors
    rows = _rows(tmp_path / "site.db")
    assert len(rows) == 1
    assert rows[0]["status"] == "pending"
    # A visitor's view raises the background job instead of adding a second one.
    assert rows[0]["priority"] == PRIORITY_VISIBLE


def test_direct_request_wins_over_a_visitor(tmp_path: Path) -> None:
    store = SnapshotStore(tmp_path / "site.db")
    store.enqueue(job(PRIORITY_POPULAR))
    store.enqueue(job(PRIORITY_VISIBLE))
    store.enqueue(job(PRIORITY_DIRECT))

    rows = _rows(tmp_path / "site.db")
    assert len(rows) == 1
    assert rows[0]["priority"] == PRIORITY_DIRECT


def test_enqueue_does_not_disturb_a_job_in_flight(tmp_path: Path) -> None:
    db = tmp_path / "site.db"
    store = SnapshotStore(db)
    store.enqueue(job())

    claimed = store.claim("worker-a", 180)
    assert claimed is not None and claimed["status"] == "rendering"

    # A visitor arrives while the render is running.
    status = store.enqueue(job(PRIORITY_DIRECT))

    assert status["status"] == "rendering"
    assert len(_rows(db)) == 1
    # A second worker must not pick the same row up again.
    assert store.claim("worker-b", 180) is None


def test_enqueue_after_ready_is_a_no_op(tmp_path: Path) -> None:
    db = tmp_path / "site.db"
    store = SnapshotStore(db)
    store.enqueue(job())
    store.claim("worker", 180)
    store.complete(
        KEY,
        artifact_path="items/kk/k.webp",
        width=960,
        height=540,
        size=2048,
        sha256="0" * 64,
    )

    status = store.enqueue(job(PRIORITY_DIRECT))

    assert status["status"] == "ready"
    rows = _rows(db)
    assert len(rows) == 1
    assert rows[0]["artifact_path"] == "items/kk/k.webp"
    assert store.claim("worker", 180) is None, "ready jobs must not be re-rendered"


def test_lease_expiry_requeues_once_not_twice(tmp_path: Path) -> None:
    db = tmp_path / "site.db"
    store = SnapshotStore(db)
    store.enqueue(job())

    claimed = store.claim("worker-a", lease_seconds=0.01)
    assert claimed is not None
    time.sleep(0.05)

    # A stale lease is recovered, but only as the single existing row.
    recovered = store.claim("worker-b", 180)
    assert recovered is not None
    assert recovered["lease_owner"] == "worker-b"
    assert len(_rows(db)) == 1


def test_same_item_different_asset_version_is_a_different_job(tmp_path: Path) -> None:
    db = tmp_path / "site.db"
    store = SnapshotStore(db)
    store.enqueue(job())

    changed = SnapshotJob(
        cache_key=render_key(
            source_kind="workshop",
            source_id=7,
            config_hash="c" * 64,
            asset_version="manifest-2",
        ),
        source_kind="workshop",
        source_id=7,
        config_hash="c" * 64,
        asset_version="manifest-2",
        camera="default",
        priority=PRIORITY_VISIBLE,
    )
    store.enqueue(changed)

    assert len(_rows(db)) == 2, "a re-exported vehicle must render again"
