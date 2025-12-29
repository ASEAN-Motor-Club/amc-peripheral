import pytest
import discord
from discord.ext import commands
from unittest.mock import AsyncMock, MagicMock
from amc_peripheral.utils.text_utils import split_markdown, is_code_block_open
from amc_peripheral.bot.knowledge_cog import KnowledgeCog


class MockBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.all()
        super().__init__(command_prefix="/", intents=intents)
        self.http_session = AsyncMock()


@pytest.mark.asyncio
async def test_split_markdown():
    # text with newlines to allow splitting
    text = ("A" * 500 + "\n\n") * 5  # 2500+ chars
    chunks = split_markdown(text)
    assert len(chunks) >= 2
    assert all(len(c) <= 2000 for c in chunks)


@pytest.mark.asyncio
async def test_is_code_block_open():
    assert is_code_block_open("```python\nprint(1)")
    assert not is_code_block_open("```python\nprint(1)\n```")


@pytest.mark.asyncio
async def test_on_ready_loads_knowledge_base():
    """Test that on_ready fetches knowledge base from the forum channel."""
    bot = MockBot()
    cog = KnowledgeCog(bot)

    # Setup mock forum channel
    mock_forum_channel = MagicMock(spec=discord.ForumChannel)
    mock_forum_channel.id = 1348530437768745020

    # Mock a thread with messages
    mock_thread = MagicMock()
    mock_thread.name = "Test Thread"

    mock_message = MagicMock()
    mock_message.content = "This is test knowledge content."
    mock_message.attachments = []

    # Setup async iterators for archived_threads and history
    async def mock_archived_threads(limit=None):
        yield mock_thread

    async def mock_history(oldest_first=True, **kwargs):
        yield mock_message

    mock_forum_channel.archived_threads = mock_archived_threads
    mock_thread.history = mock_history

    # Mock bot.get_channel: return forum channel for forum ID, None for log channel
    def mock_get_channel(channel_id):
        if channel_id == 1348530437768745020:  # KNOWLEDGE_FORUM_CHANNEL_ID
            return mock_forum_channel
        return None  # Log channel returns None to skip logging

    bot.get_channel = MagicMock(side_effect=mock_get_channel)

    # Call on_ready
    await cog.on_ready()

    # Verify knowledge_system_message is populated
    assert cog.knowledge_system_message != ""
    assert "Test Thread" in cog.knowledge_system_message
    assert "This is test knowledge content." in cog.knowledge_system_message


@pytest.mark.asyncio
async def test_on_ready_handles_missing_channel():
    """Test that on_ready handles a missing forum channel gracefully."""
    bot = MockBot()
    cog = KnowledgeCog(bot)

    # Mock bot.get_channel to return None (channel not found)
    bot.get_channel = MagicMock(return_value=None)

    # Call on_ready - should not raise
    await cog.on_ready()

    # Knowledge base should remain empty
    assert cog.knowledge_system_message == ""
