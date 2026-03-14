"""Tests for YouTubeCog - YouTube transcript auto-summarization and content analysis."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from amc_peripheral.bot.youtube_cog import (
    YouTubeCog,
    YOUTUBE_URL_PATTERN,
    _split_message,
    _score_bar,
    _format_analysis_header,
)
from amc_peripheral.bot.youtube_transcript import TranscriptResult, TranscriptSegment
from amc_peripheral.bot.ai_models import ContentTriageResult


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


class TestScoreBar:
    """Tests for score bar rendering."""

    def test_low_score_green(self):
        result = _score_bar(3)
        assert "🟩" in result
        assert result.count("🟩") == 3
        assert result.count("⬜") == 7

    def test_mid_score_yellow(self):
        result = _score_bar(5)
        assert "🟨" in result
        assert result.count("🟨") == 5

    def test_high_score_red(self):
        result = _score_bar(9)
        assert "🟥" in result
        assert result.count("🟥") == 9

    def test_zero_score(self):
        result = _score_bar(0)
        assert result == "⬜" * 10


class TestFormatAnalysisHeader:
    """Tests for analysis header formatting."""

    def test_formats_all_scores(self):
        triage = ContentTriageResult(
            controversialness=7,
            confidence=8,
            info_quality=3,
            needs_analysis=True,
            topics=["claim 1", "claim 2"],
        )
        header = _format_analysis_header(triage)
        assert "7/10" in header
        assert "8/10" in header
        assert "3/10" in header
        assert "Information Quality Report" in header


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

    @pytest.mark.asyncio
    async def test_on_message_ignores_wrong_channel(self, cog):
        """Messages in non-off-topic channels should be ignored."""
        message = MagicMock()
        message.author.bot = False
        message.channel.id = 999999999
        message.content = "https://www.youtube.com/watch?v=test123"
        await cog.on_message(message)

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
    async def test_handle_youtube_link_creates_thread_no_analysis(self, cog):
        """Should create thread without analysis when triage says not needed."""
        message = AsyncMock()
        message.channel.typing = MagicMock(return_value=AsyncMock())
        url = "https://www.youtube.com/watch?v=test123"

        success_result = TranscriptResult(
            url=url,
            title="Test Video",
            segments=[TranscriptSegment(timestamp="0:00", text="Hello world")],
            success=True,
        )

        benign_triage = ContentTriageResult(
            controversialness=2,
            confidence=1,
            info_quality=8,
            needs_analysis=False,
            topics=[],
        )

        mock_thread = AsyncMock()
        message.create_thread = AsyncMock(return_value=mock_thread)

        with patch(
            "amc_peripheral.bot.youtube_cog.get_youtube_transcript",
            return_value=success_result,
        ), patch.object(
            cog, "_summarize_transcript", new_callable=AsyncMock, return_value="Summary."
        ), patch.object(
            cog, "_triage_content", new_callable=AsyncMock, return_value=benign_triage
        ), patch.object(
            cog, "_critical_analysis", new_callable=AsyncMock
        ) as mock_analysis:
            await cog.handle_youtube_link(message, url)

            message.create_thread.assert_called_once()
            # Should NOT call critical analysis
            mock_analysis.assert_not_called()
            # Thread gets transcript file + summary only (2 sends)
            assert mock_thread.send.call_count == 2

    @pytest.mark.asyncio
    async def test_handle_youtube_link_creates_thread_with_analysis(self, cog):
        """Should create thread with analysis when triage triggers it."""
        message = AsyncMock()
        message.channel.typing = MagicMock(return_value=AsyncMock())
        url = "https://www.youtube.com/watch?v=test123"

        success_result = TranscriptResult(
            url=url,
            title="Controversial Video",
            segments=[TranscriptSegment(timestamp="0:00", text="The earth is flat")],
            success=True,
        )

        controversial_triage = ContentTriageResult(
            controversialness=9,
            confidence=10,
            info_quality=1,
            needs_analysis=True,
            topics=["flat earth claim"],
        )

        mock_thread = AsyncMock()
        message.create_thread = AsyncMock(return_value=mock_thread)

        with patch(
            "amc_peripheral.bot.youtube_cog.get_youtube_transcript",
            return_value=success_result,
        ), patch.object(
            cog, "_summarize_transcript", new_callable=AsyncMock, return_value="Summary."
        ), patch.object(
            cog, "_triage_content", new_callable=AsyncMock, return_value=controversial_triage
        ), patch.object(
            cog, "_critical_analysis", new_callable=AsyncMock, return_value="This is debunked."
        ):
            await cog.handle_youtube_link(message, url)

            message.create_thread.assert_called_once()
            # Thread gets: transcript file + summary + analysis (3+ sends)
            assert mock_thread.send.call_count >= 3

    @pytest.mark.asyncio
    async def test_summarize_transcript(self, cog):
        """Should call OpenAI and return summary text."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "This is a summary."

        cog.openai_client.chat.completions.create = AsyncMock(return_value=mock_response)

        result = await cog._summarize_transcript("Test Video", "Hello world transcript")
        assert result == "This is a summary."

    @pytest.mark.asyncio
    async def test_triage_content_returns_result(self, cog):
        """Should return a ContentTriageResult from structured output."""
        triage = ContentTriageResult(
            controversialness=7,
            confidence=8,
            info_quality=3,
            needs_analysis=True,
            topics=["dubious claim"],
        )

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.parsed = triage

        cog.openai_client.beta.chat.completions.parse = AsyncMock(return_value=mock_response)

        result = await cog._triage_content("Test", "transcript")
        assert result is not None
        assert result.controversialness == 7
        assert result.needs_analysis is True

    @pytest.mark.asyncio
    async def test_triage_content_returns_none_on_error(self, cog):
        """Should return None if triage LLM call fails."""
        cog.openai_client.beta.chat.completions.parse = AsyncMock(
            side_effect=Exception("API error")
        )

        result = await cog._triage_content("Test", "transcript")
        assert result is None

    @pytest.mark.asyncio
    async def test_critical_analysis(self, cog):
        """Should call OpenAI and return analysis text."""
        triage = ContentTriageResult(
            controversialness=8,
            confidence=9,
            info_quality=2,
            needs_analysis=True,
            topics=["claim A", "claim B"],
        )

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Critical analysis here."

        cog.openai_client.chat.completions.create = AsyncMock(return_value=mock_response)

        result = await cog._critical_analysis("Test", "transcript", triage)
        assert result == "Critical analysis here."
