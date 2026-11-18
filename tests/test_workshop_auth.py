"""Discord SSO: session signing, OAuth2 redirect, callback and account page."""

from __future__ import annotations

import time

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from amc_peripheral.workshop import auth, routes
from amc_peripheral.workshop.auth import (
    SESSION_COOKIE,
    STATE_COOKIE,
    PlayerIdentityRepository,
    SSOSettings,
    sign_session,
    verify_session,
)

GUILD_ID = 424242


@pytest.fixture
async def fake_discord():
    """Minimal stand-in for the Discord OAuth2 + users endpoints."""

    async def token(request):
        form = await request.post()
        if form.get("code") != "good-code":
            return web.json_response({"error": "invalid_grant"}, status=400)
        if form.get("redirect_uri") != "http://example.test/workshop/auth/callback":
            return web.json_response({"error": "invalid_request"}, status=400)
        return web.json_response({"access_token": "token-abc", "token_type": "Bearer"})

    async def me(request):
        if request.headers.get("Authorization") != "Bearer token-abc":
            return web.json_response({"error": "unauthorized"}, status=401)
        return web.json_response(
            {"id": "9001", "username": "driver", "global_name": "Driver"}
        )

    async def guilds(request):
        return web.json_response([{"id": str(GUILD_ID), "name": "ASEAN Motor Club"}])

    app = web.Application()
    app.router.add_post("/oauth2/token", token)
    app.router.add_get("/users/@me", me)
    app.router.add_get("/users/@me/guilds", guilds)
    server = TestServer(app)
    await server.start_server()
    yield str(server.make_url("")).rstrip("/")
    await server.close()


@pytest.fixture
def sso() -> SSOSettings:
    return SSOSettings(
        client_id="123456789",
        client_secret="client-secret",
        session_secret="session-secret-value",
        guild_id=GUILD_ID,
        # http so the aiohttp test client actually sends the Secure-less
        # cookies; the https behaviour is asserted in its own test below.
        public_url="http://example.test",
    )


class FakeIdentity:
    def __init__(self, steam_id: int | None):
        self.steam_id = steam_id
        self.calls: list[str] = []

    def steam_id_for(self, discord_id):
        self.calls.append(str(discord_id))
        return self.steam_id


@pytest.fixture
async def auth_client(settings, sso):
    identity = FakeIdentity(76561198000000000)
    app = routes.create_app(
        settings,
        sso=sso,
        player_identity=identity,  # type: ignore[arg-type]
    )
    client = TestClient(TestServer(app))
    await client.start_server()
    client.fake_identity = identity  # type: ignore[attr-defined]
    yield client
    await client.close()


def test_session_roundtrip():
    claims = {"sub": "42", "u": "driver", "n": "Driver", "m": True}
    token = sign_session(claims, "secret", ttl=60)
    restored = verify_session(token, "secret")
    assert restored is not None
    assert restored["sub"] == "42"
    assert restored["m"] is True


def test_session_rejects_tampering_and_wrong_key():
    token = sign_session({"sub": "42"}, "secret", ttl=60)
    body, signature = token.split(".")
    assert verify_session(f"{body}.{signature[:-2]}AA", "secret") is None
    assert verify_session(token, "other-secret") is None
    assert verify_session("not-a-token", "secret") is None
    assert verify_session(None, "secret") is None


def test_session_rejects_expired():
    token = sign_session({"sub": "42"}, "secret", ttl=-5)
    assert verify_session(token, "secret") is None


def test_authorize_url_has_expected_parameters(sso):
    url = auth.authorize_url(sso, "state-123")
    assert url.startswith("https://discord.com/oauth2/authorize?")
    assert "client_id=123456789" in url
    assert "state=state-123" in url
    assert "scope=identify+guilds" in url
    assert "redirect_uri=http%3A%2F%2Fexample.test%2Fworkshop%2Fauth%2Fcallback" in url


def test_claims_mark_membership():
    user = {"id": "7", "username": "alice", "global_name": "Alice", "avatar": None}
    member = auth.claims_from_discord(user, {str(GUILD_ID)}, GUILD_ID)
    assert member["m"] is True
    assert member["a"].startswith("https://cdn.discordapp.com/embed/avatars/")
    outsider = auth.claims_from_discord(user, set(), GUILD_ID)
    assert outsider["m"] is False
    unconfigured = auth.claims_from_discord(user, {str(GUILD_ID)}, 0)
    assert unconfigured["m"] is False and unconfigured["g"] is False


def test_display_name_prefers_global_name():
    assert auth.display_name({"u": "alice", "n": "Alice"}) == "Alice"
    assert auth.display_name({"u": "alice", "n": None}) == "alice"
    assert auth.display_name(None) == ""


def test_player_identity_disabled_without_dsn():
    assert PlayerIdentityRepository(None).steam_id_for("1") is None
    assert PlayerIdentityRepository(None).identity_for("1") is None
    repo = PlayerIdentityRepository("postgresql://ignored/db", enabled=False)
    assert repo.steam_id_for("1") is None


class _FakeCursor:
    def __init__(self, rows, calls):
        self.rows = rows
        self.calls = calls

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.calls.append((sql, params))

    def fetchall(self):
        return self.rows


class _FakeConnection:
    def __init__(self, rows, calls):
        self.rows = rows
        self.calls = calls
        self.closed = False

    def cursor(self):
        return _FakeCursor(self.rows, self.calls)

    def close(self):
        self.closed = True


def test_identity_carries_steam_id_and_character_guids(monkeypatch):
    """A GUID is what authorises a claim, so it has to come back from the lookup."""
    repo = PlayerIdentityRepository("postgresql://ignored/db")
    calls: list[tuple[str, tuple]] = []
    steam = 76561198000000000
    rows = [
        (steam, "8f14e45fceea167a5a36dedd4bea2543"),
        (steam, "c9f0f895fb98ab9159f51fd0297e236d"),
        (steam, None),  # a character row with no guid must not break the set
    ]
    conns = []

    def connect():
        conn = _FakeConnection(rows, calls)
        conns.append(conn)
        return conn

    monkeypatch.setattr(repo, "_connect", connect)

    identity = repo.identity_for("9001")
    assert identity is not None
    assert identity.steam_id == steam
    assert identity.character_guids == frozenset(
        {"8F14E45FCEEA167A5A36DEDD4BEA2543", "C9F0F895FB98AB9159F51FD0297E236D"}
    )
    assert repo.steam_id_for("9001") == steam

    # Cached: one query for the three calls above.
    assert len(calls) == 1
    assert "amc_character" in calls[0][0]
    assert conns[0].closed


def test_identity_is_cached_per_discord_user(monkeypatch):
    repo = PlayerIdentityRepository("postgresql://ignored/db")
    calls: list[tuple[str, tuple]] = []
    monkeypatch.setattr(
        repo,
        "_connect",
        lambda: _FakeConnection([(1, "ab")], calls),
    )

    repo.identity_for("1")
    repo.identity_for("1")
    assert len(calls) == 1

    repo.identity_for("2")
    assert len(calls) == 2


def test_identity_lookup_failure_is_not_fatal(monkeypatch):
    repo = PlayerIdentityRepository("postgresql://ignored/db")

    def boom():
        raise RuntimeError("connection refused")

    monkeypatch.setattr(repo, "_connect", boom)
    assert repo.identity_for("9001") is None
    assert repo.steam_id_for("9001") is None


async def test_login_redirects_to_discord(auth_client):
    response = await auth_client.get(
        "/workshop/auth/login?next=/workshop/gallery/", allow_redirects=False
    )
    assert response.status == 302
    location = response.headers["Location"]
    assert location.startswith("https://discord.com/oauth2/authorize?")
    cookie = response.cookies.get(STATE_COOKIE)
    assert cookie is not None
    assert cookie.value.endswith(":/workshop/gallery/")
    assert "HttpOnly" in cookie.output()
    assert "SameSite=Lax" in cookie.output()


async def test_login_ignores_offsite_next(auth_client):
    response = await auth_client.get(
        "/workshop/auth/login?next=//evil.example/", allow_redirects=False
    )
    assert response.status == 302
    assert response.cookies[STATE_COOKIE].value.endswith(":/workshop/account/")


async def test_callback_rejects_missing_state(auth_client):
    response = await auth_client.get(
        "/workshop/auth/callback?code=abc&state=forged", allow_redirects=False
    )
    assert response.status == 302
    assert response.headers["Location"] == "/workshop/?auth=failed"


async def test_callback_rejects_discord_error(auth_client):
    response = await auth_client.get(
        "/workshop/auth/callback?error=access_denied", allow_redirects=False
    )
    assert response.status == 302
    assert response.headers["Location"] == "/workshop/?auth=failed"


async def test_sign_in_exchanges_code_and_reads_membership(
    sso, monkeypatch, fake_discord
):
    monkeypatch.setattr(auth, "DISCORD_API", fake_discord)
    async with aiohttp.ClientSession() as session:
        claims = await auth.sign_in(sso, "good-code", session)

    assert claims is not None
    assert claims["sub"] == "9001"
    assert claims["m"] is True
    assert claims["a"].startswith("https://cdn.discordapp.com/")


async def test_sign_in_fails_closed_when_exchange_fails(sso, monkeypatch, fake_discord):
    monkeypatch.setattr(auth, "DISCORD_API", fake_discord)
    async with aiohttp.ClientSession() as session:
        assert await auth.sign_in(sso, "bad-code", session) is None


async def test_callback_sets_session_cookie(auth_client, sso, monkeypatch):
    login = await auth_client.get("/workshop/auth/login", allow_redirects=False)
    state = login.cookies[STATE_COOKIE].value.split(":", 1)[0]

    async def fake_sign_in(_sso, code, _session):
        assert code == "abc"
        return auth.claims_from_discord(
            {"id": "9001", "username": "driver", "global_name": "Driver"},
            {str(GUILD_ID)},
            GUILD_ID,
        )

    monkeypatch.setattr(routes, "sign_in", fake_sign_in)
    response = await auth_client.get(
        f"/workshop/auth/callback?code=abc&state={state}",
        allow_redirects=False,
    )

    assert response.status == 302
    assert response.headers["Location"] == "/workshop/account/"
    session = response.cookies[SESSION_COOKIE].value
    claims = verify_session(session, sso.session_secret)
    assert claims is not None
    assert claims["sub"] == "9001"
    assert claims["m"] is True


async def test_callback_bounces_when_sign_in_fails(auth_client, monkeypatch):
    login = await auth_client.get("/workshop/auth/login", allow_redirects=False)
    state = login.cookies[STATE_COOKIE].value.split(":", 1)[0]

    async def failing_sign_in(_sso, _code, _session):
        return None

    monkeypatch.setattr(routes, "sign_in", failing_sign_in)
    response = await auth_client.get(
        f"/workshop/auth/callback?code=abc&state={state}",
        allow_redirects=False,
    )
    assert response.status == 302
    assert response.headers["Location"] == "/workshop/?auth=failed"


async def test_login_sets_secure_cookie_on_https(settings):
    sso = SSOSettings(
        client_id="123456789",
        client_secret="client-secret",
        session_secret="session-secret-value",
        guild_id=GUILD_ID,
        public_url="https://www.example.test",
    )
    client = TestClient(TestServer(routes.create_app(settings, sso=sso)))
    await client.start_server()
    try:
        response = await client.get("/workshop/auth/login", allow_redirects=False)
        cookie = response.headers["Set-Cookie"]
        assert "Secure" in cookie
        location = response.headers["Location"]
        assert (
            "redirect_uri=https://www.example.test/workshop/auth/callback" in location
        )
    finally:
        await client.close()


async def test_me_endpoint_anonymous(auth_client):
    response = await auth_client.get("/api/workshop/me")
    body = await response.json()
    assert response.status == 200
    assert body == {
        "authenticated": False,
        "ssoEnabled": True,
        "user": None,
        "steamId": None,
    }


async def test_me_endpoint_signed_in(auth_client, sso):
    token = sign_session(
        {
            "sub": "9001",
            "u": "driver",
            "n": "Driver",
            "a": "https://cdn.discordapp.com/embed/avatars/0.png",
            "m": True,
            "g": True,
            "iat": int(time.time()),
        },
        sso.session_secret,
        sso.session_ttl,
    )
    auth_client.session.cookie_jar.update_cookies({SESSION_COOKIE: token})
    response = await auth_client.get("/api/workshop/me")
    body = await response.json()
    assert body["authenticated"] is True
    assert body["user"]["displayName"] == "Driver"
    assert body["user"]["member"] is True
    assert body["steamId"] == "76561198000000000"


async def test_account_page_requires_sign_in(auth_client):
    response = await auth_client.get("/workshop/account/", allow_redirects=False)
    assert response.status == 302
    assert response.headers["Location"].startswith("/workshop/auth/login")


async def test_account_page_lists_member_builds(auth_client, sso):
    token = sign_session(
        {"sub": "9001", "u": "driver", "n": "Driver", "m": True},
        sso.session_secret,
        sso.session_ttl,
    )
    auth_client.session.cookie_jar.update_cookies({SESSION_COOKIE: token})
    response = await auth_client.get("/workshop/account/")
    text = await response.text()
    assert response.status == 200
    assert "Driver" in text
    assert "76561198000000000" in text
    assert "/workshop/items/" in text


async def test_logout_clears_cookie(auth_client, sso):
    token = sign_session({"sub": "9001", "u": "driver"}, sso.session_secret, 60)
    auth_client.session.cookie_jar.update_cookies({SESSION_COOKIE: token})
    response = await auth_client.post("/workshop/auth/logout", allow_redirects=False)
    assert response.status == 302
    assert response.headers["Location"] == "/workshop/"
    assert response.cookies[SESSION_COOKIE].value == ""
    assert response.cookies[SESSION_COOKIE]["max-age"] == "0"


async def test_sso_disabled_hides_routes(settings):
    app = routes.create_app(settings, sso=SSOSettings())
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        assert (await client.get("/workshop/auth/login")).status == 404
        assert (await client.get("/workshop/auth/callback")).status == 404
        body = await (await client.get("/api/workshop/me")).json()
        assert body["ssoEnabled"] is False
        home = await (await client.get("/workshop/")).text()
        assert "Sign in with Discord" not in home
    finally:
        await client.close()
