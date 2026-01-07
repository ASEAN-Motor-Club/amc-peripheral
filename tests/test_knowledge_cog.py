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
    # Should now have 4 tools: song, db query, subsidies, and server commands
    assert len(tools) == 4
    tool_names = [t["function"]["name"] for t in tools]
    assert "get_currently_playing_song" in tool_names
    assert "query_game_database" in tool_names
    assert "get_current_subsidies" in tool_names
    assert "get_server_commands" in tool_names
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
    # Explicitly set tool_calls to None to stop the loop
    mock_second_message.tool_calls = None
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

    def mock_get_context(url, **kwargs):
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


# --- Global Chat Context Tests ---


@pytest.mark.asyncio
async def test_global_chat_history_tracks_all_players():
    """Test that global chat history stores messages from all players."""
    bot = MagicMock()
    bot.http_session = AsyncMock()
    cog = KnowledgeCog(bot)

    # Simulate chat messages from different players
    await cog._handle_backend_event({
        "type": "chat_message",
        "player_id": "player_a",
        "player_name": "Alice",
        "message": "Hello everyone!",
        "timestamp": "2026-01-05T10:00:00",
    })
    await cog._handle_backend_event({
        "type": "chat_message",
        "player_id": "player_b",
        "player_name": "Bob",
        "message": "Hey Alice!",
        "timestamp": "2026-01-05T10:00:01",
    })
    await cog._handle_backend_event({
        "type": "chat_message",
        "player_id": "player_c",
        "player_name": "Charlie",
        "message": "What's up?",
        "timestamp": "2026-01-05T10:00:02",
    })

    # Verify global history contains all messages
    assert len(cog._global_chat_history) == 3
    assert cog._global_chat_history[0] == ("player_a", "Alice", "Hello everyone!")
    assert cog._global_chat_history[1] == ("player_b", "Bob", "Hey Alice!")
    assert cog._global_chat_history[2] == ("player_c", "Charlie", "What's up?")


@pytest.mark.asyncio
async def test_global_chat_history_rolling_window():
    """Test that global chat history maintains a rolling window."""
    bot = MagicMock()
    bot.http_session = AsyncMock()
    cog = KnowledgeCog(bot)
    cog._max_global_history = 5  # Small window for testing

    # Add more messages than the limit
    for i in range(8):
        await cog._handle_backend_event({
            "type": "chat_message",
            "player_id": f"player_{i}",
            "player_name": f"Player{i}",
            "message": f"Message {i}",
            "timestamp": f"2026-01-05T10:00:0{i}",
        })

    # Verify only last 5 messages are kept
    assert len(cog._global_chat_history) == 5
    # Should have messages 3-7, not 0-2
    assert cog._global_chat_history[0][2] == "Message 3"
    assert cog._global_chat_history[4][2] == "Message 7"


@pytest.mark.asyncio
async def test_bot_command_receives_global_context():
    """Test that /bot command receives context from all recent players' messages."""
    bot = MagicMock()
    bot.http_session = AsyncMock()
    cog = KnowledgeCog(bot)
    
    # Mock _handle_ingame_bot_command to capture arguments
    captured_args = {}
    
    async def mock_handler(**kwargs):
        captured_args.update(kwargs)
    
    cog._handle_ingame_bot_command = mock_handler

    # Simulate conversation between two players
    await cog._handle_backend_event({
        "type": "chat_message",
        "player_id": "player_a",
        "player_name": "Alice",
        "message": "I think the factory is closed",
        "timestamp": "2026-01-05T10:00:00",
    })
    await cog._handle_backend_event({
        "type": "chat_message",
        "player_id": "player_b",
        "player_name": "Bob",
        "message": "Really? Are you sure?",
        "timestamp": "2026-01-05T10:00:01",
    })
    
    # Now player B asks the bot a contextual question
    await cog._handle_backend_event({
        "type": "chat_message",
        "player_id": "player_b",
        "player_name": "Bob",
        "message": "is it?",
        "timestamp": "2026-01-05T10:00:02",
        "is_bot_command": True,
    })

    # Verify the bot received context from BOTH players
    prev_messages = captured_args.get("prev_messages", "")
    assert "Alice: I think the factory is closed" in prev_messages
    assert "Bob: Really? Are you sure?" in prev_messages


@pytest.mark.asyncio
async def test_bot_command_excludes_current_message():
    """Test that the /bot command itself is NOT included in prev_messages."""
    bot = MagicMock()
    bot.http_session = AsyncMock()
    cog = KnowledgeCog(bot)
    
    captured_args = {}
    
    async def mock_handler(**kwargs):
        captured_args.update(kwargs)
    
    cog._handle_ingame_bot_command = mock_handler

    # Add some chat context
    await cog._handle_backend_event({
        "type": "chat_message",
        "player_id": "player_a",
        "player_name": "Alice",
        "message": "Some context",
        "timestamp": "2026-01-05T10:00:00",
    })
    
    # Bot command
    await cog._handle_backend_event({
        "type": "chat_message",
        "player_id": "player_b",
        "player_name": "Bob",
        "message": "what do you think?",
        "timestamp": "2026-01-05T10:00:01",
        "is_bot_command": True,
    })

    # The bot's own query should NOT be in prev_messages
    prev_messages = captured_args.get("prev_messages", "")
    assert "what do you think?" not in prev_messages
    # But Alice's message should be
    assert "Alice: Some context" in prev_messages


# --- Progress Feedback Tests ---


@pytest.mark.asyncio
async def test_tool_status_message_mapping():
    """Test that tool names map to user-friendly status messages."""
    bot = MagicMock()
    bot.http_session = AsyncMock()
    cog = KnowledgeCog(bot)

    # Test known tools have friendly messages
    assert "numbers" in cog._get_tool_status_message("query_game_database").lower()
    assert "radio" in cog._get_tool_status_message("get_currently_playing_song").lower()
    assert "subsidy" in cog._get_tool_status_message("get_current_subsidies").lower()
    assert "commands" in cog._get_tool_status_message("get_server_commands").lower()
    
    # Test unknown tool gets generic message
    unknown_msg = cog._get_tool_status_message("some_unknown_tool")
    assert "Processing" in unknown_msg
    assert "some_unknown_tool" in unknown_msg
    
    # Verify no emojis in messages (not supported in-game)
    for tool in ["query_game_database", "get_current_subsidies", "get_server_commands"]:
        msg = cog._get_tool_status_message(tool)
        assert not any(ord(c) > 127 for c in msg), f"Emoji found in message: {msg}"


@pytest.mark.asyncio
async def test_send_progress_feedback_discord():
    """Test that Discord interactions receive progress feedback via edit_original_response."""
    bot = MagicMock()
    bot.http_session = AsyncMock()
    cog = KnowledgeCog(bot)

    # Mock Discord interaction
    mock_interaction = MagicMock()
    mock_interaction.edit_original_response = AsyncMock()

    # Call feedback method
    await cog._send_progress_feedback(
        message="Test progress message",
        interaction=mock_interaction,
    )

    # Verify edit was called
    mock_interaction.edit_original_response.assert_called_once_with(
        content="Test progress message"
    )


@pytest.mark.asyncio
async def test_send_progress_feedback_ingame():
    """Test that in-game feedback uses the provided callback."""
    bot = MagicMock()
    bot.http_session = AsyncMock()
    cog = KnowledgeCog(bot)

    # Mock callback
    callback_messages = []
    async def mock_callback(msg):
        callback_messages.append(msg)

    # Call feedback method with callback
    await cog._send_progress_feedback(
        message="In-game status update",
        ingame_feedback_fn=mock_callback,
    )

    # Verify callback was called
    assert len(callback_messages) == 1
    assert callback_messages[0] == "In-game status update"


@pytest.mark.asyncio
async def test_send_progress_feedback_handles_errors():
    """Test that feedback errors are handled gracefully."""
    bot = MagicMock()
    bot.http_session = AsyncMock()
    cog = KnowledgeCog(bot)

    # Mock interaction that raises
    mock_interaction = MagicMock()
    mock_interaction.edit_original_response = AsyncMock(side_effect=Exception("Discord API error"))

    # Should not raise
    await cog._send_progress_feedback(
        message="Test message",
        interaction=mock_interaction,
    )
    # Test passes if no exception was raised


@pytest.mark.asyncio
async def test_ai_helper_accepts_feedback_callback():
    """Test that ai_helper accepts and forwards the ingame_feedback_fn parameter."""
    bot = MagicMock()
    bot.http_session = AsyncMock()
    cog = KnowledgeCog(bot)

    # Mock completion to return immediately (no tool calls)
    mock_message = MagicMock()
    mock_message.content = "Quick response"
    mock_message.tool_calls = None
    mock_completion = MagicMock()
    mock_completion.choices = [MagicMock(message=mock_message)]
    cog.openai_client_openrouter.chat.completions.create = AsyncMock(return_value=mock_completion)

    # Mock active players API
    mock_response = AsyncMock()
    mock_response.text = AsyncMock(return_value="Player1")
    bot.http_session.get = MagicMock(
        return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_response))
    )

    # Mock guilds
    mock_guild = MagicMock()
    mock_guild.scheduled_events = []
    bot.guilds = [mock_guild]

    # Define callback
    feedback_received = []
    async def feedback_fn(msg):
        feedback_received.append(msg)

    # Call ai_helper with callback (should not crash)
    result = await cog.ai_helper(
        "TestPlayer",
        "Quick question",
        "",
        ingame_feedback_fn=feedback_fn,
    )

    assert result == "Quick response"
    # Feedback may or may not be called depending on timing, but no crash should occur
