import pytest
from unittest.mock import MagicMock, AsyncMock, patch
import tempfile
import os
from amc_peripheral.bot.translation_cog import TranslationCog


@pytest.fixture
def mock_bot():
    bot = MagicMock()
    bot.user = MagicMock()
    bot.user.id = 12345
    bot.http_session = AsyncMock()
    bot.loop = MagicMock()
    bot.loop.create_task = MagicMock()
    bot.tree = MagicMock()
    bot.tree.add_command = MagicMock()
    return bot


@pytest.fixture
def cog(mock_bot, tmp_path):
    # Use temp db path for tests
    db_path = str(tmp_path / "test_radio.db")
    with patch("amc_peripheral.bot.translation_cog.RADIO_DB_PATH", db_path):
        return TranslationCog(mock_bot)


def test_translation_cog_init(cog):
    """Verify TranslationCog initializes with correct state."""
    assert cog.messages == []
    assert cog.eco_game_messages == []
    assert cog.openai_client_openrouter is not None


@pytest.mark.asyncio
async def test_translate_method_exists(cog):
    """Verify translate method exists and has correct signature."""
    assert hasattr(cog, 'translate')
    assert callable(cog.translate)


@pytest.mark.asyncio
async def test_translate_multi_method_exists(cog):
    """Verify translate_multi method exists and has correct signature."""
    assert hasattr(cog, 'translate_multi')
    assert callable(cog.translate_multi)


@pytest.mark.asyncio
async def test_translate_multi_with_english_method_exists(cog):
    """Verify translate_multi_with_english method exists and has correct signature."""
    assert hasattr(cog, 'translate_multi_with_english')
    assert callable(cog.translate_multi_with_english)


@pytest.mark.asyncio
async def test_translate_to_language_method_exists(cog):
    """Verify translate_to_language method exists and has correct signature."""
    assert hasattr(cog, 'translate_to_language')
    assert callable(cog.translate_to_language)
