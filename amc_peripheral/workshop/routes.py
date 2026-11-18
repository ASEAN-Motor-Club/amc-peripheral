"""HTTP routes for the workshop browser."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import mimetypes
import re
import secrets
from datetime import UTC, date, datetime
from html import escape
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode

import aiohttp
from aiohttp import web
from aiohttp.web_fileresponse import CONTENT_TYPES
from jinja2 import Environment, FileSystemLoader, select_autoescape

from .auth import (
    SESSION_COOKIE,
    STATE_COOKIE,
    PlayerIdentityRepository,
    SSOSettings,
    authorize_url,
    csrf_token,
    display_name,
    new_state,
    sign_in,
    sign_session,
    verify_csrf,
    verify_session,
)
from .character_vehicles import CharacterVehicleRepository, CharacterVehicleUnavailable
from .claims import ClaimSynchroniser
from .collections import CollectionError, CollectionStore
from .community import CommunityStore
from .config import WorkshopSettings
from .covers import write_author_cover
from .payloads import (
    PayloadError,
    asset_version_for,
    decode_payload,
    normalize_workshop,
    vehicle_display_name,
)
from .placeholders import vehicle_placeholder_url
from .queries import (
    CursorStale,
    ListFilters,
    QueryError,
    WorkshopRepository,
)
from .ratelimit import RateLimiter
from .snapshots import (
    PRIORITY_DIRECT,
    PRIORITY_VISIBLE,
    SnapshotJob,
    SnapshotStore,
    render_key,
)
from .tags import TagError, TagStore, normalise_tag

log = logging.getLogger(__name__)
HERE = Path(__file__).resolve().parent
ITEM_CODE = re.compile(r"#([0-9]{1,9})")


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def search_query(request: web.Request) -> str:
    return " ".join(request.query.get("q", "").strip().split())[:80]


def search_item_id(query: str) -> int | None:
    match = ITEM_CODE.fullmatch(query)
    return int(match.group(1)) if match else None


def _json_error(code: str, message: str, status: int = 400) -> web.Response:
    return web.json_response(
        {"error": {"code": code, "message": message}}, status=status
    )


def _iso(value: str | None) -> str | None:
    if not value:
        return None
    return value.replace(" ", "T") + "Z" if "T" not in value else value


def _date_long(value: str | None) -> str:
    """Render an ISO date as ``25 Feb 2025`` for notice copy."""
    if not value:
        return ""
    try:
        parsed = date.fromisoformat(str(value)[:10])
    except ValueError:
        return str(value)[:10]
    return f"{parsed.day} {parsed.strftime('%b %Y')}"


def _page(value: str | int | None, default: int, maximum: int) -> int:
    try:
        number = int(value) if value is not None else default
    except (TypeError, ValueError):
        raise QueryError("invalid_page_size", "Page size must be an integer") from None
    if number < 1:
        raise QueryError("invalid_page_size", "Page size must be positive")
    return min(number, maximum)


class AttachmentCatalogue:
    def __init__(self, viewer_root: Path):
        self.path = viewer_root / "attachments" / "catalog.json"
        self._mtime: float | None = None
        self._keys: set[str] | None = None
        self._lock = asyncio.Lock()

    async def keys(self) -> set[str]:
        async with self._lock:
            try:
                stat = self.path.stat()
            except OSError:
                return set()
            if self._mtime == stat.st_mtime and self._keys is not None:
                return self._keys

            def load():
                data = json.loads(self.path.read_text())
                actors = data.get("actors") or {}
                return (
                    {str(key) for key in actors} if isinstance(actors, dict) else set()
                )

            self._keys = await asyncio.to_thread(load)
            self._mtime = stat.st_mtime
            return self._keys


def create_app(
    settings: WorkshopSettings | None = None,
    *,
    repository: WorkshopRepository | None = None,
    character_vehicles: CharacterVehicleRepository | None = None,
    sso: SSOSettings | None = None,
    player_identity: PlayerIdentityRepository | None = None,
) -> web.Application:
    # Some minimal Python builds lack a system mime.types entry for WebP.
    mimetypes.add_type("image/webp", ".webp")
    CONTENT_TYPES.add_type("image/webp", ".webp")
    settings = settings or WorkshopSettings.from_env()
    settings.validate()
    repository = repository or WorkshopRepository(
        settings.source_db,
        site_db=settings.site_db,
        cache_ttl=settings.cache_ttl_seconds,
    )
    character_vehicles = character_vehicles or CharacterVehicleRepository(
        settings.character_vehicle_dsn,
        enabled=settings.character_vehicle_public,
    )
    sso = sso or SSOSettings.from_env()
    player_identity = player_identity or PlayerIdentityRepository(
        settings.player_dsn, enabled=bool(settings.player_dsn)
    )

    env = Environment(
        loader=FileSystemLoader(str(HERE / "templates")),
        autoescape=select_autoescape(("html", "xml")),
        enable_async=False,
    )
    env.filters["iso"] = _iso
    env.filters["date_long"] = _date_long
    env.filters["tag_label"] = lambda value: str(value or "").replace("_", " ")
    env.filters["vehicle_name"] = vehicle_display_name
    env.filters["vehicle_placeholder"] = vehicle_placeholder_url

    app = web.Application(client_max_size=64 * 1024)
    app["settings"] = settings
    app["repository"] = repository
    app["character_vehicles"] = character_vehicles
    app["attachment_catalogue"] = AttachmentCatalogue(settings.viewer_root)
    app["sso"] = sso
    app["player_identity"] = player_identity
    (settings.snapshot_root / "public").mkdir(parents=True, exist_ok=True)
    snapshots = SnapshotStore(settings.site_db)
    community = CommunityStore(settings.site_db)
    app["community"] = community
    claims = ClaimSynchroniser(community, repository, player_identity)
    tags_store = TagStore(settings.site_db)
    app["tags"] = tags_store
    collections_store = CollectionStore(settings.site_db)
    app["collections"] = collections_store
    limiters = {
        "like": RateLimiter(limit=1, window=2.0),
        "collection": RateLimiter(limit=1, window=2.0),
        "tag": RateLimiter(limit=3, window=2.0),
    }
    app["limiters"] = limiters

    def snapshot_job(
        card: dict[str, Any], *, priority: int = PRIORITY_VISIBLE
    ) -> SnapshotJob | None:
        config_hash = card.get("configHash") or ""
        if not config_hash:
            return None
        version = asset_version_for(settings.viewer_root, card["vehicleKey"])
        key = render_key(
            source_kind="workshop",
            source_id=int(card["id"]),
            config_hash=config_hash,
            asset_version=version,
        )
        return SnapshotJob(
            cache_key=key,
            source_kind="workshop",
            source_id=int(card["id"]),
            config_hash=config_hash,
            asset_version=version,
            camera="default",
            priority=priority,
        )

    def attach_author_snapshots(authors: list[dict[str, Any]]) -> None:
        for author in authors:
            representative = author.get("representativeId")
            if not representative:
                continue
            card = repository.get_item(int(representative))
            if card is None:
                continue
            attach_snapshots([card])
            author["snapshotUrl"] = card.get("snapshotCardUrl")

    def attach_snapshots(items: list[dict[str, Any]]) -> None:
        jobs = []
        for card in items:
            job = snapshot_job(card)
            card["snapshotKey"] = job.cache_key if job else None
            if job:
                jobs.append(job)
        ready = snapshots.ready_map(
            "workshop",
            [(int(card["id"]), card.get("configHash") or "") for card in items],
        )
        current = snapshots.statuses([job.cache_key for job in jobs])
        for card in items:
            key = card.get("snapshotKey")
            status = current.get(key) if key else None
            meta = ready.get(int(card["id"]))
            card["snapshotUrl"] = meta["url"] if meta else None
            card["snapshotCardUrl"] = (
                meta["url"].replace(".webp", "-card.webp") if meta else None
            )
            card["snapshotStatus"] = (
                status["status"] if status else (meta["status"] if meta else "missing")
            )

    def author_cover(account_id: int, items: list[dict[str, Any]]) -> str | None:
        jobs = {int(item["id"]): job for item in items if (job := snapshot_job(item))}
        current = snapshots.statuses([job.cache_key for job in jobs.values()])
        candidates = []
        for item in items:
            job = jobs.get(int(item["id"]))
            if not job:
                continue
            snapshot = current.get(job.cache_key)
            if snapshot and snapshot.get("status") == "ready":
                candidates.append({**item, "snapshot": snapshot})
        return write_author_cover(
            account_id, candidates, settings.snapshot_root / "public"
        )

    @web.middleware
    async def errors(request: web.Request, handler):
        try:
            return await handler(request)
        except QueryError as exc:
            if request.path.startswith("/api/"):
                return _json_error(exc.code, exc.message, exc.status)
            return web.Response(text=exc.message, status=exc.status)
        except PayloadError as exc:
            log.warning("workshop payload rejected for %s: %s", request.path, exc)
            return _json_error(
                "invalid_payload", "Workshop configuration is unavailable", 422
            )
        except CharacterVehicleUnavailable:
            return _json_error("not_found", "CharacterVehicle not found", 404)
        except web.HTTPException:
            raise
        except Exception:
            log.exception("workshop request failed: %s", request.path)
            return _json_error("internal_error", "Internal server error", 500)

    app.middlewares.append(errors)

    async def http_session_startup(app: web.Application) -> None:
        app["http_session"] = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=sso.timeout_seconds)
        )

    async def http_session_cleanup(app: web.Application) -> None:
        session = app.get("http_session")
        if session is not None:
            await session.close()

    app.on_startup.append(http_session_startup)
    app.on_cleanup.append(http_session_cleanup)

    async def _post_csrf(request: web.Request) -> str | None:
        try:
            form = await request.post()
        except Exception:  # noqa: BLE001 - malformed body is a failed check, not a crash
            return None
        value = form.get("csrf")
        return str(value) if value is not None else None

    @web.middleware
    async def sessions(request: web.Request, handler):
        """Attach the signed-in user (or ``None``) to every request."""
        request["user"] = (
            verify_session(request.cookies.get(SESSION_COOKIE), sso.session_secret)
            if sso.enabled
            else None
        )
        user = request["user"]
        if request.method == "POST" and not (
            sso.enabled
            and verify_csrf(user, await _post_csrf(request), sso.session_secret)
        ):
            raise web.HTTPForbidden(
                text="This form expired or came from another site. Reload and try again."
            )
        if user and request.method == "GET" and not request.path.startswith("/api/"):
            # Claims are derived from the backend's character GUIDs; keep them in
            # step off page loads, throttled per member inside the synchroniser.
            try:
                await asyncio.to_thread(
                    claims.sync,
                    str(user.get("sub") or ""),
                    now=datetime.now(UTC).isoformat(timespec="seconds"),
                )
            except Exception:
                log.warning("claim sync failed", exc_info=True)
        return await handler(request)

    app.middlewares.append(sessions)

    def render(request: web.Request, template: str, **context) -> web.Response:
        context.setdefault("settings", settings)
        context.setdefault("user", request.get("user"))
        context.setdefault("user_name", display_name(request.get("user")))
        context.setdefault("sso_enabled", sso.enabled)
        context.setdefault(
            "csrf_token", csrf_token(request.get("user"), sso.session_secret)
        )
        context.setdefault("request_path", request.path_qs)
        html = env.get_template(template).render(**context)
        return web.Response(text=html, content_type="text/html")

    def mark_asset_availability(config: dict[str, Any]) -> dict[str, Any]:
        slug = config["vehicle"]["slug"]
        available = (settings.viewer_root / slug / f"{slug}.json").is_file()
        config["vehicle"]["assetAvailable"] = available
        if not available:
            config["renderReport"]["warnings"].insert(
                0,
                f"3D geometry is not available for {config['vehicle']['key']}; "
                "only its workshop metadata is shown.",
            )
        return config

    async def configuration(workshop_id: int) -> dict[str, Any]:
        row = await asyncio.to_thread(repository.get_viewer_row, workshop_id)
        if row is None:
            raise web.HTTPNotFound()
        raw = await asyncio.to_thread(
            decode_payload,
            row["json_z"],
            declared_bytes=row.get("json_len"),
            max_bytes=settings.max_payload_bytes,
        )
        keys = await app["attachment_catalogue"].keys()
        config = normalize_workshop(
            row,
            raw,
            asset_version=asset_version_for(settings.viewer_root, row["vehicle_key"]),
            known_attachment_keys=keys,
        )
        return mark_asset_availability(config)

    async def character_configuration(vehicle_id: int) -> dict[str, Any]:
        row = await asyncio.to_thread(character_vehicles.get, vehicle_id)
        if row is None:
            raise CharacterVehicleUnavailable
        keys = await app["attachment_catalogue"].keys()
        vehicle_name = str((row.get("config") or {}).get("VehicleName") or "")
        return normalize_character_vehicle_for(row, vehicle_name, keys)

    def normalize_character_vehicle_for(row, vehicle_name, keys):
        config = character_vehicles.normalize(
            row,
            asset_version=asset_version_for(settings.viewer_root, vehicle_name),
            known_attachment_keys=keys,
        )
        return mark_asset_availability(config)

    async def api_home(request: web.Request) -> web.Response:
        data = await asyncio.to_thread(repository.home, settings.home_limit)
        attach_snapshots(data["popular"] + data["newest"])
        attach_author_snapshots(data["authors"])
        return web.json_response(data)

    async def api_search(request: web.Request) -> web.Response:
        query = search_query(request)
        item_id = search_item_id(query)
        if item_id is not None:
            item = await asyncio.to_thread(repository.get_item, item_id)
            if item is None:
                return _json_error("not_found", "Workshop item not found", 404)
            return web.json_response({"type": "item", "item": item})
        authors = await asyncio.to_thread(repository.search_authors, query)
        return web.json_response(
            {"type": "authors", "query": query, "authors": authors}
        )

    async def api_list(request: web.Request) -> web.Response:
        query = request.query
        try:
            account_id = int(query["accountId"]) if query.get("accountId") else None
        except ValueError:
            raise QueryError("invalid_filter", "accountId must be an integer") from None
        filters = ListFilters(
            vehicle=query.get("vehicle"),
            account_id=account_id,
            paint=query.get("paint") == "1",
            decal=query.get("decal") == "1",
            parts=query.get("parts") == "1",
            tuning=query.get("tuning") == "1",
            club=query.get("club") == "1",
        )
        limit = _page(query.get("limit"), settings.page_size, settings.max_page_size)
        sort = query.get("sort", "popular")
        data = await asyncio.to_thread(
            repository.list_items,
            sort=sort,
            filters=filters,
            limit=limit,
            cursor=query.get("cursor"),
        )
        attach_snapshots(data["items"])
        return web.json_response(data)

    async def api_item(request: web.Request) -> web.Response:
        item = await asyncio.to_thread(
            repository.get_item, int(request.match_info["id"])
        )
        if item is None:
            return _json_error("not_found", "Workshop item not found", 404)
        return web.json_response(item)

    async def api_viewer(request: web.Request) -> web.Response:
        config = await configuration(int(request.match_info["id"]))
        etag = f'"{config["source"]["configHash"]}"'
        if request.headers.get("If-None-Match") == etag:
            raise web.HTTPNotModified(headers={"ETag": etag})
        return web.json_response(
            config,
            headers={
                "ETag": etag,
                "Cache-Control": "public, max-age=300",
            },
        )

    async def api_character_viewer(request: web.Request) -> web.Response:
        config = await character_configuration(int(request.match_info["id"]))
        etag = f'"{config["source"]["configHash"]}"'
        if request.headers.get("If-None-Match") == etag:
            raise web.HTTPNotModified(headers={"ETag": etag})
        return web.json_response(
            config,
            headers={
                "ETag": etag,
                "Cache-Control": "private, no-store",
            },
        )

    async def api_character_meta(request: web.Request) -> web.Response:
        row = await asyncio.to_thread(
            character_vehicles.meta, int(request.match_info["id"])
        )
        if row is None:
            return _json_error("not_found", "CharacterVehicle not found", 404)
        return web.json_response(row)

    async def api_snapshot(request: web.Request) -> web.Response:
        workshop_id = int(request.match_info["id"])
        config = await configuration(workshop_id)
        item = await asyncio.to_thread(repository.get_item, workshop_id)
        if item is None:
            return _json_error("not_found", "Workshop item not found", 404)
        if not config["vehicle"].get("assetAvailable"):
            return web.json_response({"status": "unsupported", "url": None}, status=200)
        item["configHash"] = config["source"]["configHash"]
        priority = (
            PRIORITY_VISIBLE if request.query.get("via") == "card" else PRIORITY_DIRECT
        )
        job = snapshot_job(item, priority=priority)
        if job is None:
            return _json_error(
                "invalid_payload", "Configuration has no content hash", 422
            )
        status = await asyncio.to_thread(snapshots.enqueue, job)
        return web.json_response(
            status,
            status=200 if status["status"] == "ready" else 202,
            headers={"Cache-Control": "no-store", "Retry-After": "10"},
        )

    async def api_authors(request: web.Request) -> web.Response:
        author = await asyncio.to_thread(
            repository.author, int(request.match_info["id"])
        )
        if author is None:
            return _json_error("not_found", "Author not found", 404)
        listing = await asyncio.to_thread(
            repository.list_items,
            sort="new",
            filters=ListFilters(account_id=author["accountId"]),
            limit=settings.page_size,
        )
        return web.json_response({"author": author, **listing})

    async def api_vehicles(request: web.Request) -> web.Response:
        return web.json_response(
            {"vehicles": await asyncio.to_thread(repository.vehicles)}
        )

    async def api_health(request: web.Request) -> web.Response:
        stats, snapshot_health = await asyncio.gather(
            asyncio.to_thread(repository.stats),
            asyncio.to_thread(snapshots.health),
        )
        return web.json_response(
            {"status": "ok", **stats, "snapshots": snapshot_health}
        )

    async def api_snapshot_batch(request: web.Request) -> web.Response:
        raw = request.query.get("keys", "")
        keys = [key for key in raw.split(",") if key]
        allowed = set("0123456789abcdef")
        if (
            not keys
            or len(keys) > 48
            or any(
                len(key) != 64 or any(char not in allowed for char in key)
                for key in keys
            )
        ):
            return _json_error(
                "invalid_keys",
                "keys must be 1-48 comma-separated sha256 digests",
            )
        statuses = await asyncio.to_thread(snapshots.statuses, keys)
        return web.json_response(
            {"snapshots": {key: statuses.get(key) for key in keys}},
            headers={"Cache-Control": "no-store"},
        )

    async def page_home(request: web.Request) -> web.Response:
        data, stats = await asyncio.gather(
            asyncio.to_thread(repository.home, settings.home_limit),
            asyncio.to_thread(repository.stats),
        )
        attach_snapshots(data["popular"] + data["newest"])
        attach_author_snapshots(data["authors"])
        tags = await asyncio.to_thread(request.app["tags"].index, limit=12)
        return render(
            request, "home.html", page="home", data=data, stats=stats, tags=tags
        )

    async def page_search(request: web.Request) -> web.Response:
        query = search_query(request)
        item_id = search_item_id(query)
        if item_id is not None:
            item = await asyncio.to_thread(repository.get_item, item_id)
            if item is None:
                raise web.HTTPNotFound()
            raise web.HTTPFound(f"/workshop/items/{item_id}/")
        if query.startswith("#") and query != "#":
            # "#cat" is a tag lookup, not a text search — same trick as item codes.
            canonical = normalise_tag(query)
            usage = await asyncio.to_thread(request.app["tags"].usage, canonical)
            if canonical and usage is not None:
                from urllib.parse import quote

                raise web.HTTPFound(
                    f"/workshop/tags/{quote(canonical, safe='')}/"
                )
        authors = await asyncio.to_thread(repository.search_authors, query)
        vehicles = await asyncio.to_thread(repository.search_vehicles, query)
        attach_author_snapshots(authors)
        return render(
            request,
            "search.html",
            page="search",
            query=query,
            authors=authors,
            vehicles=vehicles,
        )

    async def page_gallery(request: web.Request) -> web.Response:
        query = request.query
        try:
            account_id = int(query["accountId"]) if query.get("accountId") else None
        except ValueError:
            raise QueryError("invalid_filter", "accountId must be an integer") from None
        filters = ListFilters(
            vehicle=query.get("vehicle"),
            account_id=account_id,
            paint=query.get("paint") == "1",
            decal=query.get("decal") == "1",
            parts=query.get("parts") == "1",
            tuning=query.get("tuning") == "1",
            club=query.get("club") == "1",
        )
        try:
            data, vehicles = await asyncio.gather(
                asyncio.to_thread(
                    repository.list_items,
                    sort=query.get("sort", "popular"),
                    filters=filters,
                    limit=settings.page_size,
                    cursor=query.get("cursor"),
                ),
                asyncio.to_thread(repository.vehicles),
            )
        except CursorStale:
            # The popularity ranking was rebuilt since this cursor was issued.
            # Cursors cannot survive a new aggregate run, so restart the listing
            # at page one instead of showing a dead end.
            params = [(key, value) for key, value in query.items() if key != "cursor"]
            target = "/workshop/gallery/"
            if params:
                target += "?" + urlencode(params)
            raise web.HTTPFound(target) from None
        next_query = {key: value for key, value in query.items() if key != "cursor"}
        attach_snapshots(data["items"])
        if data.get("nextCursor"):
            next_query["cursor"] = data["nextCursor"]
        next_url = (
            "/workshop/gallery/?" + urlencode(next_query)
            if data.get("nextCursor")
            else None
        )
        return render(
            request,
            "gallery.html",
            page="gallery",
            data=data,
            vehicles=vehicles,
            filters=filters,
            query=query,
            next_url=next_url,
        )

    async def page_item(request: web.Request) -> web.Response:
        workshop_id = int(request.match_info["id"])
        item = await asyncio.to_thread(repository.get_item, workshop_id)
        if item is None:
            raise web.HTTPNotFound()
        try:
            config = await configuration(workshop_id)
        except (PayloadError, web.HTTPNotFound):
            config = None
        snapshot = None
        if config and config["vehicle"].get("assetAvailable"):
            item["configHash"] = config["source"]["configHash"]
            job = snapshot_job(item, priority=PRIORITY_DIRECT)
            if job:
                snapshot = snapshots.enqueue(job)
        similar = await asyncio.to_thread(
            repository.similar_items,
            item,
            limit=settings.similarity_limit,
            min_sim=settings.similarity_min,
            copy_threshold=settings.similarity_copy_threshold,
            flag_min_layers=settings.similarity_flag_min_layers,
            flag_min_similarity=settings.similarity_flag_min_similarity,
        )
        if similar["items"]:
            attach_snapshots(similar["items"])
        likes = await asyncio.to_thread(community.like_count, workshop_id)
        viewer_user = request.get("user")
        liked = bool(
            viewer_user
            and workshop_id
            in await asyncio.to_thread(
                community.liked_ids, str(viewer_user.get("sub")), [workshop_id]
            )
        )
        in_collections = await asyncio.to_thread(
            request.app["collections"].collections_for_item, workshop_id
        )
        my_collections = (
            await asyncio.to_thread(
                request.app["collections"].owned, str(request["user"]["sub"])
            )
            if request.get("user")
            else []
        )
        meta = await asyncio.to_thread(community.meta, workshop_id)
        tags = await asyncio.to_thread(request.app["tags"].item_tags, workshop_id)
        claim = await asyncio.to_thread(community.claim_for, workshop_id)
        claim_owner = None
        if claim is not None and claim.revoked_at is None:
            owner = await asyncio.to_thread(community.profile, claim.discord_id)
            viewer = request.get("user")
            claim_owner = {
                "discordId": claim.discord_id,
                "name": owner.display_name
                if owner is not None and not owner.hidden and owner.display_name
                else None,
                "yours": bool(viewer) and str(viewer.get("sub")) == claim.discord_id,
            }
        return render(
            request,
            "item.html",
            page="workshop",
            item=item,
            config=config,
            snapshot=snapshot,
            similar=similar,
            claim=claim_owner,
            likes=likes,
            liked=liked,
            in_collections=in_collections,
            my_collections=my_collections,
            meta=meta,
            tags=tags,
            can_edit=bool(claim_owner and claim_owner["yours"]),
        )

    async def item_like(request: web.Request) -> web.Response:
        """Toggle a member's like. Form post for the no-JS path, JSON if asked."""
        workshop_id = int(request.match_info["id"])
        user = request.get("user")
        if not user:
            raise web.HTTPFound(
                f"/workshop/auth/login?next=/workshop/items/{workshop_id}/"
            )
        limiters: dict[str, RateLimiter] = request.app["limiters"]
        if not limiters["like"].allow(str(user.get("sub"))):
            raise web.HTTPTooManyRequests(text="One at a time.")
        item = await asyncio.to_thread(repository.get_item, workshop_id)
        if item is None:
            raise web.HTTPNotFound()
        liked, count = await asyncio.to_thread(
            community.toggle_like,
            workshop_id=workshop_id,
            discord_id=str(user.get("sub")),
            now=_now_iso(),
        )
        if "application/json" in request.headers.get("Accept", ""):
            return web.json_response({"liked": liked, "count": count})
        raise web.HTTPSeeOther(f"/workshop/items/{workshop_id}/")

    async def page_item_viewer(request: web.Request) -> web.Response:
        workshop_id = int(request.match_info["id"])
        item = await asyncio.to_thread(repository.get_item, workshop_id)
        if item is None:
            raise web.HTTPNotFound()
        raise web.HTTPMovedPermanently(f"/workshop/items/{workshop_id}/")

    async def page_authors(request: web.Request) -> web.Response:
        query = request.query.get("q", "")
        try:
            page = max(1, int(request.query.get("page", "1")))
        except ValueError:
            raise QueryError("invalid_page", "page must be an integer") from None
        per_page = settings.page_size
        data = await asyncio.to_thread(
            repository.authors_page,
            query=query,
            limit=per_page,
            offset=(page - 1) * per_page,
        )
        total_pages = max(1, (int(data["total"]) + per_page - 1) // per_page)

        def page_url(number: int) -> str:
            params: dict[str, Any] = {}
            if data["query"]:
                params["q"] = data["query"]
            if number > 1:
                params["page"] = number
            suffix = urlencode(params)
            return f"/workshop/authors/?{suffix}" if suffix else "/workshop/authors/"

        if page > total_pages:
            raise web.HTTPFound(page_url(total_pages))
        attach_author_snapshots(data["items"])
        numbers = sorted(
            {1, total_pages}
            | {n for n in range(page - 2, page + 3) if 1 <= n <= total_pages}
        )
        pages: list[dict[str, Any]] = []
        previous = 0
        for number in numbers:
            if number - previous > 1:
                pages.append({"gap": True})
            pages.append(
                {"number": number, "url": page_url(number), "current": number == page}
            )
            previous = number
        pagination = {
            "page": page,
            "totalPages": total_pages,
            "total": int(data["total"]),
            "perPage": per_page,
            "pages": pages,
            "prevUrl": page_url(page - 1) if page > 1 else None,
            "nextUrl": page_url(page + 1) if page < total_pages else None,
            "firstUrl": page_url(1),
            "lastUrl": page_url(total_pages),
        }
        return render(
            request,
            "authors.html",
            page="authors",
            authors=data["items"],
            query=data["query"],
            pagination=pagination,
        )

    async def page_author(request: web.Request) -> web.Response:
        account_id = int(request.match_info["id"])
        author = await asyncio.to_thread(repository.author, account_id)
        if author is None:
            raise web.HTTPNotFound()
        try:
            page = max(1, int(request.query.get("page", "1")))
        except ValueError:
            raise QueryError("invalid_page", "page must be an integer") from None
        sort = request.query.get("sort", "popular")
        if sort not in {"popular", "new"}:
            raise QueryError("invalid_sort", "sort must be popular or new")
        per_page = settings.page_size
        total = int(author["uploads"])
        total_pages = max(1, (total + per_page - 1) // per_page)
        base_url = f"/workshop/authors/{account_id}/"

        def page_url(number: int) -> str:
            params = []
            if sort != "popular":
                params.append(f"sort={sort}")
            if number > 1:
                params.append(f"page={number}")
            return f"{base_url}?{'&'.join(params)}" if params else base_url

        if page > total_pages:
            raise web.HTTPFound(page_url(total_pages))
        listing = await asyncio.to_thread(
            repository.list_items,
            sort=sort,
            filters=ListFilters(account_id=account_id),
            limit=per_page,
            offset=(page - 1) * per_page,
        )
        attach_snapshots(listing["items"])

        numbers = sorted(
            {1, total_pages}
            | {n for n in range(page - 2, page + 3) if 1 <= n <= total_pages}
        )
        pages: list[dict[str, Any]] = []
        previous = 0
        for number in numbers:
            if number - previous > 1:
                pages.append({"gap": True})
            pages.append(
                {"number": number, "url": page_url(number), "current": number == page}
            )
            previous = number
        pagination = {
            "page": page,
            "totalPages": total_pages,
            "total": total,
            "perPage": per_page,
            "pages": pages,
            "sort": sort,
            "popularUrl": page_url(1) if sort == "popular" else base_url,
            "newUrl": f"{base_url}?sort=new",
            "prevUrl": page_url(page - 1) if page > 1 else None,
            "nextUrl": page_url(page + 1) if page < total_pages else None,
            "firstUrl": page_url(1),
            "lastUrl": page_url(total_pages),
        }
        popular = await asyncio.to_thread(
            repository.list_items,
            sort="popular",
            filters=ListFilters(account_id=account_id),
            limit=60,
        )
        cover_url = await asyncio.to_thread(author_cover, account_id, popular["items"])
        return render(
            request,
            "author.html",
            page="authors",
            author=author,
            data=listing,
            vehicles=[],
            pagination=pagination,
            social_image=(
                f"https://www.aseanmotorclub.com{cover_url}" if cover_url else None
            ),
            canonical_url=f"https://www.aseanmotorclub.com/workshop/authors/{account_id}/",
        )

    async def page_vehicle(request: web.Request) -> web.Response:
        vehicle = request.match_info["vehicle"]
        try:
            page = max(1, int(request.query.get("page", "1")))
        except ValueError:
            raise QueryError("invalid_page", "page must be an integer") from None
        sort = request.query.get("sort", "popular")
        if sort not in {"popular", "new"}:
            raise QueryError("invalid_sort", "sort must be popular or new")
        filters = ListFilters(
            vehicle=vehicle,
            paint=request.query.get("paint") == "1",
            decal=request.query.get("decal") == "1",
            parts=request.query.get("parts") == "1",
            tuning=request.query.get("tuning") == "1",
            club=request.query.get("club") == "1",
        )
        filter_params = [
            (name, "1")
            for name in ("paint", "decal", "parts", "tuning", "club")
            if getattr(filters, name)
        ]
        per_page = settings.page_size
        total = await asyncio.to_thread(repository.count_items, filters)
        total_pages = max(1, (total + per_page - 1) // per_page)
        base_url = f"/workshop/vehicles/{vehicle}/"

        def page_url(number: int, *, page_sort: str = sort) -> str:
            params = [("sort", page_sort)] if page_sort != "popular" else []
            params.extend(filter_params)
            if number > 1:
                params.append(("page", str(number)))
            return f"{base_url}?{urlencode(params)}" if params else base_url

        if page > total_pages:
            raise web.HTTPFound(page_url(total_pages))
        listing = await asyncio.to_thread(
            repository.list_items,
            sort=sort,
            filters=filters,
            limit=per_page,
            offset=(page - 1) * per_page,
        )
        attach_snapshots(listing["items"])

        numbers = sorted(
            {1, total_pages}
            | {n for n in range(page - 2, page + 3) if 1 <= n <= total_pages}
        )
        pages: list[dict[str, Any]] = []
        previous = 0
        for number in numbers:
            if number - previous > 1:
                pages.append({"gap": True})
            pages.append(
                {"number": number, "url": page_url(number), "current": number == page}
            )
            previous = number
        pagination = {
            "page": page,
            "totalPages": total_pages,
            "total": total,
            "perPage": per_page,
            "pages": pages,
            "sort": sort,
            "popularUrl": page_url(1, page_sort="popular"),
            "newUrl": page_url(1, page_sort="new"),
            "prevUrl": page_url(page - 1) if page > 1 else None,
            "nextUrl": page_url(page + 1) if page < total_pages else None,
            "firstUrl": page_url(1),
            "lastUrl": page_url(total_pages),
        }
        return render(
            request,
            "author.html",
            page="gallery",
            author={
                "displayName": vehicle,
                "uploads": total,
                "installs": 0,
                "votes": 0,
                "accountId": None,
            },
            data=listing,
            vehicles=[],
            filters=filters,
            pagination=pagination,
            canonical_url=f"https://www.aseanmotorclub.com{base_url}",
        )

    async def page_character(request: web.Request) -> web.Response:
        vehicle_id = int(request.match_info["id"])
        config = await character_configuration(vehicle_id)
        return render(
            request,
            "character.html",
            page="workshop",
            vehicle_id=vehicle_id,
            config=config,
        )

    async def redirect_legacy_character(request: web.Request) -> web.Response:
        vehicle_id = request.query.get("ownerVehicleId")
        if vehicle_id:
            raise web.HTTPMovedPermanently(
                location=f"/vehicles/character/{vehicle_id}/"
            )
        raise web.HTTPFound(location="/vehicles/")

    # -- Discord SSO -------------------------------------------------------

    secure_cookies = sso.public_url.startswith("https")

    def safe_next(value: str | None) -> str:
        """Only ever bounce back into this site."""
        if not value or not value.startswith("/") or value.startswith("//"):
            return "/workshop/account/"
        return value

    async def auth_login(request: web.Request) -> web.Response:
        if not sso.enabled:
            raise web.HTTPNotFound()
        state = new_state()
        target = safe_next(request.query.get("next"))
        response = web.HTTPFound(authorize_url(sso, state))
        response.set_cookie(
            STATE_COOKIE,
            f"{state}:{target}",
            max_age=600,
            path="/",
            httponly=True,
            secure=secure_cookies,
            samesite="Lax",
        )
        raise response

    async def auth_callback(request: web.Request) -> web.Response:
        if not sso.enabled:
            raise web.HTTPNotFound()
        cookie = request.cookies.get(STATE_COOKIE) or ""
        expected_state, _, target = cookie.partition(":")
        state = request.query.get("state", "")
        if (
            request.query.get("error")
            or not state
            or not expected_state
            or not secrets.compare_digest(state, expected_state)
        ):
            log.warning(
                "workshop sign-in rejected: state mismatch or %s",
                request.query.get("error") or "missing state",
            )
            raise web.HTTPFound("/workshop/?auth=failed")
        claims = await sign_in(
            sso, request.query.get("code", ""), request.app["http_session"]
        )
        if claims is None:
            raise web.HTTPFound("/workshop/?auth=failed")
        response = web.HTTPFound(safe_next(target))
        response.set_cookie(
            SESSION_COOKIE,
            sign_session(claims, sso.session_secret, sso.session_ttl),
            max_age=sso.session_ttl,
            path="/",
            httponly=True,
            secure=secure_cookies,
            samesite="Lax",
        )
        response.del_cookie(STATE_COOKIE, path="/")
        raise response

    async def auth_logout(request: web.Request) -> web.Response:
        response = web.HTTPFound("/workshop/")
        response.del_cookie(SESSION_COOKIE, path="/")
        raise response

    def require_member(request: web.Request) -> dict[str, Any]:
        user = request.get("user")
        if not user:
            if not sso.enabled:
                raise web.HTTPNotFound()
            target = quote(request.path_qs, safe="/")
            raise web.HTTPFound(f"/workshop/auth/login?next={target}")
        return user

    async def steam_id_for(request: web.Request, claims: dict[str, Any]) -> int | None:
        identity: PlayerIdentityRepository = request.app["player_identity"]
        return await asyncio.to_thread(identity.steam_id_for, claims["sub"])

    async def api_me(request: web.Request) -> web.Response:
        user = request.get("user")
        steam_id = await steam_id_for(request, user) if user else None
        return web.json_response(
            {
                "authenticated": bool(user),
                "ssoEnabled": sso.enabled,
                "user": (
                    {
                        "id": user["sub"],
                        "username": user.get("u"),
                        "displayName": display_name(user),
                        "avatarUrl": user.get("a"),
                        "member": bool(user.get("m")),
                    }
                    if user
                    else None
                ),
                "steamId": str(steam_id) if steam_id else None,
            },
            headers={"Cache-Control": "no-store"},
        )

    # -- collections -------------------------------------------------------

    COLLECTIONS_PER_PAGE = 24

    def _collection_store(request: web.Request) -> CollectionStore:
        return request.app["collections"]

    async def page_collections(request: web.Request) -> web.Response:
        sort = request.query.get("sort", "new")
        if sort not in {"new", "liked"}:
            sort = "new"
        try:
            page_no = max(1, int(request.query.get("page", "1")))
        except ValueError:
            page_no = 1
        store = _collection_store(request)
        limit = COLLECTIONS_PER_PAGE
        offset = (page_no - 1) * limit
        listed, total = await asyncio.gather(
            asyncio.to_thread(store.listing, sort=sort, limit=limit, offset=offset),
            asyncio.to_thread(store.count_public),
        )
        covers: dict[int, dict[str, Any]] = {}
        if listed:
            cover_ids = await asyncio.to_thread(store.cover_ids, [c.id for c in listed])
            cards = await asyncio.to_thread(
                repository.items_by_ids, list(cover_ids.values())
            )
            attach_snapshots(cards)
            by_id = {card["id"]: card for card in cards}
            covers = {cid: by_id[wid] for cid, wid in cover_ids.items() if wid in by_id}
        user = request.get("user")
        mine = await asyncio.to_thread(store.owned, str(user["sub"])) if user else []
        return render(
            request,
            "collections.html",
            page="collections",
            collections=listed,
            covers=covers,
            sort=sort,
            page_no=page_no,
            has_next=offset + len(listed) < total,
            total=total,
            mine=mine,
        )

    async def page_collection(request: web.Request) -> web.Response:
        store = _collection_store(request)
        collection_id = int(request.match_info["id"])
        collection = await asyncio.to_thread(store.get, collection_id)
        user = request.get("user")
        if collection is None or collection.hidden:
            raise web.HTTPNotFound()
        is_owner = bool(user and str(user["sub"]) == collection.discord_id)
        if not collection.is_public and not is_owner:
            # Unlisted is link-only: reachable, but not indexed and not listed.
            pass
        slug = request.match_info["slug"]
        if slug != collection.slug:
            raise web.HTTPMovedPermanently(
                f"/workshop/collections/{collection.id}/{collection.slug}/"
            )
        ids = await asyncio.to_thread(store.item_ids, collection.id)
        items = await asyncio.to_thread(repository.items_by_ids, ids)
        attach_snapshots(items)
        likes = await asyncio.to_thread(community.like_counts, [i["id"] for i in items])
        mine = await asyncio.to_thread(store.owned, str(user["sub"])) if user else []
        tags = await asyncio.to_thread(request.app["tags"].collection_tags, collection.id)
        return render(
            request,
            "collection.html",
            page="collections",
            collection=collection,
            tags=tags,
            items=items,
            likes=likes,
            is_owner=is_owner,
            mine=mine,
            noindex=not collection.is_public,
        )

    async def page_collection_new(request: web.Request) -> web.Response:
        user = require_member(request)
        store = _collection_store(request)
        if request.method == "GET":
            return render(
                request,
                "collection_new.html",
                page="collections",
                item=request.query.get("item", ""),
                error=None,
            )
        form = await request.post()
        try:
            collection = await asyncio.to_thread(
                store.create,
                discord_id=str(user["sub"]),
                title=str(form.get("title", "")),
                description=str(form.get("description", "")),
                visibility=str(form.get("visibility", "public")),
                now=_now_iso(),
            )
        except CollectionError as exc:
            return render(
                request,
                "collection_new.html",
                page="collections",
                item=form.get("item", ""),
                error=str(exc),
            )
        seed = str(form.get("item", "")).strip()
        if seed.isdigit():
            item = await asyncio.to_thread(repository.get_item, int(seed))
            if item is not None:
                await asyncio.to_thread(
                    store.add_item,
                    collection_id=collection.id,
                    discord_id=str(user["sub"]),
                    workshop_id=item["id"],
                    now=_now_iso(),
                )
        raise web.HTTPSeeOther(
            f"/workshop/collections/{collection.id}/{collection.slug}/"
        )

    async def page_collection_edit(request: web.Request) -> web.Response:
        user = require_member(request)
        store = _collection_store(request)
        collection_id = int(request.match_info["id"])
        collection = await asyncio.to_thread(store.get, collection_id)
        if collection is None or collection.hidden:
            raise web.HTTPNotFound()
        if str(user["sub"]) != collection.discord_id:
            raise web.HTTPForbidden(text="That collection is not yours.")

        error = None
        if request.method == "POST":
            form = await request.post()
            try:
                updated = await asyncio.to_thread(
                    store.update,
                    collection_id=collection_id,
                    discord_id=str(user["sub"]),
                    title=str(form.get("title", "")),
                    description=str(form.get("description", "")),
                    visibility=str(form.get("visibility", "public")),
                    now=_now_iso(),
                )
            except CollectionError as exc:
                error = str(exc)
            else:
                if updated:
                    raise web.HTTPSeeOther(
                        f"/workshop/collections/{collection_id}/{collection.slug}/"
                    )
                raise web.HTTPNotFound()

        ids = await asyncio.to_thread(store.item_ids, collection_id)
        items = await asyncio.to_thread(repository.items_by_ids, ids)
        attach_snapshots(items)
        tags = await asyncio.to_thread(
            request.app["tags"].collection_tags, collection_id
        )
        return render(
            request,
            "collection_edit.html",
            page="collections",
            collection=collection,
            items=items,
            tags=tags,
            error=error or request.query.get("tag-error"),
        )

    async def collection_add_item(request: web.Request) -> web.Response:
        user = require_member(request)
        store = _collection_store(request)
        limiters: dict[str, RateLimiter] = request.app["limiters"]
        if not limiters["collection"].allow(str(user["sub"])):
            raise web.HTTPTooManyRequests(text="One at a time.")
        collection_id = int(request.match_info["id"])
        collection = await asyncio.to_thread(store.get, collection_id)
        if collection is None or collection.hidden:
            raise web.HTTPNotFound()
        back = f"/workshop/collections/{collection_id}/{collection.slug}/edit"
        form = await request.post()
        raw = str(form.get("workshop_id", "")).strip()
        workshop_id = int(raw) if raw.isdigit() else None
        if workshop_id is None:
            raise web.HTTPSeeOther(f"{back}?error=bad-id")
        item = await asyncio.to_thread(repository.get_item, workshop_id)
        if item is None:
            raise web.HTTPSeeOther(f"{back}?error=no-item")
        try:
            added = await asyncio.to_thread(
                store.add_item,
                collection_id=collection_id,
                discord_id=str(user["sub"]),
                workshop_id=workshop_id,
                now=_now_iso(),
            )
        except CollectionError:
            raise web.HTTPSeeOther(f"{back}?error=full") from None
        if not added:
            raise web.HTTPSeeOther(f"{back}?error=duplicate")
        raise web.HTTPSeeOther(f"{back}?added={workshop_id}")

    async def collection_remove_item(request: web.Request) -> web.Response:
        user = require_member(request)
        store = _collection_store(request)
        collection_id = int(request.match_info["id"])
        workshop_id = int(request.match_info["workshop_id"])
        collection = await asyncio.to_thread(store.get, collection_id)
        if collection is None:
            raise web.HTTPNotFound()
        await asyncio.to_thread(
            store.remove_item,
            collection_id=collection_id,
            discord_id=str(user["sub"]),
            workshop_id=workshop_id,
        )
        raise web.HTTPSeeOther(
            f"/workshop/collections/{collection_id}/{collection.slug}/edit"
        )

    async def collection_reorder(request: web.Request) -> web.Response:
        user = require_member(request)
        store = _collection_store(request)
        collection_id = int(request.match_info["id"])
        collection = await asyncio.to_thread(store.get, collection_id)
        if collection is None or str(user["sub"]) != collection.discord_id:
            raise web.HTTPForbidden(text="That collection is not yours.")
        form = await request.post()
        direction = str(form.get("direction", "up"))
        raw = str(form.get("workshop_id", "")).strip()
        if not raw.isdigit():
            raise web.HTTPSeeOther(
                f"/workshop/collections/{collection_id}/{collection.slug}/edit"
            )
        workshop_id = int(raw)
        ids = await asyncio.to_thread(store.item_ids, collection_id)
        if workshop_id in ids:
            index = ids.index(workshop_id)
            target = index - 1 if direction == "up" else index + 1
            if 0 <= target < len(ids):
                ids[index], ids[target] = ids[target], ids[index]
                await asyncio.to_thread(
                    store.reorder,
                    collection_id=collection_id,
                    discord_id=str(user["sub"]),
                    ordered_ids=ids,
                )
        raise web.HTTPSeeOther(
            f"/workshop/collections/{collection_id}/{collection.slug}/edit"
        )

    async def collection_delete(request: web.Request) -> web.Response:
        user = require_member(request)
        store = _collection_store(request)
        collection_id = int(request.match_info["id"])
        collection = await asyncio.to_thread(store.get, collection_id)
        if collection is None:
            raise web.HTTPNotFound()
        form = await request.post()
        if str(form.get("confirm", "")) != "yes":
            raise web.HTTPSeeOther(
                f"/workshop/collections/{collection_id}/{collection.slug}/edit?delete=1"
            )
        await asyncio.to_thread(
            store.delete, collection_id=collection_id, discord_id=str(user["sub"])
        )
        raise web.HTTPSeeOther("/workshop/collections/?deleted=1")

    async def item_collect(request: web.Request) -> web.Response:
        """`Save to collection` from an item page."""
        user = require_member(request)
        store = _collection_store(request)
        workshop_id = int(request.match_info["id"])
        form = await request.post()
        raw = str(form.get("collection_id", "")).strip()
        if raw.isdigit():
            await asyncio.to_thread(
                store.add_item,
                collection_id=int(raw),
                discord_id=str(user["sub"]),
                workshop_id=workshop_id,
                now=_now_iso(),
            )
        raise web.HTTPSeeOther(f"/workshop/items/{workshop_id}/")

    # -- member-authored text ----------------------------------------------

    PROFILE_NAME_MIN = 2
    PROFILE_NAME_MAX = 32
    PROFILE_BIO_MAX = 400

    def _clean(value: str | None, *, limit: int, field: str) -> str:
        from .text import clean_text

        return clean_text(value, limit=limit, field=field)

    async def profile_save(request: web.Request) -> web.Response:
        user = require_member(request)
        form = await request.post()
        display_name = _clean(form.get("display_name"), limit=PROFILE_NAME_MAX, field="Display name")
        bio = _clean(form.get("bio"), limit=PROFILE_BIO_MAX, field="Bio")
        error = None
        if display_name and len(display_name) < PROFILE_NAME_MIN:
            error = "A display name needs at least two characters."
        elif not display_name and not bio:
            error = "Nothing to save."
        if error is None:
            await asyncio.to_thread(
                community.save_profile,
                discord_id=str(user["sub"]),
                display_name=display_name or None,
                bio=bio or None,
                now=_now_iso(),
            )
            raise web.HTTPSeeOther("/workshop/account/")
        raise web.HTTPSeeOther("/workshop/account/?profile-error=" + quote(error))

    async def item_edit(request: web.Request) -> web.Response:
        """The claim owner's title and summary for their own build."""
        user = require_member(request)
        workshop_id = int(request.match_info["id"])
        item = await asyncio.to_thread(repository.get_item, workshop_id)
        if item is None:
            raise web.HTTPNotFound()
        claim = await asyncio.to_thread(community.claim_for, workshop_id)
        if not claim or claim.revoked_at is not None or claim.discord_id != str(user["sub"]):
            raise web.HTTPForbidden(text="Only the owner of this build can edit it.")

        error = None
        if request.method == "POST":
            form = await request.post()
            try:
                title = _clean(form.get("title"), limit=60, field="Title")
                description = _clean(form.get("description"), limit=600, field="Summary")
            except ValueError as exc:
                meta = await asyncio.to_thread(community.meta, workshop_id)
                return render(
                    request,
                    "item_edit.html",
                    page="item",
                    item=item,
                    meta=meta,
                    error=str(exc),
                    draft={"title": form.get("title"), "description": form.get("description")},
                )
            await asyncio.to_thread(
                community.save_meta,
                workshop_id=workshop_id,
                title=title or None,
                description=description or None,
                discord_id=str(user["sub"]),
                now=_now_iso(),
            )
            raise web.HTTPSeeOther(f"/workshop/items/{workshop_id}/")

        meta = await asyncio.to_thread(community.meta, workshop_id)
        tags = await asyncio.to_thread(request.app["tags"].item_tags, workshop_id)
        return render(
            request,
            "item_edit.html",
            page="item",
            item=item,
            meta=meta,
            tags=tags,
            error=error or request.query.get("tag-error"),
        )

    # -- engagement JSON and sitemaps --------------------------------------

    SITEMAP_CHUNK = 40_000

    def _site() -> str:
        return sso.public_url.rstrip("/")

    async def api_item_engagement(request: web.Request) -> web.Response:
        """One shape for the bot and for any client that wants the numbers."""
        workshop_id = int(request.match_info["id"])
        item = await asyncio.to_thread(repository.get_item, workshop_id)
        if item is None:
            return _json_error("not_found", "Workshop item not found", 404)

        likes = await asyncio.to_thread(community.like_count, workshop_id)
        collections = await asyncio.to_thread(
            request.app["collections"].count_for_item, workshop_id
        )
        viewer = request.get("user")
        liked = bool(
            viewer
            and workshop_id
            in await asyncio.to_thread(
                community.liked_ids, str(viewer.get("sub")), [workshop_id]
            )
        )
        payload = {
            "workshopId": workshop_id,
            "likes": likes,
            "likedByViewer": liked,
            "collections": collections,
            "votes": item.get("votes"),
        }
        etag = '"' + hashlib.sha256(
            json.dumps([likes, collections, item.get("votes")])
            .encode()
        ).hexdigest()[:16] + '"'
        if not viewer and request.headers.get("If-None-Match") == etag:
            raise web.HTTPNotModified(headers={"ETag": etag})
        return web.json_response(
            payload,
            headers={
                "ETag": etag,
                # A viewer's own like state must never sit in a shared cache.
                "Cache-Control": "private, no-store"
                if viewer
                else "public, max-age=30",
            },
        )

    def _url_entry(loc: str, lastmod: str | None = None) -> str:
        stamp = f"<lastmod>{lastmod[:10]}</lastmod>" if lastmod else ""
        return f"<url><loc>{escape(loc)}</loc>{stamp}</url>"

    async def sitemap_index(request: web.Request) -> web.Response:
        total = await asyncio.to_thread(repository.count_public_items)
        chunks = max(1, -(-total // SITEMAP_CHUNK))
        parts = [
            f"<sitemap><loc>{_site()}/workshop/sitemap-pages.xml</loc></sitemap>"
        ]
        parts += [
            f"<sitemap><loc>{_site()}/workshop/sitemap-items-{n}.xml</loc></sitemap>"
            for n in range(1, chunks + 1)
        ]
        body = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            + "".join(parts)
            + "</sitemapindex>"
        )
        return web.Response(
            text=body,
            content_type="application/xml",
            headers={"Cache-Control": "public, max-age=3600"},
        )

    async def sitemap_pages(request: web.Request) -> web.Response:
        site = _site()
        entries = [
            _url_entry(f"{site}/workshop/"),
            _url_entry(f"{site}/workshop/gallery/"),
            _url_entry(f"{site}/workshop/authors/"),
            _url_entry(f"{site}/workshop/collections/"),
        ]
        collections = await asyncio.to_thread(
            request.app["collections"].all_public
        )
        entries += [
            _url_entry(
                f"{site}/workshop/collections/{c.id}/{c.slug}/", c.updated_at
            )
            for c in collections
        ]
        body = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            + "".join(entries)
            + "</urlset>"
        )
        return web.Response(
            text=body,
            content_type="application/xml",
            headers={"Cache-Control": "public, max-age=1800"},
        )

    async def sitemap_items(request: web.Request) -> web.Response:
        chunk = int(request.match_info["chunk"])
        if chunk < 1:
            raise web.HTTPNotFound()
        ids = await asyncio.to_thread(
            repository.item_ids_page,
            offset=(chunk - 1) * SITEMAP_CHUNK,
            limit=SITEMAP_CHUNK,
        )
        site = _site()
        body = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            + "".join(_url_entry(f"{site}/workshop/items/{i}/") for i in ids)
            + "</urlset>"
        )
        return web.Response(
            text=body,
            content_type="application/xml",
            headers={"Cache-Control": "public, max-age=3600"},
        )

    # -- tags --------------------------------------------------------------

    def _tag_store(request: web.Request) -> TagStore:
        return request.app["tags"]

    async def page_tags(request: web.Request) -> web.Response:
        sort = request.query.get("sort", "popular")
        if sort not in {"popular", "az"}:
            sort = "popular"
        try:
            page_no = max(1, int(request.query.get("page", "1")))
        except ValueError:
            page_no = 1
        store = _tag_store(request)
        limit = 60
        offset = (page_no - 1) * limit
        tags, total = await asyncio.gather(
            asyncio.to_thread(store.index, sort=sort, limit=limit, offset=offset),
            asyncio.to_thread(store.count_tags),
        )
        return render(
            request,
            "tags.html",
            page="tags",
            tags=tags,
            sort=sort,
            page_no=page_no,
            has_next=offset + len(tags) < total,
        )

    async def page_tag(request: web.Request) -> web.Response:
        from urllib.parse import unquote

        raw = unquote(request.match_info["tag"])
        canonical = normalise_tag(raw)
        if not canonical or raw != canonical:
            if not canonical:
                raise web.HTTPNotFound()
            from urllib.parse import quote

            raise web.HTTPMovedPermanently(
                f"/workshop/tags/{quote(canonical, safe='')}/"
            )
        store = _tag_store(request)
        usage = await asyncio.to_thread(store.usage, canonical)
        if usage is None:
            return render(
                request,
                "tag.html",
                page="tags",
                tag=canonical,
                usage=None,
                items=[],
                collections=[],
                related=[],
                likes={},
                noindex=True,
            )
        item_ids, collection_ids, related = await asyncio.gather(
            asyncio.to_thread(store.item_ids, canonical),
            asyncio.to_thread(store.collection_ids, canonical),
            asyncio.to_thread(store.related, canonical),
        )
        items = await asyncio.to_thread(repository.items_by_ids, item_ids)
        attach_snapshots(items)
        likes = await asyncio.to_thread(
            community.like_counts, [i["id"] for i in items]
        )
        collections_store: CollectionStore = request.app["collections"]
        collections = [
            c
            for c in await asyncio.to_thread(
                collections_store.get_many, collection_ids
            )
            if c.is_public
        ]
        # Counts are what is *live*: a build that left the scrape should not
        # keep a tag page looking populated.
        live = usage.__class__(
            tag=canonical, items=len(items), collections=len(collections)
        )
        return render(
            request,
            "tag.html",
            page="tags",
            tag=canonical,
            usage=live,
            items=items,
            collections=collections,
            related=related,
            likes=likes,
            noindex=live.items < 3,
        )

    async def api_tags(request: web.Request) -> web.Response:
        query = request.query.get("q", "")
        results = await asyncio.to_thread(_tag_store(request).search, query, limit=12)
        return web.json_response(
            [
                {"tag": t.tag, "items": t.items, "collections": t.collections}
                for t in results
            ],
            headers={"Cache-Control": "public, max-age=30"},
        )

    async def _own_item_or_403(request: web.Request, workshop_id: int) -> dict[str, Any]:
        user = require_member(request)
        claim = await asyncio.to_thread(community.claim_for, workshop_id)
        if (
            not claim
            or claim.revoked_at is not None
            or claim.discord_id != str(user["sub"])
        ):
            raise web.HTTPForbidden(
                text="Only the owner of this build can tag it."
            )
        return user

    async def item_tags_add(request: web.Request) -> web.Response:
        workshop_id = int(request.match_info["id"])
        user = await _own_item_or_403(request, workshop_id)
        limiters: dict[str, RateLimiter] = request.app["limiters"]
        if not limiters["tag"].allow(str(user["sub"])):
            raise web.HTTPTooManyRequests(text="One at a time.")
        form = await request.post()
        try:
            await asyncio.to_thread(
                _tag_store(request).add_item_tags,
                workshop_id=workshop_id,
                discord_id=str(user["sub"]),
                raw_tags=str(form.get("tags", "")),
                now=_now_iso(),
            )
        except TagError as exc:
            from urllib.parse import quote

            raise web.HTTPSeeOther(
                f"/workshop/items/{workshop_id}/edit?tag-error={quote(str(exc))}"
            ) from None
        raise web.HTTPSeeOther(f"/workshop/items/{workshop_id}/edit")

    async def item_tag_remove(request: web.Request) -> web.Response:
        from urllib.parse import unquote

        workshop_id = int(request.match_info["id"])
        await _own_item_or_403(request, workshop_id)
        await asyncio.to_thread(
            _tag_store(request).remove_item_tag,
            workshop_id=workshop_id,
            tag=unquote(request.match_info["tag"]),
        )
        raise web.HTTPSeeOther(f"/workshop/items/{workshop_id}/edit")

    async def collection_tags_add(request: web.Request) -> web.Response:
        user = require_member(request)
        store = _tag_store(request)
        collections_store: CollectionStore = request.app["collections"]
        collection_id = int(request.match_info["id"])
        collection = await asyncio.to_thread(collections_store.get, collection_id)
        if collection is None or collection.hidden:
            raise web.HTTPNotFound()
        if str(user["sub"]) != collection.discord_id:
            raise web.HTTPForbidden(text="That collection is not yours.")
        limiters: dict[str, RateLimiter] = request.app["limiters"]
        if not limiters["tag"].allow(str(user["sub"])):
            raise web.HTTPTooManyRequests(text="One at a time.")
        form = await request.post()
        back = f"/workshop/collections/{collection_id}/{collection.slug}/edit"
        try:
            await asyncio.to_thread(
                store.add_collection_tags,
                collection_id=collection_id,
                discord_id=str(user["sub"]),
                raw_tags=str(form.get("tags", "")),
                now=_now_iso(),
            )
        except TagError as exc:
            from urllib.parse import quote

            raise web.HTTPSeeOther(f"{back}?tag-error={quote(str(exc))}") from None
        raise web.HTTPSeeOther(back)

    async def collection_tag_remove(request: web.Request) -> web.Response:
        from urllib.parse import unquote

        user = require_member(request)
        collections_store: CollectionStore = request.app["collections"]
        collection_id = int(request.match_info["id"])
        collection = await asyncio.to_thread(collections_store.get, collection_id)
        if collection is None:
            raise web.HTTPNotFound()
        if str(user["sub"]) != collection.discord_id:
            raise web.HTTPForbidden(text="That collection is not yours.")
        await asyncio.to_thread(
            _tag_store(request).remove_collection_tag,
            collection_id=collection_id,
            tag=unquote(request.match_info["tag"]),
        )
        raise web.HTTPSeeOther(
            f"/workshop/collections/{collection_id}/{collection.slug}/edit"
        )

    async def page_account(request: web.Request) -> web.Response:
        user = request.get("user")
        if not user:
            if not sso.enabled:
                raise web.HTTPNotFound()
            raise web.HTTPFound("/workshop/auth/login?next=/workshop/account/")
        steam_id = await steam_id_for(request, user)
        profile = await asyncio.to_thread(community.profile, str(user["sub"]))
        profile_error = request.query.get("profile-error")
        claimed = await asyncio.to_thread(community.claims_for, str(user["sub"]))
        active = [claim for claim in claimed.values() if claim.revoked_at is None]
        items: list[dict[str, Any]] = []
        if active:
            items = await asyncio.to_thread(
                repository.items_for_guids,
                {claim.character_guid for claim in active},
                24,
            )
        elif steam_id:
            items = await asyncio.to_thread(repository.items_for_steam_id, steam_id, 24)
        if items:
            attach_snapshots(items)
        return render(
            request,
            "account.html",
            page="account",
            steam_id=steam_id,
            items=items,
            profile=profile,
            profile_error=profile_error,
            claim_count=len(active),
        )

    app.router.add_get("/healthz", api_health)
    app.router.add_get("/workshop/", page_home)
    app.router.add_get("/workshop/account/", page_account)
    app.router.add_get("/workshop/auth/login", auth_login)
    app.router.add_get("/workshop/auth/callback", auth_callback)
    app.router.add_get("/workshop/auth/logout", auth_logout)
    app.router.add_post("/workshop/auth/logout", auth_logout)
    app.router.add_get("/workshop/search/", page_search)
    app.router.add_get("/workshop/gallery/", page_gallery)
    app.router.add_get("/workshop/items/{id:\\d+}/", page_item)
    app.router.add_get("/workshop/items/{id:\\d+}/viewer/", page_item_viewer)
    app.router.add_post("/workshop/items/{id:\\d+}/like", item_like)
    app.router.add_post("/workshop/items/{id:\\d+}/collect", item_collect)
    app.router.add_post("/workshop/profile", profile_save)
    app.router.add_get(
        "/api/workshop/items/{id:\\d+}/engagement", api_item_engagement
    )
    app.router.add_get("/workshop/tags/", page_tags)
    app.router.add_get("/workshop/tags/{tag}/", page_tag)
    app.router.add_get("/api/workshop/tags", api_tags)
    app.router.add_post("/workshop/items/{id:\\d+}/tags", item_tags_add)
    app.router.add_post(
        "/workshop/items/{id:\\d+}/tags/{tag}/remove", item_tag_remove
    )
    app.router.add_post(
        "/workshop/collections/{id:\\d+}/tags", collection_tags_add
    )
    app.router.add_post(
        "/workshop/collections/{id:\\d+}/tags/{tag}/remove", collection_tag_remove
    )
    app.router.add_get("/workshop/sitemap.xml", sitemap_index)
    app.router.add_get("/workshop/sitemap-pages.xml", sitemap_pages)
    app.router.add_get("/workshop/sitemap-items-{chunk:\\d+}.xml", sitemap_items)
    app.router.add_get("/workshop/items/{id:\\d+}/edit", item_edit)
    app.router.add_post("/workshop/items/{id:\\d+}/edit", item_edit)
    app.router.add_get("/workshop/collections/", page_collections)
    app.router.add_get("/workshop/collections/new", page_collection_new)
    app.router.add_post("/workshop/collections/new", page_collection_new)
    app.router.add_get("/workshop/collections/{id:\\d+}/{slug}/", page_collection)
    app.router.add_get("/workshop/collections/{id:\\d+}/edit", page_collection_edit)
    app.router.add_post("/workshop/collections/{id:\\d+}/edit", page_collection_edit)
    app.router.add_post("/workshop/collections/{id:\\d+}/items", collection_add_item)
    app.router.add_post(
        "/workshop/collections/{id:\\d+}/items/{workshop_id:\\d+}/remove",
        collection_remove_item,
    )
    app.router.add_post("/workshop/collections/{id:\\d+}/reorder", collection_reorder)
    app.router.add_post("/workshop/collections/{id:\\d+}/delete", collection_delete)
    app.router.add_get("/workshop/authors/", page_authors)
    app.router.add_get("/workshop/authors/{id:\\d+}/", page_author)
    app.router.add_get("/workshop/vehicles/{vehicle:[A-Za-z0-9_]+}/", page_vehicle)
    app.router.add_get("/vehicles/character/{id:\\d+}/", page_character)
    app.router.add_get("/vehicles/", redirect_legacy_character)

    app.router.add_get("/api/workshop/home", api_home)
    app.router.add_get("/api/workshop/search", api_search)
    app.router.add_get("/api/workshop/items", api_list)
    app.router.add_get("/api/workshop/items/{id:\\d+}", api_item)
    app.router.add_get("/api/workshop/items/{id:\\d+}/viewer", api_viewer)
    app.router.add_get("/api/workshop/items/{id:\\d+}/snapshot", api_snapshot)
    app.router.add_get("/api/workshop/snapshots", api_snapshot_batch)
    app.router.add_get("/api/workshop/authors/{id:\\d+}", api_authors)
    app.router.add_get("/api/workshop/vehicles", api_vehicles)
    app.router.add_get("/api/workshop/health", api_health)
    app.router.add_get("/api/workshop/me", api_me)
    app.router.add_get("/api/character-vehicles/{id:\\d+}/viewer", api_character_viewer)
    app.router.add_get("/api/character-vehicles/{id:\\d+}/meta", api_character_meta)
    app.router.add_static("/workshop/static/", HERE / "static", name="workshop-static")
    app.router.add_static(
        "/workshop/snapshots/",
        settings.snapshot_root / "public",
        name="workshop-snapshots",
    )
    return app
