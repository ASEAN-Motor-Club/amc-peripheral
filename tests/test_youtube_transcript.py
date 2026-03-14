"""Tests for YouTube transcript extraction module."""

from unittest.mock import MagicMock, patch

from amc_peripheral.bot.youtube_transcript import (
    TranscriptResult,
    TranscriptSegment,
    _extract_video_id,
    _format_timestamp,
    get_transcript_text,
    get_youtube_transcript,
)


class TestTranscriptSegment:
    """Tests for TranscriptSegment dataclass."""

    def test_to_dict(self):
        segment = TranscriptSegment(timestamp="0:00", text="Hello world")
        result = segment.to_dict()
        assert result == {"timestamp": "0:00", "text": "Hello world"}


class TestTranscriptResult:
    """Tests for TranscriptResult dataclass."""

    def test_to_list(self):
        result = TranscriptResult(
            url="https://youtube.com/watch?v=test",
            title="Test Video",
            segments=[
                TranscriptSegment(timestamp="0:00", text="First"),
                TranscriptSegment(timestamp="0:05", text="Second"),
            ],
            success=True,
        )
        expected = [
            {"timestamp": "0:00", "text": "First"},
            {"timestamp": "0:05", "text": "Second"},
        ]
        assert result.to_list() == expected

    def test_get_full_text(self):
        result = TranscriptResult(
            url="https://youtube.com/watch?v=test",
            title="Test Video",
            segments=[
                TranscriptSegment(timestamp="0:00", text="Hello"),
                TranscriptSegment(timestamp="0:05", text="world"),
            ],
            success=True,
        )
        assert result.get_full_text() == "Hello world"

    def test_get_formatted_transcript(self):
        result = TranscriptResult(
            url="https://youtube.com/watch?v=test",
            title="Test Video",
            segments=[
                TranscriptSegment(timestamp="0:00", text="Hello"),
                TranscriptSegment(timestamp="1:30", text="world"),
            ],
            success=True,
        )
        assert result.get_formatted_transcript() == "[0:00] Hello\n[1:30] world"

    def test_empty_segments(self):
        result = TranscriptResult(
            url="https://youtube.com/watch?v=test",
            title="Test Video",
            segments=[],
            success=False,
            error="No transcript available",
        )
        assert result.to_list() == []
        assert result.get_full_text() == ""


class TestVideoIdExtraction:
    """Tests for video ID extraction from URLs."""

    def test_standard_url(self):
        assert _extract_video_id("https://www.youtube.com/watch?v=abc123") == "abc123"

    def test_short_url(self):
        assert _extract_video_id("https://youtu.be/abc123") == "abc123"

    def test_embed_url(self):
        assert _extract_video_id("https://www.youtube.com/embed/abc123") == "abc123"

    def test_shorts_url(self):
        assert _extract_video_id("https://www.youtube.com/shorts/abc123") == "abc123"

    def test_url_with_extra_params(self):
        assert (
            _extract_video_id("https://www.youtube.com/watch?v=abc123&t=120")
            == "abc123"
        )

    def test_invalid_url(self):
        assert _extract_video_id("https://example.com/video") is None


class TestTimestampFormatting:
    """Tests for timestamp formatting."""

    def test_seconds_only(self):
        assert _format_timestamp(45) == "0:45"

    def test_minutes_and_seconds(self):
        assert _format_timestamp(125) == "2:05"

    def test_hours_minutes_seconds(self):
        assert _format_timestamp(3665) == "1:01:05"

    def test_zero(self):
        assert _format_timestamp(0) == "0:00"


class TestGetYoutubeTranscript:
    """Tests for get_youtube_transcript function."""

    def test_invalid_url(self):
        result = get_youtube_transcript("https://example.com/not-youtube")
        assert result.success is False
        assert "Could not extract video ID" in result.error

    def test_returns_transcript_result(self):
        with patch(
            "amc_peripheral.bot.youtube_transcript.YouTubeTranscriptApi"
        ) as mock_api:
            mock_instance = MagicMock()
            mock_api.return_value = mock_instance

            mock_snippet = MagicMock()
            mock_snippet.text = "Hello"
            mock_snippet.start = 0.0
            mock_instance.fetch.return_value = [mock_snippet]

            result = get_youtube_transcript(
                "https://www.youtube.com/watch?v=test123"
            )

            assert isinstance(result, TranscriptResult)
            assert result.success is True
            assert len(result.segments) == 1
            assert result.segments[0].text == "Hello"

    def test_handles_api_exception(self):
        with patch(
            "amc_peripheral.bot.youtube_transcript.YouTubeTranscriptApi"
        ) as mock_api:
            mock_instance = MagicMock()
            mock_api.return_value = mock_instance
            mock_instance.fetch.side_effect = Exception("Transcripts are disabled")

            result = get_youtube_transcript(
                "https://www.youtube.com/watch?v=test123"
            )

            assert result.success is False
            assert "disabled" in result.error.lower()


class TestGetTranscriptText:
    """Tests for get_transcript_text convenience function."""

    def test_returns_text_on_success(self):
        with patch(
            "amc_peripheral.bot.youtube_transcript.get_youtube_transcript"
        ) as mock_get:
            mock_get.return_value = TranscriptResult(
                url="https://youtube.com/watch?v=test",
                title="Test",
                segments=[
                    TranscriptSegment(timestamp="0:00", text="Hello"),
                    TranscriptSegment(timestamp="0:05", text="world"),
                ],
                success=True,
            )
            result = get_transcript_text("https://youtube.com/watch?v=test")
            assert result == "Hello world"

    def test_returns_error_on_failure(self):
        with patch(
            "amc_peripheral.bot.youtube_transcript.get_youtube_transcript"
        ) as mock_get:
            mock_get.return_value = TranscriptResult(
                url="https://youtube.com/watch?v=test",
                title="",
                segments=[],
                success=False,
                error="Transcript disabled",
            )
            result = get_transcript_text("https://youtube.com/watch?v=test")
            assert result == "Error: Transcript disabled"
