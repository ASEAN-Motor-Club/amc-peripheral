"""Workshop/CharacterVehicle payload normalization for the Three.js viewer."""

from __future__ import annotations

import json
import math
import re
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
    "Pickup_02": "ranch",
    "Dory_Wrecker": "dorywrecker",
    "Kuda_Dryvan_4x2": "kuda_dyrvan_4x2",
    "Nuke_Police": "nukepolice",
    "Police_01": "police",
    "PoliceInterceptor_01": "policeinterceptor1",
    "Kira_RollbackTow": "kira_rollback",
    # Asset names that do not match the workshop vehicle key. Generated from
    # the game's Vehicles data table (VehicleClass.asset) against the extracted
    # viewer folder names; keep this table universal rather than fixing keys
    # one report at a time.
    "Bus": "aircity",
    "DumpTruck_01": "dumpy",
    "GarbageTruck_01": "compacty",
    "Kuda": "kuda_semi",
    "MixerTruck_01": "mixi",
    "SchoolBus_01": "sv200",
    "SemiTruck_01": "fl1",
    "TowTruck_01": "pulio",
    "Van_01": "vani",
    "Trailer_30ft_Log_01": "trailer_9m_log_01",
    "Trailer_Bulko": "bulko",
    "Trailer_Carry": "carry",
    "Trailer_Conter_Lead_20ft": "conter_lead_20ft",
    "Trailer_Conter_Lead_40ft": "conter_lead_40ft",
    "Trailer_Conter_Rear_20ft": "conter_rear_20ft",
    "Trailer_Conter_Rear_40ft": "conter_rear_40ft",
    "Trailer_Cotra_20_3": "cotra_20_3s",
    "Trailer_Cotra_20_3L": "cotra_20_3l",
    "Trailer_Cotra_40_3": "cotra_40_3",
    "Trailer_Dinky_Dryvan": "dinky_dryvan",
    "Trailer_Dinky_Flatbed": "dinky_flatbed",
    "Trailer_Dinky_Tanker": "dinky_tanker",
    "Trailer_Dooly_D1": "dooly_d1",
    "Trailer_Dooly_D2": "dooly_d2",
    "Trailer_Dooly_S1": "dooly_s1",
    "Trailer_Dooly_S2": "dooly_s2",
    "Trailer_Eastwood": "eastwood",
    "Trailer_Flaber_Lead": "flaber_lead",
    "Trailer_Flaber_Rear": "flaber_rear",
    "Trailer_Flanker3": "flanker3",
    "Trailer_Flanker3S": "flanker3s",
    "Trailer_Hobber_Lead": "hobber_lead",
    "Trailer_Hobber_Rear": "hobber_rear",
    "Trailer_LoboVan": "lobovan",
    "Trailer_Lomax": "lomax",
    "Trailer_Olbe": "olbe",
    "Trailer_Oldum": "oldum",
    "Trailer_Ollok": "ollok",
    "Trailer_Shobed_10": "shobed_10",
    "Trailer_Shobed_7": "shobed_7",
    "Trailer_Shotan_10": "shotan_10",
    "Trailer_Shotan_7": "shotan_7",
    "Trailer_Shovan_10": "shovan_10",
    "Trailer_Shovan_7": "shovan_7",
    "Trailer_Taber_Lead": "taber_lead",
    "Trailer_Taber_Rear": "taber_rear",
    "Trailer_Tanko40": "tanko40",
    "Trailer_Vamos3": "vamos3",
}
VEHICLE_DISPLAY_NAMES = {
    "1": "Hana",
    "2": "Stinger",
    "3": "Maity",
    "4": "Spider",
    "Bus": "Air City",
    "Sports_01": "Raton",
    "Pickup_02": "Ranch",
    "PoliceInterceptor_01": "Police Interceptor 1",
    "Police_01": "Police",
    "SchoolBus_01": "SV200",
    "SemiTruck_01": "FL1",
    "TowTruck_01": "Pulio",
    "Van_01": "Vani",
    "DumpTruck_01": "Dumpy",
    "MixerTruck_01": "Mixi",
    "GarbageTruck_01": "Compacty",
    "Kuda_LiveFishTank_4x2": "Kuda LFT",
    "Kira_RollbackTow": "Kira Rollback Tow",
    "EVan": "E-Van",
    "FormulaSCM": "Formula SCM",
    "EnfoGT": "Enfo GT",
    "CheetahMk1": "Cheetah Mk1",
    "GolimaRotator": "Golima Rotator",
    "Trophy2": "Trophy 2",
    "Elisa2": "Elisa 2",
    "Goliath4": "Goliath 4",
    "Goliath6": "Goliath 6",
    "Goliath10": "Goliath 10",
    "Trailer_Bulko": "Bulko",
    "Trailer_Carry": "Carry",
    "Trailer_Cotra_20_3": "Cotra 20-3S",
    "Trailer_Cotra_20_3L": "Cotra 20-3L",
    "Trailer_Cotra_40_3": "Cotra 40-3",
    "Trailer_Shovan_7": "Shovan 7",
    "Trailer_Shovan_10": "Shovan 10",
    "Trailer_Shobed_7": "Shobed 7",
    "Trailer_Shobed_10": "Shobed 10",
    "Trailer_Shotan_7": "Shotan 7",
    "Trailer_Shotan_10": "Shotan 10",
    "Trailer_30ft_Log_01": "30 Foot Log Trailer",
    "Trailer_30ft_Tanker_01": "30 Foot Tanker Trailer",
    "Trailer_9m_Flat_01": "9m Flat Trailer",
    "Trailer_Small_Cage_01": "Small Cage Trailer",
    "Trailer_Middle_Tanker_01": "Middle Tanker Trailer",
}


def vehicle_display_name(vehicle_key: str) -> str:
    key = str(vehicle_key or "")
    if key in VEHICLE_DISPLAY_NAMES:
        return VEHICLE_DISPLAY_NAMES[key]
    # Convert internal CamelCase keys (FormulaSCM, Kira_RollbackTow) into
    # readable labels; underscore-separated keys keep their existing shape.
    label = key[len("Trailer_"):] if key.startswith("Trailer_") else key
    label = label.replace("_", " ")
    label = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", label)
    return re.sub(r"\s+", " ", label).strip()


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
    if isinstance(value, dict) and any(
        key in value for key in ("Pitch", "pitch", "Yaw", "yaw", "Roll", "roll")
    ):
        return (
            _number(value.get("Pitch", value.get("pitch"))),
            _number(value.get("Yaw", value.get("yaw"))),
            _number(value.get("Roll", value.get("roll"))),
        )
    # Workshop VectorValues store Euler angles as (Roll, Pitch, Yaw).
    x, y, z = _xyz(value)
    return y, z, x


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
        # Workshop scale triples often initialise an unused axis to 0 (e.g.
        # (1, 0.88, 0) on item 183316). The game treats a partial zero as an
        # unset axis, not a collapse; only an all-zero triple hides the part.
        if sx or sy or sz:
            sx = sx or 1.0
            sy = sy or 1.0
            sz = sz or 1.0
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
