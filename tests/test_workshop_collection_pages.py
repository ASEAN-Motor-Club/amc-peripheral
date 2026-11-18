"""Collection pages: creation, ownership gates, unlisted visibility, edits."""

from __future__ import annotations

import pytest
from aiohttp.test_utils import TestClient, TestServer

from amc_peripheral.workshop import routes
from amc_peripheral.workshop.auth import SSOSettings, csrf_token, sign_session

GUILD_ID = 424242
SECRET = "session-secret-value"
MEMBER = "9001"
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


def _as(client, member: str = MEMBER) -> tuple[dict, dict]:
    claims = {
        "sub": member,
        "u": "driver",
        "n": "Driver",
        "m": True,
        "iat": 1_700_000_000,
    }
    cookie = sign_session(claims, SECRET, ttl=3600)
    return {"amc_workshop_session": cookie}, {"csrf": csrf_token(claims, SECRET)}


async def _create(client, *, title="Night runs", visibility="public", member=MEMBER):
    cookies, form = _as(client, member)
    response = await client.post(
        "/workshop/collections/new",
        data={"title": title, "description": "", "visibility": visibility, **form},
        cookies=cookies,
        allow_redirects=False,
    )
    assert response.status == 303, response.status
    return response.headers["Location"]


def _store(client):
    return client.workshop_app["collections"]


async def test_index_is_public_and_empty(client):
    response = await client.get("/workshop/collections/")
    assert response.status == 200
    text = await response.text()
    assert "No public collections yet" in text


async def test_new_requires_sign_in(client):
    response = await client.get("/workshop/collections/new", allow_redirects=False)
    assert response.status == 302
    assert "/workshop/auth/login" in response.headers["Location"]


async def test_create_redirects_to_the_collection(client):
    location = await _create(client)
    assert "/workshop/collections/" in location

    response = await client.get(location)
    assert response.status == 200
    assert "Night runs" in (await response.text())

    cookies, _ = _as(client)
    owned = await (await client.get(location, cookies=cookies)).text()
    assert "Edit collection" in owned


async def test_missing_csrf_is_rejected(client):
    cookies, _ = _as(client)
    response = await client.post(
        "/workshop/collections/new",
        data={"title": "Nope", "visibility": "public"},
        cookies=cookies,
        allow_redirects=False,
    )
    assert response.status == 403


async def test_slug_mismatch_redirects_to_canonical(client):
    location = await _create(client)
    collection = _store(client).listing()[0] if _store(client).listing() else None
    collection_id = int(location.split("/")[3])
    response = await client.get(
        f"/workshop/collections/{collection_id}/wrong-slug/", allow_redirects=False
    )
    assert response.status == 301
    assert collection is None or response.headers["Location"].endswith("")


async def test_non_owner_cannot_edit(client):
    await _create(client)
    collection = _store(client).owned(MEMBER)[0]
    cookies, _ = _as(client, OTHER)
    response = await client.get(
        f"/workshop/collections/{collection.id}/edit",
        cookies=cookies,
        allow_redirects=False,
    )
    assert response.status == 403


async def test_owner_can_add_remove_and_reorder(client):
    from amc_peripheral.workshop.ratelimit import RateLimiter

    # The endpoint is rate limited per member; this test posts several times.
    client.workshop_app["limiters"]["collection"] = RateLimiter(limit=99, window=0.0)
    await _create(client)
    collection = _store(client).owned(MEMBER)[0]
    cookies, form = _as(client)

    added = await client.post(
        f"/workshop/collections/{collection.id}/items",
        data={"workshop_id": "1", **form},
        cookies=cookies,
        allow_redirects=False,
    )
    assert added.status == 303
    assert _store(client).item_ids(collection.id) == [1]

    duplicate = await client.post(
        f"/workshop/collections/{collection.id}/items",
        data={"workshop_id": "1", **form},
        cookies=cookies,
        allow_redirects=False,
    )
    assert "error=duplicate" in duplicate.headers["Location"]
    assert _store(client).item_ids(collection.id) == [1]

    removed = await client.post(
        f"/workshop/collections/{collection.id}/items/1/remove",
        data=form,
        cookies=cookies,
        allow_redirects=False,
    )
    assert removed.status == 303
    assert _store(client).item_ids(collection.id) == []


async def test_unknown_item_is_refused(client):
    await _create(client)
    collection = _store(client).owned(MEMBER)[0]
    cookies, form = _as(client)
    response = await client.post(
        f"/workshop/collections/{collection.id}/items",
        data={"workshop_id": "999999", **form},
        cookies=cookies,
        allow_redirects=False,
    )
    assert "error=no-item" in response.headers["Location"]


async def test_unlisted_is_reachable_but_not_listed(client):
    location = await _create(client, visibility="unlisted")
    cookies, form = _as(client)
    collection = _store(client).owned(MEMBER)[0]
    await client.post(
        f"/workshop/collections/{collection.id}/items",
        data={"workshop_id": "1", **form},
        cookies=cookies,
        allow_redirects=False,
    )

    index = await (await client.get("/workshop/collections/")).text()
    assert "Night runs" not in index

    page = await client.get(location)
    assert page.status == 200
    assert 'name="robots" content="noindex' in await page.text()


async def test_public_collection_appears_in_the_index(client):
    location = await _create(client)
    cookies, form = _as(client)
    collection = _store(client).owned(MEMBER)[0]
    await client.post(
        f"/workshop/collections/{collection.id}/items",
        data={"workshop_id": "1", **form},
        cookies=cookies,
        allow_redirects=False,
    )
    index = await (await client.get("/workshop/collections/")).text()
    assert "Night runs" in index
    assert location in index


async def test_item_page_links_back_to_the_collection(client):
    await _create(client)
    collection = _store(client).owned(MEMBER)[0]
    cookies, form = _as(client)
    await client.post(
        f"/workshop/collections/{collection.id}/items",
        data={"workshop_id": "1", **form},
        cookies=cookies,
        allow_redirects=False,
    )

    text = await (await client.get("/workshop/items/1/")).text()
    assert f"/workshop/collections/{collection.id}/" in text


async def test_save_to_collection_from_the_item_page(client):
    await _create(client)
    collection = _store(client).owned(MEMBER)[0]
    cookies, form = _as(client)
    response = await client.post(
        "/workshop/items/1/collect",
        data={"collection_id": str(collection.id), **form},
        cookies=cookies,
        allow_redirects=False,
    )
    assert response.status == 303
    assert _store(client).item_ids(collection.id) == [1]


async def test_delete_requires_confirmation(client):
    location = await _create(client)
    collection = _store(client).owned(MEMBER)[0]
    cookies, form = _as(client)

    unconfirmed = await client.post(
        f"/workshop/collections/{collection.id}/delete",
        data={"csrf": form["csrf"]},
        cookies=cookies,
        allow_redirects=False,
    )
    assert "delete=1" in unconfirmed.headers["Location"]
    assert _store(client).get(collection.id) is not None

    confirmed = await client.post(
        f"/workshop/collections/{collection.id}/delete",
        data={"confirm": "yes", **form},
        cookies=cookies,
        allow_redirects=False,
    )
    assert confirmed.headers["Location"] == "/workshop/collections/?deleted=1"
    assert _store(client).get(collection.id) is None
    assert location  # the redirect target we followed earlier
