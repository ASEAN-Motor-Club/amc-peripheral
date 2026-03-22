"""Client for the radio server HTTP API (localhost:6001)."""

import logging
from typing import Optional
import aiohttp

log = logging.getLogger(__name__)

RADIO_SERVER_BASE_URL = "http://localhost:6001"


async def get_current_song_metadata(
    http_session: aiohttp.ClientSession,
) -> Optional[dict]:
    """
    Fetch the current song metadata from the radio server.

    Returns:
        dict with metadata (e.g., {"filename": "...", ...}) or None on error.
    """
    try:
        async with http_session.get(f"{RADIO_SERVER_BASE_URL}/metadata") as resp:
            return await resp.json()
    except Exception as e:
        log.error(f"Could not fetch radio metadata: {e}")
        return None


def parse_song_info(metadata: dict) -> Optional[dict]:
    """
    Parse the raw metadata dictionary into a structured song info dict.

    Returns:
        dict with {folder, requester, song_title} or None if parsing fails.
    """
    filename = metadata.get("filename")
    if not filename:
        return None

    filename = filename.removeprefix("/var/lib/radio/")
    try:
        folder, filepath = filename.split("/")

        # Cache files use video IDs as filenames — don't try requester-title parsing
        if folder == "cache":
            title = metadata.get("title")
            if title:
                return {
                    "folder": folder,
                    "requester": metadata.get("requester", "Radio"),
                    "song_title": title,
                }
            return None

        requester, song_path = filepath.split("-", 1)
        song_title = song_path.removesuffix(".mp3").removesuffix(".opus").removesuffix(".webm")
        return {
            "folder": folder,
            "requester": requester,
            "song_title": song_title,
        }
    except ValueError:
        # Fallback for cache/playlist files without requester-title format
        # (e.g. cache/VdQY7BusJNU.mp3 or playlist/SomeFile.mp3)
        title = metadata.get("title")
        if title:
            try:
                folder = filename.split("/")[0]
            except (ValueError, IndexError):
                folder = "unknown"
            return {
                "folder": folder,
                "requester": "Radio",
                "song_title": title,
            }
        return None


ICECAST_STATUS_URL = "http://localhost:8000/status-json.xsl"


async def get_listener_count(http_session: aiohttp.ClientSession) -> int:
    """Fetch the current listener count from Icecast."""
    try:
        async with http_session.get(ICECAST_STATUS_URL) as resp:
            data = await resp.json(content_type=None)
            source = data.get("icestats", {}).get("source")
            if source is None:
                return 0
            if isinstance(source, list):
                return sum(s.get("listeners", 0) for s in source)
            return source.get("listeners", 0)
    except Exception as e:
        log.error(f"Could not fetch Icecast listener count: {e}")
        return 0


async def get_current_song(http_session: aiohttp.ClientSession) -> Optional[str]:
    """
    Get a human-readable string of the currently playing song.

    Returns:
        A string like "Song Title (requested by Requester)" or None if unavailable.
    """
    metadata = await get_current_song_metadata(http_session)
    if not metadata:
        return None

    song_info = parse_song_info(metadata)
    if not song_info:
        return None

    return f"{song_info['song_title']} (requested by {song_info['requester']})"
