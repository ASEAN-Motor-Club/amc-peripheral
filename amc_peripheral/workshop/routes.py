"""HTTP routes for the workshop browser."""

from __future__ import annotations

import asyncio
import json
import logging
import mimetypes
import re
import secrets
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

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
    display_name,
    new_state,
    sign_in,
    sign_session,
    verify_session,
)
from .character_vehicles import CharacterVehicleRepository, CharacterVehicleUnavailable
from .config import WorkshopSettings
from .covers import write_author_cover
from .payloads import (
    PayloadError,
    asset_version_for,
    decode_payload,
    normalize_workshop,
    vehicle_display_name,
)
from .queries import (
    ListFilters,
    QueryError,
    WorkshopRepository,
)
from .snapshots import (
    PRIORITY_DIRECT,
    PRIORITY_VISIBLE,
    SnapshotJob,
    SnapshotStore,
    render_key,
)

log = logging.getLogger(__name__)
HERE = Path(__file__).resolve().parent
ITEM_CODE = re.compile(r"#([0-9]{1,9})")


def search_query(request: web.Request) -> str:
    return " ".join(request.query.get("q", "").strip().split())[:80]


def search_item_id(query: str) -> int | None:
    match = ITEM_CODE.fullmatch(query)
    return int(match.group(1)) if match else None


def _json_error(code: str, message: str, status: int = 400) -> web.Response:
    return web.json_response({"error": {"code": code, "message": message}}, status=status)


def _iso(value: str | None) -> str | None:
    if not value:
        return None
    return value.replace(" ", "T") + "Z" if "T" not in value else value


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
                return {str(key) for key in actors} if isinstance(actors, dict) else set()
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
    env.filters["tag_label"] = lambda value: str(value or "").replace("_", " ")
    env.filters["vehicle_name"] = vehicle_display_name

    app = web.Application(client_max_size=64 * 1024)
    app["settings"] = settings
    app["repository"] = repository
    app["character_vehicles"] = character_vehicles
    app["attachment_catalogue"] = AttachmentCatalogue(settings.viewer_root)
    app["sso"] = sso
    app["player_identity"] = player_identity
    (settings.snapshot_root / "public").mkdir(parents=True, exist_ok=True)
    snapshots = SnapshotStore(settings.site_db)

    def snapshot_job(card: dict[str, Any], *, priority: int = PRIORITY_VISIBLE) -> SnapshotJob | None:
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
            "workshop", [(int(card["id"]), card.get("configHash") or "") for card in items]
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
            return _json_error("invalid_payload", "Workshop configuration is unavailable", 422)
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

    @web.middleware
    async def sessions(request: web.Request, handler):
        """Attach the signed-in user (or ``None``) to every request."""
        request["user"] = (
            verify_session(request.cookies.get(SESSION_COOKIE), sso.session_secret)
            if sso.enabled
            else None
        )
        return await handler(request)

    app.middlewares.append(sessions)

    def render(request: web.Request, template: str, **context) -> web.Response:
        context.setdefault("settings", settings)
        context.setdefault("user", request.get("user"))
        context.setdefault("user_name", display_name(request.get("user")))
        context.setdefault("sso_enabled", sso.enabled)
        context.setdefault("request_path", request.path_qs)
        html = env.get_template(template).render(**context)
        return web.Response(text=html, content_type="text/html")

    def mark_asset_availability(config: dict[str, Any]) -> dict[str, Any]:
        slug = config["vehicle"]["slug"]
        available = (
            settings.viewer_root / slug / f"{slug}.json"
        ).is_file()
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
        return web.json_response({"type": "authors", "query": query, "authors": authors})

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
        item = await asyncio.to_thread(repository.get_item, int(request.match_info["id"]))
        if item is None:
            return _json_error("not_found", "Workshop item not found", 404)
        return web.json_response(item)

    async def api_viewer(request: web.Request) -> web.Response:
        config = await configuration(int(request.match_info["id"]))
        etag = f'"{config["source"]["configHash"]}"'
        if request.headers.get("If-None-Match") == etag:
            raise web.HTTPNotModified(headers={"ETag": etag})
        return web.json_response(config, headers={
            "ETag": etag,
            "Cache-Control": "public, max-age=300",
        })

    async def api_character_viewer(request: web.Request) -> web.Response:
        config = await character_configuration(int(request.match_info["id"]))
        etag = f'"{config["source"]["configHash"]}"'
        if request.headers.get("If-None-Match") == etag:
            raise web.HTTPNotModified(headers={"ETag": etag})
        return web.json_response(config, headers={
            "ETag": etag,
            "Cache-Control": "private, no-store",
        })

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
            return web.json_response(
                {"status": "unsupported", "url": None}, status=200
            )
        item["configHash"] = config["source"]["configHash"]
        priority = PRIORITY_VISIBLE if request.query.get("via") == "card" else PRIORITY_DIRECT
        job = snapshot_job(item, priority=priority)
        if job is None:
            return _json_error("invalid_payload", "Configuration has no content hash", 422)
        status = await asyncio.to_thread(snapshots.enqueue, job)
        return web.json_response(
            status,
            status=200 if status["status"] == "ready" else 202,
            headers={"Cache-Control": "no-store", "Retry-After": "10"},
        )

    async def api_authors(request: web.Request) -> web.Response:
        author = await asyncio.to_thread(repository.author, int(request.match_info["id"]))
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
        return web.json_response({"vehicles": await asyncio.to_thread(repository.vehicles)})

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
        if not keys or len(keys) > 48 or any(
            len(key) != 64 or any(char not in allowed for char in key)
            for key in keys
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
        return render(request, "home.html", page="home", data=data, stats=stats)

    async def page_search(request: web.Request) -> web.Response:
        query = search_query(request)
        item_id = search_item_id(query)
        if item_id is not None:
            item = await asyncio.to_thread(repository.get_item, item_id)
            if item is None:
                raise web.HTTPNotFound()
            raise web.HTTPFound(f"/workshop/items/{item_id}/")
        authors = await asyncio.to_thread(repository.search_authors, query)
        attach_author_snapshots(authors)
        return render(request, "search.html", page="search", query=query, authors=authors)

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
            request, "gallery.html",
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
        return render(request, "item.html", page="workshop", item=item, config=config,
                      snapshot=snapshot, similar=similar)

    async def page_item_viewer(request: web.Request) -> web.Response:
        workshop_id = int(request.match_info["id"])
        item = await asyncio.to_thread(repository.get_item, workshop_id)
        if item is None:
            raise web.HTTPNotFound()
        raise web.HTTPMovedPermanently(f"/workshop/items/{workshop_id}/")

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

        numbers = sorted({1, total_pages} | {
            n for n in range(page - 2, page + 3) if 1 <= n <= total_pages
        })
        pages: list[dict[str, Any]] = []
        previous = 0
        for number in numbers:
            if number - previous > 1:
                pages.append({"gap": True})
            pages.append({"number": number, "url": page_url(number),
                          "current": number == page})
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
        return render(request, "author.html", page="gallery", author=author, data=listing,
                      vehicles=[], pagination=pagination,
                      social_image=(f"https://www.aseanmotorclub.com{cover_url}" if cover_url else None),
                      canonical_url=f"https://www.aseanmotorclub.com/workshop/authors/{account_id}/")

    async def page_vehicle(request: web.Request) -> web.Response:
        vehicle = request.match_info["vehicle"]
        listing = await asyncio.to_thread(
            repository.list_items,
            sort="popular",
            filters=ListFilters(vehicle=vehicle),
            limit=settings.page_size,
        )
        attach_snapshots(listing["items"])
        return render(
            request, "author.html",
            page="gallery",
            author={"displayName": vehicle, "uploads": len(listing["items"]),
                    "installs": 0, "votes": 0, "accountId": None},
            data=listing,
            vehicles=[],
            canonical_url=f"https://www.aseanmotorclub.com/workshop/vehicles/{vehicle}/",
        )

    async def page_character(request: web.Request) -> web.Response:
        vehicle_id = int(request.match_info["id"])
        config = await character_configuration(vehicle_id)
        return render(
            request, "character.html", page="workshop", vehicle_id=vehicle_id, config=config
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

    async def page_account(request: web.Request) -> web.Response:
        user = request.get("user")
        if not user:
            if not sso.enabled:
                raise web.HTTPNotFound()
            raise web.HTTPFound("/workshop/auth/login?next=/workshop/account/")
        steam_id = await steam_id_for(request, user)
        items: list[dict[str, Any]] = []
        if steam_id:
            items = await asyncio.to_thread(
                repository.items_for_steam_id, steam_id, 24
            )
            attach_snapshots(items)
        return render(
            request,
            "account.html",
            page="account",
            steam_id=steam_id,
            items=items,
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
    app.router.add_get("/workshop/authors/{id:\\d+}/", page_author)
    app.router.add_get(
        "/workshop/vehicles/{vehicle:[A-Za-z0-9_]+}/", page_vehicle
    )
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
    app.router.add_get(
        "/api/character-vehicles/{id:\\d+}/viewer", api_character_viewer
    )
    app.router.add_get(
        "/api/character-vehicles/{id:\\d+}/meta", api_character_meta
    )
    app.router.add_static("/workshop/static/", HERE / "static", name="workshop-static")
    app.router.add_static(
        "/workshop/snapshots/",
        settings.snapshot_root / "public",
        name="workshop-snapshots",
    )
    return app
