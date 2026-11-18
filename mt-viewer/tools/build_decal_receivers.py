#!/usr/bin/env python3
"""Emit the exact set of material slots that receive decals, per vehicle.

Motor Town's decal component keeps a material slot when its name is in the
vehicle's `BodyMaterialNames` OR its `DecalableMaterialSlotNames` (the latter is
augmented at runtime with names from equipped parts). The viewer needs that
union; it must not guess from material-name prefixes.

usage: build_decal_receivers.py <parsed_dir> <out_json>
"""
import glob
import json
import os
import re
import sys


def cdo_props(exports, vehicle):
    prefix = "Default__" + vehicle + "_"
    for export in exports:
        if str(export.get("ExportName", "")).startswith(prefix):
            return export.get("Properties") or {}
    return {}


def main():
    parsed_dir, out_path = sys.argv[1], sys.argv[2]
    receivers = {}
    for path in sorted(glob.glob(os.path.join(parsed_dir, "*_parsed.json"))):
        vehicle = re.sub(r"_parsed\.json$", "", os.path.basename(path))
        try:
            data = json.load(open(path))
        except (OSError, ValueError):
            continue
        props = cdo_props(data.get("Data", {}).get("Exports", []), vehicle)
        names = []
        for key in ("BodyMaterialNames", "DecalableMaterialSlotNames"):
            value = props.get(key)
            if isinstance(value, list):
                names.extend(str(v) for v in value if isinstance(v, str))
        slots = list(dict.fromkeys(names))
        if slots:
            receivers[vehicle] = slots
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        json.dump({"format": 1, "vehicles": receivers}, f, indent=1, sort_keys=True)
        f.write("\n")
    print(f"{len(receivers)} vehicles -> {out_path}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(2)
    main()
