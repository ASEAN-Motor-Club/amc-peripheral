#!/usr/bin/env python3
"""Local test harness for MiMo v2 TTS.

Usage:
    python scripts/test_mimo_tts.py                        # default voice, test phrase
    python scripts/test_mimo_tts.py --voice default_zh --text "你好世界"
    python scripts/test_mimo_tts.py --list-voices          # show known voices
    python scripts/test_mimo_tts.py --style Happy          # with a style tag
    python scripts/test_mimo_tts.py --all-voices           # test every known voice
    python scripts/test_mimo_tts.py --compare "Hello"      # side-by-side Google vs MiMo

Requires MIMO_API_KEY in env or .env file.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Ensure the package is importable from the repo root
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


# Load .env early so MIMO_API_KEY is available
def _load_dotenv(path: Path) -> None:
    """Minimal .env loader — no external deps needed."""
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip("\"'")
        if key and key not in os.environ:
            os.environ[key] = val


_load_dotenv(REPO_ROOT / ".env")

from amc_peripheral.radio.tts import MIMO_VOICES, MIMO_STYLES  # noqa: E402


# ---------------------------------------------------------------------------
def list_voices() -> None:
    """Print the known voice table."""
    print("\nKnown MiMo TTS voices:\n")
    for vid, desc in MIMO_VOICES.items():
        print(f"  {vid:<20s} {desc}")
    print(f"\n  Total: {len(MIMO_VOICES)}")
    print("\nKnown style tags:")
    for s in MIMO_STYLES:
        print(f"  - {s}")


# ---------------------------------------------------------------------------
def synthesize(
    text: str,
    voice: str = "default_en",
    style: str | None = None,
    audio_format: str = "mp3",
    out_path: str | None = None,
) -> Path:
    """Call tts_mimo and write the result to disk.  Returns the output path."""
    from amc_peripheral.radio.tts import tts_mimo

    kwargs: dict = dict(text=text, voice=voice, audio_format=audio_format)
    if style is not None:
        kwargs["style"] = style
    effective_style = style if style is not None else "British accent"

    t0 = time.perf_counter()
    audio = tts_mimo(**kwargs)
    elapsed = time.perf_counter() - t0

    if out_path is None:
        safe_voice = voice.replace("/", "_")
        suffix = f"_{effective_style}" if effective_style else ""
        suffix = suffix.replace(" ", "_")
        out_path = str(REPO_ROOT / f"tts_test_{safe_voice}{suffix}.{audio_format}")

    Path(out_path).write_bytes(audio)
    kb = len(audio) / 1024
    print(
        f"  [{elapsed:.2f}s  {kb:.1f} KB]  voice={voice}  style={effective_style or '-'}  -> {out_path}"
    )
    return Path(out_path)


# ---------------------------------------------------------------------------
def test_all_voices(text: str, style: str | None, audio_format: str) -> None:
    """Synthesize text with every known voice."""
    print(f'\nTesting all voices: "{text}"')
    if style:
        print(f"Style: {style}")
    print()
    for voice in MIMO_VOICES:
        try:
            synthesize(text, voice=voice, style=style, audio_format=audio_format)
        except Exception as exc:
            print(f"  [FAIL] {voice}: {exc}")


# ---------------------------------------------------------------------------
def compare_providers(text: str, voice: str, style: str | None) -> None:
    """Generate audio with both Google Cloud TTS and MiMo for comparison."""
    from amc_peripheral.radio.tts import tts as google_tts, tts_mimo

    out_dir = REPO_ROOT

    # Google
    t0 = time.perf_counter()
    google_audio = google_tts(text)
    g_elapsed = time.perf_counter() - t0
    g_path = out_dir / "tts_compare_google.mp3"
    g_path.write_bytes(google_audio)
    print(
        f"  [Google] {g_elapsed:.2f}s  {len(google_audio) / 1024:.1f} KB  -> {g_path}"
    )

    # MiMo
    t0 = time.perf_counter()
    mimo_audio = tts_mimo(text=text, voice=voice, style=style)
    m_elapsed = time.perf_counter() - t0
    m_path = out_dir / "tts_compare_mimo.mp3"
    m_path.write_bytes(mimo_audio)
    print(f"  [MiMo]   {m_elapsed:.2f}s  {len(mimo_audio) / 1024:.1f} KB  -> {m_path}")


# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Test MiMo v2 TTS locally",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--text",
        "-t",
        default="Hello! Welcome to Radio ASEAN, broadcasting live from Motor Town.",
        help="Text to synthesize",
    )
    parser.add_argument(
        "--voice",
        "-v",
        default="default_en",
        help="MiMo voice ID (default: default_en)",
    )
    parser.add_argument(
        "--style",
        "-s",
        default=None,
        choices=MIMO_STYLES,
        help="Optional style tag",
    )
    parser.add_argument(
        "--format",
        "-f",
        default="mp3",
        choices=["mp3", "wav", "pcm16"],
        help="Audio format (default: mp3)",
    )
    parser.add_argument(
        "--output",
        "-o",
        default=None,
        help="Output file path (auto-generated if omitted)",
    )
    parser.add_argument(
        "--list-voices",
        action="store_true",
        help="Show known voices and exit",
    )
    parser.add_argument(
        "--all-voices",
        action="store_true",
        help="Test every known voice with the given text",
    )
    parser.add_argument(
        "--compare",
        action="store_true",
        help="Compare Google Cloud TTS vs MiMo side-by-side",
    )

    args = parser.parse_args()

    if args.list_voices:
        list_voices()
        return

    # Check API key
    if not os.environ.get("MIMO_API_KEY"):
        print(
            "ERROR: MIMO_API_KEY not set. Add it to .env or export it.", file=sys.stderr
        )
        sys.exit(1)

    if args.all_voices:
        test_all_voices(args.text, args.style, args.format)
        return

    if args.compare:
        compare_providers(args.text, args.voice, args.style)
        return

    # Single synthesis
    print(f'Text: "{args.text}"\n')
    out = synthesize(
        text=args.text,
        voice=args.voice,
        style=args.style,
        audio_format=args.format,
        out_path=args.output,
    )
    print(f"\nDone. Play with:  afplay {out}")


if __name__ == "__main__":
    main()
