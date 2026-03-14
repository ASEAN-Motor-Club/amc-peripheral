"""
YouTube transcript extraction utility using youtube-transcript-api.
Provides simple functions to fetch video transcripts from YouTube.
"""

from dataclasses import dataclass, asdict
from youtube_transcript_api import YouTubeTranscriptApi
import re


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


def get_youtube_transcript(
    url: str,
    languages: list[str] | None = None,
) -> TranscriptResult:
    """
    Extract the transcript from a YouTube video URL.

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

    try:
        # Fetch transcript using the API
        api = YouTubeTranscriptApi()
        transcript_data = api.fetch(video_id, languages=languages)

        # Convert to our format
        segments = [
            TranscriptSegment(timestamp=_format_timestamp(entry.start), text=entry.text)
            for entry in transcript_data
        ]

        return TranscriptResult(
            url=url, title=f"Video {video_id}", segments=segments, success=True
        )

    except Exception as e:
        error_msg = str(e)
        if "disabled" in error_msg.lower():
            error_msg = "Transcripts are disabled for this video"
        elif "unavailable" in error_msg.lower():
            error_msg = "Video is unavailable"
        elif "No transcript" in error_msg or "not found" in error_msg.lower():
            error_msg = "No transcript found for this video"

        return TranscriptResult(
            url=url, title="", segments=[], success=False, error=error_msg
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
