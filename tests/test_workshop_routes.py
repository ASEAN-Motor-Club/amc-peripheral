"""HTTP and SSR behavior tests."""

from __future__ import annotations

import json

from PIL import Image


async def test_home_page_renders_without_webgl(client):
    response = await client.get("/workshop/")
    assert response.status == 200
    text = await response.text()
    assert "Find your next build" in text
    assert "Popular builds" in text
    assert "Vamos3" in text
    assert "webgl" not in text.lower()
    assert "76561198000000000" not in text


async def test_home_api_excludes_canary_and_exposes_no_steam_ids(client):
    response = await client.get("/api/workshop/home")
    assert response.status == 200
    data = await response.json()
    ids = {item["id"] for item in data["popular"] + data["newest"]}
    assert 999999999 not in ids
    assert 5 not in ids and 6 not in ids
    assert "76561198000000000" not in json.dumps(data)


async def test_gallery_paginates_and_cursor_stays_in_filters(client):
    first = await client.get("/api/workshop/items?sort=popular&limit=1")
    assert first.status == 200
    body = await first.json()
    assert body["items"][0]["id"] == 1
    cursor = body["nextCursor"]
    assert cursor
    second = await client.get(
        "/api/workshop/items", params={"sort": "popular", "limit": 1, "cursor": cursor}
    )
    assert second.status == 200
    assert (await second.json())["items"][0]["id"] == 3
    wrong = await client.get(
        "/api/workshop/items",
        params={"sort": "popular", "limit": 1, "cursor": cursor, "vehicle": "Boxy"},
    )
    assert wrong.status == 400
    assert (await wrong.json())["error"]["code"] == "invalid_cursor"


async def test_item_and_viewer_endpoints(client):
    item = await client.get("/api/workshop/items/1")
    assert item.status == 200
    body = await item.json()
    assert body["vehicleKey"] == "Vamos3"
    assert body["accountId"] == 11

    viewer = await client.get("/api/workshop/items/1/viewer")
    assert viewer.status == 200
    config = await viewer.json()
    assert config["source"]["kind"] == "workshop"
    assert config["vehicle"]["slug"] == "vamos3"
    assert config["paint"]["colors"][0]["rgba"] == [18, 24, 30, 255]
    assert config["decals"][0]["rot"] == [-89.9, 10.0, 11.8]
    assert config["attachments"][0]["key"] == "Attachment_Light_04"
    etag = viewer.headers["ETag"]
    cached = await client.get(
        "/api/workshop/items/1/viewer", headers={"If-None-Match": etag}
    )
    assert cached.status == 304


async def test_item_page_reports_configuration(client):
    response = await client.get("/workshop/items/1/")
    assert response.status == 200
    text = await response.text()
    assert "Configuration" in text
    assert "Motor Town: Behind The Wheel" in text
    assert '<a href="/">Main site</a>' in text
    assert 'id="item-viewer-frame"' in text
    assert 'src="/vehicles/index.html?workshop=1&amp;ui=0&amp;embed=1"' in text
    assert 'id="item-viewer-fullscreen"' in text
    assert "/workshop/static/item-viewer.js" in text
    assert "View in 3D" not in text
    assert "Rendered decals" in text
    assert "snapshot-api" in text
    assert text.index("Parts (") < text.index("Decal layers (")
    assert 'class="detail-list part-list"' in text
    redirect = await client.get(
        "/workshop/items/1/viewer/", allow_redirects=False
    )
    assert redirect.status == 301
    assert redirect.headers["Location"] == "/workshop/items/1/"


async def test_snapshot_endpoint_queues_then_reports_ready(client, settings):
    from amc_peripheral.workshop.snapshots import SnapshotStore

    first = await client.get("/api/workshop/items/1/snapshot")
    assert first.status == 202
    queued = await first.json()
    assert queued["status"] == "pending"
    assert queued["priority"] == 100
    assert queued["url"] is None

    store = SnapshotStore(settings.site_db)
    claimed = store.claim("test-worker", lease_seconds=60)
    assert claimed and claimed["cache_key"] == queued["key"]
    store.complete(
        queued["key"], artifact_path="items/aa/preview.webp", width=960,
        height=540, size=2048, sha256="e" * 64,
    )
    second = await client.get("/api/workshop/items/1/snapshot")
    assert second.status == 200
    ready = await second.json()
    assert ready["status"] == "ready"
    assert ready["url"] == "/workshop/snapshots/items/aa/preview.webp"


async def test_card_snapshot_uses_visible_priority(client):
    response = await client.get("/api/workshop/items/1/snapshot?via=card")
    assert response.status == 202
    payload = await response.json()
    assert payload["status"] == "pending"
    assert payload["priority"] == 50

    direct = await client.get("/api/workshop/items/1/snapshot")
    boosted = await direct.json()
    assert boosted["priority"] == 100


async def test_search_finds_authors_and_opens_exact_item_codes(client):
    home = await client.get("/workshop/")
    text = await home.text()
    assert 'action="/workshop/search/"' in text
    assert 'name="q"' in text
    assert "#179250" in text

    page = await client.get("/workshop/search/?q=ALI")
    assert page.status == 200
    body = await page.text()
    assert "Alice" in body
    assert '/workshop/authors/11/' in body
    assert "Bob" not in body

    authors = await client.get("/api/workshop/search?q=ALI")
    payload = await authors.json()
    assert payload["type"] == "authors"
    assert [a["accountId"] for a in payload["authors"]] == [11]

    item = await client.get("/workshop/search/?q=%231", allow_redirects=False)
    assert item.status == 302
    assert item.headers["Location"] == "/workshop/items/1/"
    api_item = await client.get("/api/workshop/search?q=%231")
    assert (await api_item.json())["item"]["id"] == 1

    hidden = await client.get("/workshop/search/?q=%235", allow_redirects=False)
    assert hidden.status == 404
    missing = await client.get("/api/workshop/search?q=%23999999")
    assert missing.status == 404


async def test_gallery_exposes_snapshot_keys_and_bounds_the_queue(client):
    response = await client.get("/workshop/gallery/?sort=new")
    assert response.status == 200
    text = await response.text()
    assert "/workshop/gallery/" in text
    assert "data-snapshot-api" in text
    assert "Rendering preview" in text
    listing = await client.get("/api/workshop/items?sort=new")
    data = await listing.json()
    assert all(item["snapshotKey"] for item in data["items"])



async def test_hidden_deleted_and_unknown_items_are_404(client):
    for workshop_id in (5, 6, 999999999, 404):
        response = await client.get(f"/api/workshop/items/{workshop_id}")
        assert response.status == 404
        assert (await response.json())["error"]["code"] == "not_found"


async def test_author_and_vehicle_pages(client, settings):
    author = await client.get("/workshop/authors/11/")
    assert author.status == 200
    assert "Alice" in await author.text()
    unknown_author = await client.get("/workshop/authors/999/")
    assert unknown_author.status == 404
    vehicle = await client.get("/workshop/vehicles/Vamos3/")
    assert vehicle.status == 200
    vehicle_text = await vehicle.text()
    assert "Vamos3" in vehicle_text
    assert "workshop/vehicles/Vamos3/" in vehicle_text

    from amc_peripheral.workshop.snapshots import SnapshotStore

    assert SnapshotStore(settings.site_db).health()["queueDepth"] == 0


async def test_club_filter_uses_safe_projection(client):
    response = await client.get("/api/workshop/items?club=1")
    assert response.status == 200
    data = await response.json()
    assert {item["id"] for item in data["items"]} == {1, 3}
    assert "76561198000000000" not in await response.text()


async def test_character_vehicle_endpoint_is_disabled_by_default(client):
    for path in ("/api/character-vehicles/1/viewer",
                 "/api/character-vehicles/1/meta",
                 "/vehicles/character/1/"):
        response = await client.get(path)
        assert response.status == 404


async def test_legacy_character_url_redirects_after_opt_in(settings):
    from aiohttp.test_utils import TestClient, TestServer

    from amc_peripheral.workshop.routes import create_app

    enabled = type(settings)(
        **{**settings.__dict__, "character_vehicle_dsn": "dbname=unused",
           "character_vehicle_public": True}
    )
    client = TestClient(TestServer(create_app(enabled)))
    await client.start_server()
    try:
        response = await client.get(
            "/vehicles/?vehicle=vamos3&ownerVehicleId=2367", allow_redirects=False
        )
        assert response.status == 301
        assert response.headers["Location"] == "/vehicles/character/2367/"
    finally:
        await client.close()


async def test_snapshot_batch_is_bounded_and_reports_missing(client):
    queued = await (await client.get("/api/workshop/items/1/snapshot")).json()
    response = await client.get(
        "/api/workshop/snapshots", params={"keys": f"{queued['key']},{'0' * 64}"}
    )
    assert response.status == 200
    data = await response.json()
    assert data["snapshots"][queued["key"]]["status"] == "pending"
    assert data["snapshots"]["0" * 64] is None
    bad = await client.get("/api/workshop/snapshots", params={"keys": "not-a-key"})
    assert bad.status == 400
    assert (await bad.json())["error"]["code"] == "invalid_keys"


async def test_health_includes_snapshot_worker_state(client):
    response = await client.get("/api/workshop/health")
    assert response.status == 200
    data = await response.json()
    assert data["status"] == "ok"
    assert data["items"] == 3
    assert data["runId"] == 7
    assert data["snapshots"]["queueDepth"] == 0
    assert data["snapshots"]["artifactBytes"] == 0


async def test_author_page_publishes_render_collage_metadata(client, settings):
    from amc_peripheral.workshop.snapshots import SnapshotStore

    queued = await (await client.get("/api/workshop/items/1/snapshot")).json()
    artifact = settings.snapshot_root / "public/items/aa/author-cover-source.webp"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (960, 540), (20, 80, 140)).save(artifact)
    SnapshotStore(settings.site_db).complete(
        queued["key"], artifact_path="items/aa/author-cover-source.webp",
        width=960, height=540, size=artifact.stat().st_size, sha256="f" * 64,
    )

    response = await client.get("/workshop/authors/11/")
    assert response.status == 200
    text = await response.text()
    assert 'property="og:image" content="https://www.aseanmotorclub.com/workshop/snapshots/authors/11-' in text
    assert 'property="og:image:width" content="1200"' in text
    assert 'property="og:image:height" content="630"' in text
    assert 'name="twitter:card" content="summary_large_image"' in text

    marker = "https://www.aseanmotorclub.com"
    url = text.split('property="og:image" content="', 1)[1].split('"', 1)[0]
    cover = await client.get(url.removeprefix(marker))
    assert cover.status == 200
    assert cover.headers["Content-Type"] == "image/webp"
    assert len(await cover.read()) > 100
