"""Tag pages: ownership gates, the tag index, the tag page and search."""

from __future__ import annotations

import sqlite3

import pytest
from aiohttp.test_utils import TestClient, TestServer

from amc_peripheral.workshop import routes
from amc_peripheral.workshop.auth import SSOSettings, csrf_token, sign_session

GUILD_ID = 424242
SECRET = "session-secret-value"
OWNER = "9001"
OTHER = "1111"


@pytest.fixture
def sso() -> SSOSettings:
    return SSOSettings(
        client_id="123456789",
        client_secret="client-secret",
        session_secret=SECRET,
        guild_id=GUILD_ID,
        public_url="http://example.test",
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


def _as(member: str = OWNER) -> tuple[dict, dict]:
    claims = {"sub": member, "u": "driver", "n": "Driver", "m": True, "iat": 1_700_000_000}
    return (
        {"amc_workshop_session": sign_session(claims, SECRET, ttl=3600)},
        {"csrf": csrf_token(claims, SECRET)},
    )


def _claim(client, workshop_id: int = 1, member: str = OWNER, revoked: str | None = None):
    store = client.workshop_app["community"]
    with sqlite3.connect(store.path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO workshop_claim (workshop_id, discord_id, steam_id,"
            " character_guid, claimed_at, last_verified_at, revoked_at)"
            " VALUES (?, ?, '765', 'GUID', 'now', 'now', ?)",
            (workshop_id, member, revoked),
        )


def _unlimited(client):
    from amc_peripheral.workshop.ratelimit import RateLimiter

    client.workshop_app["limiters"]["tag"] = RateLimiter(limit=99, window=0.0)


# -- item tagging -----------------------------------------------------------


async def test_tagging_requires_ownership(client):
    _unlimited(client)
    cookies, form = _as(OTHER)
    response = await client.post(
        "/workshop/items/1/tags",
        data={"tags": "#cat", **form},
        cookies=cookies,
        allow_redirects=False,
    )
    assert response.status == 403


async def test_anonymous_cannot_tag(client):
    response = await client.post(
        "/workshop/items/1/tags", data={"tags": "#cat"}, allow_redirects=False
    )
    assert response.status == 403


async def test_owner_tags_their_build(client):
    _claim(client)
    _unlimited(client)
    cookies, form = _as()

    response = await client.post(
        "/workshop/items/1/tags",
        data={"tags": "#cat, drift", **form},
        cookies=cookies,
        allow_redirects=False,
    )
    assert response.status == 303
    assert client.workshop_app["tags"].item_tags(1) == ["cat", "drift"]

    page = await (await client.get("/workshop/items/1/")).text()
    assert ">#cat</a>" in page
    assert "/workshop/tags/cat/" in page


async def test_revoked_claim_cannot_tag_but_keeps_existing_tags(client):
    _claim(client)
    _unlimited(client)
    cookies, form = _as()
    await client.post(
        "/workshop/items/1/tags",
        data={"tags": "#cat", **form},
        cookies=cookies,
        allow_redirects=False,
    )

    _claim(client, revoked="2026-01-01T00:00:00Z")
    denied = await client.post(
        "/workshop/items/1/tags",
        data={"tags": "#racer", **form},
        cookies=cookies,
        allow_redirects=False,
    )
    assert denied.status == 403
    # The description of the build survives the loss of the claim.
    assert client.workshop_app["tags"].item_tags(1) == ["cat"]


async def test_remove_tag(client):
    _claim(client)
    _unlimited(client)
    cookies, form = _as()
    await client.post(
        "/workshop/items/1/tags",
        data={"tags": "#cat", **form},
        cookies=cookies,
        allow_redirects=False,
    )
    removed = await client.post(
        "/workshop/items/1/tags/cat/remove",
        data=form,
        cookies=cookies,
        allow_redirects=False,
    )
    assert removed.status == 303
    assert client.workshop_app["tags"].item_tags(1) == []


async def test_tag_budget_surfaces_as_a_message(client):
    _claim(client)
    _unlimited(client)
    cookies, form = _as()
    await client.post(
        "/workshop/items/1/tags",
        data={"tags": "a b c", **form},
        cookies=cookies,
        allow_redirects=False,
    )
    blocked = await client.post(
        "/workshop/items/1/tags",
        data={"tags": "d", **form},
        cookies=cookies,
        allow_redirects=False,
    )
    assert "tag-error" in blocked.headers["Location"]


# -- collection tagging -----------------------------------------------------


async def test_collection_tagging_is_owner_only(client):
    _unlimited(client)
    cookies, form = _as()
    await client.post(
        "/workshop/collections/new",
        data={"title": "Night", "description": "", "visibility": "public", **form},
        cookies=cookies,
        allow_redirects=False,
    )
    collection = client.workshop_app["collections"].owned(OWNER)[0]

    denied = await client.post(
        f"/workshop/collections/{collection.id}/tags",
        data={"tags": "#drift", **_as(OTHER)[1]},
        cookies=_as(OTHER)[0],
        allow_redirects=False,
    )
    assert denied.status == 403

    allowed = await client.post(
        f"/workshop/collections/{collection.id}/tags",
        data={"tags": "#drift", **form},
        cookies=cookies,
        allow_redirects=False,
    )
    assert allowed.status == 303
    assert client.workshop_app["tags"].collection_tags(collection.id) == ["drift"]


# -- pages ------------------------------------------------------------------


async def test_tag_index_lists_used_tags(client):
    _claim(client)
    _unlimited(client)
    cookies, form = _as()
    await client.post(
        "/workshop/items/1/tags",
        data={"tags": "#cat", **form},
        cookies=cookies,
        allow_redirects=False,
    )
    text = await (await client.get("/workshop/tags/")).text()
    assert "#cat" in text
    assert "Most used" in text


async def test_tag_page_shows_the_build_and_related_tags(client):
    _claim(client)
    _claim(client, workshop_id=2)
    _unlimited(client)
    cookies, form = _as()
    await client.post(
        "/workshop/items/1/tags",
        data={"tags": "#cat #racer", **form},
        cookies=cookies,
        allow_redirects=False,
    )
    await client.post(
        "/workshop/items/2/tags",
        data={"tags": "#cat #drift", **form},
        cookies=cookies,
        allow_redirects=False,
    )

    page = await client.get("/workshop/tags/cat/")
    assert page.status == 200
    text = await page.text()
    assert "/workshop/items/1/" in text
    assert "/workshop/items/2/" in text
    assert "#drift" in text  # related
    assert 'content="noindex' in text  # only two builds


async def test_tag_page_301s_to_canonical(client):
    response = await client.get("/workshop/tags/Cat/", allow_redirects=False)
    assert response.status == 301
    assert response.headers["Location"].endswith("/workshop/tags/cat/")


async def test_unknown_tag_renders_an_empty_page(client):
    page = await client.get("/workshop/tags/nothing-here/")
    assert page.status == 200
    assert "No builds carry this tag yet" in await page.text()


async def test_tag_api_searches(client):
    _claim(client)
    _unlimited(client)
    cookies, form = _as()
    await client.post(
        "/workshop/items/1/tags",
        data={"tags": "#caterham", **form},
        cookies=cookies,
        allow_redirects=False,
    )
    response = await client.get("/api/workshop/tags?q=cat")
    assert response.status == 200
    payload = await response.json()
    assert payload[0]["tag"] == "caterham"
    assert payload[0]["items"] == 1


async def test_search_box_routes_hash_to_the_tag_page(client):
    _claim(client)
    _unlimited(client)
    cookies, form = _as()
    await client.post(
        "/workshop/items/1/tags",
        data={"tags": "#cat", **form},
        cookies=cookies,
        allow_redirects=False,
    )
    response = await client.get("/workshop/search/?q=%23cat", allow_redirects=False)
    assert response.status == 302
    assert response.headers["Location"].endswith("/workshop/tags/cat/")


async def test_home_page_shows_tag_strip(client):
    _claim(client)
    _unlimited(client)
    cookies, form = _as()
    await client.post(
        "/workshop/items/1/tags",
        data={"tags": "#cat", **form},
        cookies=cookies,
        allow_redirects=False,
    )
    text = await (await client.get("/workshop/")).text()
    assert 'class="tag-strip"' in text
    assert "/workshop/tags/cat/" in text
