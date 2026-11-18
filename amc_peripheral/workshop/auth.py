"""Discord OAuth2 sign-in for the workshop site.

The workshop browser is a standalone aiohttp app on amc-peripheral, so it does
not have Django's session stack. Sign-in is a plain browser authorization-code
flow against the Discord REST API, and the session is a signed, stateless
cookie — the site has no user table to keep sessions in.

Config comes from the environment (see ``SSOSettings.from_env``). When the
client id/secret or the signing key is missing the whole feature stays dark:
``SSOSettings.enabled`` is false, the header hides the sign-in link and the
auth routes answer 404.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlencode

DISCORD_API = "https://discord.com/api/v10"
AUTHORIZE_URL = "https://discord.com/oauth2/authorize"
# ``guilds`` is what lets us answer "is this user in the club?" without a bot
# token on the web process. It only lists guilds the *user* is a member of.
SCOPE = "identify guilds"

SESSION_COOKIE = "amc_workshop_session"
STATE_COOKIE = "amc_workshop_state"
SESSION_VERSION = 1

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class SSOSettings:
    """Discord OAuth2 configuration for the workshop site."""

    client_id: str = ""
    client_secret: str = ""
    session_secret: str = ""
    guild_id: int = 0
    public_url: str = "https://www.aseanmotorclub.com"
    session_ttl: int = 30 * 24 * 3600
    timeout_seconds: float = 10.0

    @property
    def enabled(self) -> bool:
        return bool(self.client_id and self.client_secret and self.session_secret)

    @property
    def redirect_uri(self) -> str:
        return f"{self.public_url.rstrip('/')}/workshop/auth/callback"

    @classmethod
    def from_env(cls) -> SSOSettings:
        try:
            guild_id = int(os.environ.get("AMC_WORKSHOP_DISCORD_GUILD_ID", "0") or 0)
        except ValueError:
            guild_id = 0
        try:
            ttl = int(os.environ.get("AMC_WORKSHOP_SESSION_TTL", "") or 0)
        except ValueError:
            ttl = 0
        return cls(
            client_id=os.environ.get("AMC_WORKSHOP_DISCORD_CLIENT_ID", "").strip(),
            client_secret=os.environ.get(
                "AMC_WORKSHOP_DISCORD_CLIENT_SECRET", ""
            ).strip(),
            session_secret=os.environ.get("AMC_WORKSHOP_SESSION_SECRET", "").strip(),
            guild_id=guild_id,
            public_url=os.environ.get(
                "AMC_WORKSHOP_PUBLIC_URL", "https://www.aseanmotorclub.com"
            ).rstrip("/"),
            session_ttl=ttl or 30 * 24 * 3600,
        )


# ---------------------------------------------------------------------------
# Signed session cookie
# ---------------------------------------------------------------------------


def _b64_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _b64_decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def sign_session(claims: dict[str, Any], secret: str, ttl: int) -> str:
    """Serialize claims into a tamper-evident ``payload.signature`` token."""
    payload = {**claims, "v": SESSION_VERSION, "exp": int(time.time()) + int(ttl)}
    body = _b64_encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    )
    signature = _b64_encode(
        hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest()
    )
    return f"{body}.{signature}"


def verify_session(token: str | None, secret: str) -> dict[str, Any] | None:
    """Return the claims of a valid session token, or ``None``."""
    if not token or not secret or len(token) > 4096 or token.count(".") != 1:
        return None
    body, signature = token.split(".", 1)
    expected = _b64_encode(
        hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest()
    )
    if not hmac.compare_digest(signature, expected):
        return None
    try:
        claims = json.loads(_b64_decode(body))
    except (ValueError, TypeError):
        return None
    if not isinstance(claims, dict) or claims.get("v") != SESSION_VERSION:
        return None
    try:
        expires = int(claims.get("exp") or 0)
    except (TypeError, ValueError):
        return None
    if expires < time.time():
        return None
    return claims


def new_state() -> str:
    return secrets.token_urlsafe(24)


def authorize_url(sso: SSOSettings, state: str) -> str:
    return (
        AUTHORIZE_URL
        + "?"
        + urlencode(
            {
                "client_id": sso.client_id,
                "response_type": "code",
                "scope": SCOPE,
                "redirect_uri": sso.redirect_uri,
                "state": state,
            }
        )
    )


def avatar_url(user: dict[str, Any], size: int = 64) -> str:
    """Discord CDN avatar, falling back to the default embed avatar."""
    user_id = str(user.get("id") or "0")
    digest = user.get("avatar")
    if digest:
        return (
            f"https://cdn.discordapp.com/avatars/{quote(user_id)}/{quote(str(digest))}"
            f".png?size={int(size)}"
        )
    try:
        index = (int(user_id) >> 22) % 6
    except ValueError:
        index = 0
    return f"https://cdn.discordapp.com/embed/avatars/{index}.png"


# ---------------------------------------------------------------------------
# OAuth2 code exchange
# ---------------------------------------------------------------------------


async def _fetch_guild_ids(session, access_token: str) -> set[str]:
    async with session.get(
        f"{DISCORD_API}/users/@me/guilds",
        headers={"Authorization": f"Bearer {access_token}"},
    ) as response:
        if response.status != 200:
            log.warning("Discord guild list failed: %s", response.status)
            return set()
        guilds = await response.json()
    if not isinstance(guilds, list):
        return set()
    return {str(guild.get("id")) for guild in guilds if isinstance(guild, dict)}


async def sign_in(sso: SSOSettings, code: str, session) -> dict[str, Any] | None:
    """Exchange an authorization code for verified session claims.

    Returns ``None`` for every failure mode — the caller answers with a
    generic "sign-in failed" so a Discord outage and a replayed code look the
    same to the browser.
    """
    if not sso.enabled or not code:
        return None
    async with session.post(
        f"{DISCORD_API}/oauth2/token",
        data={
            "client_id": sso.client_id,
            "client_secret": sso.client_secret,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": sso.redirect_uri,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    ) as response:
        data = await response.json(content_type=None)
        if response.status != 200 or not isinstance(data, dict):
            log.warning("Discord token exchange failed: %s %s", response.status, data)
            return None
    access_token = data.get("access_token")
    if not access_token:
        return None

    async with session.get(
        f"{DISCORD_API}/users/@me",
        headers={"Authorization": f"Bearer {access_token}"},
    ) as response:
        if response.status != 200:
            log.warning("Discord user lookup failed: %s", response.status)
            return None
        user = await response.json(content_type=None)
    if not isinstance(user, dict) or not user.get("id"):
        return None

    guild_ids = await _fetch_guild_ids(session, access_token)
    return claims_from_discord(user, guild_ids, sso.guild_id)


def claims_from_discord(
    user: dict[str, Any], guild_ids: set[str], guild_id: int
) -> dict[str, Any]:
    """Minimal, self-contained session claims — nothing here needs a refresh."""
    return {
        "sub": str(user["id"]),
        "u": str(user.get("username") or ""),
        "n": user.get("global_name") or None,
        "a": avatar_url(user, 64),
        "m": bool(guild_id) and str(guild_id) in guild_ids,
        "g": bool(guild_id),
        "iat": int(time.time()),
    }


def display_name(claims: dict[str, Any] | None) -> str:
    if not claims:
        return ""
    return str(claims.get("n") or claims.get("u") or "")


def csrf_token(claims: dict[str, Any] | None, secret: str) -> str:
    """Per-session CSRF token.

    SameSite=Lax already keeps a cross-site form from carrying the session
    cookie, but a subdomain of ours is same-site and would pass: a token bound
    to the session's own ``sub``/``iat`` closes that.
    """
    if not claims:
        return ""
    material = f"{claims.get('sub')}:{claims.get('iat')}".encode()
    return hmac.new(secret.encode(), material, hashlib.sha256).hexdigest()[:32]


def verify_csrf(claims: dict[str, Any] | None, token: str | None, secret: str) -> bool:
    expected = csrf_token(claims, secret)
    if not expected or not token:
        return False
    return hmac.compare_digest(expected, str(token))


# ---------------------------------------------------------------------------
# Steam identity (optional, read-only)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Identity:
    """A player's in-game identity, as the backend knows it."""

    steam_id: int
    character_guids: frozenset[str] = frozenset()


class PlayerIdentityRepository:
    """Resolve a Discord user to their AMC player row.

    Read-only, single fixed query, and disabled unless a DSN is configured —
    the same posture as ``CharacterVehicleRepository``. The workshop scrape
    knows Steam ids (``club_character``) but no Discord ids, so this is the
    only join that can turn "who signed in" into "which builds are theirs".

    The lookup returns the player's Steam id *and* their character GUIDs: the
    GUID set is what authorises a claim, because a GUID is minted by the game
    server and bound to one player, unlike a name or an account id.

    ``amc_player.unique_id`` is the primary key, so ``amc_character.player_id``
    holds the Steam id — not a surrogate row id.
    """

    def __init__(self, dsn: str | None, *, enabled: bool = True, ttl: float = 300.0):
        self.dsn = dsn
        self.enabled = bool(dsn) and enabled
        self.ttl = ttl
        self._cache: dict[str, tuple[float, Identity | None]] = {}

    def _connect(self):
        import psycopg2

        conn = psycopg2.connect(
            self.dsn,
            options=("-c statement_timeout=3000 -c default_transaction_read_only=on"),
        )
        conn.set_session(readonly=True, autocommit=True)
        return conn

    def identity_for(self, discord_id: str | int) -> Identity | None:
        """Steam id + character GUIDs for a Discord user, cached for ``ttl``."""
        if not self.enabled:
            return None
        key = str(discord_id)
        now = time.monotonic()
        hit = self._cache.get(key)
        if hit is not None and now - hit[0] < self.ttl:
            return hit[1]
        value = self._fetch(key)
        self._cache[key] = (now, value)
        return value

    def _fetch(self, key: str) -> Identity | None:
        try:
            player_id = int(key)
        except (TypeError, ValueError):
            return None
        try:
            conn = self._connect()
        except Exception as exc:  # noqa: BLE001 - psycopg2 raises a tree of errors
            log.warning("player identity lookup unavailable: %s", exc)
            return None
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT p.unique_id, c.guid FROM amc_player p "
                    "LEFT JOIN amc_character c ON c.player_id = p.unique_id "
                    "WHERE p.discord_user_id = %s",
                    (player_id,),
                )
                rows = cur.fetchall()
        except Exception as exc:  # noqa: BLE001 - never fail the page on a DB hiccup
            log.warning("player identity lookup failed: %s", exc)
            return None
        finally:
            conn.close()
        if not rows or rows[0][0] is None:
            return None
        guids = frozenset(str(guid).upper() for _, guid in rows if guid)
        return Identity(steam_id=int(rows[0][0]), character_guids=guids)

    def steam_id_for(self, discord_id: str | int) -> int | None:
        identity = self.identity_for(discord_id)
        return identity.steam_id if identity else None
