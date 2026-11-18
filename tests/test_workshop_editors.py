"""Member-authored text: the profile editor and the item title/summary editor."""

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


# -- profile ----------------------------------------------------------------


async def test_profile_requires_sign_in(client):
    response = await client.post("/workshop/profile", data={"display_name": "X"}, allow_redirects=False)
    assert response.status == 403


async def test_profile_saves_and_updates(client):
    cookies, form = _as()
    saved = await client.post(
        "/workshop/profile",
        data={"display_name": "Night Driver", "bio": "Hana and Maity", **form},
        cookies=cookies,
        allow_redirects=False,
    )
    assert saved.status == 303

    store = client.workshop_app["community"]
    profile = store.profile(OWNER)
    assert profile is not None
    assert (profile.display_name, profile.bio) == ("Night Driver", "Hana and Maity")

    updated = await client.post(
        "/workshop/profile",
        data={"display_name": "Day Driver", "bio": "", **form},
        cookies=cookies,
        allow_redirects=False,
    )
    assert updated.status == 303
    assert store.profile(OWNER).display_name == "Day Driver"


async def test_profile_strips_links(client):
    cookies, form = _as()
    await client.post(
        "/workshop/profile",
        data={"display_name": "Driver", "bio": "find me at https://example.com/x", **form},
        cookies=cookies,
        allow_redirects=False,
    )
    assert client.workshop_app["community"].profile(OWNER).bio == "find me at"


async def test_profile_rejects_one_character_name(client):
    cookies, form = _as()
    response = await client.post(
        "/workshop/profile",
        data={"display_name": "X", "bio": "", **form},
        cookies=cookies,
        allow_redirects=False,
    )
    assert "profile-error" in response.headers["Location"]


async def test_profile_form_renders_current_values(client):
    cookies, form = _as()
    await client.post(
        "/workshop/profile",
        data={"display_name": "Night Driver", "bio": "Hana", **form},
        cookies=cookies,
        allow_redirects=False,
    )
    text = await (await client.get("/workshop/account/", cookies=cookies)).text()
    assert "Night Driver" in text
    assert 'name="bio"' in text


# -- item editor ------------------------------------------------------------


async def test_item_edit_requires_a_claim(client):
    cookies, _form = _as(OTHER)
    response = await client.get(
        "/workshop/items/1/edit", cookies=cookies, allow_redirects=False
    )
    assert response.status == 403


async def test_item_edit_rejects_revoked_claims(client):
    _claim(client, revoked="2026-01-01T00:00:00Z")
    cookies, _form = _as()
    response = await client.get(
        "/workshop/items/1/edit", cookies=cookies, allow_redirects=False
    )
    assert response.status == 403


async def test_owner_saves_title_and_summary(client):
    _claim(client)
    cookies, form = _as()

    editor = await client.get("/workshop/items/1/edit", cookies=cookies)
    assert editor.status == 200
    assert "Edit your build" in await editor.text()

    saved = await client.post(
        "/workshop/items/1/edit",
        data={"title": "Night run Hana", "description": "Built for the Kuching loop.", **form},
        cookies=cookies,
        allow_redirects=False,
    )
    assert saved.status == 303

    page = await (await client.get("/workshop/items/1/", cookies=cookies)).text()
    assert "Night run Hana" in page
    assert "Built for the Kuching loop." in page
    assert "Edit title, summary &amp; tags" in page


async def test_anonymous_item_page_shows_no_editor(client):
    _claim(client)
    text = await (await client.get("/workshop/items/1/")).text()
    assert "Edit title, summary &amp; tags" not in text


async def test_item_edit_strips_links_and_caps_length(client):
    _claim(client)
    cookies, form = _as()
    await client.post(
        "/workshop/items/1/edit",
        data={
            "title": "Night run",
            "description": "see https://example.com/x for the run",
            **form,
        },
        cookies=cookies,
        allow_redirects=False,
    )
    meta = client.workshop_app["community"].meta(1)
    assert meta.description == "see for the run"

    too_long = await client.post(
        "/workshop/items/1/edit",
        data={"title": "x" * 61, "description": "", **form},
        cookies=cookies,
        allow_redirects=False,
    )
    # The form comes back with the message and the draft intact, nothing saved.
    assert too_long.status == 200
    assert "Title is limited to 60 characters" in await too_long.text()
    assert client.workshop_app["community"].meta(1).title == "Night run"


async def test_empty_title_falls_back_to_the_vehicle_name(client):
    _claim(client)
    cookies, form = _as()
    await client.post(
        "/workshop/items/1/edit",
        data={"title": "", "description": "", **form},
        cookies=cookies,
        allow_redirects=False,
    )
    assert client.workshop_app["community"].meta(1).title is None
