#!/usr/bin/env python3
"""Build the workshop vehicle-key -> viewer-slug placeholder manifest.

Inputs are the viewer catalogue and a JSON list of distinct workshop vehicle
keys. The output is committed; capture runs later and does not query the DB.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path


def _vehicle_slug():
    """Load payloads.py directly; its package __init__ imports the web app."""
    path = Path(__file__).resolve().parents[2] / "amc_peripheral/workshop/payloads.py"
    spec = importlib.util.spec_from_file_location("_workshop_payloads", path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.vehicle_slug


def build(catalogue_rows: list[dict], keys: list[str], resolve) -> dict[str, str]:
    slugs = {str(row["slug"]) for row in catalogue_rows}
    resolved: dict[str, str] = {}
    missing: list[str] = []
    for key in keys:
        slug = resolve(str(key))
        if slug not in slugs:
            missing.append(str(key))
        else:
            resolved[str(key)] = slug

    if missing:
        raise SystemExit(f"unresolved vehicle keys: {missing}")

    by_slug: dict[str, list[str]] = {}
    for key, slug in resolved.items():
        by_slug.setdefault(slug, []).append(key)
    duplicates = {slug: names for slug, names in by_slug.items() if len(names) > 1}
    if duplicates:
        raise SystemExit(f"vehicle keys map to the same viewer slug: {duplicates}")

    return dict(sorted(resolved.items(), key=lambda pair: pair[0].lower()))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vehicles-json", required=True, type=Path)
    parser.add_argument("--keys-json", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    catalogue = json.loads(args.vehicles_json.read_text())
    keys = json.loads(args.keys_json.read_text())
    if not isinstance(catalogue, list) or not isinstance(keys, list):
        print("inputs must both be JSON lists", file=sys.stderr)
        return 2

    mapping = build(catalogue, [str(key) for key in keys], _vehicle_slug())
    payload = {
        "version": 1,
        "source": "Motor Town viewer catalogue (vehicles.json)",
        "camera": "iso",
        "format": "webp",
        "vehicles": mapping,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"wrote {len(mapping)} keys -> {len(set(mapping.values()))} slugs to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
