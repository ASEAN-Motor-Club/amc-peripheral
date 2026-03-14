"""
YouTube transcript extraction utility using youtube-transcript-api.
Provides simple functions to fetch video transcripts from YouTube.

Uses a dual-strategy approach:
1. youtube-transcript-api with cookies (fast, no download)
2. yt-dlp subtitle extraction as fallback (handles cloud IP blocks)
"""

from dataclasses import dataclass, asdict
from http.cookiejar import MozillaCookieJar
from youtube_transcript_api import YouTubeTranscriptApi
import logging
import os
import re

from requests import Session

from ..settings import YT_COOKIES_PATH, DENO_PATH

log = logging.getLogger(__name__)


def _build_http_client() -> Session | None:
    """Build a requests Session with YouTube cookies if available."""
    if not YT_COOKIES_PATH or not os.path.exists(YT_COOKIES_PATH):
        return None

    try:
        session = Session()
        cookie_jar = MozillaCookieJar(YT_COOKIES_PATH)
        cookie_jar.load(ignore_discard=True, ignore_expires=True)
        session.cookies = cookie_jar
        log.info("Loaded YouTube cookies from %s", YT_COOKIES_PATH)
        return session
    except Exception as e:
        log.warning("Failed to load YouTube cookies: %s", e)
        return None


@dataclass
class TranscriptSegment:
    """A single segment of transcript with timestamp."""

    timestamp: str
    text: str

    def to_dict(self) -> dict[str, str]:
        """Convert to dictionary format."""
        return asdict(self)


@dataclass
class TranscriptResult:
    """Result of a transcript extraction operation."""

    url: str
    title: str
    segments: list[TranscriptSegment]
    success: bool
    error: str | None = None

    def to_list(self) -> list[dict[str, str]]:
        """Return segments as list of dictionaries."""
        return [seg.to_dict() for seg in self.segments]

    def get_full_text(self) -> str:
        """Return concatenated transcript text without timestamps."""
        return " ".join(seg.text for seg in self.segments)

    def get_formatted_transcript(self) -> str:
        """Return formatted transcript with timestamps for a text file."""
        return "\n".join(f"[{seg.timestamp}] {seg.text}" for seg in self.segments)


def _extract_video_id(url: str) -> str | None:
    """Extract video ID from various YouTube URL formats."""
    patterns = [
        r"(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/)([^&\n?#]+)",
        r"youtube\.com/shorts/([^&\n?#]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def _format_timestamp(seconds: float) -> str:
    """Convert seconds to MM:SS or HH:MM:SS format."""
    total_seconds = int(seconds)
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    secs = total_seconds % 60

    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def _fetch_via_transcript_api(
    video_id: str,
    languages: list[str],
) -> list[TranscriptSegment] | None:
    """Try fetching transcript via youtube-transcript-api. Returns None on failure."""
    try:
        http_client = _build_http_client()
        ytt_api = (
            YouTubeTranscriptApi(http_client=http_client)
            if http_client
            else YouTubeTranscriptApi()
        )
        fetched = ytt_api.fetch(video_id, languages=languages)

        return [
            TranscriptSegment(
                timestamp=_format_timestamp(snippet.start), text=snippet.text
            )
            for snippet in fetched
        ]
    except Exception as e:
        log.warning("youtube-transcript-api failed: %s", e)
        return None


def _fetch_via_ytdlp(url: str, languages: list[str]) -> list[TranscriptSegment] | None:
    """Fallback: extract subtitles via yt-dlp with cookie support."""
    try:
        import yt_dlp
    except ImportError:
        log.warning("yt-dlp not available for subtitle fallback")
        return None

    from tempfile import TemporaryDirectory

    try:
        with TemporaryDirectory() as temp_dir:
            outtmpl = os.path.join(temp_dir, "subs")
            ydl_opts = {
                "skip_download": True,
                "writesubtitles": True,
                "writeautomaticsub": True,
                "subtitleslangs": languages,
                "subtitlesformat": "vtt",
                "outtmpl": outtmpl,
                "quiet": True,
                "no_warnings": True,
            }

            if DENO_PATH:
                ydl_opts["js_runtimes"] = {"deno": {"path": DENO_PATH}}
                ydl_opts["remote_components"] = ["ejs:github"]

            if YT_COOKIES_PATH and os.path.exists(YT_COOKIES_PATH):
                ydl_opts["cookiefile"] = YT_COOKIES_PATH
                log.info("yt-dlp using cookies from %s", YT_COOKIES_PATH)

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])

            # Find the subtitle file (yt-dlp appends language code)
            vtt_file = None
            for f in os.listdir(temp_dir):
                if f.endswith(".vtt"):
                    vtt_file = os.path.join(temp_dir, f)
                    break

            if not vtt_file:
                log.warning("yt-dlp: no subtitle file produced")
                return None

            return _parse_vtt(vtt_file)

    except Exception as e:
        log.warning("yt-dlp subtitle extraction failed: %s", e)
        return None


def _parse_vtt(filepath: str) -> list[TranscriptSegment]:
    """Parse a WebVTT subtitle file into TranscriptSegment objects."""
    segments = []
    seen_texts: set[str] = set()

    with open(filepath, "r", encoding="utf-8") as f:
        lines = f.readlines()

    i = 0
    while i < len(lines):
        line = lines[i].strip()
        # Match timestamp lines like "00:00:01.000 --> 00:00:04.000"
        if "-->" in line:
            parts = line.split("-->")
            start_str = parts[0].strip()
            # Parse start time
            time_parts = start_str.replace(",", ".").split(":")
            if len(time_parts) == 3:
                seconds = (
                    int(time_parts[0]) * 3600
                    + int(time_parts[1]) * 60
                    + float(time_parts[2])
                )
            elif len(time_parts) == 2:
                seconds = int(time_parts[0]) * 60 + float(time_parts[1])
            else:
                i += 1
                continue

            # Collect text lines until blank line
            i += 1
            text_lines = []
            while i < len(lines) and lines[i].strip():
                # Strip VTT tags like <c> </c> and positioning
                text = re.sub(r"<[^>]+>", "", lines[i].strip())
                if text:
                    text_lines.append(text)
                i += 1

            text = " ".join(text_lines).strip()
            # Deduplicate (auto-generated subs often repeat)
            if text and text not in seen_texts:
                seen_texts.add(text)
                segments.append(
                    TranscriptSegment(timestamp=_format_timestamp(seconds), text=text)
                )
        else:
            i += 1

    return segments


def get_youtube_transcript(
    url: str,
    languages: list[str] | None = None,
) -> TranscriptResult:
    """
    Extract the transcript from a YouTube video URL.
    Tries youtube-transcript-api first, falls back to yt-dlp subtitles.

    Args:
        url: The YouTube video URL
        languages: Preferred languages for transcript (default: ['en'])

    Returns:
        TranscriptResult with extracted transcript segments
    """
    if languages is None:
        languages = ["en"]

    video_id = _extract_video_id(url)
    if not video_id:
        return TranscriptResult(
            url=url,
            title="",
            segments=[],
            success=False,
            error=f"Could not extract video ID from URL: {url}",
        )

    # Strategy 1: youtube-transcript-api (fast, no download)
    segments = _fetch_via_transcript_api(video_id, languages)

    # Strategy 2: yt-dlp subtitle extraction (handles cloud IP blocks)
    if segments is None:
        log.info("Falling back to yt-dlp for subtitle extraction")
        segments = _fetch_via_ytdlp(url, languages)

    if segments:
        return TranscriptResult(
            url=url,
            title=f"Video {video_id}",
            segments=segments,
            success=True,
        )

    return TranscriptResult(
        url=url,
        title="",
        segments=[],
        success=False,
        error="Could not extract transcript (both youtube-transcript-api and yt-dlp failed)",
    )


def get_transcript_text(url: str, languages: list[str] | None = None) -> str:
    """
    Get just the transcript text (without timestamps) from a YouTube video.

    Args:
        url: The YouTube video URL
        languages: Preferred languages for transcript

    Returns:
        The full transcript text, or an error message if extraction failed
    """
    result = get_youtube_transcript(url, languages=languages)

    if result.success:
        return result.get_full_text()
    else:
        return f"Error: {result.error}"
