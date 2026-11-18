"""Tests for the workshop source-database sync (no network access)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from amc_peripheral.workshop import sync
from amc_peripheral.workshop.config import WorkshopSettings


def _row(entry_id: int, payload: dict | None = None, **extra) -> dict:
    body = payload if payload is not None else {"bHasPaint": True, "bHasDecal": False}
    row = {
        "id": entry_id,
        "account_id": 42,
        "character_guid": "A" * 32,
        "created_at": "2026-01-02 03:04:05",
        "category": "Garage",
        "vehicle_key": "Tuscan",
        "json_data": json.dumps(body),
        "author_name": "Tester",
        "votes": 3,
        "reports": 0,
        "installed": 7,
        "hidden": 0,
        "hot": -1.5,
        "duplicate_key": f"v1:{entry_id}",
    }
    row.update(extra)
    return row


@pytest.fixture()
def store(tmp_path: Path) -> tuple[sync.SyncStore, sqlite3.Connection]:
    settings = WorkshopSettings(
        source_db=tmp_path / "source.db",
        site_db=tmp_path / "site.db",
        viewer_root=tmp_path,
        snapshot_root=tmp_path,
    )
    sync_store = sync.SyncStore(settings.source_db)
    return sync_store, sync_store.connect()


def test_decode_payload_flattens_paint_and_decals() -> None:
    payload = {
        "bHasPaint": True,
        "bHasDecal": True,
        "bHasParts": True,
        "bHasTunings": False,
        "paint": {
            "bodyColors": [
                {
                    "materialSlotName": "Body_01",
                    "color": {"r": 255, "g": 0, "b": 16, "a": 255},
                    "metallic": 1,
                    "roughness": 0,
                }
            ]
        },
        "decal": {
            "decal": {
                "decalLayers": [
                    {"decalKey": "Flame_01", "position": {"x": 1, "y": 2}},
                    {"decalKey": "Ring_02"},
                ]
            }
        },
        "parts": {"parts": [{"slot": "Engine", "key": "H2_30HP"}]},
        "workshopTags": ["race"],
    }

    decoded = sync.decode_payload(json.dumps(payload))

    assert decoded["has_paint"] == 1
    assert decoded["has_tunings"] == 0
    assert decoded["decal_layers"] == 2
    assert decoded["part_count"] == 1
    assert json.loads(decoded["paint_slots"])[0]["rgba"] == "#ff0010ff"
    assert decoded["parts"] == [("Engine", "H2_30HP")]
    assert json.loads(decoded["tags"]) == ["race"]


def test_decode_payload_rejects_non_object() -> None:
    with pytest.raises(ValueError):
        sync.decode_payload("[]")


def test_upsert_is_idempotent_and_refreshes_counters(store) -> None:
    sync_store, connection = store
    run = sync_store.start_run(connection, "test")

    first = sync_store.upsert_rows(connection, "Tuscan", [_row(1)], run)
    assert first == {"inserted": 1, "updated": 0, "unchanged": 0, "quarantined": 0}

    # Same payload, moved counters: no revision bump, but the counters refresh.
    again = sync_store.upsert_rows(
        connection, "Tuscan", [_row(1, installed=99, votes=8)], run
    )
    assert again["unchanged"] == 1
    installed, votes, revision = connection.execute(
        "SELECT installed, votes, revision FROM workshop WHERE id=1"
    ).fetchone()
    assert (installed, votes, revision) == (99, 8, 1)


def test_upsert_bumps_revision_on_edit(store) -> None:
    sync_store, connection = store
    run = sync_store.start_run(connection, "test")
    sync_store.upsert_rows(connection, "Tuscan", [_row(2)], run)

    changed = {"bHasPaint": True, "bHasDecal": True}
    stats = sync_store.upsert_rows(connection, "Tuscan", [_row(2, changed)], run)

    assert stats["updated"] == 1
    assert (
        connection.execute("SELECT revision FROM workshop WHERE id=2").fetchone()[0]
        == 2
    )
    assert len(sync_store_stats(connection)) == 1


def sync_store_stats(connection: sqlite3.Connection) -> list:
    return connection.execute(
        "SELECT id FROM workshop WHERE json_sha256 <> '' AND deleted_at IS NULL"
    ).fetchall()


def test_malformed_payload_is_quarantined(store) -> None:
    sync_store, connection = store
    run = sync_store.start_run(connection, "test")

    bad = _row(3, json_data="{truncated")
    stats = sync_store.upsert_rows(connection, "Tuscan", [bad], run)

    assert stats["quarantined"] == 1
    assert connection.execute("SELECT COUNT(*) FROM workshop").fetchone()[0] == 0
    assert connection.execute("SELECT COUNT(*) FROM quarantine").fetchone()[0] == 1

    # A repeated sync of the same malformed row must not re-count it.
    assert sync_store.upsert_rows(connection, "Tuscan", [bad], run)["quarantined"] == 0


def test_tombstone_is_scoped_to_the_keys_read(store) -> None:
    sync_store, connection = store
    run = sync_store.start_run(connection, "test")
    sync_store.upsert_rows(connection, "Tuscan", [_row(10), _row(11)], run)
    sync_store.upsert_rows(connection, "Ambi", [_row(12)], run)

    deleted = sync_store.tombstone_missing(connection, {10}, run, ["Tuscan"])

    assert deleted == 1
    live = dict(
        connection.execute(
            "SELECT id, vehicle_key FROM workshop WHERE deleted_at IS NULL"
        ).fetchall()
    )
    assert live == {10: "Tuscan", 12: "Ambi"}


def _settings(tmp_path: Path) -> WorkshopSettings:
    return WorkshopSettings(
        source_db=tmp_path / "source.db",
        site_db=tmp_path / "site.db",
        viewer_root=tmp_path,
        snapshot_root=tmp_path,
    )


def test_delta_probe_skips_keys_with_no_new_ids(tmp_path, monkeypatch) -> None:
    """A key whose probe window is entirely at or below the watermark costs no write."""
    settings = _settings(tmp_path)
    store = sync.SyncStore(settings.source_db)
    connection = store.connect()
    run = store.start_run(connection, "seed")
    store.upsert_rows(connection, "Tuscan", [_row(1), _row(2)], run)
    store.set_watermark(connection, "Tuscan", 2)
    connection.close()

    calls = []

    def fake_fetch(vehicle_key, count, timeout=300):
        calls.append((vehicle_key, count))
        return {"workshops": [_row(2), _row(1)]}

    monkeypatch.setattr(sync, "fetch", fake_fetch)
    monkeypatch.setattr(sync, "REQUEST_DELAY", 0)

    stats = sync.sync(settings, mode="delta", keys=["Tuscan"])

    assert stats["keys_skipped"] == 1
    assert stats["new_ids"] == 0
    assert stats["inserted"] == 0
    assert calls == [("Tuscan", sync.PROBE_COUNT)]


def test_delta_writes_only_ids_above_the_watermark(tmp_path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    store = sync.SyncStore(settings.source_db)
    connection = store.connect()
    run = store.start_run(connection, "seed")
    store.upsert_rows(connection, "Tuscan", [_row(5)], run)
    store.set_watermark(connection, "Tuscan", 5)
    connection.close()

    def fake_fetch(vehicle_key, count, timeout=300):
        # newest first, as the API returns them; 5 is already stored
        return {"workshops": [_row(7), _row(6), _row(5)]}

    monkeypatch.setattr(sync, "fetch", fake_fetch)
    monkeypatch.setattr(sync, "REQUEST_DELAY", 0)

    stats = sync.sync(settings, mode="delta", keys=["Tuscan"])

    assert stats["new_ids"] == 2
    assert stats["inserted"] == 2
    connection = store.connect()
    assert [
        r[0] for r in connection.execute("SELECT id FROM workshop ORDER BY id")
    ] == [5, 6, 7]
    assert store.watermark(connection, "Tuscan") == 7


def test_delta_widens_once_when_the_probe_saturates(tmp_path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    store = sync.SyncStore(settings.source_db)
    connection = store.connect()
    store.set_watermark(connection, "Tuscan", 100)
    connection.close()

    calls = []

    def fake_fetch(vehicle_key, count, timeout=300):
        calls.append(count)
        if count == sync.PROBE_COUNT:
            # every probed row is new -> the window may be truncating the backlog
            return {"workshops": [_row(i) for i in range(300, 300 - count, -1)]}
        return {"workshops": [_row(i) for i in range(300, 100, -1)]}

    monkeypatch.setattr(sync, "fetch", fake_fetch)
    monkeypatch.setattr(sync, "REQUEST_DELAY", 0)

    stats = sync.sync(settings, mode="delta", keys=["Tuscan"])

    assert calls == [sync.PROBE_COUNT, sync.CATCHUP_COUNT]
    assert stats["new_ids"] == 200  # ids 101..300, nothing at or below the watermark
    connection = store.connect()
    assert connection.execute("SELECT COUNT(*) FROM workshop").fetchone()[0] == 200
    assert store.watermark(connection, "Tuscan") == 300
