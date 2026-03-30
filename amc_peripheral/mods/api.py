"""
aiohttp API routes for tire mod building.

Endpoints:
  POST /api/mods/tire/upload  — Upload a .pak file for compatibility inspection
  POST /api/mods/tire/build   — Build a tire mod PAK from JSON config
  GET  /api/mods/health       — Health check
"""

import logging
import shutil
import tempfile
import time
import uuid
from collections import defaultdict
from pathlib import Path

from aiohttp import web
from pydantic import ValidationError

from .mod_inspector import inspect_mod_pak
from .schemas import BuildRequest, ModInspection
from .tire_builder import build_tire_pack

logger = logging.getLogger(__name__)

# In-memory storage for uploaded mods (1hr TTL)
_uploaded_mods: dict[str, dict] = {}  # mod_id -> {path, filename, expires}
_MOD_TTL_SECONDS = 3600
_MAX_UPLOAD_SIZE = 50 * 1024 * 1024  # 50MB

# Rate limiting: 5 builds per minute per IP
_rate_limits: dict[str, list[float]] = defaultdict(list)
_RATE_LIMIT = 5
_RATE_WINDOW = 60


def _check_rate_limit(ip: str) -> bool:
    """Return True if request is allowed."""
    now = time.time()
    # Remove old entries
    _rate_limits[ip] = [t for t in _rate_limits[ip] if now - t < _RATE_WINDOW]
    if len(_rate_limits[ip]) >= _RATE_LIMIT:
        return False
    _rate_limits[ip].append(now)
    return True


def _cleanup_expired_mods():
    """Remove expired uploaded mod files."""
    now = time.time()
    expired = [
        mid for mid, info in _uploaded_mods.items() if info["expires"] < now
    ]
    for mid in expired:
        info = _uploaded_mods.pop(mid, None)
        if info and Path(info["path"]).exists():
            shutil.rmtree(Path(info["path"]).parent, ignore_errors=True)


async def handle_upload(request: web.Request) -> web.Response:
    """
    POST /api/mods/tire/upload

    Accepts multipart/form-data with a .pak file.
    Returns inspection results.
    """
    _cleanup_expired_mods()

    reader = await request.multipart()
    field = await reader.next()

    if field is None or field.name != "file":
        return web.json_response({"error": "No file field provided"}, status=400)

    filename = field.filename or "unknown.pak"
    if not filename.endswith(".pak"):
        return web.json_response(
            {"error": "Only .pak files are accepted"}, status=400
        )

    # Read file with size limit
    data = bytearray()
    while True:
        chunk = await field.read_chunk(8192)
        if not chunk:
            break
        data.extend(chunk)
        if len(data) > _MAX_UPLOAD_SIZE:
            return web.json_response(
                {"error": f"File too large (max {_MAX_UPLOAD_SIZE // 1024 // 1024}MB)"},
                status=413,
            )

    mod_id = str(uuid.uuid4())[:8]
    mod_dir = Path(tempfile.mkdtemp(prefix=f"modupload_{mod_id}_"))
    pak_path = mod_dir / filename

    pak_path.write_bytes(data)
    logger.info("Uploaded mod: %s (%d bytes) -> %s", filename, len(data), mod_id)

    # Inspect the PAK
    try:
        inspection = await inspect_mod_pak(pak_path)
    except Exception as e:
        logger.error("Failed to inspect %s: %s", filename, e)
        shutil.rmtree(mod_dir, ignore_errors=True)
        return web.json_response(
            {"error": f"Failed to inspect PAK: {str(e)}"}, status=400
        )

    # Store for later use in builds
    _uploaded_mods[mod_id] = {
        "path": str(pak_path),
        "filename": filename,
        "expires": time.time() + _MOD_TTL_SECONDS,
    }

    result = ModInspection(
        mod_id=mod_id,
        filename=filename,
        file_count=inspection["file_count"],
        has_vehicle_parts0=inspection["has_vehicle_parts0"],
        tire_asset_count=inspection["tire_asset_count"],
    )

    return web.json_response(result.model_dump())


async def handle_build(request: web.Request) -> web.Response:
    """
    POST /api/mods/tire/build

    Accepts JSON body matching BuildRequest schema.
    Returns the .pak file as an octet-stream download.
    """
    ip = request.remote or "unknown"
    if not _check_rate_limit(ip):
        return web.json_response(
            {"error": "Rate limit exceeded. Max 5 builds per minute."},
            status=429,
        )

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    try:
        build_req = BuildRequest(**body)
    except ValidationError as e:
        return web.json_response(
            {"error": "Validation failed", "details": e.errors()}, status=400
        )

    # Resolve compat mod paths
    compat_paths = []
    for mod_id in build_req.compat_mods:
        mod_info = _uploaded_mods.get(mod_id)
        if not mod_info:
            return web.json_response(
                {"error": f"Compat mod not found: {mod_id}. Upload it first."},
                status=400,
            )
        compat_paths.append(Path(mod_info["path"]))

    # Build the config dict matching create_tirepack.py format
    config = {
        "tires": [
            {
                "tire_physics": {
                    "name": t.tire_physics.name,
                    "template": t.tire_physics.template,
                    "static_mu": t.tire_physics.static_mu,
                    "sliding_mu": t.tire_physics.sliding_mu,
                    **(
                        {"offroad_friction": t.tire_physics.offroad_friction}
                        if t.tire_physics.offroad_friction is not None
                        else {}
                    ),
                },
                "tire_part": {
                    "row_name": t.tire_part.row_name,
                    "display_name": t.tire_part.display_name,
                    "cost": t.tire_part.cost,
                    "mass_kg": t.tire_part.mass_kg,
                    "vehicle_types": [vt.value for vt in t.tire_part.vehicle_types],
                    "tire_asset_path": t.tire_part.tire_asset_path,
                },
            }
            for t in build_req.tires
        ]
    }

    try:
        pak_path = await build_tire_pack(
            config, build_req.pack_name, compat_paths
        )
    except Exception as e:
        logger.error("Build failed: %s", e, exc_info=True)
        return web.json_response(
            {"error": f"Build failed: {str(e)}"}, status=500
        )

    # Send the PAK file as download
    filename = f"{build_req.pack_name}_P.pak"
    pak_data = pak_path.read_bytes()

    # Clean up build artifacts
    build_dir = pak_path.parent
    shutil.rmtree(build_dir, ignore_errors=True)

    return web.Response(
        body=pak_data,
        content_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(pak_data)),
        },
    )


async def handle_health(request: web.Request) -> web.Response:
    """GET /api/mods/health — basic health check."""
    return web.json_response({"status": "ok"})


def create_app() -> web.Application:
    """Create and configure the aiohttp application."""
    app = web.Application(client_max_size=_MAX_UPLOAD_SIZE + 1024)

    # CORS middleware
    @web.middleware
    async def cors_middleware(request, handler):
        if request.method == "OPTIONS":
            return web.Response(
                headers={
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                    "Access-Control-Allow-Headers": "Content-Type",
                    "Access-Control-Max-Age": "3600",
                }
            )
        response = await handler(request)
        response.headers["Access-Control-Allow-Origin"] = "*"
        return response

    app.middlewares.append(cors_middleware)

    app.router.add_post("/api/mods/tire/upload", handle_upload)
    app.router.add_post("/api/mods/tire/build", handle_build)
    app.router.add_get("/api/mods/health", handle_health)

    return app
