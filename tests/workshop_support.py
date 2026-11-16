"""Fixtures for the workshop service tests."""

from __future__ import annotations

import json
import sqlite3
import zlib
from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer

from amc_peripheral.workshop.config import WorkshopSettings
from amc_peripheral.workshop.routes import create_app


def _payload(*, extra_layers: int = 0, attachment: str = "Attachment_Light_04",
             attachment_known: bool = True) -> bytes:
    layers = [{
        "decalKey": "Numbers_01_077-76",
        "color": {"r": 255, "g": 0, "b": 0, "a": 255},
        "position": {"x": 20.1108, "y": 57.7052},
        "rotation": {"pitch": 10.0, "yaw": -89.9, "roll": 11.8},
        "decalScale": 0.427,
        "stretch": 2.0,
        "coverage": 0.75,
        "flags": 12,
    }]
    for index in range(extra_layers):
        layers.append({
            "decalKey": f"Extra_{index}",
            "color": {"r": 1, "g": 2, "b": 3, "a": 255},
            "position": {"x": 0, "y": 0},
            "rotation": {"pitch": 0, "yaw": 0, "roll": 0},
            "decalScale": 1,
            "stretch": 1,
            "coverage": 1,
            "flags": 0,
        })
    body = {
        "paint": {
            "bodyMaterialIndex": 0,
            "bodyColors": [{
                "materialSlotName": "Body_01",
                "color": {"r": 18, "g": 24, "b": 30, "a": 255},
                "metallic": 0.3,
                "roughness": 0.5,
            }],
        },
        "decal": {"decal": {"decalLayers": layers}},
        "parts": {"parts": [
            {"key": "DefaultBody", "slot": "Body", "floatValues": {},
             "int64Values": {}, "stringValues": {}, "vectorValues": {}},
            {"key": "DefaultAttachment", "slot": "Attachment0",
             "floatValues": {}, "int64Values": {},
             "stringValues": {"0": attachment, "1": ""},
             "vectorValues": {
                 "0": {"x": 241, "y": 0, "z": 90},
                 "1": {"x": 0, "y": -5, "z": 0},
             }},
        ]},
        "workshopTags": ["drift", "night"],
    }
    if not attachment_known:
        body["parts"]["parts"][1]["stringValues"]["0"] = "Attachment_Unknown"
    return zlib.compress(json.dumps(body).encode())


def build_fixture_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript("""
      CREATE TABLE workshop (
        id INTEGER PRIMARY KEY, vehicle_key TEXT NOT NULL, category TEXT NOT NULL,
        account_id INTEGER NOT NULL, character_guid TEXT NOT NULL,
        created_at TEXT NOT NULL, json_sha256 TEXT NOT NULL, json_len INTEGER NOT NULL,
        json_z BLOB NOT NULL, has_paint INTEGER NOT NULL, has_decal INTEGER NOT NULL,
        has_parts INTEGER NOT NULL, has_tunings INTEGER NOT NULL,
        decal_layers INTEGER NOT NULL, part_count INTEGER NOT NULL,
        paint_slots TEXT, tags TEXT, revision INTEGER NOT NULL,
        first_seen TEXT NOT NULL, last_seen TEXT NOT NULL, deleted_at TEXT,
        author_name TEXT, votes INTEGER, reports INTEGER, installed INTEGER,
        hidden INTEGER, hot REAL, duplicate_key TEXT
      );
      CREATE TABLE club_character (
        character_guid TEXT PRIMARY KEY, steam_id TEXT NOT NULL,
        char_name TEXT, loaded_at TEXT NOT NULL
      );
      CREATE TABLE sync_runs (
        run_id INTEGER PRIMARY KEY, finished_at TEXT
      );
      INSERT INTO sync_runs VALUES (7, '2026-11-16T07:00:00Z');
    """)

    rows = [
        # id 1 is chronologically newest even though a higher id exists. Its
        # installed/votes tuple exercises popular ordering and NULL safety.
        (1, "Vamos3", 11, "g1", "2026-11-15 12:00:00", "a" * 64, 1, 1, 1, 0,
         1, 2, '[{"slot":"Body_01"}]', '["drift","night"]', 3, "Alice", 5, 100, 0),
        # id 2 is older; id DESC would incorrectly put it before... nothing, but
        # id 1 above proves created_at wins over a lower id only with id 9 below.
        (2, "Boxy", 22, "g2", "2024-01-01 00:00:00", "b" * 64, 1, 0, 0, 0,
         0, 0, None, None, 1, "Bob", 1, 5, 0),
        # Equal installed, lower votes than id 1.
        (3, "Vamos3", 11, "g1", "2025-05-01 00:00:00", "c" * 64, 1, 0, 0, 1,
         0, 0, None, '["tuned"]', 2, "Alice", 4, 100, 0),
        # Canary: account_id 0 and epoch garbage.
        (999999999, "Zydro_Police", 0, "canary", "2000-01-01 00:00:00", "d" * 64,
         1, 0, 0, 0, 0, 0, None, None, 0, None, None, None, 0),
        # Hidden/deleted must never appear. Higher created_at and metrics on purpose.
        (5, "Vamos3", 11, "g1", "2027-01-01 00:00:00", "e" * 64, 1, 0, 0, 0,
         0, 0, None, None, 1, "Hidden", 999, 999, 1),
    ]
    for (wid, vehicle, account, guid, created, sha, paint, decal, parts, tuning,
         layers, part_count, paint_slots, tags, revision, author, votes,
         installed, hidden) in rows:
        blob = _payload()
        conn.execute(
            """INSERT INTO workshop (
              id,vehicle_key,category,account_id,character_guid,created_at,
              json_sha256,json_len,json_z,has_paint,has_decal,has_parts,
              has_tunings,decal_layers,part_count,paint_slots,tags,revision,
              first_seen,last_seen,deleted_at,author_name,votes,reports,
              installed,hidden,hot,duplicate_key
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                wid, vehicle, "Garage", account, guid, created, sha, len(blob),
                blob, paint, decal, parts, tuning, layers, part_count,
                paint_slots, tags, revision, "2026-01-01T00:00:00Z",
                "2026-01-01T00:00:00Z", None, author, votes, 0, installed,
                hidden, 0.0, None,
            ),
        )
    conn.execute(
        "INSERT INTO club_character VALUES ('g1','76561198000000000','Alice',"
        "'2026-01-01T00:00:00Z')"
    )
    # A deleted duplicate gets a later timestamp and huge metrics so an accidental
    # missing tombstone predicate is immediately visible in ordering tests.
    row = conn.execute("SELECT * FROM workshop WHERE id = 2").fetchone()
    names = [item[1] for item in conn.execute("PRAGMA table_info(workshop)")]
    duplicate = dict(zip(names, row))
    duplicate.update(id=6, created_at="2027-02-01 00:00:00",
                     deleted_at="2026-02-01", votes=999, installed=999)
    conn.execute(
        f"INSERT INTO workshop ({','.join(names)}) VALUES "
        f"({','.join('?' for _ in names)})",
        [duplicate[name] for name in names],
    )
    # Apply the real migration so plan assertions cannot drift from production.
    migration = (
        Path(__file__).resolve().parents[1]
        / "amc_peripheral" / "workshop" / "schema" / "workshop_indexes.sql"
    )
    conn.executescript(migration.read_text())
    conn.commit()
    conn.close()


@pytest.fixture
def settings(tmp_path: Path) -> WorkshopSettings:
    db = tmp_path / "workshop.db"
    build_fixture_db(db)
    viewer = tmp_path / "viewer"
    (viewer / "attachments").mkdir(parents=True)
    (viewer / "attachments" / "catalog.json").write_text(json.dumps({
        "actors": {"Attachment_Light_04": {"mesh": "LED_04", "components": []}}
    }))
    (viewer / "vamos3").mkdir()
    (viewer / "vamos3" / "vamos3.json").write_text('{"vehicle":"Vamos3"}')
    return WorkshopSettings(
        source_db=db,
        site_db=tmp_path / "site.db",
        viewer_root=viewer,
        snapshot_root=tmp_path / "snapshots",
        page_size=2,
        max_page_size=4,
        home_limit=3,
        cache_ttl_seconds=0,
    )


@pytest.fixture
async def client(settings: WorkshopSettings):
    app = create_app(settings)
    server = TestServer(app)
    client = TestClient(server)
    await client.start_server()
    yield client
    await client.close()
