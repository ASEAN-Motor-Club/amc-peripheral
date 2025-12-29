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


@pytest.mark.asyncio
async def test_ai_helper_has_get_currently_playing_song_tool():
    """Test that ai_helper includes the get_currently_playing_song tool."""
    # Use MagicMock instead of MockBot to allow setting guilds
    bot = MagicMock()
    bot.http_session = AsyncMock()
    cog = KnowledgeCog(bot)

    # Mock the openai client
    mock_completion = MagicMock()
    mock_message = MagicMock()
    mock_message.content = "The current song is Test Song by Test Artist."
    mock_message.tool_calls = None
    mock_completion.choices = [MagicMock(message=mock_message)]

    cog.openai_client_openrouter.chat.completions.create = AsyncMock(
        return_value=mock_completion
    )

    # Mock the active players API call
    mock_response = AsyncMock()
    mock_response.text = AsyncMock(return_value="Player1, Player2")
    bot.http_session.get = MagicMock(
        return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_response))
    )

    # Mock guilds for scheduled events
    mock_guild = MagicMock()
    mock_guild.scheduled_events = []
    bot.guilds = [mock_guild]

    # Call ai_helper
    result = await cog.ai_helper("TestPlayer", "What song is playing?", "")

    # Verify the completion was called with tools
    call_args = cog.openai_client_openrouter.chat.completions.create.call_args
    assert "tools" in call_args.kwargs
    tools = call_args.kwargs["tools"]
    assert len(tools) == 1
    assert tools[0]["function"]["name"] == "get_currently_playing_song"
    assert result == "The current song is Test Song by Test Artist."


@pytest.mark.asyncio
async def test_ai_helper_handles_tool_call():
    """Test that ai_helper correctly handles when the LLM calls the song tool."""
    # Use MagicMock instead of MockBot to allow setting guilds
    bot = MagicMock()
    bot.http_session = AsyncMock()
    cog = KnowledgeCog(bot)

    # Mock tool call response from OpenAI
    mock_tool_call = MagicMock()
    mock_tool_call.id = "call_123"
    mock_tool_call.function.name = "get_currently_playing_song"
    mock_tool_call.function.arguments = "{}"

    mock_first_message = MagicMock()
    mock_first_message.content = None
    mock_first_message.tool_calls = [mock_tool_call]

    mock_first_completion = MagicMock()
    mock_first_completion.choices = [MagicMock(message=mock_first_message)]

    # Mock second completion (after tool result)
    mock_second_message = MagicMock()
    mock_second_message.content = "Currently playing: Test Song (requested by DJ)"
    mock_second_completion = MagicMock()
    mock_second_completion.choices = [MagicMock(message=mock_second_message)]

    cog.openai_client_openrouter.chat.completions.create = AsyncMock(
        side_effect=[mock_first_completion, mock_second_completion]
    )

    # Mock the active players API call
    mock_players_response = AsyncMock()
    mock_players_response.text = AsyncMock(return_value="Player1")
    
    # Mock the radio server metadata call
    mock_radio_response = AsyncMock()
    mock_radio_response.json = AsyncMock(
        return_value={"filename": "/var/lib/radio/requests/DJ-Test_Song.mp3"}
    )

    def mock_get_context(url):
        async def aenter_mock():
            if "active_players" in url:
                return mock_players_response
            elif "localhost:6001" in url:
                return mock_radio_response
            return mock_players_response
        
        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(side_effect=aenter_mock)
        return mock_cm

    bot.http_session.get = MagicMock(side_effect=mock_get_context)

    # Mock guilds
    mock_guild = MagicMock()
    mock_guild.scheduled_events = []
    bot.guilds = [mock_guild]

    # Call ai_helper
    result = await cog.ai_helper("TestPlayer", "What song is playing?", "")

    # Verify the second completion was called after tool handling
    assert cog.openai_client_openrouter.chat.completions.create.call_count == 2
    assert result == "Currently playing: Test Song (requested by DJ)"

