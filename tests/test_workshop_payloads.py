"""Payload decoding and normalization tests."""

from __future__ import annotations

import json
import zlib

import pytest
from workshop_support import _payload

from amc_peripheral.workshop.payloads import (
    PayloadError,
    convert_attachment,
    decode_payload,
    normalize_character_vehicle,
    normalize_workshop,
    vehicle_display_name,
    vehicle_slug,
)


def _row(**overrides):
    row = {
        "id": 59797,
        "vehicle_key": "Liliput",
        "revision": 3,
        "json_sha256": "a" * 64,
        "config_hash": "b" * 64,
    }
    row.update(overrides)
    return row


def test_declared_payload_size_is_bounded():
    with pytest.raises(PayloadError):
        decode_payload(_payload(), declared_bytes=3 * 1024 * 1024, max_bytes=2 * 1024 * 1024)


def test_decompression_output_is_bounded():
    bomb = zlib.compress(b"x" * 5000)
    with pytest.raises(PayloadError):
        decode_payload(bomb, max_bytes=1000)


def test_invalid_compression_and_json_are_rejected():
    with pytest.raises(PayloadError):
        decode_payload(b"not zlib", max_bytes=1000)
    with pytest.raises(PayloadError):
        decode_payload(zlib.compress(b"[]"), max_bytes=1000)


def test_normalization_preserves_paint_and_decal_fields():
    raw = json.loads(zlib.decompress(_payload()))
    config = normalize_workshop(
        _row(), raw, asset_version="manifest-1",
        known_attachment_keys={"Attachment_Light_04"},
    )
    assert config["schemaVersion"] == 1
    assert config["vehicle"]["slug"] == "liliput"
    assert config["paint"]["colors"] == [{
        "slot": "Body_01", "rgba": [18, 24, 30, 255],
        "metallic": 0.3, "roughness": 0.5,
    }]
    layer = config["decals"][0]
    assert layer["key"] == "Numbers_01_077-76"
    assert layer["rot"] == [-89.9, 10.0, 11.8]  # yaw, pitch, roll
    assert layer["pos"] == [20.1108, 57.7052]
    assert layer["scale"] == 0.427
    assert layer["stretch"] == 2.0
    assert layer["coverage"] == 0.75
    assert layer["flags"] == 12


def test_attachment_conversion_matches_ue_to_gltf_axes():
    raw = json.loads(zlib.decompress(_payload()))
    config = normalize_workshop(
        _row(), raw, asset_version="manifest-1",
        known_attachment_keys={"Attachment_Light_04"},
    )
    attachment = config["attachments"][0]
    assert attachment["key"] == "Attachment_Light_04"
    assert attachment["position"] == pytest.approx([2.41, 0.9, 0.0])
    assert attachment["scale"] == [1.0, 1.0, 1.0]
    assert len(attachment["rotation"]) == 4


def test_racers_xyz_attachment_rotations_match_named_rotators():
    xyz = convert_attachment(
        {"x": -215, "y": 16, "z": 35},
        {"x": 45.06376647949219, "y": -90.2572021484375, "z": 90},
        {"x": 1, "y": 1, "z": 1},
    )
    named = convert_attachment(
        {"X": -215, "Y": 16, "Z": 35},
        {"pitch": 45.06376647949219, "yaw": -90.2572021484375, "roll": 90},
        {"X": 1, "Y": 1, "Z": 1},
    )
    assert xyz["rotation"] == pytest.approx(named["rotation"])
    assert xyz["rotation"] != pytest.approx([0, 0, 0, 1])


def test_unknown_attachment_is_reported_not_dropped_silently():
    raw = json.loads(zlib.decompress(_payload(attachment_known=False)))
    config = normalize_workshop(
        _row(), raw, asset_version="manifest-1",
        known_attachment_keys={"Attachment_Light_04"},
    )
    assert config["attachments"] == []
    assert config["renderReport"]["unsupportedAttachments"] == ["Attachment_Unknown"]
    assert any("Attachment_Unknown" in w for w in config["renderReport"]["warnings"])


def test_decal_limit_is_reported():
    raw = json.loads(zlib.decompress(_payload(extra_layers=40)))
    config = normalize_workshop(
        _row(), raw, asset_version="manifest-1",
        known_attachment_keys={"Attachment_Light_04"},
    )
    assert config["renderReport"]["decalLayersTotal"] == 41
    assert config["renderReport"]["decalLayersRenderable"] == 32
    assert any("32 of 41" in w for w in config["renderReport"]["warnings"])


def test_vehicle_slug_aliases():
    assert vehicle_slug("3") == "maity"
    assert vehicle_slug("Vamos3") == "vamos3"
    assert vehicle_slug("Sports_01") == "raton"
    assert vehicle_display_name("Sports_01") == "Raton"
    assert vehicle_display_name("3") == "Maity"
    assert vehicle_display_name("Vamos3") == "Vamos3"


def test_character_vehicle_pascal_config_normalizes():
    row = {
        "id": 2367,
        "config_hash": "c" * 64,
        "config": {
            "VehicleName": "Vamos3",
            "Customization": {
                "BodyMaterialIndex": 0,
                "BodyColors": [{
                    "materialSlotName": "Body_01",
                    "color": {"r": 0, "g": 0, "b": 0, "a": 255},
                }],
            },
            "Decal": {"DecalLayers": [{
                "decalKey": "Numbers_01_077-76",
                "color": {"r": 255, "g": 0, "b": 0, "a": 255},
                "Position": {"X": 1, "Y": 2},
                "Rotation": {"Pitch": 3, "Yaw": 4, "Roll": 5},
                "DecalScale": 1, "Stretch": 1, "Coverage": 1, "Flags": 0,
            }]},
            "Parts": [{
                "Key": "DefaultAttachment", "Slot": "Attachment0",
                "StringValues": {"0": "Attachment_Light_04"},
                "VectorValues": {
                    "0": {"X": 100, "Y": 0, "Z": 0},
                    "1": {"X": 0, "Y": 0, "Z": 0},
                },
            }],
        },
    }
    config = normalize_character_vehicle(
        row, asset_version="vamos-manifest",
        known_attachment_keys={"Attachment_Light_04"},
    )
    assert config["source"]["kind"] == "character_vehicle"
    assert config["source"]["configHash"] == "c" * 64
    assert config["vehicle"]["slug"] == "vamos3"
    assert config["paint"]["colors"][0]["rgba"] == [0, 0, 0, 255]
    assert config["decals"][0]["rot"] == [4.0, 3.0, 5.0]
    assert config["attachments"][0]["position"] == pytest.approx([1.0, 0.0, 0.0])
