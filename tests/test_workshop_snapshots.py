"""Snapshot queue state-machine tests."""

from __future__ import annotations

import time
from dataclasses import replace
from pathlib import Path
from typing import Any

from amc_peripheral.workshop.snapshots import (
    SnapshotJob,
    SnapshotStore,
    render_key,
)


def job(key="k" * 64, source_id=1, config_hash="c" * 64):
    return SnapshotJob(
        cache_key=key,
        source_kind="workshop",
        source_id=source_id,
        config_hash=config_hash,
        asset_version="manifest-1",
        camera="default",
    )


def test_render_key_is_stable_and_config_specific():
    kwargs: dict[str, Any] = {
        "source_kind": "workshop", "source_id": 1, "config_hash": "a" * 64,
        "asset_version": "manifest-1",
    }
    assert render_key(**kwargs) == render_key(**kwargs)
    assert render_key(**kwargs) != render_key(**{**kwargs, "config_hash": "b" * 64})
    assert render_key(**kwargs) != render_key(**{**kwargs, "asset_version": "manifest-2"})


def test_enqueue_and_claim_are_idempotent(tmp_path: Path):
    store = SnapshotStore(tmp_path / "site.db")
    store.enqueue(job())
    store.enqueue(job())
    claimed = store.claim("worker-a", lease_seconds=60)
    assert claimed["cache_key"] == "k" * 64
    assert claimed["status"] == "rendering"
    assert store.claim("worker-b", lease_seconds=60) is None


def test_page_view_boosts_an_existing_background_job(tmp_path: Path):
    store = SnapshotStore(tmp_path / "site.db")
    store.enqueue(replace(job(), priority=-10))
    store.enqueue(replace(job(), priority=100))
    status = store.status("k" * 64)
    assert status and status["priority"] == 100
    store.enqueue(replace(job(), priority=-10))
    status = store.status("k" * 64)
    assert status and status["priority"] == 100


def test_expired_lease_is_recovered(tmp_path: Path):
    store = SnapshotStore(tmp_path / "site.db")
    store.enqueue(job())
    claimed = store.claim("dead-worker", lease_seconds=0.01)
    assert claimed
    time.sleep(0.05)
    recovered = store.claim("live-worker", lease_seconds=60)
    assert recovered["cache_key"] == "k" * 64
    assert recovered["lease_owner"] == "live-worker"


def test_completion_publishes_a_hashed_url(tmp_path: Path):
    store = SnapshotStore(tmp_path / "site.db")
    store.enqueue(job())
    store.claim("worker", lease_seconds=60)
    store.complete(
        "k" * 64, artifact_path="ab/k.webp", width=960, height=540,
        size=1234, sha256="d" * 64,
    )
    status = store.status("k" * 64)
    assert status["status"] == "ready"
    assert status["url"] == "/workshop/snapshots/ab/k.webp"
    assert status["bytes"] == 1234
    ready = store.ready_map("workshop", [(1, "c" * 64)])
    assert ready[1]["url"].endswith("k.webp")
    assert store.ready_map("workshop", [(1, "e" * 64)]) == {}


def test_transient_failure_retries_then_becomes_permanent(tmp_path: Path):
    store = SnapshotStore(tmp_path / "site.db")
    store.enqueue(job())
    store.claim("worker", lease_seconds=60)
    store.fail("k" * 64, code="timeout", message="slow", permanent=False,
               max_attempts=2)
    status = store.status("k" * 64)
    assert status["status"] == "retry_pending"
    assert status["error"]["code"] == "timeout"

    # Make it due immediately so the claim does not depend on the retry delay.
    import sqlite3

    with sqlite3.connect(tmp_path / "site.db") as conn:
        conn.execute("UPDATE snapshot_jobs SET next_attempt=0")
    store.claim("worker", lease_seconds=60)
    store.fail("k" * 64, code="timeout", message="slow", permanent=False,
               max_attempts=2)
    assert store.status("k" * 64)["status"] == "failed_permanent"


def test_deterministic_unsupported_never_retries(tmp_path: Path):
    store = SnapshotStore(tmp_path / "site.db")
    store.enqueue(job())
    store.claim("worker", lease_seconds=60)
    store.fail("k" * 64, code="unsupported", message="bad config", permanent=True)
    assert store.status("k" * 64)["status"] == "unsupported"


def test_supersede_retires_only_missing_keys(tmp_path: Path):
    store = SnapshotStore(tmp_path / "site.db")
    for index, key in enumerate(("a" * 64, "b" * 64)):
        store.enqueue(job(key=key, source_id=index + 1))
        store.claim("worker", lease_seconds=60)
        store.complete(key, artifact_path=f"x/{key}.webp", width=1, height=1,
                       size=1, sha256="s" * 64)
    assert store.supersede_missing({"a" * 64}) == 1
    assert store.status("a" * 64)["status"] == "ready"
    assert store.status("b" * 64)["status"] == "superseded"
