#!/usr/bin/env python3
"""Composite raw viewer wireframes onto the workshop placeholder background."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

WIDTH = 960
HEIGHT = 540
INK = (159, 180, 208)
LABEL = "PREVIEW PENDING"

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/nix/var/nix/profiles/default/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]


def load_font(size: int) -> ImageFont.ImageFont:
    for candidate in FONT_CANDIDATES:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


def background() -> Image.Image:
    image = Image.new("RGB", (WIDTH, HEIGHT), (7, 10, 16))
    draw = ImageDraw.Draw(image)
    for y in range(HEIGHT):
        t = y / max(1, HEIGHT - 1)
        r = int(13 - 6 * t)
        g = int(19 - 9 * t)
        b = int(30 - 14 * t)
        draw.line((0, y, WIDTH, y), fill=(r, g, b))

    # Faint technical grid, stronger at the horizon.
    for x in range(0, WIDTH + 1, 40):
        major = x % 200 == 0
        draw.line((x, 0, x, HEIGHT), fill=(38, 50, 68) if major else (25, 34, 48))
    for y in range(0, HEIGHT + 1, 40):
        major = y % 200 == 0
        draw.line((0, y, WIDTH, y), fill=(38, 50, 68) if major else (25, 34, 48))

    # Corner vignette keeps the centre readable without a visible vignette edge.
    overlay = Image.new("L", (WIDTH, HEIGHT), 0)
    od = ImageDraw.Draw(overlay)
    od.ellipse((-300, -220, WIDTH + 300, HEIGHT + 220), fill=70)
    overlay = overlay.filter(ImageFilter.GaussianBlur(120))
    glow = Image.new("RGB", (WIDTH, HEIGHT), (10, 16, 26))
    image = Image.composite(glow, image, overlay.point(lambda p: int(p * 0.55)))
    return image


def compose(raw_path: Path, out_path: Path) -> None:
    raw = Image.open(raw_path).convert("RGB")
    if raw.size != (WIDTH, HEIGHT):
        raw = raw.resize((WIDTH, HEIGHT), Image.Resampling.LANCZOS)
    image = ImageChops.screen(background(), raw)

    draw = ImageDraw.Draw(image)
    font = load_font(17)
    small = load_font(11)
    bbox = draw.textbbox((0, 0), LABEL, font=font)
    tw = bbox[2] - bbox[0]
    x = (WIDTH - tw) // 2
    y = HEIGHT - 34
    draw.text((x, y), LABEL, fill=(125, 143, 166), font=font)

    # A thin footer rule and a small technical mark, both generic.
    draw.line((x - 70, y - 10, x - 22, y - 10), fill=(47, 62, 82), width=1)
    draw.line((x + tw + 22, y - 10, x + tw + 70, y - 10), fill=(47, 62, 82), width=1)
    draw.text((24, 22), "AMC / VEHICLE WIREFRAME", fill=(62, 78, 98), font=small)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(out_path, "WEBP", quality=84, method=6)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--slugs", help="comma-separated slugs; default: all raw PNGs")
    args = parser.parse_args()

    if args.slugs:
        slugs = [s.strip() for s in args.slugs.split(",") if s.strip()]
    else:
        slugs = sorted(path.stem for path in args.raw.glob("*.png"))
    if not slugs:
        raise SystemExit(f"no raw PNGs in {args.raw}")

    mapping = {}
    if args.manifest:
        mapping = json.loads(args.manifest.read_text()).get("vehicles", {})

    missing: list[str] = []
    for slug in slugs:
        raw_path = args.raw / f"{slug}.png"
        if not raw_path.exists():
            missing.append(slug)
            continue
        out_path = args.out / f"{slug}.webp"
        compose(raw_path, out_path)
        print(f"{slug}.webp {out_path.stat().st_size} bytes")
    if missing:
        raise SystemExit(f"missing raw captures: {missing}")
    if mapping and len(mapping) != len(set(mapping.values())):
        raise SystemExit("manifest has duplicate viewer slugs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
