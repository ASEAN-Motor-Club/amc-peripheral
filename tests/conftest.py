"""Shared workshop test fixtures."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer
from workshop_support import build_fixture_db

from amc_peripheral.workshop.config import WorkshopSettings
from amc_peripheral.workshop.routes import create_app


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
