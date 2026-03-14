"""Tests for YouTube transcript extraction module."""

from unittest.mock import patch

from amc_peripheral.bot.youtube_transcript import (
    TranscriptResult,
    TranscriptSegment,
    _extract_video_id,
    _format_timestamp,
    _parse_vtt,
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


class TestParseVtt:
    """Tests for VTT subtitle parsing."""

    def test_parses_basic_vtt(self, tmp_path):
        vtt_content = (
            "WEBVTT\n\n"
            "00:00:01.000 --> 00:00:04.000\n"
            "Hello world\n\n"
            "00:00:05.000 --> 00:00:08.000\n"
            "Second line\n\n"
        )
        vtt_file = tmp_path / "test.vtt"
        vtt_file.write_text(vtt_content)

        segments = _parse_vtt(str(vtt_file))
        assert len(segments) == 2
        assert segments[0].text == "Hello world"
        assert segments[0].timestamp == "0:01"
        assert segments[1].text == "Second line"

    def test_deduplicates_repeated_text(self, tmp_path):
        vtt_content = (
            "WEBVTT\n\n"
            "00:00:01.000 --> 00:00:04.000\n"
            "Hello world\n\n"
            "00:00:04.000 --> 00:00:07.000\n"
            "Hello world\n\n"
            "00:00:07.000 --> 00:00:10.000\n"
            "New text\n\n"
        )
        vtt_file = tmp_path / "test.vtt"
        vtt_file.write_text(vtt_content)

        segments = _parse_vtt(str(vtt_file))
        assert len(segments) == 2  # Deduplicated


class TestGetYoutubeTranscript:
    """Tests for get_youtube_transcript function (dual-strategy)."""

    def test_invalid_url(self):
        result = get_youtube_transcript("https://example.com/not-youtube")
        assert result.success is False
        assert "Could not extract video ID" in result.error

    def test_returns_transcript_via_api(self):
        with patch(
            "amc_peripheral.bot.youtube_transcript._fetch_via_transcript_api"
        ) as mock_api:
            mock_api.return_value = [
                TranscriptSegment(timestamp="0:00", text="Hello")
            ]

            result = get_youtube_transcript(
                "https://www.youtube.com/watch?v=test123"
            )

            assert result.success is True
            assert len(result.segments) == 1
            assert result.segments[0].text == "Hello"

    def test_falls_back_to_ytdlp(self):
        with patch(
            "amc_peripheral.bot.youtube_transcript._fetch_via_transcript_api",
            return_value=None,
        ), patch(
            "amc_peripheral.bot.youtube_transcript._fetch_via_ytdlp"
        ) as mock_ytdlp:
            mock_ytdlp.return_value = [
                TranscriptSegment(timestamp="0:00", text="Fallback")
            ]

            result = get_youtube_transcript(
                "https://www.youtube.com/watch?v=test123"
            )

            assert result.success is True
            assert result.segments[0].text == "Fallback"
            mock_ytdlp.assert_called_once()

    def test_both_strategies_fail(self):
        with patch(
            "amc_peripheral.bot.youtube_transcript._fetch_via_transcript_api",
            return_value=None,
        ), patch(
            "amc_peripheral.bot.youtube_transcript._fetch_via_ytdlp",
            return_value=None,
        ):
            result = get_youtube_transcript(
                "https://www.youtube.com/watch?v=test123"
            )

            assert result.success is False
            assert "both" in result.error.lower()


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
