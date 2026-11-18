#!/usr/bin/env python3
"""Merge Motor Town colour-slot defaults into an mt-viewer manifest.

Reads a vehicle manifest (e.g. boxy.json) and, for each part, looks up the
game's part ColourSlots defaults (from vehicle_colours.json, which is derived
from the extracted VehicleParts/AeroParts/Wheels/... DataTables) so the
three.js viewer can tint the part with its stock default colour + metallic +
roughness.

Only parts that carry a colour slot get a `color` entry; everything else is
left neutral (the viewer falls back to its default grey). The mounting part's
name is resolved via a `part` field on each manifest entry — the generator maps
blueprint component ids to the game part row they mount.

Usage:
  python3 merge_colours.py boxy.json vehicle_colours.json [-o out.json]
"""
import argparse, json, sys


def hex_of(rgba):
    if not isinstance(rgba, dict) or not isinstance(rgba.get("R"), int):
        return None
    return "#%02X%02X%02X" % (rgba["R"], rgba["G"], rgba["B"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("manifest")
    ap.add_argument("colours")
    ap.add_argument("-o", "--output")
    args = ap.parse_args()

    manifest = json.load(open(args.manifest))
    colours = json.load(open(args.colours))["vehicle_parts"]

    # Map each manifest part to a game part name.
    # The manifest may tag each entry with `part` (game part name). If absent,
    # fall back to matching by id prefix where possible.
    patched = 0
    for part in manifest.get("parts", []):
        part_name = part.get("part")
        if not part_name:
            continue
        slot_data = colours.get(part_name)
        if not slot_data:
            continue
        slots = slot_data.get("slots", {})
        if not slots:
            continue
        # Use the first colour slot's default as the part tint (a part usually
        # has one paint slot; multi-slot parts like Trophy2_03 expose Wheel_01
        # and Wheel_02 for separate sections).
        first_slot = next(iter(slots.values()))
        hexc = hex_of(first_slot.get("default_rgba"))
        if hexc is None:
            continue
        part["color"] = {
            "hex": hexc,
            "metalness": first_slot.get("metallic", 0.3),
            "roughness": first_slot.get("roughness", 0.5),
        }
        # keep track of which slot we used
        part["color"]["slot"] = next(iter(slots.keys()))
        patched += 1

    out = args.output or args.manifest
    with open(out, "w") as f:
        json.dump(manifest, f, indent=1)
    print(f"patched {patched}/{len(manifest.get('parts', []))} parts -> {out}")


if __name__ == "__main__":
    main()
