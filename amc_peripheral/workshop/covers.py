"""Deterministic, render-backed social collages for workshop authors."""

from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

COVER_WIDTH = 1200
COVER_HEIGHT = 630
COVER_VERSION = 1


def cover_weight(item: dict[str, Any]) -> float:
    popularity = 1.0 + max(0, int(item.get("votes") or 0)) * 4.0
    popularity += max(0, int(item.get("installs") or 0)) * 2.0
    return popularity * (3.0 if item.get("hasDecal") else 1.0)


def sample_cover_items(
    items: list[dict[str, Any]], account_id: int, count: int = 6
) -> list[dict[str, Any]]:
    """Stable weighted sampling without replacement (Efraimidis-Spirakis)."""
    rng = random.Random(f"author-cover-v{COVER_VERSION}:{account_id}")
    ranked = sorted(
        items,
        key=lambda item: rng.random() ** (1.0 / cover_weight(item)),
        reverse=True,
    )[:count]
    return sorted(
        ranked,
        key=lambda item: (
            bool(item.get("hasDecal")),
            int(item.get("votes") or 0) + int(item.get("installs") or 0),
            int(item["id"]),
        ),
        reverse=True,
    )


def _grid(count: int) -> tuple[int, int]:
    if count <= 2:
        return count, 1
    if count <= 4:
        return 2, 2
    return 3, 2


def write_author_cover(
    account_id: int,
    candidates: list[dict[str, Any]],
    public_root: Path,
) -> str | None:
    """Create a 1200x630 collage from candidates with ready snapshot metadata."""
    available = []
    prefix = "/workshop/snapshots/"
    for item in candidates:
        snapshot_url = item["snapshot"].get("url") or ""
        if snapshot_url.startswith(prefix) and (public_root / snapshot_url.removeprefix(prefix)).is_file():
            available.append(item)
    if not available:
        return None
    selected = sample_cover_items(available, account_id)
    signature = hashlib.sha256(json.dumps([
        COVER_VERSION,
        [(item["id"], item["snapshot"]["key"], item["snapshot"].get("sha256"))
         for item in selected],
    ], separators=(",", ":")).encode()).hexdigest()[:20]
    relative = Path("authors") / f"{account_id}-{signature}.webp"
    output = public_root / relative
    url = f"/workshop/snapshots/{relative.as_posix()}"
    if output.exists():
        return url

    output.parent.mkdir(parents=True, exist_ok=True)
    columns, rows = _grid(len(selected))
    cell_width = COVER_WIDTH // columns
    cell_height = COVER_HEIGHT // rows
    collage = Image.new("RGB", (COVER_WIDTH, COVER_HEIGHT), "#0b1017")
    opened: list[Image.Image] = []
    try:
        for index, item in enumerate(selected):
            snapshot_url = item["snapshot"]["url"]
            prefix = "/workshop/snapshots/"
            if not snapshot_url.startswith(prefix):
                continue
            source = public_root / snapshot_url.removeprefix(prefix)
            image = Image.open(source)
            opened.append(image)
            tile = ImageOps.fit(
                image.convert("RGB"), (cell_width - 4, cell_height - 4),
                method=Image.Resampling.LANCZOS,
            )
            x = (index % columns) * cell_width + 2
            y = (index // columns) * cell_height + 2
            collage.paste(tile, (x, y))
        temporary = output.with_suffix(".tmp")
        collage.save(temporary, format="WEBP", quality=88, method=6)
        temporary.replace(output)
    finally:
        for image in opened:
            image.close()
    return url
