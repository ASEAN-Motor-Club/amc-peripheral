import pytest
from unittest.mock import MagicMock, AsyncMock
from amc_peripheral.bot.knowledge_cog import KnowledgeCog

@pytest.fixture
def mock_bot():
    bot = MagicMock()
    bot.tree = MagicMock()
    bot.user.id = 12345
    bot.http_session = AsyncMock()
    return bot

@pytest.fixture
def cog(mock_bot):
    return KnowledgeCog(mock_bot)

@pytest.mark.asyncio
async def test_knowledge_cog_load(cog):
    """Verify knowledge cog_load adds its context menu."""
    await cog.cog_load()
    
    # Process Image with Prompt (KnowledgeCog has 1)
    assert cog.bot.tree.add_command.call_count == 1

@pytest.mark.asyncio
async def test_knowledge_cog_unload(cog):
    """Verify knowledge cog_unload removes its context menu."""
    cog.ctx_menus = [MagicMock()]
    await cog.cog_unload()
    
    # Should attempt to remove its context menu
    assert cog.bot.tree.remove_command.called
