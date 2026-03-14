"""Tests for YouTubeCog - YouTube transcript auto-summarization."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from amc_peripheral.bot.youtube_cog import YouTubeCog, YOUTUBE_URL_PATTERN, _split_message
from amc_peripheral.bot.youtube_transcript import TranscriptResult, TranscriptSegment


class TestYoutubeUrlPattern:
    """Tests for the YouTube URL regex pattern."""

    def test_matches_standard_url(self):
        assert YOUTUBE_URL_PATTERN.search("check this https://www.youtube.com/watch?v=abc123")

    def test_matches_short_url(self):
        assert YOUTUBE_URL_PATTERN.search("https://youtu.be/abc123")

    def test_matches_shorts(self):
        assert YOUTUBE_URL_PATTERN.search("https://youtube.com/shorts/abc123")

    def test_no_match_for_other_urls(self):
        assert YOUTUBE_URL_PATTERN.search("https://example.com/video") is None

    def test_matches_without_protocol(self):
        assert YOUTUBE_URL_PATTERN.search("youtube.com/watch?v=abc123")


class TestSplitMessage:
    """Tests for message splitting utility."""

    def test_short_message_not_split(self):
        assert _split_message("Hello world") == ["Hello world"]

    def test_long_message_split(self):
        long_text = "word " * 500  # ~2500 chars
        chunks = _split_message(long_text)
        assert len(chunks) > 1
        for chunk in chunks:
            assert len(chunk) <= 2000


class TestYouTubeCog:
    """Tests for the YouTubeCog Discord cog."""

    @pytest.fixture
    def mock_bot(self):
        bot = MagicMock()
        return bot

    @pytest.fixture
    def cog(self, mock_bot):
        with patch("amc_peripheral.bot.youtube_cog.OPENAI_API_KEY_OPENROUTER", "test-key"):
            return YouTubeCog(mock_bot)

    @pytest.mark.asyncio
    async def test_on_message_ignores_bot(self, cog):
        """Bot messages should be ignored."""
        message = MagicMock()
        message.author.bot = True
        await cog.on_message(message)
        # No exception means it returned early

    @pytest.mark.asyncio
    async def test_on_message_ignores_wrong_channel(self, cog):
        """Messages in non-off-topic channels should be ignored."""
        message = MagicMock()
        message.author.bot = False
        message.channel.id = 999999999
        message.content = "https://www.youtube.com/watch?v=test123"
        await cog.on_message(message)
        # No thread creation attempted

    @pytest.mark.asyncio
    async def test_on_message_detects_youtube_link(self, cog):
        """YouTube links in #off-topic should trigger handle_youtube_link."""
        message = MagicMock()
        message.author.bot = False
        message.content = "check this out https://www.youtube.com/watch?v=test123"

        with patch.object(
            cog, "handle_youtube_link", new_callable=AsyncMock
        ) as mock_handle, patch(
            "amc_peripheral.bot.youtube_cog.OFF_TOPIC_CHANNEL_ID", message.channel.id
        ):
            await cog.on_message(message)
            mock_handle.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_youtube_link_silent_fail_no_transcript(self, cog):
        """Should silently return if transcript extraction fails."""
        message = MagicMock()
        url = "https://www.youtube.com/watch?v=test123"

        failed_result = TranscriptResult(
            url=url, title="", segments=[], success=False, error="No transcript"
        )

        with patch(
            "amc_peripheral.bot.youtube_cog.get_youtube_transcript",
            return_value=failed_result,
        ):
            await cog.handle_youtube_link(message, url)
            message.create_thread.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_youtube_link_creates_thread(self, cog):
        """Should create thread with transcript file and summary on success."""
        message = AsyncMock()
        message.channel.typing = MagicMock(return_value=AsyncMock())
        url = "https://www.youtube.com/watch?v=test123"

        success_result = TranscriptResult(
            url=url,
            title="Test Video",
            segments=[TranscriptSegment(timestamp="0:00", text="Hello world")],
            success=True,
        )

        mock_thread = AsyncMock()
        message.create_thread = AsyncMock(return_value=mock_thread)

        with patch(
            "amc_peripheral.bot.youtube_cog.get_youtube_transcript",
            return_value=success_result,
        ), patch.object(
            cog, "_summarize_transcript", new_callable=AsyncMock, return_value="This is a summary."
        ):
            await cog.handle_youtube_link(message, url)

            message.create_thread.assert_called_once()
            # Thread should receive transcript file and summary
            assert mock_thread.send.call_count >= 2

    @pytest.mark.asyncio
    async def test_summarize_transcript(self, cog):
        """Should call OpenAI and return summary text."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "This is a summary."

        cog.openai_client.chat.completions.create = AsyncMock(return_value=mock_response)

        result = await cog._summarize_transcript("Test Video", "Hello world transcript")
        assert result == "This is a summary."
