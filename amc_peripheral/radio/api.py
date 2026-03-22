"""Radio Web Interface — aiohttp REST API.

Thin HTTP API that exposes radio actions for the SvelteKit Discord Activity.
Runs alongside the Discord bot in the same event loop, sharing RadioCog.

Auth: Discord OAuth2 code exchange + access_token validation via Discord API.
"""
import logging
from functools import wraps
from typing import Any

import aiohttp
from aiohttp import web

from amc_peripheral.settings import (
    DISCORD_CLIENT_ID,
    DISCORD_CLIENT_SECRET,
    GUILD_ID,
    DJ_ROLE_ID,
)
from amc_peripheral.radio.radio_server import get_current_song_metadata, parse_song_info

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------
DISCORD_API = "https://discord.com/api/v10"


async def _discord_user(session: aiohttp.ClientSession, access_token: str) -> dict | None:
    """Fetch the authenticated Discord user from an OAuth2 access_token."""
    async with session.get(
        f"{DISCORD_API}/users/@me",
        headers={"Authorization": f"Bearer {access_token}"},
    ) as resp:
        if resp.status != 200:
            return None
        return await resp.json()


async def _discord_guild_member(
    session: aiohttp.ClientSession, access_token: str, guild_id: int
) -> dict | None:
    """Fetch the user's guild member object (includes roles)."""
    async with session.get(
        f"{DISCORD_API}/users/@me/guilds/{guild_id}/member",
        headers={"Authorization": f"Bearer {access_token}"},
    ) as resp:
        if resp.status != 200:
            return None
        return await resp.json()


def require_auth(fn):
    """Decorator: validate Bearer token, attach user + member to request."""

    @wraps(fn)
    async def wrapper(request: web.Request) -> web.Response:
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return web.json_response({"error": "unauthorized"}, status=401)
        access_token = auth_header[7:]

        http_session: aiohttp.ClientSession = request.app["http_session"]

        user = await _discord_user(http_session, access_token)
        if not user:
            return web.json_response({"error": "invalid_token"}, status=401)

        member = await _discord_guild_member(http_session, access_token, GUILD_ID)

        request["discord_user"] = user
        request["discord_member"] = member
        request["access_token"] = access_token
        return await fn(request)

    return wrapper


def _is_dj_or_admin(request: web.Request) -> bool:
    """Check if the authenticated user has DJ or admin role."""
    member = request.get("discord_member")
    if not member:
        return False
    roles = member.get("roles", [])
    return str(DJ_ROLE_ID) in roles


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

async def handle_token_exchange(request: web.Request) -> web.Response:
    """Exchange a Discord OAuth2 authorization code for an access_token."""
    body = await request.json()
    code = body.get("code")
    if not code:
        return web.json_response({"error": "missing code"}, status=400)

    http_session: aiohttp.ClientSession = request.app["http_session"]
    async with http_session.post(
        f"{DISCORD_API}/oauth2/token",
        data={
            "client_id": DISCORD_CLIENT_ID,
            "client_secret": DISCORD_CLIENT_SECRET,
            "grant_type": "authorization_code",
            "code": code,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    ) as resp:
        data = await resp.json()
        if resp.status != 200:
            log.warning(f"Token exchange failed: {data}")
            return web.json_response({"error": "token_exchange_failed"}, status=400)
        return web.json_response({"access_token": data["access_token"]})


@require_auth
async def handle_now_playing(request: web.Request) -> web.Response:
    """Get the currently playing song + like count."""
    http_session: aiohttp.ClientSession = request.app["http_session"]
    cog = request.app["radio_cog"]

    metadata = await get_current_song_metadata(http_session)
    if not metadata:
        return web.json_response({"playing": False})

    song_info = parse_song_info(metadata)
    if not song_info:
        return web.json_response({"playing": False})

    like_count = cog.db.get_song_like_count(song_info["song_title"])
    return web.json_response({
        "playing": True,
        "song_title": song_info["song_title"],
        "folder": song_info["folder"],
        "requester": song_info["requester"],
        "like_count": like_count,
    })


@require_auth
async def handle_queue_song(request: web.Request) -> web.Response:
    """Queue a song by search query or YouTube link."""
    body = await request.json()
    query = body.get("query", "").strip()
    if not query:
        return web.json_response({"error": "missing query"}, status=400)

    cog = request.app["radio_cog"]
    user = request["discord_user"]
    requester = user.get("global_name") or user.get("username", "Web User")
    discord_id = user.get("id")

    bypass = _is_dj_or_admin(request)

    try:
        title, _ = await cog.request_song(
            query,
            requester=requester,
            discord_id=discord_id,
            bypass_throttling=bypass,
        )
        return web.json_response({"ok": True, "title": title})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)


@require_auth
async def handle_skip(request: web.Request) -> web.Response:
    """Skip the current track."""
    cog = request.app["radio_cog"]
    http_session: aiohttp.ClientSession = request.app["http_session"]
    await cog.lq.skip_current_track(http_session, "song_requests")
    return web.json_response({"ok": True})


@require_auth
async def handle_like(request: web.Request) -> web.Response:
    """Like the currently playing song."""
    cog = request.app["radio_cog"]
    http_session: aiohttp.ClientSession = request.app["http_session"]
    user = request["discord_user"]

    metadata = await get_current_song_metadata(http_session)
    if not metadata:
        return web.json_response({"error": "nothing playing"}, status=400)

    song_info = parse_song_info(metadata)
    if not song_info:
        return web.json_response({"error": "cannot identify song"}, status=400)

    cog.db.add_like(discord_id=user["id"], song_title=song_info["song_title"])
    return web.json_response({"ok": True, "song_title": song_info["song_title"]})


@require_auth
async def handle_dislike(request: web.Request) -> web.Response:
    """Dislike the currently playing song."""
    cog = request.app["radio_cog"]
    http_session: aiohttp.ClientSession = request.app["http_session"]
    user = request["discord_user"]

    metadata = await get_current_song_metadata(http_session)
    if not metadata:
        return web.json_response({"error": "nothing playing"}, status=400)

    song_info = parse_song_info(metadata)
    if not song_info:
        return web.json_response({"error": "cannot identify song"}, status=400)

    cog.db.add_dislike(discord_id=user["id"], song_title=song_info["song_title"])
    return web.json_response({"ok": True, "song_title": song_info["song_title"]})


@require_auth
async def handle_recent_requests(request: web.Request) -> web.Response:
    """Get recent song requests."""
    cog = request.app["radio_cog"]
    limit = int(request.query.get("limit", "20"))
    rows = cog.db.get_recent_requests(limit=limit)
    return web.json_response({"requests": rows})


@require_auth
async def handle_top_liked(request: web.Request) -> web.Response:
    """Get top liked songs."""
    cog = request.app["radio_cog"]
    limit = int(request.query.get("limit", "10"))
    top = cog.db.get_top_liked_songs(limit=limit)
    return web.json_response({"songs": top})


@require_auth
async def handle_queue_trending(request: web.Request) -> web.Response:
    """Queue a trending song from Last.fm."""
    cog = request.app["radio_cog"]
    try:
        song_query = await cog._pick_trending_song()
        title, _ = await cog.request_song(
            song_query,
            requester="DJ Annie",
            discord_id=None,
            bypass_throttling=True,
        )
        cog.db.add_auto_queue(song_title=str(title))
        return web.json_response({"ok": True, "title": title})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)


# ---------------------------------------------------------------------------
# Phase 2 stubs
# ---------------------------------------------------------------------------

async def _phase2_stub(_request: web.Request) -> web.Response:
    return web.json_response(
        {"error": "not_implemented", "message": "Coming in Phase 2"},
        status=501,
    )


# ---------------------------------------------------------------------------
# CORS middleware
# ---------------------------------------------------------------------------

@web.middleware
async def cors_middleware(request: web.Request, handler: Any) -> web.Response:
    if request.method == "OPTIONS":
        resp = web.Response(status=204)
    else:
        try:
            resp = await handler(request)
        except web.HTTPException as ex:
            resp = ex
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    return resp


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def create_api_app(
    radio_cog: Any,
    http_session: aiohttp.ClientSession,
) -> web.Application:
    """Create the aiohttp web application."""
    app = web.Application(middlewares=[cors_middleware])

    app["radio_cog"] = radio_cog
    app["http_session"] = http_session

    # Phase 1 — functional
    app.router.add_post("/api/token", handle_token_exchange)
    app.router.add_get("/api/now-playing", handle_now_playing)
    app.router.add_post("/api/queue", handle_queue_song)
    app.router.add_post("/api/skip", handle_skip)
    app.router.add_post("/api/like", handle_like)
    app.router.add_post("/api/dislike", handle_dislike)
    app.router.add_get("/api/recent-requests", handle_recent_requests)
    app.router.add_get("/api/top-liked", handle_top_liked)
    app.router.add_post("/api/queue-trending", handle_queue_trending)

    # Phase 2 — stubs
    for method, path in [
        ("GET", "/api/playlist"),
        ("POST", "/api/playlist/add"),
        ("POST", "/api/playlist/recompile"),
        ("GET", "/api/user-playlists"),
        ("POST", "/api/user-playlists"),
        ("POST", "/api/talkshow/generate"),
        ("POST", "/api/segment/generate"),
        ("POST", "/api/track/generate"),
        ("POST", "/api/voice-announce"),
        ("GET", "/api/news/recent"),
        ("GET", "/api/jingles/recent"),
        ("POST", "/api/news/regenerate"),
        ("POST", "/api/jingles/regenerate"),
        ("POST", "/api/mode/event"),
        ("POST", "/api/mode/race"),
    ]:
        if method == "GET":
            app.router.add_get(path, _phase2_stub)
        else:
            app.router.add_post(path, _phase2_stub)

    return app


async def start_api_server(
    radio_cog: Any,
    http_session: aiohttp.ClientSession,
    port: int = 7001,
) -> web.AppRunner:
    """Start the API server. Call from the bot's event loop."""
    app = create_api_app(radio_cog, http_session)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", port)
    await site.start()
    log.info(f"Radio API server listening on http://127.0.0.1:{port}")
    return runner
