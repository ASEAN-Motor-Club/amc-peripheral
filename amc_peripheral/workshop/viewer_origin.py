"""Private viewer origin for remote snapshot renderers.

The snapshot worker normally drives a local Chromium against the public site.
That works, but it makes the render cost include a public-edge round trip for
every asset, and the public edge is where our assets are slowest: the catch-all
vhost location answers with ``no-cache, no-store`` so every render (and every
visitor) re-downloads multi-megabyte GLBs.

This module serves the same viewer tree over the private network instead:
``/vehicles/*`` comes straight off the deployed tree on disk, and ``/api/*`` is
proxied to the workshop app on loopback. A renderer on another machine (for
example one with a real GPU) can then render ``http://<tailnet-ip>:<port>/``
without touching the public hostname.

Assets here are served with cache headers that match how the viewer references
them: binaries carry no version in the URL, so they get an hour plus
stale-while-revalidate; documents and scripts carry ``?v=N`` where it matters and
revalidate normally.
"""

from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path
from urllib.parse import urlsplit

from aiohttp import ClientSession, ClientTimeout, web

log = logging.getLogger(__name__)

BINARY_SUFFIXES = frozenset(
    {
        ".glb",
        ".gltf",
        ".bin",
        ".png",
        ".jpg",
        ".jpeg",
        ".webp",
        ".ktx2",
        ".hdr",
        ".exr",
        ".dds",
        ".tga",
        ".woff2",
        ".woff",
        ".ttf",
        ".otf",
        ".mp4",
        ".webm",
    }
)

# The viewer does not version binary URLs, so an immutable year would pin stale
# meshes after a re-stage. An hour still collapses a whole backfill run (and a
# renderer's persistent browser profile) onto one download per asset.
BINARY_CACHE = "public, max-age=3600, stale-while-revalidate=86400"
# Documents and scripts either carry ?v=N or must be revalidated to pick up a
# renderer bump.
DOCUMENT_CACHE = "no-cache"

SETTINGS_KEY: web.AppKey[ViewerOriginSettings] = web.AppKey("settings")
SESSION_KEY: web.AppKey[ClientSession] = web.AppKey("session")


HOP_BY_HOP = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
        "host",
        "content-length",
    }
)


class ViewerOriginSettings:
    def __init__(
        self,
        *,
        root: Path,
        upstream: str,
        bind: str,
        port: int,
        upstream_timeout: float = 30.0,
    ) -> None:
        self.root = root
        self.upstream = upstream.rstrip("/")
        self.bind = bind
        self.port = port
        self.upstream_timeout = upstream_timeout

    @classmethod
    def from_env(cls) -> ViewerOriginSettings:
        return cls(
            root=Path(
                os.environ.get(
                    "AMC_WORKSHOP_VIEWER_ROOT",
                    "/var/www/www.aseanmotorclub.com/vehicles",
                )
            ),
            upstream=os.environ.get(
                "AMC_WORKSHOP_ORIGIN_UPSTREAM", "http://127.0.0.1:7003"
            ),
            bind=os.environ.get("AMC_VIEWER_ORIGIN_BIND", "127.0.0.1"),
            port=int(os.environ.get("AMC_VIEWER_ORIGIN_PORT", "7004")),
            upstream_timeout=float(
                os.environ.get("AMC_VIEWER_ORIGIN_UPSTREAM_TIMEOUT", "30")
            ),
        )


def _resolve_asset(root: Path, tail: str) -> Path | None:
    """Map a request path onto the viewer tree, or None if it escapes it."""
    relative = tail.strip("/")
    if not relative:
        relative = "index.html"
    parts = [part for part in relative.split("/") if part]
    if not parts or any(part.startswith(".") for part in parts):
        return None
    base = root.resolve()
    candidate = (base / Path(*parts)).resolve()
    try:
        candidate.relative_to(base)
    except ValueError:
        return None
    return candidate


def _cache_control(path: Path) -> str:
    return BINARY_CACHE if path.suffix.lower() in BINARY_SUFFIXES else DOCUMENT_CACHE


async def _serve_vehicle(request: web.Request) -> web.StreamResponse:
    settings = request.app[SETTINGS_KEY]
    path = _resolve_asset(settings.root, request.match_info.get("tail", ""))
    if path is None:
        raise web.HTTPNotFound()
    if path.is_dir():
        path = path / "index.html"
    if not path.is_file():
        raise web.HTTPNotFound()

    response = web.FileResponse(path)
    response.headers["Cache-Control"] = _cache_control(path)
    response.headers["X-Viewer-Origin"] = "amc"
    # GLB payloads are already compressed; gzip/mime-types are handled here so
    # proxies in front of us do not have to guess.
    suffix = path.suffix.lower()
    if suffix == ".glb":
        response.headers.setdefault("Content-Type", "model/gltf-binary")
    elif suffix == ".gltf":
        response.headers.setdefault("Content-Type", "model/gltf+json")
    return response


async def _proxy_api(request: web.Request) -> web.StreamResponse:
    settings = request.app[SETTINGS_KEY]
    tail = request.match_info.get("tail", "")
    query = request.query_string
    target = f"{settings.upstream}/api/{tail}"
    if query:
        target = f"{target}?{query}"

    headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in HOP_BY_HOP
    }
    body = await request.read() if request.method not in {"GET", "HEAD"} else None

    session = request.app[SESSION_KEY]
    try:
        async with session.request(
            request.method,
            target,
            headers=headers,
            data=body,
            timeout=ClientTimeout(total=settings.upstream_timeout),
            allow_redirects=False,
        ) as upstream:
            payload = await upstream.read()
            response = web.Response(
                status=upstream.status,
                body=payload,
                headers={
                    key: value
                    for key, value in upstream.headers.items()
                    if key.lower() not in HOP_BY_HOP
                },
            )
    except Exception as exc:  # noqa: BLE001 - surface any upstream failure as 502
        log.warning("upstream %s failed: %s", target, exc)
        raise web.HTTPBadGateway(reason=f"workshop app unavailable: {exc}") from exc
    response.headers["X-Viewer-Origin"] = "amc-proxy"
    return response


async def _health(request: web.Request) -> web.StreamResponse:
    settings = request.app[SETTINGS_KEY]
    index = settings.root / "index.html"
    return web.json_response(
        {
            "ok": index.is_file(),
            "root": str(settings.root),
            "upstream": settings.upstream,
        },
        status=200 if index.is_file() else 503,
    )


async def _session_start(app: web.Application) -> None:
    app[SESSION_KEY] = ClientSession()


async def _session_close(app: web.Application) -> None:
    session: ClientSession | None = app.get(SESSION_KEY)
    if session is not None:
        await session.close()


def build_app(settings: ViewerOriginSettings) -> web.Application:
    app = web.Application()
    app[SETTINGS_KEY] = settings
    app.on_startup.append(_session_start)
    app.on_cleanup.append(_session_close)
    app.router.add_get("/healthz", _health)
    app.router.add_get("/vehicles/{tail:.*}", _serve_vehicle)
    app.router.add_route("*", "/api/{tail:.*}", _proxy_api)
    return app


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bind", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(message)s",
    )
    settings = ViewerOriginSettings.from_env()
    if args.bind:
        settings.bind = args.bind
    if args.port:
        settings.port = args.port
    if not settings.root.is_dir():
        raise SystemExit(f"viewer root does not exist: {settings.root}")
    log.info(
        "viewer origin %s:%s root=%s upstream=%s",
        settings.bind,
        settings.port,
        settings.root,
        urlsplit(settings.upstream).netloc or settings.upstream,
    )
    web.run_app(build_app(settings), host=settings.bind, port=settings.port, print=None)


if __name__ == "__main__":
    main()
