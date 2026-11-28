"""Tests for ScheduledEvent-driven Discord event and radio jingle automation."""

from datetime import UTC, datetime, timedelta

import pytest

from amc_peripheral.bot import backend_db, event_sync_cog
from amc_peripheral.db import RadioDB
from amc_peripheral.radio import radio_cog


def test_marker_round_trip():
    assert event_sync_cog.marker_for(79) == "AMC-SE-79"
    assert event_sync_cog.managed_se_id("Event\n\nAMC-SE-79") == 79
    assert event_sync_cog.managed_se_id("No marker here") is None


def test_description_has_marker_on_own_line():
    desc = event_sync_cog.description_for({"id": 79, "name": "AMC Duro 290 - Aewol Big"})
    assert desc.endswith("\n\nAMC-SE-79")


def test_event_drifted():
    start = datetime(2026, 11, 28, 12, tzinfo=UTC)
    row = {
        "id": 79,
        "name": "AMC Duro 290 - Aewol Big",
        "start_time": start,
        "end_time": start + timedelta(hours=3),
    }

    class FakeEvent:
        name = row["name"]
        description = event_sync_cog.description_for(row)
        start_time = start
        end_time = start + timedelta(hours=3)

    assert event_sync_cog.event_drifted(FakeEvent(), row) is False
    FakeEvent.name = "Renamed"
    assert event_sync_cog.event_drifted(FakeEvent(), row) is True


def test_jingle_script_uses_local_time_and_no_markdown():
    start = datetime(2026, 11, 28, 12, tzinfo=UTC)
    script = radio_cog.build_event_jingle_script("AMC Duro 290 - Aewol Big", start)
    assert "Saturday at 7 PM" in script
    assert "AMC Duro 290 - Aewol Big" in script
    assert "*" not in script and "#" not in script


def test_fetch_scheduled_events_uses_readonly_connection(monkeypatch):
    class FakeCursor:
        def execute(self, sql):
            assert "amc_scheduledevent" in sql

        def fetchall(self):
            return [(79, "AMC Duro 290 - Aewol Big", "Full description", "start", "end")]

    class FakeConn:
        def cursor(self):
            return FakeCursor()

        def close(self):
            pass

    monkeypatch.setattr(backend_db, "_get_connection", lambda: FakeConn())
    rows = backend_db.fetch_scheduled_events()
    assert rows == [
        {
            "id": 79,
            "name": "AMC Duro 290 - Aewol Big",
            "description": "Full description",
            "start_time": "start",
            "end_time": "end",
        }
    ]


def test_description_for_uses_django_description_and_caps_length():
    row = {"id": 79, "name": "Ignored", "description": "A" * 1200}
    desc = event_sync_cog.description_for(row)
    assert len(desc) == 1000
    assert desc.startswith("A" * 989)
    assert desc.endswith("\n\nAMC-SE-79")


@pytest.mark.asyncio
async def test_event_jingle_install_dedupe_and_removal(monkeypatch, tmp_path):
    jingle_dir = tmp_path / "jingles"
    db = RadioDB(str(tmp_path / "radio.db"))

    cog = radio_cog.RadioCog.__new__(radio_cog.RadioCog)
    cog.db = db

    start = datetime.now(UTC) + timedelta(days=1)
    rows = [
        {
            "id": 79,
            "name": "AMC Duro 290 - Aewol Big",
            "start_time": start,
            "end_time": start + timedelta(hours=3),
        }
    ]
    monkeypatch.setattr(radio_cog, "fetch_scheduled_events", lambda: rows)
    monkeypatch.setattr(radio_cog, "tts_dispatch", lambda *a, **kw: b"audio")
    monkeypatch.setattr(radio_cog, "JINGLES_PATH", str(jingle_dir))

    await cog.sync_event_jingles.coro(cog)
    assert (jingle_dir / "AMC-SE-79.mp3").read_bytes() == b"audio"
    assert len(list(db.db["generated_jingles"].rows_where("audio_filename = ?", ["AMC-SE-79.mp3"]))) == 1

    await cog.sync_event_jingles.coro(cog)
    assert len(list(db.db["generated_jingles"].rows_where("audio_filename = ?", ["AMC-SE-79.mp3"]))) == 1

    monkeypatch.setattr(radio_cog, "fetch_scheduled_events", list)
    await cog.sync_event_jingles.coro(cog)
    assert not (jingle_dir / "AMC-SE-79.mp3").exists()
    assert len(list(db.db["generated_jingles"].rows_where("audio_filename = ?", ["AMC-SE-79.mp3"]))) == 0
