"""Per-vehicle workshop placeholder lookup."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

MANIFEST_PATH = Path(__file__).with_name("placeholder_vehicles.json")


@lru_cache(maxsize=1)
def placeholder_vehicles() -> dict[str, str]:
    try:
        payload = json.loads(MANIFEST_PATH.read_text())
    except (OSError, ValueError):
        return {}
    vehicles = payload.get("vehicles", payload)
    if not isinstance(vehicles, dict):
        return {}
    return {str(key): str(slug) for key, slug in vehicles.items()}


@lru_cache(maxsize=1)
def _known_slugs() -> frozenset[str]:
    return frozenset(placeholder_vehicles().values())


def vehicle_placeholder_url(vehicle_key: object) -> str:
    """Return the committed per-vehicle wireframe, or an empty src if unknown."""
    key = str(vehicle_key or "")
    mapping = placeholder_vehicles()
    slug = mapping.get(key)
    if not slug:
        # Some callers hold the viewer display name rather than the workshop
        # key (for example "Vamos3" instead of "Trailer_Vamos3").
        direct = key.lower()
        if direct in _known_slugs():
            slug = direct
    if not slug:
        return ""
    return f"/workshop/static/placeholders/{slug}.webp"
