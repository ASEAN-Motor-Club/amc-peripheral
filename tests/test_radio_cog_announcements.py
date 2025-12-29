import sys
from unittest.mock import MagicMock, AsyncMock, patch

# Mock google.cloud.texttospeech before importing RadioCog
mock_texttospeech = MagicMock()
mock_texttospeech.TextToSpeechClient = MagicMock()
sys.modules["google.cloud.texttospeech"] = mock_texttospeech
sys.modules["google.cloud"] = MagicMock()
sys.modules["google"] = MagicMock()

import pytest  # noqa: E402
from amc_peripheral.radio.radio_cog import RadioCog  # noqa: E402
from amc_peripheral.settings import REQUESTS_PATH  # noqa: E402

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
def cog(mock_bot):
    with patch("amc_peripheral.radio.radio_cog.LiquidsoapController"):
        with patch("amc_peripheral.radio.radio_cog.AsyncOpenAI"):
            cog = RadioCog(mock_bot)
            cog.lq = MagicMock()
            return cog

@pytest.mark.asyncio
async def test_request_song_pushes_to_queue(cog):
    """Test that request_song calls push_to_queue with the correct path."""
    requester = "TestUser"
    song_name = "Test Song"
    
    # Mock yt_dlp
    mock_info = {
        "title": "Test Song Title",
        "duration": 120,
        "webpage_url": "https://youtube.com/watch?v=123"
    }
    
    with patch("yt_dlp.YoutubeDL") as mock_ydl:
        instance = mock_ydl.return_value.__enter__.return_value
        instance.extract_info.return_value = mock_info
        
        # Mock successful download
        instance.download = MagicMock()
        
        # Call request_song
        title, duration = await cog.request_song(song_name, requester)
        
        assert title == "Test Song Title"
        
        # Verify push_to_queue was called
        # safe_requester = "TestUser", safe_title = "Test_Song_Title"
        expected_path = f"{REQUESTS_PATH}/TestUser-Test_Song_Title.mp3"
        cog.lq.push_to_queue.assert_called_once_with("song_requests", expected_path)

@pytest.mark.asyncio
async def test_request_song_handles_telnet_exception(cog):
    """Test that request_song survives a telnet exception."""
    requester = "TestUser"
    song_name = "Test Song"
    
    # Mock yt_dlp
    mock_info = {
        "title": "Test Song Title",
        "duration": 120,
        "webpage_url": "https://youtube.com/watch?v=123"
    }
    
    with patch("yt_dlp.YoutubeDL") as mock_ydl:
        instance = mock_ydl.return_value.__enter__.return_value
        instance.extract_info.return_value = mock_info
        instance.download = MagicMock()
        
        # Mock telnet failure
        cog.lq.push_to_queue.side_effect = Exception("Telnet Error")
        
        # Should NOT raise exception
        title, duration = await cog.request_song(song_name, requester)
        
        assert title == "Test Song Title"
        # Verify it was still attempted
        cog.lq.push_to_queue.assert_called_once()

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
