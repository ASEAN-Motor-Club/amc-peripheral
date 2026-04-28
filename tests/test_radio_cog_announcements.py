import sys
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch

# Mock google.cloud.texttospeech before importing RadioCog
mock_texttospeech = MagicMock()
mock_texttospeech.TextToSpeechClient = MagicMock()
sys.modules["google.cloud.texttospeech"] = mock_texttospeech
sys.modules["google.cloud"] = MagicMock()
sys.modules["google"] = MagicMock()

import pytest  # noqa: E402
from amc_peripheral.radio.radio_cog import RadioCog  # noqa: E402

@pytest.fixture
def mock_bot():
    bot = MagicMock()
    bot.http_session = AsyncMock()
    
    # Mock channel and its send method
    mock_channel = MagicMock()
    mock_channel.send = AsyncMock()
    bot.get_channel = MagicMock(return_value=mock_channel)
    
    bot.loop = MagicMock()
    return bot

@pytest.fixture
def cog(mock_bot, tmp_path, monkeypatch):
    db_path = str(tmp_path / "radio.db")
    monkeypatch.setattr("amc_peripheral.radio.radio_cog.RADIO_DB_PATH", db_path)
    with patch("amc_peripheral.radio.radio_cog.LiquidsoapController"):
        with patch("amc_peripheral.radio.radio_cog.AsyncOpenAI"):
            cog = RadioCog(mock_bot)
            cog.lq = AsyncMock()
            return cog

@pytest.mark.asyncio
async def test_request_song_pushes_to_queue(cog):
    """Test that request_song calls push_to_queue with resolved metadata."""
    cog._get_or_download = AsyncMock(
        return_value=("Test Song Title", 120, "/tmp/test.webm", "https://youtube.com/watch?v=123", "Test Artist")
    )
    cog._screen_song_content = AsyncMock(return_value=None)
    cog.lq.push_to_queue = AsyncMock()

    worker = asyncio.create_task(cog._download_worker())

    try:
        title, duration = await cog.request_song("Test Song", "TestUser", bypass_throttling=True)

        assert title == "Test Song Title"
        assert duration == 120
        cog.lq.push_to_queue.assert_called_once_with(
            cog.bot.http_session, "song_requests", "/tmp/test.webm",
            title="Test Song Title", requester="TestUser",
        )
    finally:
        worker.cancel()

@pytest.mark.asyncio
async def test_request_song_handles_push_exception(cog):
    """Test that request_song survives a push exception."""
    cog._get_or_download = AsyncMock(
        return_value=("Test Song Title", 120, "/tmp/test.webm", "https://youtube.com/watch?v=123", "Test Artist")
    )
    cog._screen_song_content = AsyncMock(return_value=None)
    cog.lq.push_to_queue = AsyncMock(side_effect=Exception("Telnet Error"))

    worker = asyncio.create_task(cog._download_worker())

    try:
        # Should NOT raise exception — push failure is caught internally
        title, duration = await cog.request_song("Test Song", "TestUser", bypass_throttling=True)

        assert title == "Test Song Title"
        cog.lq.push_to_queue.assert_called_once()
    finally:
        worker.cancel()

@pytest.mark.asyncio
async def test_game_request_song_announces_success(cog):
    """Test that game_request_song makes an in-game announcement."""
    requester = "TestUser"
    song_name = "Test Song"
    
    # Mock request_song success
    cog.request_song = AsyncMock(return_value=("Test Song Title", 120))
    
    # Mock announcement
    with patch("amc_peripheral.radio.radio_cog.announce_in_game", new_callable=AsyncMock) as mock_announce:
        await cog.game_request_song(song_name, requester)
        
        # Verify announcement was made
        mock_announce.assert_called_once()
        args, kwargs = mock_announce.call_args
        assert "Test Song Title" in args[1]
        assert requester in args[1]

@pytest.mark.asyncio
async def test_game_request_song_announces_even_if_push_failed(cog):
    """The check in test_request_song_handles_telnet_exception shows 
    request_song doesn't raise if telnet fails. This test ensures
    game_request_song calls announce_in_game normally when request_song returns normally.
    """
    requester = "TestUser"
    song_name = "Test Song"
    
    # request_song succeeds (even if telnet failed internally, it catches it)
    cog.request_song = AsyncMock(return_value=("Test Song Title", 120))
    
    with patch("amc_peripheral.radio.radio_cog.announce_in_game", new_callable=AsyncMock) as mock_announce:
        await cog.game_request_song(song_name, requester)
        
        mock_announce.assert_called_once()
