"""Workshop/CharacterVehicle payload normalization for the Three.js viewer."""

from __future__ import annotations

import json
import math
import zlib
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
DECAL_LIMIT = 128
RENDERER_DECAL_LIMIT = 32

VEHICLE_SLUG_ALIASES = {
    "1": "hana",
    "2": "stinger",
    "3": "maity",
    "4": "spider",
    "Sports_01": "raton",
}
VEHICLE_DISPLAY_NAMES = {
    "1": "Hana",
    "2": "Stinger",
    "3": "Maity",
    "4": "Spider",
    "Sports_01": "Raton",
}


def vehicle_display_name(vehicle_key: str) -> str:
    key = str(vehicle_key or "")
    return VEHICLE_DISPLAY_NAMES.get(key, key.replace("_", " "))


class PayloadError(ValueError):
    pass


def decode_payload(blob: bytes, *, declared_bytes: int | None = None,
                   max_bytes: int) -> dict[str, Any]:
    if not isinstance(blob, (bytes, bytearray, memoryview)):
        raise PayloadError("payload is not compressed bytes")
    if declared_bytes is not None and declared_bytes > max_bytes:
        raise PayloadError("declared payload exceeds size limit")
    obj = zlib.decompressobj()
    try:
        raw = obj.decompress(bytes(blob), max_bytes + 1)
    except zlib.error as exc:
        raise PayloadError(f"payload decompression failed: {exc}") from None
    if len(raw) > max_bytes or obj.unconsumed_tail or not obj.eof:
        raise PayloadError("payload exceeds decoded size limit")
    try:
        data = json.loads(raw)
    except (UnicodeDecodeError, ValueError) as exc:
        raise PayloadError(f"payload is not valid JSON: {exc}") from None
    if not isinstance(data, dict):
        raise PayloadError("payload root is not an object")
    return data


def vehicle_slug(vehicle_key: str) -> str:
    key = str(vehicle_key or "")
    if key in VEHICLE_SLUG_ALIASES:
        return VEHICLE_SLUG_ALIASES[key]
    if key.startswith("Trailer_"):
        return key.removeprefix("Trailer_").lower()
    return key.lower()


def _int_byte(value: Any) -> int:
    try:
        return max(0, min(255, int(value)))
    except (TypeError, ValueError):
        return 0


def _rgba(value: Any) -> list[int]:
    value = value if isinstance(value, dict) else {}
    return [
        _int_byte(value.get("r", value.get("R"))),
        _int_byte(value.get("g", value.get("G"))),
        _int_byte(value.get("b", value.get("B"))),
        _int_byte(value.get("a", value.get("A", 255))),
    ]


def _number(value: Any, default: float = 0.0) -> float:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return default
    return value if math.isfinite(value) else default


def _xyz(value: Any, default: float = 0.0) -> list[float]:
    if isinstance(value, dict):
        return [_number(value.get(k, value.get(k.lower(), default))) for k in ("X", "Y", "Z")]
    if isinstance(value, (list, tuple)) and len(value) >= 3:
        return [_number(value[i], default) for i in range(3)]
    return [default, default, default]


def _rotator(value: Any) -> tuple[float, float, float]:
    if isinstance(value, dict):
        return (
            _number(value.get("Pitch", value.get("pitch"))),
            _number(value.get("Yaw", value.get("yaw"))),
            _number(value.get("Roll", value.get("roll"))),
        )
    p, y, r = _xyz(value)
    return p, y, r


def _q_mul(a: tuple[float, float, float, float],
           b: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
        aw * bw - ax * bx - ay * by - az * bz,
    )


def _q_conj(q):
    return (-q[0], -q[1], -q[2], q[3])


def _q_normalize(q):
    n = math.sqrt(sum(c * c for c in q)) or 1.0
    return tuple(c / n for c in q)


def _q_from_rotator(pitch: float, yaw: float, roll: float):
    def axis(ax, ay, az, deg):
        h = math.radians(deg) * 0.5
        s = math.sin(h)
        return (ax * s, ay * s, az * s, math.cos(h))

    return _q_mul(_q_mul(axis(0, 0, 1, yaw), axis(0, 1, 0, pitch)),
                  axis(1, 0, 0, roll))


_QC = _q_from_rotator(0.0, 0.0, -90.0)
_QC_INV = _q_conj(_QC)


def _ue_to_gltf_quat(q):
    return _q_normalize(_q_mul(_q_mul(_QC, q), _QC_INV))


def convert_attachment(position: Any, rotation: Any, scale: Any = None) -> dict[str, Any]:
    x, y, z = _xyz(position)
    pitch, yaw, roll = _rotator(rotation)
    if scale is None:
        sx = sy = sz = 1.0
    else:
        sx, sy, sz = _xyz(scale, 1.0)
    return {
        "position": [x / 100.0, z / 100.0, -y / 100.0],
        "rotation": list(_ue_to_gltf_quat(_q_from_rotator(pitch, yaw, roll))),
        "scale": [sx, sz, sy],
    }


def _indexed(values: Any, index: int, default=None):
    if isinstance(values, dict):
        return values.get(str(index), values.get(index, default))
    if isinstance(values, list) and len(values) > index:
        return values[index]
    return default


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _paint(raw: dict[str, Any]) -> dict[str, Any]:
    paint = _as_dict(raw.get("paint"))
    colors = []
    for entry in paint.get("bodyColors") or paint.get("BodyColors") or []:
        if not isinstance(entry, dict):
            continue
        metallic = entry.get("metallic")
        roughness = entry.get("roughness")
        colors.append({
            "slot": str(entry.get("materialSlotName") or entry.get("Slot") or ""),
            "rgba": _rgba(entry.get("color") or entry.get("Color") or {}),
            "metallic": None if metallic is None else _number(metallic),
            "roughness": None if roughness is None else _number(roughness),
        })
    return {
        "bodyMaterialIndex": int(paint.get("bodyMaterialIndex") or 0),
        "colors": colors,
    }


def _decals(raw: dict[str, Any]) -> list[dict[str, Any]]:
    decal = _as_dict(raw.get("decal"))
    decal = _as_dict(decal.get("decal")) or decal
    layers = decal.get("decalLayers") or decal.get("DecalLayers") or []
    if isinstance(layers, dict):
        layers = list(layers.values())
    out = []
    for layer in layers[:DECAL_LIMIT]:
        if not isinstance(layer, dict):
            continue
        pos = layer.get("position") or layer.get("Position") or {}
        rot = layer.get("rotation") or layer.get("Rotation") or {}
        pitch, yaw, roll = _rotator(rot)
        out.append({
            "key": str(layer.get("decalKey") or layer.get("Key") or ""),
            "color": _rgba(layer.get("color") or layer.get("Color") or {}),
            "pos": [_number(pos.get("x", pos.get("X"))), _number(pos.get("y", pos.get("Y")))],
            "rot": [yaw, pitch, roll],
            "scale": _number(layer.get("decalScale", layer.get("Scale", 1.0)), 1.0),
            "stretch": _number(layer.get("stretch", layer.get("Stretch", 1.0)), 1.0),
            "coverage": _number(layer.get("coverage", layer.get("Coverage", 1.0)), 1.0),
            "flags": int(layer.get("flags", layer.get("Flags", 0)) or 0),
        })
    return out


def _parts(raw: dict[str, Any]) -> list[dict[str, Any]]:
    parts = _as_dict(raw.get("parts"))
    values = parts.get("parts") or parts.get("Parts") or []
    out = []
    for part in values if isinstance(values, list) else []:
        if not isinstance(part, dict):
            continue
        out.append({
            "slot": str(part.get("slot") or part.get("Slot") or ""),
            "key": str(part.get("key") or part.get("Key") or ""),
            "values": {
                "float": part.get("floatValues") or part.get("FloatValues") or {},
                "int64": part.get("int64Values") or part.get("Int64Values") or {},
                "string": part.get("stringValues") or part.get("StringValues") or {},
                "vector": part.get("vectorValues") or part.get("VectorValues") or {},
            },
        })
    return out


def _attachments(parts: list[dict[str, Any]], known_keys: set[str] | None) -> tuple[
        list[dict[str, Any]], list[str]]:
    records, unsupported = [], []
    for part in parts:
        strings = part["values"].get("string") or {}
        key = str(_indexed(strings, 0, "") or "")
        if not key.startswith("Attachment_"):
            continue
        if known_keys is not None and key not in known_keys:
            unsupported.append(key)
            continue
        vectors = part["values"].get("vector") or {}
        transform = convert_attachment(
            _indexed(vectors, 0), _indexed(vectors, 1), _indexed(vectors, 2)
        )
        records.append({
            "key": key,
            "slot": part["slot"],
            **transform,
        })
    return records, sorted(set(unsupported))


def normalize_workshop(
    row: dict[str, Any],
    raw: dict[str, Any],
    *,
    asset_version: str,
    known_attachment_keys: set[str] | None = None,
) -> dict[str, Any]:
    parts = _parts(raw)
    decals = _decals(raw)
    attachments, unsupported_attachments = _attachments(parts, known_attachment_keys)
    tunings = raw.get("tunings") or raw.get("Tunings") or []
    warnings = []
    if len(decals) > RENDERER_DECAL_LIMIT:
        warnings.append(
            f"The viewer renders 32 of {len(decals)} decal layers; "
            f"{len(decals) - RENDERER_DECAL_LIMIT} are not shown."
        )
    for key in unsupported_attachments[:8]:
        warnings.append(f"Attachment mesh not available in the viewer catalogue: {key}")
    return {
        "schemaVersion": SCHEMA_VERSION,
        "source": {
            "kind": "workshop",
            "id": int(row["id"]),
            "revision": int(row.get("revision") or 0),
            "configHash": row.get("json_sha256") or "",
        },
        "vehicle": {
            "key": row["vehicle_key"],
            "slug": vehicle_slug(row["vehicle_key"]),
            "assetVersion": asset_version,
        },
        "paint": _paint(raw),
        "decals": decals,
        "parts": parts,
        "attachments": attachments,
        "tunings": tunings if isinstance(tunings, list) else [],
        "renderReport": {
            "decalLayersTotal": len(decals),
            "decalLayersRenderable": min(len(decals), RENDERER_DECAL_LIMIT),
            "partsTotal": len(parts),
            "attachmentsRenderable": len(attachments),
            "unsupportedAttachments": unsupported_attachments,
            "warnings": warnings,
        },
    }


def normalize_character_vehicle(
    row: dict[str, Any],
    *,
    asset_version: str,
    known_attachment_keys: set[str] | None = None,
) -> dict[str, Any]:
    """Normalize the PascalCase config stored in amc_charactervehicle.config."""
    config = row.get("config") or {}
    if isinstance(config, str):
        config = json.loads(config)
    customization = config.get("Customization") or {}
    raw = {
        "paint": {
            "bodyMaterialIndex": customization.get("BodyMaterialIndex", 0),
            "bodyColors": customization.get("BodyColors") or [],
        },
        "decal": {"decal": {"decalLayers": (config.get("Decal") or {}).get("DecalLayers") or []}},
        "parts": {"parts": config.get("Parts") or []},
    }
    vehicle_name = str(config.get("VehicleName") or row.get("vehicle_name") or "")
    if not vehicle_name:
        raise PayloadError("CharacterVehicle has no vehicle name")
    normalized = normalize_workshop(
        {
            "id": int(row["id"]),
            "vehicle_key": vehicle_name,
            "revision": 0,
            "json_sha256": str(row.get("config_hash") or ""),
        },
        raw,
        asset_version=asset_version,
        known_attachment_keys=known_attachment_keys,
    )
    normalized["source"]["kind"] = "character_vehicle"
    return normalized


def asset_version_for(viewer_root, vehicle_key: str) -> str:
    """Cheap manifest version; unversioned is explicit, never a guessed hash."""
    slug = vehicle_slug(vehicle_key)
    manifest = Path(viewer_root) / slug / f"{slug}.json"
    try:
        return f"manifest-mtime-{int(manifest.stat().st_mtime)}"
    except OSError:
        return "unversioned"
