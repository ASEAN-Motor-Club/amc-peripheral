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

@pytest.fixture
def mock_bot():
    bot = MagicMock()
    bot.http_session = AsyncMock()
    bot.loop = MagicMock()
    return bot

@pytest.fixture
def cog(mock_bot, tmp_path, monkeypatch):
    db_path = str(tmp_path / "radio.db")
    monkeypatch.setattr("amc_peripheral.radio.radio_cog.RADIO_DB_PATH", db_path)
    with patch("amc_peripheral.radio.radio_cog.LiquidsoapController"):
        with patch("amc_peripheral.radio.radio_cog.AsyncOpenAI"):
            cog = RadioCog(mock_bot)
            return cog

@pytest.mark.asyncio
async def test_list_likes_empty(cog):
    # Mock Interaction
    interaction = AsyncMock()
    interaction.response.defer = AsyncMock()
    interaction.followup.send = AsyncMock()
    
    # Mock DB empty
    cog.db.get_all_song_stats = MagicMock(return_value=[])
    
    await cog.list_likes_cmd.callback(cog, interaction)
    
    interaction.response.defer.assert_called_once_with(ephemeral=True)
    interaction.followup.send.assert_called_once_with("No likes or unlikes recorded yet.", ephemeral=True)

@pytest.mark.asyncio
async def test_list_likes_with_data(cog):
    # Mock Interaction
    interaction = AsyncMock()
    interaction.response.defer = AsyncMock()
    interaction.followup.send = AsyncMock()
    
    # Mock DB data
    cog.db.get_all_song_stats = MagicMock(return_value=[
        {"song_title": "First Song", "like_count": 5, "dislike_count": 1},
        {"song_title": "Second Song", "like_count": 0, "dislike_count": 2},
    ])
    
    # Mock split_markdown
    with patch("amc_peripheral.radio.radio_cog.split_markdown", return_value=["Mock Chunk 1"]):
        await cog.list_likes_cmd.callback(cog, interaction)
    
    interaction.response.defer.assert_called_once_with(ephemeral=True)
    
    # Verify it called send with a chunk containing our song data
    interaction.followup.send.assert_called_with("Mock Chunk 1", ephemeral=True)

@pytest.mark.asyncio
async def test_list_likes_formatting(cog):
    # Mock Interaction
    interaction = AsyncMock()
    interaction.followup.send = AsyncMock()
    
    # Mock DB data
    cog.db.get_all_song_stats = MagicMock(return_value=[
        {"song_title": "Awesome Hit", "like_count": 10, "dislike_count": 0},
    ])
    
    await cog.list_likes_cmd.callback(cog, interaction)
    
    # Check what was sent
    args, kwargs = interaction.followup.send.call_args
    content = args[0]
    assert "Awesome Hit" in content
    assert "❤️ 10" in content
    assert "👎 0" in content
