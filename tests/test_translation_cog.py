import pytest
from unittest.mock import MagicMock, AsyncMock, patch
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


# --- _safe_parse tests ---

def test_safe_parse_returns_parsed_when_available(cog):
    """When parsed is not None, _safe_parse should return it directly."""
    from amc_peripheral.bot.ai_models import TranslationResponse
    expected = TranslationResponse(translation="hello")
    
    completion = MagicMock()
    completion.choices = [MagicMock()]
    completion.choices[0].message.parsed = expected
    
    result = cog._safe_parse(TranslationResponse, completion)
    assert result is expected


def test_safe_parse_fallback_from_content(cog):
    """When parsed is None but content has valid JSON, should parse manually."""
    from amc_peripheral.bot.ai_models import TranslationResponse
    
    completion = MagicMock()
    completion.choices = [MagicMock()]
    completion.choices[0].message.parsed = None
    completion.choices[0].message.content = '{"translation": "hello world"}'
    
    result = cog._safe_parse(TranslationResponse, completion)
    assert result is not None
    assert result.translation == "hello world"


def test_safe_parse_strips_think_tags(cog):
    """When content has <think> tags, should strip them and parse the JSON."""
    from amc_peripheral.bot.ai_models import TranslationResponse
    
    completion = MagicMock()
    completion.choices = [MagicMock()]
    completion.choices[0].message.parsed = None
    completion.choices[0].message.content = '<think>I need to translate this...</think>{"translation": "bonjour"}'
    
    result = cog._safe_parse(TranslationResponse, completion)
    assert result is not None
    assert result.translation == "bonjour"


def test_safe_parse_empty_content_returns_none(cog):
    """When parsed is None and content is empty, should return None."""
    from amc_peripheral.bot.ai_models import TranslationResponse
    
    completion = MagicMock()
    completion.choices = [MagicMock()]
    completion.choices[0].message.parsed = None
    completion.choices[0].message.content = ""
    
    result = cog._safe_parse(TranslationResponse, completion)
    assert result is None


def test_safe_parse_invalid_json_returns_none(cog):
    """When content is not valid JSON, should return None."""
    from amc_peripheral.bot.ai_models import TranslationResponse
    
    completion = MagicMock()
    completion.choices = [MagicMock()]
    completion.choices[0].message.parsed = None
    completion.choices[0].message.content = "this is not json at all"
    
    result = cog._safe_parse(TranslationResponse, completion)
    assert result is None
