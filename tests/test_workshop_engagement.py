"""Engagement JSON and the workshop sitemap."""

from __future__ import annotations

import sqlite3

import pytest
from aiohttp.test_utils import TestClient, TestServer

from amc_peripheral.workshop import routes
from amc_peripheral.workshop.auth import SSOSettings, csrf_token, sign_session

GUILD_ID = 424242
SECRET = "session-secret-value"
MEMBER = "9001"


@pytest.fixture
def sso() -> SSOSettings:
    return SSOSettings(
        client_id="123456789",
        client_secret="client-secret",
        session_secret=SECRET,
        guild_id=GUILD_ID,
        public_url="https://example.test",
    )


class FakeIdentity:
    steam_id = 76561198000000000

    def identity_for(self, discord_id):
        from amc_peripheral.workshop.auth import Identity

        return Identity(self.steam_id, frozenset())

    def steam_id_for(self, discord_id):
        return self.steam_id


@pytest.fixture
async def client(settings, sso):
    app = routes.create_app(settings, sso=sso, player_identity=FakeIdentity())  # type: ignore[arg-type]
    test_client = TestClient(TestServer(app))
    await test_client.start_server()
    test_client.workshop_app = app  # type: ignore[attr-defined]
    yield test_client
    await test_client.close()


def _session(member: str = MEMBER) -> tuple[dict, dict]:
    claims = {"sub": member, "u": "driver", "n": "Driver", "m": True, "iat": 1_700_000_000}
    return (
        {"amc_workshop_session": sign_session(claims, SECRET, ttl=3600)},
        {"csrf": csrf_token(claims, SECRET)},
    )


async def test_engagement_shape(client):
    response = await client.get("/api/workshop/items/1/engagement")
    assert response.status == 200
    body = await response.json()
    assert set(body) == {"workshopId", "likes", "likedByViewer", "collections", "votes"}
    assert body["workshopId"] == 1
    assert body["likes"] == 0
    assert body["likedByViewer"] is False


async def test_engagement_counts_likes_and_collections(client):
    community = client.workshop_app["community"]
    community.toggle_like(workshop_id=1, discord_id="a", now="2026-11-18T00:00:00Z")
    community.toggle_like(workshop_id=1, discord_id="b", now="2026-11-18T00:00:00Z")

    store = client.workshop_app["collections"]
    cookies, form = _session()
    await client.post(
        "/workshop/collections/new",
        data={"title": "Eng", "description": "", "visibility": "public", **form},
        cookies=cookies,
        allow_redirects=False,
    )
    collection = store.owned(MEMBER)[0]
    await client.post(
        f"/workshop/collections/{collection.id}/items",
        data={"workshop_id": "1", **form},
        cookies=cookies,
        allow_redirects=False,
    )

    body = await (await client.get("/api/workshop/items/1/engagement")).json()
    assert body["likes"] == 2
    assert body["collections"] == 1


async def test_engagement_is_viewer_scoped_and_uncacheable(client):
    community = client.workshop_app["community"]
    community.toggle_like(workshop_id=1, discord_id=MEMBER, now="2026-11-18T00:00:00Z")
    cookies, _ = _session()

    response = await client.get(
        "/api/workshop/items/1/engagement", cookies=cookies
    )
    body = await response.json()
    assert body["likedByViewer"] is True
    assert response.headers["Cache-Control"] == "private, no-store"

    anonymous = await client.get("/api/workshop/items/1/engagement")
    assert anonymous.headers["Cache-Control"] == "public, max-age=30"


async def test_engagement_404(client):
    response = await client.get("/api/workshop/items/999999/engagement")
    assert response.status == 404


# -- sitemap ----------------------------------------------------------------


async def test_sitemap_index_lists_pages_and_item_chunks(client):
    response = await client.get("/workshop/sitemap.xml")
    assert response.status == 200
    assert response.content_type == "application/xml"
    text = await response.text()
    assert text.startswith('<?xml version="1.0" encoding="UTF-8"?>')
    assert "sitemap-pages.xml" in text
    assert "sitemap-items-1.xml" in text


async def test_pages_sitemap_includes_public_collections_only(client):
    cookies, form = _session()
    store = client.workshop_app["collections"]

    await client.post(
        "/workshop/collections/new",
        data={"title": "Listed", "description": "", "visibility": "public", **form},
        cookies=cookies,
        allow_redirects=False,
    )
    await client.post(
        "/workshop/collections/new",
        data={"title": "Hidden", "description": "", "visibility": "unlisted", **form},
        cookies=cookies,
        allow_redirects=False,
    )
    for collection in store.owned(MEMBER):
        with sqlite3.connect(store.path) as conn:
            conn.execute(
                "INSERT INTO workshop_collection_item"
                " (collection_id, workshop_id, position, added_at) VALUES (?, 1, 0, 'now')",
                (collection.id,),
            )

    text = await (await client.get("/workshop/sitemap-pages.xml")).text()
    assert "/workshop/collections/" in text
    assert "lastmod" in text
    listed = next(c for c in store.owned(MEMBER) if c.title == "Listed")
    hidden = next(c for c in store.owned(MEMBER) if c.title == "Hidden")
    assert f"/{listed.id}/{listed.slug}/" in text
    assert f"/{hidden.id}/{hidden.slug}/" not in text


async def test_item_sitemap_has_urls(client):
    text = await (await client.get("/workshop/sitemap-items-1.xml")).text()
    assert "<urlset" in text
    assert "/workshop/items/" in text


async def test_item_sitemap_rejects_chunk_zero(client):
    response = await client.get("/workshop/sitemap-items-0.xml")
    assert response.status == 404
