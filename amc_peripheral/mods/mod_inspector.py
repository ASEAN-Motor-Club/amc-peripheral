"""Inspect uploaded mod PAK files using mod_explore."""

import asyncio
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

MOD_EXPLORE = os.environ.get("TIRE_BUILDER_MOD_EXPLORE", "mod_explore")


async def inspect_mod_pak(pak_path: Path) -> dict:
    """
    Run mod_explore --list on a PAK file.

    Returns dict with:
      - file_count: total files in PAK
      - has_vehicle_parts0: whether it contains VehicleParts0.uasset
      - tire_asset_count: number of tire .uasset files detected
    """
    proc = await asyncio.create_subprocess_exec(
        MOD_EXPLORE,
        str(pak_path),
        "--list",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        raise RuntimeError(
            f"mod_explore failed (exit {proc.returncode}): {stderr.decode()}"
        )

    output = stdout.decode()
    lines = output.strip().splitlines()

    has_vehicle_parts0 = False
    tire_asset_count = 0
    file_count = 0

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("===") or stripped.startswith("Summary:"):
            # Parse summary line for total count
            if stripped.startswith("Summary:"):
                # "Summary: X .uasset, Y .uexp, Z other"
                parts = stripped.split()
                for i, p in enumerate(parts):
                    if p == ".uasset,":
                        try:
                            file_count += int(parts[i - 1])
                        except (ValueError, IndexError):
                            pass
                    elif p == ".uexp,":
                        try:
                            file_count += int(parts[i - 1])
                        except (ValueError, IndexError):
                            pass
                    elif p == "other":
                        try:
                            file_count += int(parts[i - 1])
                        except (ValueError, IndexError):
                            pass
            continue

        if stripped.startswith("Opening") or stripped.startswith("Version:"):
            continue
        if stripped.startswith("Mount point:") or stripped.startswith("Total files:"):
            if stripped.startswith("Total files:"):
                try:
                    file_count = int(stripped.split(":")[-1].strip())
                except ValueError:
                    pass
            continue

        # File listing lines (indented file paths)
        if "VehicleParts0.uasset" in stripped:
            has_vehicle_parts0 = True
        if "/Tire/" in stripped and stripped.endswith(".uasset"):
            tire_asset_count += 1

    return {
        "file_count": file_count,
        "has_vehicle_parts0": has_vehicle_parts0,
        "tire_asset_count": tire_asset_count,
    }
