"""
Tire mod PAK builder — server-side equivalent of create_tirepack.py.

Orchestrates the C# CargoExtractor (--patch-tire, --add-tire-parts)
and Rust mod_pack to build a tire mod PAK from JSON config.
"""

import asyncio
import json
import logging
import os
import shutil
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

# Tool paths from environment (set by NixOS service)
DOTNET_TOOL = os.environ.get("TIRE_BUILDER_DOTNET_TOOL", "CargoExtractor")
MOD_PACK = os.environ.get("TIRE_BUILDER_MOD_PACK", "mod_pack")
MOD_EXPLORE = os.environ.get("TIRE_BUILDER_MOD_EXPLORE", "mod_explore")
TEMPLATES_DIR = os.environ.get("TIRE_BUILDER_TEMPLATES_DIR", "")


async def _run(cmd: list[str], label: str, cwd: str | None = None) -> str:
    """Run a subprocess and return stdout. Raises on failure."""
    logger.info("Running %s: %s", label, " ".join(cmd))
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
    )
    stdout, stderr = await proc.communicate()
    stdout_str = stdout.decode()
    stderr_str = stderr.decode()

    if proc.returncode != 0:
        logger.error("%s failed (exit %s): %s", label, proc.returncode, stderr_str)
        raise RuntimeError(f"{label} failed: {stderr_str[:500]}")

    if stdout_str:
        logger.info("%s output: %s", label, stdout_str[:200])
    return stdout_str


async def extract_vehicle_parts0(
    mod_pak_path: Path, output_dir: Path
) -> Path | None:
    """Extract VehicleParts0.uasset/.uexp from a mod PAK. Returns path or None."""
    for ext in ["uasset", "uexp"]:
        pak_path = f"MotorTown/Content/DataAsset/VehicleParts/VehicleParts0.{ext}"
        try:
            await _run(
                [MOD_EXPLORE, str(mod_pak_path), "--extract", pak_path],
                f"extract VehicleParts0.{ext}",
            )
            # mod_explore writes to mod_out/ in CWD
            src = Path("mod_out") / f"VehicleParts0.{ext}"
            dst = output_dir / f"VehicleParts0.{ext}"
            if src.exists():
                shutil.move(str(src), str(dst))
        except RuntimeError:
            logger.warning(
                "Could not extract VehicleParts0.%s from %s",
                ext,
                mod_pak_path.name,
            )

    extracted = output_dir / "VehicleParts0.uasset"
    return extracted if extracted.exists() else None


async def build_tire_pack(
    config: dict,
    pack_name: str,
    compat_mod_paths: list[Path] | None = None,
) -> Path:
    """
    Build a tire mod PAK from config dict.

    Returns the path to the generated .pak file.
    """
    if compat_mod_paths is None:
        compat_mod_paths = []

    tires = config.get("tires", [config])  # Support single-tire compat

    build_dir = Path(tempfile.mkdtemp(prefix="tirepack_"))
    try:
        return await _build_in_dir(build_dir, tires, pack_name, compat_mod_paths)
    except Exception:
        # Clean up on failure
        shutil.rmtree(build_dir, ignore_errors=True)
        raise


async def _build_in_dir(
    build_dir: Path,
    tires: list[dict],
    pack_name: str,
    compat_mod_paths: list[Path],
) -> Path:
    """Core build logic inside a temp directory."""

    # Resolve VehicleParts0 base template
    parts0_template = Path(TEMPLATES_DIR) / "VehicleParts0.uasset"

    # If compat mods provided, extract VehicleParts0 from each in order
    if compat_mod_paths:
        for mod_pak in compat_mod_paths:
            extract_dir = Path(tempfile.mkdtemp(prefix="compat_"))
            extracted = await extract_vehicle_parts0(mod_pak, extract_dir)
            if extracted:
                parts0_template = extracted
                logger.info("Using VehicleParts0 from: %s", mod_pak.name)

    if not parts0_template.exists():
        raise RuntimeError(f"VehicleParts0 template not found: {parts0_template}")

    tire_assets = []  # List of (tire_name, uasset_path, uexp_path)

    # Step 1: Create tire physics assets
    for i, entry in enumerate(tires, 1):
        tire_physics = entry["tire_physics"]
        tire_name = tire_physics["name"]
        template_name = tire_physics.get("template", "BasicTire_45")

        tire_template = Path(TEMPLATES_DIR) / f"{template_name}.uasset"
        if not tire_template.exists():
            raise RuntimeError(f"Tire template not found: {tire_template}")

        # Write single-entry config
        single_config = build_dir / f"tire_{i}.json"
        single_config.write_text(json.dumps(entry))

        tire_out = build_dir / f"tire_physics_{i}"
        tire_out.mkdir(parents=True, exist_ok=True)

        await _run(
            [DOTNET_TOOL, "--patch-tire", str(single_config), str(tire_template), str(tire_out)],
            f"patch-tire {tire_name}",
        )

        tire_asset = tire_out / tire_name / f"{tire_name}.uasset"
        tire_uexp = tire_out / tire_name / f"{tire_name}.uexp"
        if not tire_asset.exists():
            raise RuntimeError(f"Tire asset not created: {tire_asset}")
        tire_assets.append((tire_name, tire_asset, tire_uexp))

    # Step 2: Add tire parts to VehicleParts0
    current_template = parts0_template
    parts_out = None

    for i, entry in enumerate(tires, 1):
        tire_name = entry["tire_physics"]["name"]
        single_config = build_dir / f"tire_{i}.json"

        parts_out = build_dir / f"parts_vp0_{i}"
        parts_out.mkdir(parents=True, exist_ok=True)

        await _run(
            [
                DOTNET_TOOL,
                "--add-tire-parts",
                str(single_config),
                str(current_template),
                str(parts_out),
            ],
            f"add-tire-parts {tire_name}",
        )

        # Chain: use output as input for next tire
        current_template = parts_out / "VehicleParts0.uasset"

    assert parts_out is not None
    parts_asset = parts_out / "VehicleParts0.uasset"
    parts_uexp = parts_out / "VehicleParts0.uexp"
    if not parts_asset.exists():
        raise RuntimeError(f"VehicleParts0 not created: {parts_asset}")

    # Step 3: Assemble PAK directory structure
    pak_dir = build_dir / "pak_content"

    # Tire physics assets — FLAT path (no subfolder!)
    tire_pak_dir = pak_dir / "MotorTown" / "Content" / "Cars" / "Parts" / "Tire"
    tire_pak_dir.mkdir(parents=True, exist_ok=True)
    for tire_name, asset, uexp in tire_assets:
        shutil.copy2(str(asset), str(tire_pak_dir / f"{tire_name}.uasset"))
        shutil.copy2(str(uexp), str(tire_pak_dir / f"{tire_name}.uexp"))

    # VehicleParts0
    parts_pak_dir = (
        pak_dir / "MotorTown" / "Content" / "DataAsset" / "VehicleParts"
    )
    parts_pak_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(parts_asset), str(parts_pak_dir / "VehicleParts0.uasset"))
    shutil.copy2(str(parts_uexp), str(parts_pak_dir / "VehicleParts0.uexp"))

    # Step 4: Build PAK
    output_path = build_dir / f"{pack_name}_P.pak"
    await _run(
        [MOD_PACK, str(pak_dir), str(output_path)],
        "mod_pack",
    )

    if not output_path.exists():
        raise RuntimeError("PAK file was not created")

    return output_path
