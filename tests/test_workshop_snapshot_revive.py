"""A permanently failed job can be revived, but only by opening the item."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from amc_peripheral.workshop.snapshots import (
    PRIORITY_DIRECT,
    PRIORITY_VISIBLE,
    SnapshotJob,
    SnapshotStore,
)

KEY = "r" * 64


def job(priority: int = PRIORITY_VISIBLE) -> SnapshotJob:
    return SnapshotJob(
        cache_key=KEY,
        source_kind="workshop",
        source_id=9,
        config_hash="c" * 64,
        asset_version="manifest-1",
        camera="default",
        priority=priority,
    )


def row(db: Path) -> sqlite3.Row:
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute("SELECT * FROM snapshot_jobs").fetchone()


def exhaust(store: SnapshotStore) -> None:
    """Drive a job into failed_permanent: fail once with max_attempts=1."""
    store.enqueue(job())
    store.claim("worker", 180)
    store.fail(
        KEY,
        code="render_timeout",
        message="page wait timed out",
        permanent=False,
        max_attempts=1,
    )


def test_a_direct_request_revives_a_permanently_failed_job(tmp_path: Path) -> None:
    db = tmp_path / "site.db"
    store = SnapshotStore(db)
    exhaust(store)
    assert row(db)["status"] == "failed_permanent"

    status = store.enqueue(job(PRIORITY_DIRECT))

    assert status["status"] == "pending"
    revived = row(db)
    assert revived["status"] == "pending"
    assert revived["attempts"] == 0, "a revived job gets a fresh retry budget"
    assert revived["error_code"] is None and revived["error_message"] is None
    assert revived["priority"] == PRIORITY_DIRECT
    # And it is claimable again.
    claimed = store.claim("worker", 180)
    assert claimed is not None and claimed["status"] == "rendering"


def test_a_card_thumbnail_does_not_revive_a_failed_job(tmp_path: Path) -> None:
    db = tmp_path / "site.db"
    store = SnapshotStore(db)
    exhaust(store)

    status = store.enqueue(job(PRIORITY_VISIBLE))

    assert status["status"] == "failed_permanent"
    still = row(db)
    assert still["status"] == "failed_permanent"
    assert still["attempts"] == 1, "a card must not reset the retry budget"
    assert store.claim("worker", 180) is None


def test_unsupported_assets_are_never_revived(tmp_path: Path) -> None:
    db = tmp_path / "site.db"
    store = SnapshotStore(db)
    store.enqueue(job())
    store.claim("worker", 180)
    store.fail(KEY, code="unsupported_asset", message="no body mesh", permanent=True)
    assert row(db)["status"] == "unsupported"

    status = store.enqueue(job(PRIORITY_DIRECT))

    assert status["status"] == "unsupported", "a missing mesh will not appear on retry"
    assert store.claim("worker", 180) is None
