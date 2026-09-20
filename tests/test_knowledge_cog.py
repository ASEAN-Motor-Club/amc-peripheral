import pytest
import discord
from discord.ext import commands
from unittest.mock import AsyncMock, MagicMock, patch
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
async def test_ai_helper_discord_shared_tool_definitions():
    """Test that the ask path advertises the shared agentic tool set."""
    # Use MagicMock instead of MockBot to allow setting guilds
    bot = MagicMock()
    bot.http_session = AsyncMock()
    cog = KnowledgeCog(bot)
    cog._memory_store = None  # cog_load not run in unit tests

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

    # Call ai_helper_discord (the surviving ask path)
    result = await cog.ai_helper_discord("TestPlayer", "What song is playing?", "")

    # Verify the completion was called with tools
    call_args = cog.openai_client_openrouter.chat.completions.create.call_args
    assert "tools" in call_args.kwargs
    tools = call_args.kwargs["tools"]
    tool_names = [t["function"]["name"] for t in tools]
    # Shared agentic toolset: wiki/run/discord/memory + interim send_message
    assert tool_names == ["run", "wiki", "discord", "memory", "send_message"]
    assert result == "The current song is Test Song by Test Artist."


@pytest.mark.asyncio
async def test_ai_helper_handles_tool_call():
    """Test that ai_helper correctly handles when the LLM calls the song tool."""
    # Use MagicMock instead of MockBot to allow setting guilds
    bot = MagicMock()
    bot.http_session = AsyncMock()
    cog = KnowledgeCog(bot)
    cog._memory_store = None  # cog_load not run in unit tests

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

    # Call ai_helper_discord (the surviving ask path)
    result = await cog.ai_helper_discord("TestPlayer", "What song is playing?", "")

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
async def test_bot_command_sends_sunset_notice():
    """In-game /bot is retired — the SSE handler announces the Discord redirect."""
    bot = MagicMock()
    bot.http_session = AsyncMock()
    cog = KnowledgeCog(bot)

    announced = []

    async def fake_announce(http_session, message, **kwargs):
        announced.append(message)

    with patch("amc_peripheral.bot.knowledge_cog.announce_in_game", fake_announce):
        await cog._handle_backend_event({
            "type": "chat_message",
            "player_id": "player_b",
            "player_name": "Bob",
            "message": "is it?",
            "timestamp": "2026-01-05T10:00:02",
            "is_bot_command": True,
        })

    assert len(announced) == 1
    assert "retired" in announced[0]
    assert "#ask-bot" in announced[0]
    # The command text itself still lands in global chat history
    assert any(msg == "is it?" for _, _, msg in cog._global_chat_history)


@pytest.mark.asyncio
async def test_bot_command_sunset_notice_cooldown():
    """Repeat /bot commands don't spam game chat: one notice per player per window."""
    bot = MagicMock()
    bot.http_session = AsyncMock()
    cog = KnowledgeCog(bot)

    announced = []

    async def fake_announce(http_session, message, **kwargs):
        announced.append(message)

    with patch("amc_peripheral.bot.knowledge_cog.announce_in_game", fake_announce):
        for ts in ("2026-01-05T10:00:00", "2026-01-05T10:00:10", "2026-01-05T10:00:20"):
            await cog._handle_backend_event({
                "type": "chat_message",
                "player_id": "player_b",
                "player_name": "Bob",
                "message": "hello?",
                "timestamp": ts,
                "is_bot_command": True,
            })
        # A different player still gets their own notice
        await cog._handle_backend_event({
            "type": "chat_message",
            "player_id": "player_c",
            "player_name": "Carol",
            "message": "anyone there?",
            "timestamp": "2026-01-05T10:00:30",
            "is_bot_command": True,
        })

    assert len(announced) == 2


# --- Progress Feedback Tests ---


@pytest.mark.asyncio
async def test_send_message_tool_definition_exists():
    """send_message must be advertised to the LLM alongside run/wiki/discord/memory."""
    bot = MagicMock()
    bot.http_session = AsyncMock()
    cog = KnowledgeCog(bot)

    tools = cog._get_shared_tool_definitions()
    names = [t["function"]["name"] for t in tools]
    assert "send_message" in names


@pytest.mark.asyncio
async def test_send_message_tool_sends_interim_message():
    """A first-turn send_message tool call sends BEFORE other tools run and returns the final answer."""
    bot = MagicMock()
    bot.http_session = AsyncMock()
    cog = KnowledgeCog(bot)

    sent: list[str] = []
    order: list[str] = []

    async def feedback_fn(msg: str) -> None:
        sent.append(msg)
        order.append("send_message")

    async def fake_execute_tool(name, args, interaction=None, player_id=None):
        order.append(f"tool:{name}")
        return "ok"

    # First turn: send_message + run in the SAME batch. Second turn: final answer.
    sm_call = MagicMock()
    sm_call.id = "call_1"
    sm_call.function.name = "send_message"
    sm_call.function.arguments = '{"message": "let me look that up"}'
    run_call = MagicMock()
    run_call.id = "call_2"
    run_call.function.name = "run"
    run_call.function.arguments = '{"command": "vehicle Air City"}'

    interim_msg = MagicMock()
    interim_msg.tool_calls = [sm_call, run_call]
    final_msg = MagicMock()
    final_msg.content = "The answer is 42."
    final_msg.tool_calls = None
    completion_1 = MagicMock()
    completion_1.choices = [MagicMock(message=interim_msg)]
    completion_2 = MagicMock()
    completion_2.choices = [MagicMock(message=final_msg)]
    cog.openai_client_openrouter.chat.completions.create = AsyncMock(
        side_effect=[completion_1, completion_2]
    )
    with patch.object(cog, "_execute_tool", side_effect=fake_execute_tool):
        result = await cog._call_llm_with_tools(
            messages=[{"role": "user", "content": "what is it"}],
            tools=cog._get_shared_tool_definitions(),
            model="test-model",
            ingame_feedback_fn=feedback_fn,
        )

    assert sent == ["let me look that up"]
    assert result == "The answer is 42."
    # send_message fired BEFORE the other tool call in the same batch
    assert order.index("send_message") < order.index("tool:run")


@pytest.mark.asyncio
async def test_send_message_only_fires_once():
    """A send_message in a LATER turn does not send again — user sees only one interim message."""
    bot = MagicMock()
    bot.http_session = AsyncMock()
    cog = KnowledgeCog(bot)

    sent: list[str] = []

    async def feedback_fn(msg: str) -> None:
        sent.append(msg)

    sm_call_1 = MagicMock()
    sm_call_1.id = "call_1"
    sm_call_1.function.name = "send_message"
    sm_call_1.function.arguments = '{"message": "first"}'
    sm_call_2 = MagicMock()
    sm_call_2.id = "call_2"
    sm_call_2.function.name = "send_message"
    sm_call_2.function.arguments = '{"message": "again"}'

    turn1 = MagicMock()
    turn1.tool_calls = [sm_call_1]
    turn2 = MagicMock()
    turn2.tool_calls = [sm_call_2]
    final_msg = MagicMock()
    final_msg.content = "done"
    final_msg.tool_calls = None
    completion_1 = MagicMock()
    completion_1.choices = [MagicMock(message=turn1)]
    completion_2 = MagicMock()
    completion_2.choices = [MagicMock(message=turn2)]
    completion_3 = MagicMock()
    completion_3.choices = [MagicMock(message=final_msg)]
    cog.openai_client_openrouter.chat.completions.create = AsyncMock(
        side_effect=[completion_1, completion_2, completion_3]
    )

    messages: list = [{"role": "user", "content": "hi"}]
    result = await cog._call_llm_with_tools(
        messages=messages,
        tools=cog._get_shared_tool_definitions(),
        model="test-model",
        ingame_feedback_fn=feedback_fn,
    )

    # Second-turn send_message is a no-op: nothing extra sent to the user
    assert sent == ["first"]
    assert result == "done"
    # The repeat call got the downgrade tool-result
    tool_results = [m["content"] for m in messages if m.get("role") == "tool"]
    assert "Message already sent for this reply." in tool_results


@pytest.mark.asyncio
async def test_send_message_tool_empty_message_is_rejected():
    """An empty message body returns an error tool-result instead of sending."""
    bot = MagicMock()
    bot.http_session = AsyncMock()
    cog = KnowledgeCog(bot)

    sent: list[str] = []

    async def feedback_fn(msg: str) -> None:
        sent.append(msg)

    tool_call = MagicMock()
    tool_call.id = "call_1"
    tool_call.function.name = "send_message"
    tool_call.function.arguments = '{"message": ""}'

    interim_msg = MagicMock()
    interim_msg.tool_calls = [tool_call]
    final_msg = MagicMock()
    final_msg.content = "done"
    final_msg.tool_calls = None
    completion_1 = MagicMock()
    completion_1.choices = [MagicMock(message=interim_msg)]
    completion_2 = MagicMock()
    completion_2.choices = [MagicMock(message=final_msg)]
    cog.openai_client_openrouter.chat.completions.create = AsyncMock(
        side_effect=[completion_1, completion_2]
    )

    messages: list = [{"role": "user", "content": "hi"}]

    result = await cog._call_llm_with_tools(
        messages=messages,
        tools=cog._get_shared_tool_definitions(),
        model="test-model",
        ingame_feedback_fn=feedback_fn,
    )

    assert sent == []  # nothing went out to the user
    assert result == "done"
    tool_results = [m["content"] for m in messages if m.get("role") == "tool"]
    assert tool_results == ["Error: message parameter required."]


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
async def test_call_llm_with_tools_accepts_feedback_callback():
    """Test that the shared LLM loop accepts and forwards ingame_feedback_fn."""
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

    # Define callback
    feedback_received = []
    async def feedback_fn(msg):
        feedback_received.append(msg)

    # Call the shared loop with callback (should not crash)
    result = await cog._call_llm_with_tools(
        [{"role": "user", "content": "Quick question"}],
        [],
        "test-model",
        ingame_feedback_fn=feedback_fn,
    )

    assert result == "Quick response"
    # Feedback may or may not be called depending on timing, but no crash should occur


# --- Ask-Bot Channel & @Mention Tests ---


@pytest.fixture
def knowledge_cog_with_ai():
    """Create a KnowledgeCog with mocked ai_helper_discord."""
    bot = MagicMock()
    bot.http_session = AsyncMock()
    bot.user = MagicMock()
    bot.user.id = 999
    bot.user.mentioned_in = MagicMock(return_value=False)
    cog = KnowledgeCog(bot)
    cog.ai_helper_discord = AsyncMock(return_value="Bot response")
    return cog, bot


@pytest.mark.asyncio
async def test_on_message_responds_in_ask_bot_channel(knowledge_cog_with_ai):
    """Test that the bot responds to any message in #ask-bot channel."""
    cog, bot = knowledge_cog_with_ai

    msg = MagicMock(spec=discord.Message)
    msg.author = MagicMock()
    msg.author.display_name = "TestUser"
    msg.content = "How do I deliver cargo?"
    msg.id = 12345
    msg.mentions = []
    msg.channel = MagicMock()
    msg.channel.id = 1349258054599835740  # ASK_BOT_CHANNEL_ID
    msg.reply = AsyncMock()

    # Mock channel.history
    async def mock_history(limit=20):
        return
        yield  # empty async generator

    msg.channel.history = mock_history
    msg.channel.typing = MagicMock(return_value=AsyncMock())

    await cog.on_message(msg)

    cog.ai_helper_discord.assert_called_once()
    call_args = cog.ai_helper_discord.call_args
    assert call_args[0][0] == "TestUser"
    assert call_args[0][1] == "How do I deliver cargo?"
    msg.reply.assert_called_once_with("Bot response", mention_author=False)


@pytest.mark.asyncio
async def test_on_message_responds_to_mention(knowledge_cog_with_ai):
    """Test that the bot responds when @mentioned in any channel."""
    cog, bot = knowledge_cog_with_ai

    msg = MagicMock(spec=discord.Message)
    msg.author = MagicMock()
    msg.author.display_name = "Mentioner"
    msg.content = f"<@{bot.user.id}> what is UBI?"
    msg.id = 67890
    msg.mentions = [bot.user]
    msg.channel = MagicMock()
    msg.channel.id = 111111  # Some random channel
    msg.reply = AsyncMock()

    async def mock_history(limit=20):
        return
        yield

    msg.channel.history = mock_history
    msg.channel.typing = MagicMock(return_value=AsyncMock())

    await cog.on_message(msg)

    cog.ai_helper_discord.assert_called_once()
    call_args = cog.ai_helper_discord.call_args
    assert call_args[0][0] == "Mentioner"
    assert call_args[0][1] == "what is UBI?"  # Mention stripped
    assert call_args.kwargs.get("generic") or call_args[0][3]  # generic=True for mentions
    msg.reply.assert_called_once()


@pytest.mark.asyncio
async def test_on_message_ignores_non_ask_bot_channel(knowledge_cog_with_ai):
    """Test that the bot does NOT respond in unrelated channels without a mention."""
    cog, bot = knowledge_cog_with_ai

    msg = MagicMock(spec=discord.Message)
    msg.author = MagicMock()
    msg.content = "Just chatting"
    msg.mentions = []
    msg.channel = MagicMock()
    msg.channel.id = 111111  # Not the ask-bot channel

    await cog.on_message(msg)

    cog.ai_helper_discord.assert_not_called()


@pytest.mark.asyncio
async def test_on_message_ignores_own_messages(knowledge_cog_with_ai):
    """Test that the bot does not respond to its own messages."""
    cog, bot = knowledge_cog_with_ai

    msg = MagicMock(spec=discord.Message)
    msg.author = bot.user  # Message from the bot itself
    msg.content = "I said something"
    msg.channel = MagicMock()
    msg.channel.id = 1349258054599835740  # Even in #ask-bot

    await cog.on_message(msg)

    cog.ai_helper_discord.assert_not_called()


# --- Long-term memory parity: Discord /bot recalls the same memory as in-game /bot ---


@pytest.mark.asyncio
async def test_ai_helper_discord_no_legacy_semantic_memory():
    """Legacy ChromaDB semantic memory is retired — the Discord ask path must not
    reference it and must build its prompt from wiki/memory/chat context only."""
    bot = MagicMock()
    cog = KnowledgeCog(bot)
    cog.knowledge_system_message = ""
    cog._memory_store = None  # cog_load not run in unit tests
    cog._wiki_index = MagicMock()
    cog._wiki_index.get_index = MagicMock(return_value="")
    cog._call_llm_with_tools = AsyncMock(return_value="Bot response")

    await cog.ai_helper_discord(
        "Alice",
        "do you remember my favourite vehicle?",
        "",
        generic=False,
        player_id="123",
    )

    args, _ = cog._call_llm_with_tools.call_args
    messages = args[0]
    combined = "\n".join(
        m.get("content", "") for m in messages if m.get("role") == "user"
    )
    assert "Relevant past conversations:" not in combined


@pytest.mark.asyncio
async def test_ingame_reply_is_not_truncated():
    """RETIRED with the in-game /bot (2026-09-20): the in-game reply path is gone.
    Sunset notice text lives in the SSE handler and is announced unmodified."""
    bot = MagicMock()
    bot.http_session = AsyncMock()
    cog = KnowledgeCog(bot)

    notice = (
        "The in-game /bot has been retired. Ask me on Discord instead: "
        "#ask-bot or @mention me."
    )
    announced = []

    async def fake_announce(http_session, message, **kwargs):
        announced.append(message)

    with patch("amc_peripheral.bot.knowledge_cog.announce_in_game", fake_announce):
        await cog._handle_backend_event({
            "type": "chat_message",
            "player_id": "76561198000000000",
            "player_name": "MrMoo6000",
            "message": "how do I invite someone to my company",
            "timestamp": "2026-01-05T10:00:00",
            "is_bot_command": True,
        })

    assert announced == [notice]

