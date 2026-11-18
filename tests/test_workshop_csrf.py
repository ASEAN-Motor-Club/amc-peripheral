"""CSRF and rate limiting on write endpoints, plus the like endpoint end to end."""

from __future__ import annotations

import pytest
from aiohttp.test_utils import TestClient, TestServer

from amc_peripheral.workshop import routes
from amc_peripheral.workshop.auth import SSOSettings, csrf_token, sign_session
from amc_peripheral.workshop.ratelimit import RateLimiter

GUILD_ID = 424242
SECRET = "session-secret-value"


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
    def __init__(self):
        self.steam_id = 76561198000000000

    def identity_for(self, discord_id):
        from amc_peripheral.workshop.auth import Identity

        return Identity(self.steam_id, frozenset())

    def steam_id_for(self, discord_id):
        return self.steam_id


@pytest.fixture
async def auth_client(settings, sso):
    app = routes.create_app(settings, sso=sso, player_identity=FakeIdentity())  # type: ignore[arg-type]
    client = TestClient(TestServer(app))
    await client.start_server()
    client.workshop_app = app  # type: ignore[attr-defined]
    yield client
    await client.close()


def _session_cookie(client, *, iat: int = 1_700_000_000, sub: str = "9001") -> str:
    claims = {"sub": sub, "u": "driver", "n": "Driver", "m": True, "iat": iat}
    return sign_session(claims, SECRET, ttl=3600)


def _token(*, iat: int = 1_700_000_000, sub: str = "9001") -> str:
    return csrf_token({"sub": sub, "iat": iat}, SECRET)


# -- primitives --------------------------------------------------------------


def test_csrf_token_is_session_bound():
    assert _token() == _token()
    assert _token(sub="9001") != _token(sub="9002")
    assert _token(iat=1) != _token(iat=2)
    assert csrf_token(None, SECRET) == ""


def test_rate_limiter_allows_then_blocks():
    now = [100.0]
    limiter = RateLimiter(limit=1, window=2.0, clock=lambda: now[0])

    assert limiter.allow("member") is True
    assert limiter.allow("member") is False
    now[0] += 2.5
    assert limiter.allow("member") is True


def test_rate_limiter_is_per_key():
    limiter = RateLimiter(limit=1, window=60.0, clock=lambda: 5.0)
    assert limiter.allow("a") is True
    assert limiter.allow("b") is True
    assert limiter.allow("a") is False


# -- middleware --------------------------------------------------------------


async def test_post_without_csrf_is_forbidden(auth_client):
    cookie = _session_cookie(auth_client)
    response = await auth_client.post(
        "/workshop/items/1/like",
        data={},
        cookies={"amc_workshop_session": cookie},
        allow_redirects=False,
    )
    assert response.status == 403


async def test_post_with_wrong_csrf_is_forbidden(auth_client):
    cookie = _session_cookie(auth_client)
    response = await auth_client.post(
        "/workshop/items/1/like",
        data={"csrf": "deadbeef"},
        cookies={"amc_workshop_session": cookie},
        allow_redirects=False,
    )
    assert response.status == 403


async def test_post_without_session_is_forbidden(auth_client):
    response = await auth_client.post(
        "/workshop/items/1/like", data={"csrf": _token()}, allow_redirects=False
    )
    assert response.status == 403


# -- the like endpoint -------------------------------------------------------


async def test_like_toggles_and_redirects(auth_client):
    cookie = _session_cookie(auth_client)
    token = _token()

    first = await auth_client.post(
        "/workshop/items/1/like",
        data={"csrf": token},
        cookies={"amc_workshop_session": cookie},
        allow_redirects=False,
    )
    assert first.status == 303
    assert first.headers["Location"].endswith("/workshop/items/1/")

    store = auth_client.workshop_app["community"]
    assert store.like_count(1) == 1

    # The limiter is per member with a 2s window; wait it out before toggling back.
    auth_client.workshop_app["limiters"]["like"] = RateLimiter(limit=5, window=0.0)
    second = await auth_client.post(
        "/workshop/items/1/like",
        data={"csrf": token},
        cookies={"amc_workshop_session": cookie},
        allow_redirects=False,
    )
    assert second.status == 303
    assert store.like_count(1) == 0


async def test_like_returns_json_when_asked(auth_client):
    cookie = _session_cookie(auth_client)
    response = await auth_client.post(
        "/workshop/items/1/like",
        data={"csrf": _token()},
        headers={"Accept": "application/json"},
        cookies={"amc_workshop_session": cookie},
    )
    assert response.status == 200
    assert await response.json() == {"liked": True, "count": 1}


async def test_like_is_rate_limited(auth_client):
    cookie = _session_cookie(auth_client)
    token = _token()
    await auth_client.post(
        "/workshop/items/1/like",
        data={"csrf": token},
        cookies={"amc_workshop_session": cookie},
        allow_redirects=False,
    )
    second = await auth_client.post(
        "/workshop/items/1/like",
        data={"csrf": token},
        cookies={"amc_workshop_session": cookie},
        allow_redirects=False,
    )
    assert second.status == 429


async def test_like_on_missing_item_404s(auth_client):
    auth_client.workshop_app["limiters"]["like"] = RateLimiter(limit=5, window=0.0)
    response = await auth_client.post(
        "/workshop/items/999999/like",
        data={"csrf": _token()},
        cookies={"amc_workshop_session": _session_cookie(auth_client)},
        allow_redirects=False,
    )
    assert response.status == 404


async def test_item_page_shows_like_state(auth_client):
    cookie = _session_cookie(auth_client)
    await auth_client.post(
        "/workshop/items/1/like",
        data={"csrf": _token()},
        cookies={"amc_workshop_session": cookie},
        allow_redirects=False,
    )

    response = await auth_client.get(
        "/workshop/items/1/", cookies={"amc_workshop_session": cookie}
    )
    text = await response.text()
    assert 'aria-pressed="true"' in text

    anonymous = await (await auth_client.get("/workshop/items/1/")).text()
    assert "Sign in to like" in anonymous
    assert 'aria-pressed="true"' not in anonymous


async def test_logout_form_carries_a_token(auth_client):
    text = await (
        await auth_client.get(
            "/workshop/account/",
            cookies={"amc_workshop_session": _session_cookie(auth_client)},
        )
    ).text()
    assert 'name="csrf"' in text
