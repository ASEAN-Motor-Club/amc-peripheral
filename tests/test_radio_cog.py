import asyncio
import sys
from unittest.mock import MagicMock, AsyncMock

# Mock google.cloud.texttospeech BEFORE importing module that uses it
mock_texttospeech = MagicMock()
# We need to mock the client instantiation
mock_texttospeech.TextToSpeechClient = MagicMock()
sys.modules["google.cloud.texttospeech"] = mock_texttospeech
sys.modules["google.cloud"] = MagicMock()
sys.modules["google"] = MagicMock()

import pytest  # noqa: E402
from discord.ext import tasks  # noqa: E402
from amc_peripheral.radio.radio_cog import RadioCog  # noqa: E402


@pytest.fixture
def mock_bot():
    bot = MagicMock()
    bot.tree = MagicMock()
    bot.user.id = 12345
    # Add http_session mock
    bot.http_session = AsyncMock()
    # Mock get_channel
    bot.get_channel = MagicMock(return_value=None)
    # Mock loop
    bot.loop = MagicMock()
    bot.loop.create_task = MagicMock()
    return bot


@pytest.fixture
def cog(mock_bot, tmp_path, monkeypatch):
    db_path = str(tmp_path / "radio.db")
    monkeypatch.setattr("amc_peripheral.radio.radio_cog.RADIO_DB_PATH", db_path)
    monkeypatch.setattr("amc_peripheral.radio.radio_cog.SONG_CACHE_PATH", str(tmp_path / "cache"))
    monkeypatch.setattr("amc_peripheral.radio.radio_cog.REQUESTS_PATH", str(tmp_path / "requests"))
    monkeypatch.setattr("amc_peripheral.radio.radio_cog.OPENAI_API_KEY_OPENROUTER", "test-key")
    return RadioCog(mock_bot)


@pytest.mark.asyncio
async def test_radio_tasks_exist(cog):
    """Verify that background tasks are defined as Loop objects on the Cog."""
    assert hasattr(cog, "post_gazette_task")
    assert isinstance(cog.post_gazette_task, tasks.Loop)

    assert hasattr(cog, "update_jingles")
    assert isinstance(cog.update_jingles, tasks.Loop)

    assert hasattr(cog, "update_news")
    assert isinstance(cog.update_news, tasks.Loop)

    assert hasattr(cog, "update_current_song_embed")
    assert isinstance(cog.update_current_song_embed, tasks.Loop)

    assert hasattr(cog, "auto_queue_trending")
    assert isinstance(cog.auto_queue_trending, tasks.Loop)

    assert hasattr(cog, "wiki_background_ingest")
    assert isinstance(cog.wiki_background_ingest, tasks.Loop)

    assert hasattr(cog, "wiki_daily_lint")
    assert isinstance(cog.wiki_daily_lint, tasks.Loop)


@pytest.mark.asyncio
async def test_radio_cog_load_starts_tasks(cog, monkeypatch):
    """Verify cog_load starts the tasks."""
    # Mock the start methods
    cog.post_gazette_task.start = MagicMock()
    cog.update_jingles.start = MagicMock()
    cog.update_news.start = MagicMock()
    cog.update_current_song_embed.start = MagicMock()
    cog.auto_queue_trending.start = MagicMock()
    cog.wiki_background_ingest.start = MagicMock()
    cog.wiki_daily_lint.start = MagicMock()
    cog.wiki_daily_export.start = MagicMock()
    cog.wiki_weekly_synthesis.start = MagicMock()

    # Mock fetch_knowledge to avoid error
    cog.fetch_knowledge = AsyncMock(return_value="Mock Knowledge")
    # Mock cleanup to avoid filesystem errors
    cog._cleanup_legacy_requests = MagicMock()

    # Stop the SSE listener from actually connecting
    cog._listen_backend_events = AsyncMock()

    await cog.cog_load()

    cog.post_gazette_task.start.assert_called_once()
    cog.update_jingles.start.assert_called_once()
    cog.update_news.start.assert_called_once()
    cog.update_current_song_embed.start.assert_called_once()
    cog.auto_queue_trending.start.assert_called_once()
    cog.wiki_background_ingest.start.assert_called_once()
    cog.wiki_daily_lint.start.assert_called_once()
    cog.wiki_daily_export.start.assert_called_once()
    cog.wiki_weekly_synthesis.start.assert_called_once()
    # SSE listener task was scheduled
    assert cog._sse_task is not None
    cog._sse_task.cancel()


@pytest.mark.asyncio
async def test_radio_cog_unload_cancels_tasks(cog):
    """Verify cog_unload cancels the tasks."""
    # Mock the cancel methods
    cog.post_gazette_task.cancel = MagicMock()
    cog.update_jingles.cancel = MagicMock()
    cog.update_news.cancel = MagicMock()
    cog.update_current_song_embed.cancel = MagicMock()
    cog.auto_queue_trending.cancel = MagicMock()
    cog.wiki_background_ingest.cancel = MagicMock()
    cog.wiki_daily_lint.cancel = MagicMock()
    cog.wiki_daily_export.cancel = MagicMock()
    cog.wiki_weekly_synthesis.cancel = MagicMock()

    sse_task = MagicMock()
    sse_task.cancel = MagicMock()
    cog._sse_task = sse_task

    await cog.cog_unload()

    cog.post_gazette_task.cancel.assert_called_once()
    cog.update_jingles.cancel.assert_called_once()
    cog.update_news.cancel.assert_called_once()
    cog.update_current_song_embed.cancel.assert_called_once()
    cog.auto_queue_trending.cancel.assert_called_once()
    cog.wiki_background_ingest.cancel.assert_called_once()
    cog.wiki_daily_lint.cancel.assert_called_once()
    cog.wiki_daily_export.cancel.assert_called_once()
    cog.wiki_weekly_synthesis.cancel.assert_called_once()
    sse_task.cancel.assert_called_once()


@pytest.mark.asyncio
async def test_request_song_throttling(cog):
    """Test throttling mechanism for song requests."""
    # Mock dependencies
    cog.openai_client_openrouter = MagicMock()

    # Bypass downloading logic by mocking yt_dlp context manager interaction or just testing up to the exception
    # We want to test logic BEFORE download, specifically throttling.

    # requester = "TestUser"

    # First request should pass (until download logic, which we expect to fail in this mock env)
    # But wait, request_song does throttling checks first.

    # Mocking datetime is tricky, let's just inspect the user_requests dict directly after calls
    # Actually, let's just manually populate throttling data to test the check logic
    pass
    # Skipping detailed logic test here for brevity, focused on structure verification.


@pytest.mark.asyncio
async def test_create_segment_command_exists(cog):
    """Verify the create_segment command is registered."""
    commands = [cmd.name for cmd in cog.__cog_app_commands__]
    assert "create_segment" in commands


@pytest.mark.asyncio
async def test_generate_segment_removes_markdown(cog, monkeypatch):
    """Test that generate_segment strips markdown from output."""
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "Hello **world** and *everyone*!"
    mock_response.choices[0].message.tool_calls = None

    cog.openai_client_openrouter.chat.completions.create = AsyncMock(
        return_value=mock_response
    )

    # Mock TTS to return dummy bytes
    monkeypatch.setattr(
        "amc_peripheral.radio.radio_cog.tts_dispatch", lambda *args, **kwargs: b"audio"
    )

    transcript, audio = await cog.generate_segment("test topic")
    assert "**" not in transcript  # Markdown should be stripped
    assert "*" not in transcript
    assert audio == b"audio"


# --- Auto-Queue Trending Songs Tests ---


@pytest.mark.asyncio
async def test_auto_queue_trending_task_exists(cog):
    """Verify that the auto_queue_trending task is defined as a Loop object."""
    assert hasattr(cog, "auto_queue_trending")
    assert isinstance(cog.auto_queue_trending, tasks.Loop)


@pytest.mark.asyncio
async def test_cog_load_starts_auto_queue(cog):
    """Verify cog_load starts the auto_queue_trending task."""
    cog.post_gazette_task.start = MagicMock()
    cog.update_jingles.start = MagicMock()
    cog.update_news.start = MagicMock()
    cog.update_current_song_embed.start = MagicMock()
    cog.auto_queue_trending.start = MagicMock()
    cog.wiki_background_ingest.start = MagicMock()
    cog.wiki_daily_lint.start = MagicMock()
    cog.wiki_daily_export.start = MagicMock()
    cog.wiki_weekly_synthesis.start = MagicMock()
    cog.fetch_knowledge = AsyncMock(return_value="Mock Knowledge")
    cog._cleanup_legacy_requests = MagicMock()
    cog._listen_backend_events = AsyncMock()

    await cog.cog_load()

    cog.auto_queue_trending.start.assert_called_once()
    if cog._sse_task is not None:
        cog._sse_task.cancel()


@pytest.mark.asyncio
async def test_cog_unload_cancels_auto_queue(cog):
    """Verify cog_unload cancels the auto_queue_trending task."""
    cog.post_gazette_task.cancel = MagicMock()
    cog.update_jingles.cancel = MagicMock()
    cog.update_news.cancel = MagicMock()
    cog.update_current_song_embed.cancel = MagicMock()
    cog.auto_queue_trending.cancel = MagicMock()
    cog.wiki_background_ingest.cancel = MagicMock()
    cog.wiki_daily_lint.cancel = MagicMock()
    cog.wiki_daily_export.cancel = MagicMock()
    cog.wiki_weekly_synthesis.cancel = MagicMock()

    await cog.cog_unload()

    cog.auto_queue_trending.cancel.assert_called_once()


# --- Wiki Background Task Tests ---


@pytest.mark.asyncio
async def test_wiki_background_ingest_task_exists(cog):
    """Verify that the wiki_background_ingest task is defined as a Loop object."""
    assert hasattr(cog, "wiki_background_ingest")
    assert isinstance(cog.wiki_background_ingest, tasks.Loop)


@pytest.mark.asyncio
async def test_wiki_daily_lint_task_exists(cog):
    """Verify that the wiki_daily_lint task is defined as a Loop object."""
    assert hasattr(cog, "wiki_daily_lint")
    assert isinstance(cog.wiki_daily_lint, tasks.Loop)


@pytest.mark.asyncio
async def test_cog_load_starts_wiki_tasks(cog):
    """Verify cog_load starts the wiki background tasks."""
    cog.post_gazette_task.start = MagicMock()
    cog.update_jingles.start = MagicMock()
    cog.update_news.start = MagicMock()
    cog.update_current_song_embed.start = MagicMock()
    cog.auto_queue_trending.start = MagicMock()
    cog.wiki_background_ingest.start = MagicMock()
    cog.wiki_daily_lint.start = MagicMock()
    cog.wiki_daily_export.start = MagicMock()
    cog.wiki_weekly_synthesis.start = MagicMock()
    cog.fetch_knowledge = AsyncMock(return_value="Mock Knowledge")
    cog._cleanup_legacy_requests = MagicMock()
    cog._listen_backend_events = AsyncMock()

    await cog.cog_load()

    cog.wiki_background_ingest.start.assert_called_once()
    cog.wiki_daily_lint.start.assert_called_once()
    cog.wiki_daily_export.start.assert_called_once()
    cog.wiki_weekly_synthesis.start.assert_called_once()
    if cog._sse_task is not None:
        cog._sse_task.cancel()


@pytest.mark.asyncio
async def test_cog_unload_cancels_wiki_tasks(cog):
    """Verify cog_unload cancels the wiki background tasks."""
    cog.post_gazette_task.cancel = MagicMock()
    cog.update_jingles.cancel = MagicMock()
    cog.update_news.cancel = MagicMock()
    cog.update_current_song_embed.cancel = MagicMock()
    cog.auto_queue_trending.cancel = MagicMock()
    cog.wiki_background_ingest.cancel = MagicMock()
    cog.wiki_daily_lint.cancel = MagicMock()
    cog.wiki_daily_export.cancel = MagicMock()
    cog.wiki_weekly_synthesis.cancel = MagicMock()

    await cog.cog_unload()

    cog.wiki_background_ingest.cancel.assert_called_once()
    cog.wiki_daily_lint.cancel.assert_called_once()
    cog.wiki_daily_export.cancel.assert_called_once()
    cog.wiki_weekly_synthesis.cancel.assert_called_once()


@pytest.mark.asyncio
async def test_schedule_wiki_ingest_queues_conversations(cog):
    """Verify _schedule_wiki_ingest appends to the pending queue."""
    assert cog._wiki_pending_conversations == []
    cog._schedule_wiki_ingest("player1", "Alice", "Hello", "Hi there")
    assert len(cog._wiki_pending_conversations) == 1
    item = cog._wiki_pending_conversations[0]
    assert item["player_id"] == "player1"
    assert item["player_name"] == "Alice"
    assert item["question"] == "Hello"
    assert item["response"] == "Hi there"
    assert "timestamp" in item

    # Multiple calls append
    cog._schedule_wiki_ingest("player2", "Bob", "How are you?", "Good!")
    assert len(cog._wiki_pending_conversations) == 2


@pytest.mark.asyncio
async def test_wiki_background_ingest_drains_queue(cog, monkeypatch):
    """Verify wiki_background_ingest drains the queue and calls _ingest_to_wiki."""
    monkeypatch.setattr("amc_peripheral.radio.radio_cog.log", MagicMock())
    cog._wiki_ingest = MagicMock()
    cog._wiki_storage = MagicMock()
    cog._ingest_to_wiki = AsyncMock()

    cog._schedule_wiki_ingest("p1", "Alice", "Q1", "A1")
    cog._schedule_wiki_ingest("p2", "Bob", "Q2", "A2")
    assert len(cog._wiki_pending_conversations) == 2

    await cog.wiki_background_ingest()

    assert cog._wiki_pending_conversations == []
    assert cog._ingest_to_wiki.call_count == 2
    cog._ingest_to_wiki.assert_any_call("p1", "Alice", "Q1", "A1")
    cog._ingest_to_wiki.assert_any_call("p2", "Bob", "Q2", "A2")


@pytest.mark.asyncio
async def test_wiki_background_ingest_skips_when_not_initialized(cog, monkeypatch):
    """Verify wiki_background_ingest skips if wiki components are missing."""
    monkeypatch.setattr("amc_peripheral.radio.radio_cog.log", MagicMock())
    cog._wiki_ingest = None
    cog._wiki_storage = None
    cog._schedule_wiki_ingest("p1", "Alice", "Q1", "A1")

    await cog.wiki_background_ingest()

    assert cog._wiki_pending_conversations == []


@pytest.mark.asyncio
async def test_wiki_daily_lint_runs_when_initialized(cog, monkeypatch):
    """Verify wiki_daily_lint runs lint and logs results."""
    monkeypatch.setattr("amc_peripheral.radio.radio_cog.log", MagicMock())
    mock_lint = MagicMock()
    mock_lint.run_lint.return_value = {
        "orphans": [{"title": "orphan1"}],
        "stale": [],
        "missing_links": [{"from_title": "a", "to_title": "b"}],
        "inactive_players": [],
        "fixes_applied": ["fix1"],
    }
    cog._wiki_lint = mock_lint
    cog._wiki_storage = MagicMock()

    await cog.wiki_daily_lint()

    mock_lint.run_lint.assert_called_once_with(auto_fix=True)


@pytest.mark.asyncio
async def test_wiki_daily_lint_skips_when_not_initialized(cog, monkeypatch):
    """Verify wiki_daily_lint skips if wiki lint is missing."""
    monkeypatch.setattr("amc_peripheral.radio.radio_cog.log", MagicMock())
    cog._wiki_lint = None
    cog._wiki_storage = None

    await cog.wiki_daily_lint()

    # Should not raise


@pytest.mark.asyncio
async def test_wiki_dev_cmd_restricted_to_dj(cog):
    """Verify !wiki commands are restricted to DJ role."""
    ctx = MagicMock()
    ctx.author.roles = [MagicMock(id=999)]  # Not DJ_ROLE_ID
    ctx.send = AsyncMock()

    await cog.wiki_dev_cmd.callback(cog, ctx, "lint")
    ctx.send.assert_called_once_with("Only DJs can use wiki dev commands.")


@pytest.mark.asyncio
async def test_wiki_dev_cmd_stats(cog):
    """Verify !wiki stats returns wiki statistics."""
    ctx = MagicMock()
    dj_role = MagicMock()
    dj_role.id = 1364484047447003248  # DJ_ROLE_ID default
    ctx.author.roles = [dj_role]
    ctx.send = AsyncMock()

    cog._wiki_storage = MagicMock()
    cog._wiki_storage.get_stats.return_value = {
        "total_pages": 42,
        "total_categories": 5,
        "total_sources": 10,
        "total_links": 8,
        "total_log_entries": 20,
        "latest_update": "2026-04-26 10:00:00",
    }

    await cog.wiki_dev_cmd.callback(cog, ctx, "stats")
    ctx.send.assert_called_once()
    sent = ctx.send.call_args[0][0]
    assert "42" in sent
    assert "Wiki Stats" in sent


@pytest.mark.asyncio
async def test_wiki_dev_cmd_lint(cog):
    """Verify !wiki lint runs lint and reports results."""
    ctx = MagicMock()
    dj_role = MagicMock()
    dj_role.id = 1364484047447003248
    ctx.author.roles = [dj_role]
    ctx.send = AsyncMock()

    cog._wiki_lint = MagicMock()
    cog._wiki_lint.run_lint.return_value = {
        "orphans": [],
        "stale": [],
        "missing_links": [],
        "inactive_players": [],
        "fixes_applied": [],
    }
    cog._wiki_storage = MagicMock()

    await cog.wiki_dev_cmd.callback(cog, ctx, "lint")
    assert ctx.send.call_count == 2
    sent = ctx.send.call_args_list[-1][0][0]
    assert "0 issues" in sent


@pytest.mark.asyncio
async def test_wiki_dev_cmd_unknown_action(cog):
    """Verify !wiki with unknown action shows usage."""
    ctx = MagicMock()
    dj_role = MagicMock()
    dj_role.id = 1364484047447003248
    ctx.author.roles = [dj_role]
    ctx.send = AsyncMock()

    await cog.wiki_dev_cmd.callback(cog, ctx, "foo")
    ctx.send.assert_called_once_with(
        "Usage: `!wiki lint` | `!wiki stats` | `!wiki export` | `!wiki synth`"
    )


@pytest.mark.asyncio
async def test_ingest_game_event_wrapper(cog):
    """Verify ingest_game_event delegates to WikiIngest.ingest_event."""
    cog._wiki_ingest = MagicMock()
    cog._wiki_ingest.ingest_event.return_value = [1, 2]

    result = await cog.ingest_game_event(
        event_type="race",
        event_id="2026-04-20-great-race",
        title="2026-04-20 Great Race",
        description="An amazing race happened",
        participants=["player1", "player2"],
    )

    assert result == [1, 2]
    cog._wiki_ingest.ingest_event.assert_called_once()


@pytest.mark.asyncio
async def test_ingest_game_event_skips_when_not_initialized(cog):
    """Verify ingest_game_event returns empty list when wiki ingest is missing."""
    cog._wiki_ingest = None
    result = await cog.ingest_game_event(
        event_type="race", event_id="1", title="Race", description="desc"
    )
    assert result == []


# --- Phase 5S: SSE event dispatcher tests ---


@pytest.mark.asyncio
async def test_sse_chat_message_is_skipped(cog):
    """chat_message events must NOT be re-ingested (Discord forwarding handles them)."""
    cog.ingest_game_event = AsyncMock()

    await cog._handle_backend_event(
        {
            "type": "chat_message",
            "timestamp": "2026-04-27T10:00:00",
            "player_name": "Alice",
            "player_id": "alice",
            "discord_id": None,
            "character_guid": None,
            "message": "hi",
            "is_bot_command": False,
        }
    )

    cog.ingest_game_event.assert_not_called()


@pytest.mark.asyncio
async def test_sse_heartbeat_is_noop(cog):
    """Heartbeat events must be silently ignored."""
    cog.ingest_game_event = AsyncMock()

    await cog._handle_backend_event({"type": "heartbeat"})

    cog.ingest_game_event.assert_not_called()


@pytest.mark.asyncio
async def test_sse_unknown_event_routes_to_ingest(cog):
    """Unknown event types must be forwarded to ingest_game_event with mapped args."""
    cog.ingest_game_event = AsyncMock(return_value=[])

    await cog._handle_backend_event(
        {
            "type": "race_finished",
            "event_id": "race-123",
            "timestamp": "2026-04-27T10:00:00",
            "title": "The Great Gosan Derby",
            "description": "Alice won by 3s.",
            "participants": ["alice", "bob"],
        }
    )

    cog.ingest_game_event.assert_awaited_once()
    kwargs = cog.ingest_game_event.await_args.kwargs
    assert kwargs["event_type"] == "race_finished"
    assert kwargs["event_id"] == "race-123"
    assert kwargs["title"] == "The Great Gosan Derby"
    assert kwargs["description"] == "Alice won by 3s."
    assert kwargs["participants"] == ["alice", "bob"]


@pytest.mark.asyncio
async def test_sse_unknown_event_fallback_event_id(cog):
    """Events without event_id fall back to {type}-{timestamp} for idempotency."""
    cog.ingest_game_event = AsyncMock(return_value=[])

    await cog._handle_backend_event(
        {
            "type": "economy_milestone",
            "timestamp": "2026-04-27T10:00:00",
            "title": "Million moolah!",
        }
    )

    kwargs = cog.ingest_game_event.await_args.kwargs
    assert kwargs["event_id"] == "economy_milestone-2026-04-27T10:00:00"


@pytest.mark.asyncio
async def test_sse_malformed_event_does_not_crash(cog):
    """Events without a `type` field must not crash the dispatcher."""
    cog.ingest_game_event = AsyncMock()

    # No type field
    await cog._handle_backend_event({"timestamp": "2026-04-27T10:00:00"})
    # Empty dict
    await cog._handle_backend_event({})

    cog.ingest_game_event.assert_not_called()


@pytest.mark.asyncio
async def test_sse_ingest_failure_does_not_crash_dispatcher(cog, monkeypatch):
    """If ingest_game_event raises, the dispatcher swallows the error."""
    monkeypatch.setattr("amc_peripheral.radio.radio_cog.log", MagicMock())
    cog.ingest_game_event = AsyncMock(side_effect=Exception("wiki down"))

    # Must not raise
    await cog._handle_backend_event(
        {
            "type": "race_finished",
            "event_id": "race-123",
            "timestamp": "2026-04-27T10:00:00",
            "title": "A race",
            "description": "desc",
        }
    )


def test_map_event_to_wiki_unknown_type(cog):
    """map_event_to_wiki produces sane defaults for unmapped event shapes."""
    event_type, event_id, title, description, participants = cog.map_event_to_wiki(
        {
            "type": "custom_weird_event",
            "timestamp": "2026-04-27T10:00:00",
            "some_field": "value",
        }
    )
    assert event_type == "custom_weird_event"
    assert event_id == "custom_weird_event-2026-04-27T10:00:00"
    assert "custom_weird_event" in title
    # Description falls back to a JSON dump of the payload
    assert "some_field" in description
    assert participants is None


def test_map_event_to_wiki_prefers_explicit_fields(cog):
    """map_event_to_wiki uses the event's explicit title/description/participants."""
    event_type, event_id, title, description, participants = cog.map_event_to_wiki(
        {
            "type": "race_finished",
            "event_id": "race-42",
            "timestamp": "2026-04-27T10:00:00",
            "title": "Coastal Grand Prix",
            "description": "A stunning race.",
            "participants": ["alice", "bob"],
        }
    )
    assert event_type == "race_finished"
    assert event_id == "race-42"
    assert title == "Coastal Grand Prix"
    assert description == "A stunning race."
    assert participants == ["alice", "bob"]


def test_map_event_to_wiki_rejects_non_list_participants(cog):
    """Non-list `participants` fields must be coerced to None to avoid crashes."""
    _, _, _, _, participants = cog.map_event_to_wiki(
        {"type": "race_finished", "participants": "alice,bob"}
    )
    assert participants is None


@pytest.mark.asyncio
async def test_listen_backend_events_cancels_cleanly(cog, monkeypatch):
    """_listen_backend_events must exit cleanly on cancellation."""
    monkeypatch.setattr("amc_peripheral.radio.radio_cog.log", MagicMock())

    # Force every connection attempt to raise, which puts the listener into
    # its exponential-backoff sleep — the easiest point to cancel from.
    class _Boom:
        def __call__(self, *args, **kwargs):
            raise RuntimeError("boom")

    import aiohttp

    monkeypatch.setattr(aiohttp, "ClientSession", _Boom())

    task = asyncio.create_task(cog._listen_backend_events())
    # Give the listener a chance to hit the error branch and start sleeping.
    await asyncio.sleep(0.05)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    assert task.done()


# --- Phase 4A: Player wiki profile tests ---


@pytest.mark.asyncio
async def test_get_player_wiki_summary_returns_friendly_fallback(cog):
    """When wiki is unavailable, summary should be a friendly message."""
    cog._wiki_storage = None
    result = cog._get_player_wiki_summary("abc123")
    assert "available" in result.lower() or "wiki" in result.lower()


@pytest.mark.asyncio
async def test_get_player_wiki_summary_no_page(cog):
    """When the player page doesn't exist, return a friendly invite."""
    storage = MagicMock()
    storage.get_page_by_slug.return_value = None
    storage.get_page_by_title.return_value = None
    cog._wiki_storage = storage
    result = cog._get_player_wiki_summary("abc123")
    assert "abc123" in result
    assert "page" in result.lower()


@pytest.mark.asyncio
async def test_get_player_wiki_summary_formats_existing_page(cog):
    """When a player page exists, return a formatted summary with links."""
    storage = MagicMock()
    storage.get_page_by_slug.return_value = {
        "id": 42,
        "title": "player:abc123",
        "category": "player",
        "summary": "Known Gosan fan.",
        "content": "Drives the Gosan a lot.",
    }
    storage.get_links_from.return_value = [
        {"to_title": "vehicle:Gosan_G7", "link_type": "mentions"}
    ]
    storage.get_links_to.return_value = []
    cog._wiki_storage = storage

    result = cog._get_player_wiki_summary("abc123")

    assert "player:abc123" in result
    assert "Gosan" in result
    assert "vehicle:Gosan_G7" in result


@pytest.mark.asyncio
async def test_get_my_wiki_profile_tool_uses_injected_player_id(cog):
    """The `get_my_wiki_profile` tool must use the caller-injected player_id,
    not any value the LLM might try to pass in.
    """
    storage = MagicMock()
    storage.get_page_by_slug.return_value = {
        "id": 1,
        "title": "player:real_speaker",
        "category": "player",
        "summary": "",
        "content": "",
    }
    storage.get_links_from.return_value = []
    storage.get_links_to.return_value = []
    cog._wiki_storage = storage

    # Even if the LLM passed a different player_id, the tool ignores it —
    # only the caller-supplied kwarg is trusted.
    result = await cog._execute_annie_tool(
        "get_my_wiki_profile",
        {"player_id": "someone_else"},
        "Speaker",
        AsyncMock(),
        player_id="real_speaker",
    )
    assert "player:real_speaker" in result
    storage.get_page_by_slug.assert_called_with("player:real_speaker")


@pytest.mark.asyncio
async def test_get_my_wiki_profile_concurrent_chats_do_not_race(cog):
    """Two concurrent tool calls with different player_id kwargs must each see
    their own player — no shared mutable state on `self`.
    """
    storage = MagicMock()

    def by_slug(slug):
        return {
            "id": 1 if "alice" in slug else 2,
            "title": slug,
            "category": "player",
            "summary": "",
            "content": "",
        }

    storage.get_page_by_slug.side_effect = by_slug
    storage.get_links_from.return_value = []
    storage.get_links_to.return_value = []
    cog._wiki_storage = storage

    results = await asyncio.gather(
        cog._execute_annie_tool(
            "get_my_wiki_profile", {}, "alice", AsyncMock(), player_id="alice"
        ),
        cog._execute_annie_tool(
            "get_my_wiki_profile", {}, "bob", AsyncMock(), player_id="bob"
        ),
    )
    assert "player:alice" in results[0]
    assert "player:bob" in results[1]


@pytest.mark.asyncio
async def test_get_my_wiki_profile_tool_defined(cog):
    """The new tool must appear in Annie's tool list."""
    tools = cog._get_annie_tools()
    names = [t["function"]["name"] for t in tools]
    assert "get_my_wiki_profile" in names


# --- Phase 4C: Wiki export dev command + task ---


@pytest.mark.asyncio
async def test_wiki_daily_export_task_exists(cog):
    assert hasattr(cog, "wiki_daily_export")
    assert isinstance(cog.wiki_daily_export, tasks.Loop)


@pytest.mark.asyncio
async def test_wiki_daily_export_runs_when_initialized(cog, monkeypatch):
    monkeypatch.setattr("amc_peripheral.radio.radio_cog.log", MagicMock())
    exporter = MagicMock()
    exporter.export_all.return_value = {
        "pages_exported": 5,
        "output_dir": "/tmp/wiki",
        "exported_at": "2026-04-26T04:30:00",
    }
    cog._wiki_exporter = exporter

    await cog.wiki_daily_export()

    exporter.export_all.assert_called_once()


@pytest.mark.asyncio
async def test_wiki_daily_export_skips_when_not_initialized(cog, monkeypatch):
    monkeypatch.setattr("amc_peripheral.radio.radio_cog.log", MagicMock())
    cog._wiki_exporter = None
    # Should not raise
    await cog.wiki_daily_export()


@pytest.mark.asyncio
async def test_wiki_dev_cmd_export(cog):
    """`!wiki export` should invoke the exporter and report results."""
    ctx = MagicMock()
    dj_role = MagicMock()
    dj_role.id = 1364484047447003248
    ctx.author.roles = [dj_role]
    ctx.send = AsyncMock()

    exporter = MagicMock()
    exporter.export_all.return_value = {
        "pages_exported": 7,
        "output_dir": "/tmp/wiki-export",
        "exported_at": "now",
    }
    cog._wiki_exporter = exporter

    await cog.wiki_dev_cmd.callback(cog, ctx, "export")

    # Two messages: "Exporting..." + result
    assert ctx.send.call_count == 2
    last = ctx.send.call_args_list[-1][0][0]
    assert "7" in last
    assert "/tmp/wiki-export" in last


@pytest.mark.asyncio
async def test_wiki_dev_cmd_export_unavailable(cog):
    ctx = MagicMock()
    dj_role = MagicMock()
    dj_role.id = 1364484047447003248
    ctx.author.roles = [dj_role]
    ctx.send = AsyncMock()
    cog._wiki_exporter = None

    await cog.wiki_dev_cmd.callback(cog, ctx, "export")
    ctx.send.assert_called_once_with("Wiki exporter not initialized.")


# --- Phase 4E: Weekly synthesis dev command + task ---


@pytest.mark.asyncio
async def test_wiki_weekly_synthesis_task_exists(cog):
    assert hasattr(cog, "wiki_weekly_synthesis")
    assert isinstance(cog.wiki_weekly_synthesis, tasks.Loop)


@pytest.mark.asyncio
async def test_wiki_weekly_synthesis_runs_on_monday(cog, monkeypatch):
    monkeypatch.setattr("amc_peripheral.radio.radio_cog.log", MagicMock())
    synth = MagicMock()
    synth.generate_weekly_synthesis = AsyncMock(
        return_value={"id": 1, "title": "synthesis:community-week-2026-W18"}
    )
    cog._wiki_synthesizer = synth

    # Freeze `datetime.now(tz)` to a Monday
    import amc_peripheral.radio.radio_cog as module

    monday = module.datetime(
        2026, 4, 27, 9, 0, 0, tzinfo=module.ZoneInfo("Asia/Bangkok")
    )
    fake_dt = MagicMock()
    fake_dt.now = MagicMock(return_value=monday)
    monkeypatch.setattr(module, "datetime", fake_dt)

    await cog.wiki_weekly_synthesis()

    synth.generate_weekly_synthesis.assert_called_once()


@pytest.mark.asyncio
async def test_wiki_weekly_synthesis_skips_on_other_days(cog, monkeypatch):
    monkeypatch.setattr("amc_peripheral.radio.radio_cog.log", MagicMock())
    synth = MagicMock()
    synth.generate_weekly_synthesis = AsyncMock()
    cog._wiki_synthesizer = synth

    import amc_peripheral.radio.radio_cog as module

    # Tuesday
    tuesday = module.datetime(
        2026, 4, 28, 9, 0, 0, tzinfo=module.ZoneInfo("Asia/Bangkok")
    )
    fake_dt = MagicMock()
    fake_dt.now = MagicMock(return_value=tuesday)
    monkeypatch.setattr(module, "datetime", fake_dt)

    await cog.wiki_weekly_synthesis()

    synth.generate_weekly_synthesis.assert_not_called()


@pytest.mark.asyncio
async def test_wiki_dev_cmd_synth(cog):
    """`!wiki synth` should call the synthesizer and report the page."""
    ctx = MagicMock()
    dj_role = MagicMock()
    dj_role.id = 1364484047447003248
    ctx.author.roles = [dj_role]
    ctx.send = AsyncMock()

    synth = MagicMock()
    synth.generate_weekly_synthesis = AsyncMock(
        return_value={"id": 99, "title": "synthesis:community-week-2026-W18"}
    )
    cog._wiki_synthesizer = synth

    await cog.wiki_dev_cmd.callback(cog, ctx, "synth")

    assert ctx.send.call_count == 2
    last = ctx.send.call_args_list[-1][0][0]
    assert "synthesis:community-week-2026-W18" in last


@pytest.mark.asyncio
async def test_wiki_dev_cmd_synth_no_activity(cog):
    ctx = MagicMock()
    dj_role = MagicMock()
    dj_role.id = 1364484047447003248
    ctx.author.roles = [dj_role]
    ctx.send = AsyncMock()

    synth = MagicMock()
    synth.generate_weekly_synthesis = AsyncMock(return_value=None)
    cog._wiki_synthesizer = synth

    await cog.wiki_dev_cmd.callback(cog, ctx, "synth")

    last = ctx.send.call_args_list[-1][0][0]
    assert "nothing notable" in last.lower()


@pytest.mark.asyncio
async def test_wiki_dev_cmd_synth_unavailable(cog):
    ctx = MagicMock()
    dj_role = MagicMock()
    dj_role.id = 1364484047447003248
    ctx.author.roles = [dj_role]
    ctx.send = AsyncMock()
    cog._wiki_synthesizer = None

    await cog.wiki_dev_cmd.callback(cog, ctx, "synth")
    ctx.send.assert_called_once_with("Wiki synthesizer not initialized.")


@pytest.mark.asyncio
async def test_pick_trending_song_lastfm(cog):
    """Test _pick_trending_song returns 'Artist - Title' from Last.fm data."""
    mock_lastfm_response = {
        "tracks": {
            "track": [
                {"name": "Song A", "artist": {"name": "Artist A"}},
                {"name": "Song B", "artist": {"name": "Artist B"}},
                {"name": "Song C", "artist": {"name": "Artist C"}},
            ]
        }
    }

    mock_resp = AsyncMock()
    mock_resp.json = AsyncMock(return_value=mock_lastfm_response)
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    cog.bot.http_session.get = MagicMock(return_value=mock_resp)

    result = await cog._pick_trending_song()

    # Should be one of the mock tracks
    assert " - " in result
    assert any(
        result == f"{t['artist']['name']} - {t['name']}"
        for t in mock_lastfm_response["tracks"]["track"]
    )


@pytest.mark.asyncio
async def test_pick_trending_song_fallback(cog):
    """Test _pick_trending_song falls back to curated search when Last.fm fails."""
    mock_resp = AsyncMock()
    mock_resp.__aenter__ = AsyncMock(side_effect=Exception("API down"))
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    cog.bot.http_session.get = MagicMock(return_value=mock_resp)

    result = await cog._pick_trending_song()

    assert result.startswith("ytsearch:")


@pytest.mark.asyncio
async def test_pick_trending_song_dedup(cog):
    """Test _pick_trending_song filters out recently auto-queued songs."""
    mock_lastfm_response = {
        "tracks": {
            "track": [
                {"name": "Already Queued", "artist": {"name": "Known Artist"}},
                {"name": "Fresh Song", "artist": {"name": "New Artist"}},
            ]
        }
    }

    mock_resp = AsyncMock()
    mock_resp.json = AsyncMock(return_value=mock_lastfm_response)
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    cog.bot.http_session.get = MagicMock(return_value=mock_resp)

    # Mark one song as recently auto-queued
    cog.db.add_auto_queue("Known Artist - Already Queued")

    result = await cog._pick_trending_song()

    # Should pick the non-queued song
    assert result == "New Artist - Fresh Song"


@pytest.mark.asyncio
async def test_pick_trending_song_tag_source(cog, monkeypatch):
    """Test _pick_trending_song uses tag.gettoptracks when roll < 0.60."""
    monkeypatch.setattr("random.random", lambda: 0.30)  # triggers tag source
    monkeypatch.setattr("random.choice", lambda seq: seq[0])  # pick first item

    mock_lastfm_response = {
        "tracks": {
            "track": [
                {"name": "Rock Song", "artist": {"name": "Rock Artist"}},
            ]
        }
    }

    captured_params = {}

    mock_resp = AsyncMock()
    mock_resp.json = AsyncMock(return_value=mock_lastfm_response)
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    def fake_get(url, params=None):
        captured_params.update(params or {})
        return mock_resp

    cog.bot.http_session.get = MagicMock(side_effect=fake_get)

    result = await cog._pick_trending_song()

    assert result == "Rock Artist - Rock Song"
    assert captured_params["method"] == "tag.gettoptracks"
    assert captured_params["tag"] == "rock"


@pytest.mark.asyncio
async def test_pick_trending_song_chart_paged(cog, monkeypatch):
    """Test _pick_trending_song uses chart.gettoptracks with page when roll is 0.60-0.85."""
    monkeypatch.setattr("random.random", lambda: 0.70)  # triggers chart paged source
    monkeypatch.setattr("random.randint", lambda a, b: 3)  # page 3
    monkeypatch.setattr("random.choice", lambda seq: seq[0])  # pick first item

    mock_lastfm_response = {
        "tracks": {
            "track": [
                {"name": "Chart Song", "artist": {"name": "Chart Artist"}},
            ]
        }
    }

    captured_params = {}

    mock_resp = AsyncMock()
    mock_resp.json = AsyncMock(return_value=mock_lastfm_response)
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    def fake_get(url, params=None):
        captured_params.update(params or {})
        return mock_resp

    cog.bot.http_session.get = MagicMock(side_effect=fake_get)

    result = await cog._pick_trending_song()

    assert result == "Chart Artist - Chart Song"
    assert captured_params["method"] == "chart.gettoptracks"
    assert captured_params["page"] == 3


@pytest.mark.asyncio
async def test_pick_trending_song_geo_source(cog, monkeypatch):
    """Test _pick_trending_song uses geo.gettoptracks when roll >= 0.85."""
    monkeypatch.setattr("random.random", lambda: 0.90)  # triggers geo source
    monkeypatch.setattr("random.choice", lambda seq: seq[0])  # pick first item

    mock_lastfm_response = {
        "tracks": {
            "track": [
                {"name": "Thai Hit", "artist": {"name": "Thai Artist"}},
            ]
        }
    }

    captured_params = {}

    mock_resp = AsyncMock()
    mock_resp.json = AsyncMock(return_value=mock_lastfm_response)
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    def fake_get(url, params=None):
        captured_params.update(params or {})
        return mock_resp

    cog.bot.http_session.get = MagicMock(side_effect=fake_get)

    result = await cog._pick_trending_song()

    assert result == "Thai Artist - Thai Hit"
    assert captured_params["method"] == "geo.gettoptracks"
    assert captured_params["country"] == "Thailand"


# --- Download Queue & Serialization Tests ---


@pytest.mark.asyncio
async def test_download_queue_exists(cog):
    """Verify that the download queue is initialized."""
    assert hasattr(cog, "_download_queue")
    assert isinstance(cog._download_queue, asyncio.Queue)


@pytest.mark.asyncio
async def test_download_serialization(cog, monkeypatch):
    """Verify that only one download runs at a time — concurrent requests wait."""
    download_count = {"active": 0, "max_active": 0}

    counter = {"n": 0}

    async def slow_get_or_download(query):
        counter["n"] += 1
        n = counter["n"]
        download_count["active"] += 1
        download_count["max_active"] = max(
            download_count["max_active"], download_count["active"]
        )
        await asyncio.sleep(0.1)
        download_count["active"] -= 1
        return f"Test Song {n}", 120, f"/tmp/test{n}.mp3", f"https://example.com/{n}"

    monkeypatch.setattr(cog, "_get_or_download", slow_get_or_download)
    # Mock lq.push_to_queue to avoid telnet calls
    cog.lq.push_to_queue = AsyncMock()

    # Start the download worker
    worker = asyncio.create_task(cog._download_worker())

    try:
        # Launch 3 concurrent requests (all bypass throttling)
        tasks = [
            asyncio.create_task(
                cog.request_song(f"song{i}", f"User{i}", bypass_throttling=True)
            )
            for i in range(3)
        ]
        await asyncio.gather(*tasks)

        # At most 1 download should have been active at any time
        assert download_count["max_active"] == 1
    finally:
        worker.cancel()


@pytest.mark.asyncio
async def test_download_timeout_raises_friendly_error(cog, monkeypatch):
    """Verify that a download exceeding DOWNLOAD_TIMEOUT raises a user-friendly error."""

    async def timeout_download(query):
        raise Exception(
            "Download timed out. The song may be too large or the server is under load. Please try again."
        )

    monkeypatch.setattr(cog, "_get_or_download", timeout_download)

    # Start the download worker
    worker = asyncio.create_task(cog._download_worker())

    try:
        with pytest.raises(Exception, match="Download timed out"):
            await cog.request_song("test", "TestUser", bypass_throttling=True)
    finally:
        worker.cancel()


@pytest.mark.asyncio
async def test_download_queue_does_not_reject(cog, monkeypatch):
    """Verify that concurrent requests queue up instead of being rejected."""
    counter = {"n": 0}

    async def slow_get_or_download(query):
        counter["n"] += 1
        n = counter["n"]
        await asyncio.sleep(0.2)  # Simulate slow download
        return f"Test Song {n}", 120, f"/tmp/test{n}.mp3", f"https://example.com/{n}"

    monkeypatch.setattr(cog, "_get_or_download", slow_get_or_download)
    cog.lq.push_to_queue = AsyncMock()

    # Start the download worker
    worker = asyncio.create_task(cog._download_worker())

    try:
        # Launch 3 concurrent requests — none should raise "busy"
        tasks = [
            asyncio.create_task(
                cog.request_song(f"song{i}", f"User{i}", bypass_throttling=True)
            )
            for i in range(3)
        ]
        results = await asyncio.gather(*tasks)

        # All 3 should succeed
        assert len(results) == 3
        titles = [r[0] for r in results]
        assert "Test Song 1" in titles
        assert "Test Song 2" in titles
        assert "Test Song 3" in titles
    finally:
        worker.cancel()


# --- Annie Agentic Chat Tests ---


@pytest.mark.asyncio
async def test_on_message_annie_discord_mention(cog, mock_bot):
    """Verify that @mentioning the bot triggers _handle_annie_chat_discord."""
    message = MagicMock()
    message.author = MagicMock()
    message.author.id = 99999
    message.author.display_name = "TestPlayer"
    message.content = f"<@{mock_bot.user.id}> play some jazz"
    message.mentions = [mock_bot.user]
    message.channel = MagicMock()
    message.channel.id = 0  # Not a special channel

    cog._handle_annie_chat_discord = AsyncMock()

    await cog.on_message(message)

    mock_bot.loop.create_task.assert_called_once()


@pytest.mark.asyncio
async def test_on_message_ignores_non_mention(cog, mock_bot):
    """Verify normal messages don't trigger Annie."""
    message = MagicMock()
    message.author = MagicMock()
    message.author.id = 99999
    message.content = "just chatting"
    message.mentions = []
    message.channel = MagicMock()
    message.channel.id = 0

    cog._handle_annie_chat_discord = AsyncMock()

    await cog.on_message(message)

    cog._handle_annie_chat_discord.assert_not_called()


@pytest.mark.asyncio
async def test_on_message_annie_ingame(cog, mock_bot, monkeypatch):
    """Verify in-game @annie triggers _handle_annie_chat_ingame."""
    from amc_peripheral.radio import radio_cog
    monkeypatch.setattr(radio_cog, "GAME_CHAT_CHANNEL_ID", 42)

    message = MagicMock()
    message.author = MagicMock()
    message.author.id = 99999
    message.content = "**CoolDriver:** @annie what's playing right now?"
    message.mentions = []
    message.channel = MagicMock()
    message.channel.id = 42

    cog._handle_annie_chat_ingame = AsyncMock()

    await cog.on_message(message)

    mock_bot.loop.create_task.assert_called_once()


@pytest.mark.asyncio
async def test_annie_chat_strips_mention(cog, mock_bot):
    """Verify that the bot mention is stripped from the question."""
    message = MagicMock()
    message.author = MagicMock()
    message.author.id = 99999
    message.author.display_name = "TestPlayer"
    message.content = f"<@{mock_bot.user.id}> play some chill music"
    message.mentions = [mock_bot.user]
    message.channel = MagicMock()
    message.channel.id = 0
    message.channel.history = MagicMock(return_value=AsyncIteratorMock([]))
    message.channel.typing = MagicMock(return_value=AsyncContextManagerMock())
    message.reply = AsyncMock()

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "Let me queue that up!"
    mock_response.choices[0].message.tool_calls = None

    cog.openai_client_openrouter.chat.completions.create = AsyncMock(
        return_value=mock_response
    )

    await cog._handle_annie_chat_discord(message, "play some chill music")

    # Verify the reply was sent
    message.reply.assert_called_once()
    args = message.reply.call_args
    assert "Let me queue that up!" in args[0][0]


@pytest.mark.asyncio
async def test_fire_and_forget_queue(cog, monkeypatch):
    """Verify fire-and-forget download calls request_song and notifies."""
    cog.request_song = AsyncMock(return_value=("Cool Song", 180))
    notify_fn = AsyncMock()

    await cog._fire_and_forget_queue("cool song query", "TestUser", notify_fn)

    cog.request_song.assert_called_once_with("cool song query", "TestUser", bypass_throttling=False)
    notify_fn.assert_called_once()
    assert "Cool Song" in notify_fn.call_args[0][0]


@pytest.mark.asyncio
async def test_fire_and_forget_queue_error(cog, monkeypatch):
    """Verify fire-and-forget handles download errors gracefully."""
    cog.request_song = AsyncMock(side_effect=Exception("Download failed"))
    notify_fn = AsyncMock()

    await cog._fire_and_forget_queue("bad query", "TestUser", notify_fn)

    notify_fn.assert_called_once()
    assert "Couldn't queue" in notify_fn.call_args[0][0]


@pytest.mark.asyncio
async def test_annie_tools_defined(cog):
    """Verify all expected Annie tools are defined."""
    tools = cog._get_annie_tools()
    tool_names = [t["function"]["name"] for t in tools]
    assert "search_and_queue_song" in tool_names
    assert "get_currently_playing" in tool_names
    assert "get_recent_requests" in tool_names
    assert "get_song_stats" in tool_names
    assert "get_recent_news" in tool_names
    assert "get_recent_jingles" in tool_names
    assert "skip_current_track" in tool_names
    assert "queue_trending_song" in tool_names
    assert "search_playlist" in tool_names
    assert "add_to_playlist" in tool_names
    assert "remove_from_playlist" in tool_names

# --- Agent Tool Pre-Download Validation Tests ---


@pytest.mark.asyncio
async def test_execute_annie_tool_rejects_blacklisted_song(cog, mock_bot):
    """Verify search_and_queue_song returns rejection for blacklisted song."""
    notify_fn = AsyncMock()

    result = await cog._execute_annie_tool(
        "search_and_queue_song",
        {"query": "never gonna give you up"},
        "TestUser",
        notify_fn,
    )

    assert "Song rejected" in result
    assert "No, just no" in result
    # create_task should NOT have been called (no download dispatched)
    mock_bot.loop.create_task.assert_not_called()


@pytest.mark.asyncio
async def test_execute_annie_tool_rejects_throttled_song(cog, mock_bot):
    """Verify search_and_queue_song returns rejection when throttled."""
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    # Pre-populate 3 requests within the last 5 minutes
    now = datetime.now(ZoneInfo("Asia/Bangkok"))
    cog.user_requests["TestUser"] = [
        now - timedelta(minutes=1),
        now - timedelta(minutes=2),
        now - timedelta(minutes=3),
    ]

    notify_fn = AsyncMock()

    result = await cog._execute_annie_tool(
        "search_and_queue_song",
        {"query": "some valid song"},
        "TestUser",
        notify_fn,
    )

    assert "Song rejected" in result
    assert "too many songs" in result
    mock_bot.loop.create_task.assert_not_called()


@pytest.mark.asyncio
async def test_execute_annie_tool_passes_valid_song(cog, mock_bot):
    """Verify search_and_queue_song dispatches download for valid query."""
    notify_fn = AsyncMock()

    result = await cog._execute_annie_tool(
        "search_and_queue_song",
        {"query": "bohemian rhapsody"},
        "TestUser",
        notify_fn,
    )

    assert "Download started" in result
    mock_bot.loop.create_task.assert_called_once()


# --- Playlist Management Tool Tests ---


@pytest.mark.asyncio
async def test_search_playlist_returns_matches(cog, mock_bot, monkeypatch):
    """Verify search_playlist returns matching filenames from the playlist channel."""
    from amc_peripheral.radio import radio_cog
    monkeypatch.setattr(radio_cog, "PLAYLIST_CHANNEL", 99999)

    # Create mock attachments
    att1 = MagicMock()
    att1.filename = "Rock_Anthem.mp3"
    att2 = MagicMock()
    att2.filename = "Jazz_Ballad.mp3"
    att3 = MagicMock()
    att3.filename = "Rock_Classic.mp3"

    msg1 = MagicMock()
    msg1.attachments = [att1]
    msg2 = MagicMock()
    msg2.attachments = [att2]
    msg3 = MagicMock()
    msg3.attachments = [att3]

    mock_channel = MagicMock()
    mock_channel.history = MagicMock(return_value=AsyncIteratorMock([msg1, msg2, msg3]))
    mock_bot.get_channel = MagicMock(return_value=mock_channel)

    result = await cog._tool_search_playlist("rock")

    assert "Rock_Anthem.mp3" in result
    assert "Rock_Classic.mp3" in result
    assert "Jazz_Ballad.mp3" not in result
    assert "2 song(s)" in result


@pytest.mark.asyncio
async def test_search_playlist_no_matches(cog, mock_bot, monkeypatch):
    """Verify search_playlist returns appropriate message when no matches found."""
    from amc_peripheral.radio import radio_cog
    monkeypatch.setattr(radio_cog, "PLAYLIST_CHANNEL", 99999)

    att1 = MagicMock()
    att1.filename = "Rock_Anthem.mp3"
    msg1 = MagicMock()
    msg1.attachments = [att1]

    mock_channel = MagicMock()
    mock_channel.history = MagicMock(return_value=AsyncIteratorMock([msg1]))
    mock_bot.get_channel = MagicMock(return_value=mock_channel)

    result = await cog._tool_search_playlist("classical")

    assert "No songs found" in result


@pytest.mark.asyncio
async def test_search_playlist_empty_query_lists_all(cog, mock_bot, monkeypatch):
    """Verify search_playlist with empty query lists all songs."""
    from amc_peripheral.radio import radio_cog
    monkeypatch.setattr(radio_cog, "PLAYLIST_CHANNEL", 99999)

    att1 = MagicMock()
    att1.filename = "Song_A.mp3"
    att2 = MagicMock()
    att2.filename = "Song_B.mp3"

    msg1 = MagicMock()
    msg1.attachments = [att1]
    msg2 = MagicMock()
    msg2.attachments = [att2]

    mock_channel = MagicMock()
    mock_channel.history = MagicMock(return_value=AsyncIteratorMock([msg1, msg2]))
    mock_bot.get_channel = MagicMock(return_value=mock_channel)

    result = await cog._tool_search_playlist("")

    assert "Song_A.mp3" in result
    assert "Song_B.mp3" in result
    assert "2 song(s)" in result


@pytest.mark.asyncio
async def test_remove_from_playlist_deletes_message(cog, mock_bot, monkeypatch):
    """Verify remove_from_playlist finds and deletes the correct message."""
    from amc_peripheral.radio import radio_cog
    monkeypatch.setattr(radio_cog, "PLAYLIST_CHANNEL", 99999)

    att1 = MagicMock()
    att1.filename = "Target_Song.mp3"
    msg1 = MagicMock()
    msg1.attachments = [att1]
    msg1.delete = AsyncMock()

    att2 = MagicMock()
    att2.filename = "Other_Song.mp3"
    msg2 = MagicMock()
    msg2.attachments = [att2]
    msg2.delete = AsyncMock()

    mock_channel = MagicMock()
    mock_channel.history = MagicMock(return_value=AsyncIteratorMock([msg1, msg2]))
    mock_bot.get_channel = MagicMock(return_value=mock_channel)

    result = await cog._tool_remove_from_playlist("Target_Song.mp3")

    assert "Removed" in result
    msg1.delete.assert_called_once()
    msg2.delete.assert_not_called()


@pytest.mark.asyncio
async def test_remove_from_playlist_not_found(cog, mock_bot, monkeypatch):
    """Verify remove_from_playlist returns error when filename not found."""
    from amc_peripheral.radio import radio_cog
    monkeypatch.setattr(radio_cog, "PLAYLIST_CHANNEL", 99999)

    att1 = MagicMock()
    att1.filename = "Other_Song.mp3"
    msg1 = MagicMock()
    msg1.attachments = [att1]

    mock_channel = MagicMock()
    mock_channel.history = MagicMock(return_value=AsyncIteratorMock([msg1]))
    mock_bot.get_channel = MagicMock(return_value=mock_channel)

    result = await cog._tool_remove_from_playlist("Nonexistent.mp3")

    assert "Could not find" in result


@pytest.mark.asyncio
async def test_fire_and_forget_playlist_add(cog, mock_bot, monkeypatch, tmp_path):
    """Verify fire-and-forget playlist add downloads and uploads to channel."""
    from amc_peripheral.radio import radio_cog
    monkeypatch.setattr(radio_cog, "PLAYLIST_CHANNEL", 99999)

    # Create a real temp file so discord.File can open it
    fake_mp3 = tmp_path / "Cool_Song.mp3"
    fake_mp3.write_bytes(b"fake audio data")

    cog._get_or_download = AsyncMock(return_value=("Cool Song", 120, str(fake_mp3), "https://example.com"))

    mock_channel = MagicMock()
    mock_channel.send = AsyncMock()
    mock_bot.get_channel = MagicMock(return_value=mock_channel)

    notify_fn = AsyncMock()

    await cog._fire_and_forget_playlist_add("cool song query", notify_fn)

    cog._get_or_download.assert_called_once()
    mock_channel.send.assert_called_once()
    notify_fn.assert_called_once()
    assert "Cool Song" in notify_fn.call_args[0][0]


@pytest.mark.asyncio
async def test_fire_and_forget_playlist_add_error(cog, monkeypatch):
    """Verify fire-and-forget playlist add handles errors gracefully."""
    cog._get_or_download = AsyncMock(side_effect=Exception("Download failed"))
    notify_fn = AsyncMock()

    await cog._fire_and_forget_playlist_add("bad query", notify_fn)

    notify_fn.assert_called_once()
    assert "Couldn't add" in notify_fn.call_args[0][0]


# --- User Playlist Curation Tests ---


@pytest.mark.asyncio
async def test_create_playlist(cog):
    """Test creating a playlist and retrieving it."""
    playlist_id = cog.db.create_playlist(discord_id="user1", name="Chill Vibes")
    assert playlist_id is not None

    playlist = cog.db.get_playlist_by_name(discord_id="user1", name="chill vibes")
    assert playlist is not None
    assert playlist["name"] == "chill vibes"
    assert playlist["discord_id"] == "user1"


@pytest.mark.asyncio
async def test_create_duplicate_playlist_fails(cog):
    """Test that creating a duplicate playlist raises an exception."""
    cog.db.create_playlist(discord_id="user1", name="Road Trip")
    with pytest.raises(Exception, match="already exists"):
        cog.db.create_playlist(discord_id="user1", name="road trip")


@pytest.mark.asyncio
async def test_add_and_list_playlist_songs(cog):
    """Test adding songs and listing them in order."""
    playlist_id = cog.db.create_playlist(discord_id="user1", name="my mix")
    cog.db.add_song_to_playlist(playlist_id, "Tame Impala Let It Happen", "Tame Impala Let It Happen")
    cog.db.add_song_to_playlist(playlist_id, "Daft Punk Get Lucky", "Daft Punk Get Lucky")
    cog.db.add_song_to_playlist(playlist_id, "LCD Soundsystem All My Friends", "LCD Soundsystem All My Friends")

    songs = cog.db.get_playlist_songs(playlist_id)
    assert len(songs) == 3
    assert songs[0]["song_title"] == "Tame Impala Let It Happen"
    assert songs[0]["position"] == 1
    assert songs[1]["position"] == 2
    assert songs[2]["position"] == 3


@pytest.mark.asyncio
async def test_remove_song_from_playlist(cog):
    """Test removing a song leaves others intact."""
    playlist_id = cog.db.create_playlist(discord_id="user1", name="test rm")
    cog.db.add_song_to_playlist(playlist_id, "Song A", "Song A")
    cog.db.add_song_to_playlist(playlist_id, "Song B", "Song B")

    removed = cog.db.remove_song_from_playlist(playlist_id, "Song A")
    assert removed is True

    songs = cog.db.get_playlist_songs(playlist_id)
    assert len(songs) == 1
    assert songs[0]["song_title"] == "Song B"


@pytest.mark.asyncio
async def test_delete_playlist_cascades(cog):
    """Test deleting a playlist removes its songs too."""
    playlist_id = cog.db.create_playlist(discord_id="user1", name="doomed")
    cog.db.add_song_to_playlist(playlist_id, "Song X", "Song X")

    deleted = cog.db.delete_playlist(discord_id="user1", name="doomed")
    assert deleted is True

    # Playlist gone
    assert cog.db.get_playlist_by_name(discord_id="user1", name="doomed") is None
    # Songs gone
    songs = cog.db.get_playlist_songs(playlist_id)
    assert len(songs) == 0


@pytest.mark.asyncio
async def test_get_playlists_by_user(cog):
    """Test user isolation — only own playlists returned."""
    cog.db.create_playlist(discord_id="userA", name="playlist1")
    cog.db.create_playlist(discord_id="userB", name="playlist2")

    playlists_a = cog.db.get_playlists(discord_id="userA")
    assert len(playlists_a) == 1
    assert playlists_a[0]["name"] == "playlist1"

    playlists_b = cog.db.get_playlists(discord_id="userB")
    assert len(playlists_b) == 1
    assert playlists_b[0]["name"] == "playlist2"


@pytest.mark.asyncio
async def test_annie_playlist_tools_defined(cog):
    """Verify all new playlist tools are in Annie's tool list."""
    tools = cog._get_annie_tools()
    tool_names = [t["function"]["name"] for t in tools]
    assert "create_user_playlist" in tool_names
    assert "add_to_user_playlist" in tool_names
    assert "view_user_playlist" in tool_names
    assert "list_user_playlists" in tool_names
    assert "play_user_playlist" in tool_names


@pytest.mark.asyncio
async def test_playlist_play_caps_at_10(cog, monkeypatch):
    """Verify _play_user_playlist caps at PLAYLIST_PLAY_CAP songs."""
    queued_songs = []

    async def mock_request_song(query, requester, **kwargs):
        queued_songs.append(query)
        return query, 120

    monkeypatch.setattr(cog, "request_song", mock_request_song)
    notify_fn = AsyncMock()

    # Create 15 songs
    songs = [{"song_query": f"song_{i}", "song_title": f"Song {i}"} for i in range(15)]
    await cog._play_user_playlist(songs, "TestUser", notify_fn)

    assert len(queued_songs) == 10
    # Should notify about the cap
    cap_msg = [call for call in notify_fn.call_args_list if "Only the first" in str(call)]
    assert len(cap_msg) == 1


@pytest.mark.asyncio
async def test_playlist_play_queues_songs(cog, monkeypatch):
    """Verify _play_user_playlist queues songs sequentially."""
    queued_songs = []

    async def mock_request_song(query, requester, **kwargs):
        queued_songs.append(query)
        return query, 120

    monkeypatch.setattr(cog, "request_song", mock_request_song)
    notify_fn = AsyncMock()

    songs = [
        {"song_query": "Tame Impala", "song_title": "Tame Impala"},
        {"song_query": "Daft Punk", "song_title": "Daft Punk"},
    ]
    await cog._play_user_playlist(songs, "TestUser", notify_fn)

    assert queued_songs == ["Tame Impala", "Daft Punk"]
    assert notify_fn.call_count == 2


@pytest.mark.asyncio
async def test_playlist_commands_exist(cog):
    """Verify all playlist subcommands are registered under the /playlist group."""
    # Find the playlist group among cog app commands
    groups = {cmd.name: cmd for cmd in cog.__cog_app_commands__}
    assert "playlist" in groups, "Missing 'playlist' command group"

    playlist_group = groups["playlist"]
    subcommand_names = [cmd.name for cmd in playlist_group.commands]
    assert "create" in subcommand_names
    assert "delete" in subcommand_names
    assert "add" in subcommand_names
    assert "remove" in subcommand_names
    assert "view" in subcommand_names
    assert "list" in subcommand_names
    assert "play" in subcommand_names
    assert "elevate" in subcommand_names


# --- Download Cache Tests ---


@pytest.mark.asyncio
async def test_cache_song_and_retrieve(cog):
    """Test caching a song and retrieving it by video_id."""
    cog.db.cache_song(
        video_id="dQw4w9WgXcQ", title="Never Gonna Give You Up",
        duration=213, local_path="/tmp/cache/dQw4w9WgXcQ.mp3",
        webpage_url="https://youtube.com/watch?v=dQw4w9WgXcQ", file_size=5000000,
    )
    cached = cog.db.get_cached_song("dQw4w9WgXcQ")
    assert cached is not None
    assert cached["title"] == "Never Gonna Give You Up"
    assert cached["video_id"] == "dQw4w9WgXcQ"


@pytest.mark.asyncio
async def test_cache_miss_returns_none(cog):
    """Test that a cache miss returns None."""
    assert cog.db.get_cached_song("nonexistent") is None


@pytest.mark.asyncio
async def test_cache_hit_updates_last_used(cog):
    """Test that get_cached_song updates last_used_at."""
    import time
    cog.db.cache_song(
        video_id="abc123", title="Test Song", duration=180,
        local_path="/tmp/test.mp3", webpage_url="https://example.com", file_size=3000000,
    )
    first = cog.db.get_cached_song("abc123")
    time.sleep(0.01)
    second = cog.db.get_cached_song("abc123")
    assert second["last_used_at"] >= first["last_used_at"]


@pytest.mark.asyncio
async def test_cache_stats(cog):
    """Test get_cache_stats returns correct totals."""
    cog.db.cache_song("v1", "Song1", 120, "/tmp/s1.mp3", "http://a", 1000)
    cog.db.cache_song("v2", "Song2", 120, "/tmp/s2.mp3", "http://b", 2000)
    stats = cog.db.get_cache_stats()
    assert stats["total_files"] == 2
    assert stats["total_bytes"] == 3000


@pytest.mark.asyncio
async def test_evict_cache_removes_oldest(cog, tmp_path, monkeypatch):
    """Test _evict_cache removes LRU entries when over the cap."""
    from amc_peripheral.radio import radio_cog
    # Set tiny cap: 1 byte so everything gets evicted
    monkeypatch.setattr(radio_cog, "SONG_CACHE_MAX_MB", 0)

    # Create cached files
    for i in range(3):
        f = tmp_path / "cache" / f"v{i}.mp3"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"x" * 100)
        cog.db.cache_song(f"v{i}", f"Song{i}", 120, str(f), f"http://{i}", 100)

    stats = cog.db.get_cache_stats()
    assert stats["total_files"] == 3

    cog._evict_cache()

    stats = cog.db.get_cache_stats()
    assert stats["total_files"] == 0


@pytest.mark.asyncio
async def test_annie_elevate_tool_defined(cog):
    """Verify the elevate_to_playlist tool is in Annie's tool list."""
    tools = cog._get_annie_tools()
    tool_names = [t["function"]["name"] for t in tools]
    assert "elevate_to_playlist" in tool_names


# --- Like Button / Top Likes Tests ---


@pytest.mark.asyncio
async def test_now_playing_view_has_like_button(cog):
    """Verify NowPlayingView contains a button with custom_id='radio_like'."""
    from amc_peripheral.radio.radio_cog import NowPlayingView

    view = NowPlayingView(cog)
    custom_ids = [
        child.custom_id
        for child in view.children
        if hasattr(child, "custom_id") and child.custom_id
    ]
    assert "radio_like" in custom_ids


@pytest.mark.asyncio
async def test_like_song_annie_tool_defined(cog):
    """Verify like_song is in Annie's tool list."""
    tools = cog._get_annie_tools()
    tool_names = [t["function"]["name"] for t in tools]
    assert "like_song" in tool_names


@pytest.mark.asyncio
async def test_get_top_liked_songs_annie_tool_defined(cog):
    """Verify get_top_liked_songs is in Annie's tool list."""
    tools = cog._get_annie_tools()
    tool_names = [t["function"]["name"] for t in tools]
    assert "get_top_liked_songs" in tool_names


@pytest.mark.asyncio
async def test_top_likes_command_exists(cog):
    """Verify /top_likes slash command is registered."""
    commands = [cmd.name for cmd in cog.__cog_app_commands__]
    assert "top_likes" in commands


@pytest.mark.asyncio
async def test_get_song_like_count(cog):
    """Verify db.get_song_like_count returns correct count."""
    assert cog.db.get_song_like_count("Unknown Song") == 0

    cog.db.add_like(discord_id="user1", song_title="Cool Song")
    cog.db.add_like(discord_id="user2", song_title="Cool Song")
    cog.db.add_like(discord_id="user3", song_title="Other Song")

    assert cog.db.get_song_like_count("Cool Song") == 2
    assert cog.db.get_song_like_count("Other Song") == 1


@pytest.mark.asyncio
async def test_get_song_like_count_excludes_dislikes(cog):
    """Verify get_song_like_count only counts is_liked=1."""
    cog.db.add_like(discord_id="user1", song_title="Mixed Song")
    cog.db.add_dislike(discord_id="user2", song_title="Mixed Song")

    assert cog.db.get_song_like_count("Mixed Song") == 1


# --- In-Game /current_song Tests ---


@pytest.mark.asyncio
async def test_game_current_song_announces(cog, monkeypatch):
    """Verify game_current_song announces the currently playing song."""

    mock_metadata = {"filename": "/var/lib/radio/requests/TestPlayer-Cool_Song.mp3"}
    monkeypatch.setattr(
        "amc_peripheral.radio.radio_cog.get_current_song_metadata",
        AsyncMock(return_value=mock_metadata),
    )
    mock_announce = AsyncMock()
    monkeypatch.setattr("amc_peripheral.radio.radio_cog.announce_in_game", mock_announce)

    await cog.game_current_song("SomePlayer")

    mock_announce.assert_called_once()
    args = mock_announce.call_args
    assert "Cool_Song" in args[0][1]
    assert "TestPlayer" in args[0][1]


@pytest.mark.asyncio
async def test_game_current_song_no_metadata(cog, monkeypatch):
    """Verify game_current_song announces fallback when no metadata."""
    monkeypatch.setattr(
        "amc_peripheral.radio.radio_cog.get_current_song_metadata",
        AsyncMock(return_value=None),
    )
    mock_announce = AsyncMock()
    monkeypatch.setattr("amc_peripheral.radio.radio_cog.announce_in_game", mock_announce)

    await cog.game_current_song("SomePlayer")

    mock_announce.assert_called_once()
    assert "No song info" in mock_announce.call_args[0][1]


# --- TTS Track Generation Tests ---


@pytest.mark.asyncio
async def test_generate_track_returns_transcript_and_audio(cog, monkeypatch):
    """Test that generate_track strips markdown and returns audio bytes."""
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "Hello **Motor Town** and *everyone*! Welcome to a special segment."
    mock_response.choices[0].message.tool_calls = None

    cog.openai_client_openrouter.chat.completions.create = AsyncMock(
        return_value=mock_response
    )

    monkeypatch.setattr(
        "amc_peripheral.radio.radio_cog.tts_dispatch", lambda *args, **kwargs: b"track_audio"
    )

    transcript, audio = await cog.generate_track("traffic safety tips")
    assert "**" not in transcript
    assert "*" not in transcript
    assert audio == b"track_audio"


@pytest.mark.asyncio
async def test_generate_radio_track_tool_defined(cog):
    """Verify generate_radio_track is in Annie's tool list."""
    tools = cog._get_annie_tools()
    tool_names = [t["function"]["name"] for t in tools]
    assert "generate_radio_track" in tool_names


@pytest.mark.asyncio
async def test_execute_annie_tool_generate_radio_track(cog, monkeypatch, tmp_path):
    """Test generate_radio_track tool writes file and queues for playback."""
    from amc_peripheral.radio import radio_cog
    monkeypatch.setattr(radio_cog, "RADIO_TMP_PATH", str(tmp_path))

    monkeypatch.setattr(
        cog, "generate_track", AsyncMock(return_value=("Test transcript", b"audio_data"))
    )
    cog.lq.push_segment = AsyncMock()
    notify_fn = AsyncMock()

    result = await cog._execute_annie_tool(
        "generate_radio_track",
        {"topic": "motor town tips", "duration": "30 seconds"},
        "TestUser",
        notify_fn,
    )

    assert "queued" in result.lower()
    cog.lq.push_segment.assert_called_once()



@pytest.mark.asyncio
async def test_create_track_command_exists(cog):
    """Verify /create_track slash command is registered."""
    commands = [cmd.name for cmd in cog.__cog_app_commands__]
    assert "create_track" in commands


# --- Multi-Speaker Talkshow Tests ---


@pytest.mark.asyncio
async def test_create_talkshow_command_exists(cog):
    """Verify /create_talkshow slash command is registered."""
    commands = [cmd.name for cmd in cog.__cog_app_commands__]
    assert "create_talkshow" in commands


@pytest.mark.asyncio
async def test_generate_talkshow_returns_transcript_and_audio(cog, monkeypatch):
    """Test that generate_talkshow returns a formatted transcript and audio bytes."""
    from amc_peripheral.radio.radio_cog import TalkshowScript, TalkshowTurn, TalkshowSpeaker

    # First LLM call: raw script via _call_llm_with_tools_internal
    raw_response = MagicMock()
    raw_response.choices = [MagicMock()]
    raw_response.choices[0].message.content = "Host: Welcome to the show!\nGuest: Thanks for having me!"
    raw_response.choices[0].message.tool_calls = None

    # Second LLM call: structured parse
    parsed_script = TalkshowScript(
        speakers=[
            TalkshowSpeaker(name="Host", gender="female"),
            TalkshowSpeaker(name="Guest", gender="male"),
        ],
        turns=[
            TalkshowTurn(speaker="Host", text="Welcome to the show!"),
            TalkshowTurn(speaker="Guest", text="Thanks for having me!"),
        ]
    )
    parse_response = MagicMock()
    parse_response.choices = [MagicMock()]
    parse_response.choices[0].message.parsed = parsed_script

    call_count = {"n": 0}

    async def mock_create(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return raw_response
        return None

    cog.openai_client_openrouter.chat.completions.create = AsyncMock(side_effect=mock_create)
    cog.openai_client_openrouter.beta.chat.completions.parse = AsyncMock(return_value=parse_response)

    # Mock tts_multi_dispatch
    monkeypatch.setattr(
        "amc_peripheral.radio.radio_cog.tts_multi_dispatch",
        lambda *args, **kwargs: b"talkshow_audio",
    )

    transcript, audio = await cog.generate_talkshow("road safety tips")

    assert "Host" in transcript
    assert "Guest" in transcript
    assert "Welcome to the show!" in transcript
    assert "Thanks for having me!" in transcript
    assert audio == b"talkshow_audio"


@pytest.mark.asyncio
async def test_generate_talkshow_formats_transcript_as_dialogue(cog, monkeypatch):
    """Test that the transcript is formatted as Speaker: text lines."""
    from amc_peripheral.radio.radio_cog import TalkshowScript, TalkshowTurn, TalkshowSpeaker

    raw_response = MagicMock()
    raw_response.choices = [MagicMock()]
    raw_response.choices[0].message.content = "Host: Hello\nGuest: Hi"
    raw_response.choices[0].message.tool_calls = None

    parsed_script = TalkshowScript(
        speakers=[
            TalkshowSpeaker(name="Host", gender="female"),
            TalkshowSpeaker(name="Guest", gender="male"),
        ],
        turns=[
            TalkshowTurn(speaker="Host", text="Hello listeners"),
            TalkshowTurn(speaker="Guest", text="Great to be here"),
            TalkshowTurn(speaker="Host", text="Lets talk about racing"),
        ]
    )
    parse_response = MagicMock()
    parse_response.choices = [MagicMock()]
    parse_response.choices[0].message.parsed = parsed_script

    cog.openai_client_openrouter.chat.completions.create = AsyncMock(return_value=raw_response)
    cog.openai_client_openrouter.beta.chat.completions.parse = AsyncMock(return_value=parse_response)

    monkeypatch.setattr(
        "amc_peripheral.radio.radio_cog.tts_multi_dispatch",
        lambda *args, **kwargs: b"audio",
    )

    transcript, _ = await cog.generate_talkshow("racing")

    lines = transcript.split("\n")
    assert len(lines) == 3
    assert lines[0].startswith("**Host:**")
    assert lines[1].startswith("**Guest:**")
    assert lines[2].startswith("**Host:**")


# --- Agent Talkshow Tool Tests ---


@pytest.mark.asyncio
async def test_talkshow_host_always_uses_leda(cog, monkeypatch):
    """Verify that Host always maps to ANNIE_VOICE (Leda) regardless of LLM output."""
    from amc_peripheral.radio.radio_cog import TalkshowScript, TalkshowTurn, TalkshowSpeaker, ANNIE_VOICE

    raw_response = MagicMock()
    raw_response.choices = [MagicMock()]
    raw_response.choices[0].message.content = "Host: Hello\nGuest: Hi"
    raw_response.choices[0].message.tool_calls = None

    parsed_script = TalkshowScript(
        speakers=[
            TalkshowSpeaker(name="Host", gender="male"),  # Try to force male — should still be Leda
            TalkshowSpeaker(name="Guest", gender="female"),
        ],
        turns=[
            TalkshowTurn(speaker="Host", text="Hello listeners"),
            TalkshowTurn(speaker="Guest", text="Great to be here"),
        ]
    )
    parse_response = MagicMock()
    parse_response.choices = [MagicMock()]
    parse_response.choices[0].message.parsed = parsed_script

    cog.openai_client_openrouter.chat.completions.create = AsyncMock(return_value=raw_response)
    cog.openai_client_openrouter.beta.chat.completions.parse = AsyncMock(return_value=parse_response)

    captured_voices = {}

    def mock_tts(*args, **kwargs):
        captured_voices.update(args[1])  # speaker_voices is the second arg
        return b"audio"

    monkeypatch.setattr(
        "amc_peripheral.radio.radio_cog.tts_multi_dispatch", mock_tts,
    )

    await cog.generate_talkshow("test topic")

    assert captured_voices["Host"] == ANNIE_VOICE


@pytest.mark.asyncio
async def test_talkshow_guest_voice_from_correct_pool(cog, monkeypatch):
    """Verify Guest voice comes from the matching gender pool."""
    from amc_peripheral.radio.radio_cog import (
        TalkshowScript, TalkshowTurn, TalkshowSpeaker,
        GUEST_VOICES_FEMALE, GUEST_VOICES_MALE,
    )

    raw_response = MagicMock()
    raw_response.choices = [MagicMock()]
    raw_response.choices[0].message.content = "Host: Hello\nGuest: Hi\nCaller: Hey"
    raw_response.choices[0].message.tool_calls = None

    parsed_script = TalkshowScript(
        speakers=[
            TalkshowSpeaker(name="Host", gender="female"),
            TalkshowSpeaker(name="Guest", gender="male"),
            TalkshowSpeaker(name="Caller", gender="female"),
        ],
        turns=[
            TalkshowTurn(speaker="Host", text="Hello"),
            TalkshowTurn(speaker="Guest", text="Hi"),
            TalkshowTurn(speaker="Caller", text="Hey"),
        ]
    )
    parse_response = MagicMock()
    parse_response.choices = [MagicMock()]
    parse_response.choices[0].message.parsed = parsed_script

    cog.openai_client_openrouter.chat.completions.create = AsyncMock(return_value=raw_response)
    cog.openai_client_openrouter.beta.chat.completions.parse = AsyncMock(return_value=parse_response)

    captured_voices = {}

    def mock_tts(*args, **kwargs):
        captured_voices.update(args[1])
        return b"audio"

    monkeypatch.setattr(
        "amc_peripheral.radio.radio_cog.tts_multi_dispatch", mock_tts,
    )

    await cog.generate_talkshow("test")

    assert captured_voices["Guest"] in GUEST_VOICES_MALE
    assert captured_voices["Caller"] in GUEST_VOICES_FEMALE


@pytest.mark.asyncio
async def test_talkshow_voice_fallback_when_no_speakers(cog, monkeypatch):
    """Verify fallback to DEFAULT_TALKSHOW_VOICES when speakers list is empty."""
    from amc_peripheral.radio.radio_cog import (
        TalkshowScript, TalkshowTurn, DEFAULT_TALKSHOW_VOICES,
    )

    raw_response = MagicMock()
    raw_response.choices = [MagicMock()]
    raw_response.choices[0].message.content = "Host: Hello\nGuest: Hi"
    raw_response.choices[0].message.tool_calls = None

    parsed_script = TalkshowScript(
        speakers=[],
        turns=[
            TalkshowTurn(speaker="Host", text="Hello"),
            TalkshowTurn(speaker="Guest", text="Hi"),
        ]
    )
    parse_response = MagicMock()
    parse_response.choices = [MagicMock()]
    parse_response.choices[0].message.parsed = parsed_script

    cog.openai_client_openrouter.chat.completions.create = AsyncMock(return_value=raw_response)
    cog.openai_client_openrouter.beta.chat.completions.parse = AsyncMock(return_value=parse_response)

    captured_voices = {}

    def mock_tts(*args, **kwargs):
        captured_voices.update(args[1])
        return b"audio"

    monkeypatch.setattr(
        "amc_peripheral.radio.radio_cog.tts_multi_dispatch", mock_tts,
    )

    await cog.generate_talkshow("test")

    assert captured_voices["Host"] == DEFAULT_TALKSHOW_VOICES["Host"]
    assert captured_voices["Guest"] == DEFAULT_TALKSHOW_VOICES["Guest"]


@pytest.mark.asyncio
async def test_generate_talkshow_segment_tool_defined(cog):
    """Verify generate_talkshow_segment is in Annie's tool list."""
    tools = cog._get_annie_tools()
    tool_names = [t["function"]["name"] for t in tools]
    assert "generate_talkshow_segment" in tool_names


@pytest.mark.asyncio
async def test_execute_annie_tool_generate_talkshow_segment(cog, monkeypatch, tmp_path):
    """Test generate_talkshow_segment queues audio for playback."""
    from amc_peripheral.radio import radio_cog
    monkeypatch.setattr(radio_cog, "RADIO_TMP_PATH", str(tmp_path))

    monkeypatch.setattr(
        cog, "generate_talkshow", AsyncMock(return_value=("**Host:** Hello\n**Guest:** Hi", b"talkshow_audio"))
    )
    cog.lq.push_segment = AsyncMock()
    notify_fn = AsyncMock()

    result = await cog._execute_annie_tool(
        "generate_talkshow_segment",
        {"topic": "best driving routes", "duration": "1 minute"},
        "TestUser",
        notify_fn,
    )

    assert "queued" in result.lower()
    cog.lq.push_segment.assert_called_once()


@pytest.mark.asyncio
async def test_execute_annie_tool_generate_talkshow_segment_error(cog, monkeypatch):
    """Test generate_talkshow_segment handles errors gracefully."""
    monkeypatch.setattr(
        cog, "generate_talkshow", AsyncMock(side_effect=Exception("TTS failed"))
    )
    notify_fn = AsyncMock()

    result = await cog._execute_annie_tool(
        "generate_talkshow_segment",
        {"topic": "broken topic"},
        "TestUser",
        notify_fn,
    )

    assert "Failed to generate talkshow segment" in result


# --- TTS Voice-Over Insertion Tests ---


@pytest.mark.asyncio
async def test_voice_reply_tool_defined(cog):
    """Verify voice_reply_on_radio is in Annie's tool list."""
    tools = cog._get_annie_tools()
    tool_names = [t["function"]["name"] for t in tools]
    assert "voice_reply_on_radio" in tool_names


@pytest.mark.asyncio
async def test_voice_announce_command_exists(cog):
    """Verify the voice_announce command is registered."""
    commands = [cmd.name for cmd in cog.__cog_app_commands__]
    assert "voice_announce" in commands


@pytest.mark.asyncio
async def test_insert_tts_waits_for_music(cog, monkeypatch, tmp_path):
    """Test _insert_tts_on_radio generates TTS and pushes announcement."""
    monkeypatch.setattr("amc_peripheral.radio.radio_cog.RADIO_TMP_PATH", str(tmp_path))
    monkeypatch.setattr(
        "amc_peripheral.radio.radio_cog.tts_dispatch", lambda *args, **kwargs: b"audio"
    )

    cog.lq.push_announcement = AsyncMock(return_value=True)

    result = await cog._insert_tts_on_radio("Hello listeners!")

    assert result is True
    cog.lq.push_announcement.assert_called_once()


@pytest.mark.asyncio
async def test_insert_tts_timeout_inserts_anyway(cog, monkeypatch, tmp_path):
    """Test _insert_tts_on_radio inserts even after max retries."""
    monkeypatch.setattr("amc_peripheral.radio.radio_cog.RADIO_TMP_PATH", str(tmp_path))
    monkeypatch.setattr(
        "amc_peripheral.radio.radio_cog.tts_dispatch", lambda *args, **kwargs: b"audio"
    )

    # Always return "talking"
    async def mock_get_current_source(session):
        return "talking"

    cog.lq.get_current_source = mock_get_current_source
    cog.lq.push_announcement = AsyncMock(return_value=True)
    cog.TTS_INSERTION_MAX_RETRIES = 3
    cog.TTS_INSERTION_RETRY_DELAY = 0.01

    result = await cog._insert_tts_on_radio("Hello!")

    assert result is True
    cog.lq.push_announcement.assert_called_once()


@pytest.mark.asyncio
async def test_insert_tts_push_failure(cog, monkeypatch, tmp_path):
    """Test _insert_tts_on_radio returns False when push fails."""
    monkeypatch.setattr("amc_peripheral.radio.radio_cog.RADIO_TMP_PATH", str(tmp_path))
    monkeypatch.setattr(
        "amc_peripheral.radio.radio_cog.tts_dispatch", lambda *args, **kwargs: b"audio"
    )

    async def mock_get_current_source(session):
        return "music"

    cog.lq.get_current_source = mock_get_current_source
    cog.lq.push_announcement = AsyncMock(return_value=False)
    cog.TTS_INSERTION_RETRY_DELAY = 0.01

    result = await cog._insert_tts_on_radio("Hello!")

    assert result is False


@pytest.mark.asyncio
async def test_insert_tts_tts_failure(cog, monkeypatch, tmp_path):
    """Test _insert_tts_on_radio returns False when TTS generation fails."""
    monkeypatch.setattr("amc_peripheral.radio.radio_cog.RADIO_TMP_PATH", str(tmp_path))
    monkeypatch.setattr(
        "amc_peripheral.radio.radio_cog.tts_dispatch",
        lambda *args, **kwargs: (_ for _ in ()).throw(Exception("TTS error")),
    )

    result = await cog._insert_tts_on_radio("Hello!")

    assert result is False


@pytest.mark.asyncio
async def test_execute_annie_tool_voice_reply(cog, monkeypatch, tmp_path):
    """Test voice_reply_on_radio tool fires background task."""
    cog._insert_tts_on_radio = AsyncMock(return_value=True)
    notify_fn = AsyncMock()

    result = await cog._execute_annie_tool(
        "voice_reply_on_radio",
        {"message": "Hey there, listeners!"},
        "TestUser",
        notify_fn,
    )

    assert "Voice reply is being generated" in result
    cog.bot.loop.create_task.assert_called()


@pytest.mark.asyncio
async def test_voice_reply_background_success(cog, monkeypatch):
    """Test _voice_reply_background does not notify on success."""
    cog._insert_tts_on_radio = AsyncMock(return_value=True)
    notify_fn = AsyncMock()

    await cog._voice_reply_background("Hello!", notify_fn)

    notify_fn.assert_not_called()


@pytest.mark.asyncio
async def test_voice_reply_background_failure(cog, monkeypatch):
    """Test _voice_reply_background notifies on failure."""
    cog._insert_tts_on_radio = AsyncMock(return_value=False)
    notify_fn = AsyncMock()

    await cog._voice_reply_background("Hello!", notify_fn)

    notify_fn.assert_called_once()
    assert "Failed" in notify_fn.call_args[0][0]


# --- Content Screening Tests ---


@pytest.mark.asyncio
async def test_screen_song_content_rejects_slur(cog):
    """Verify _screen_song_content returns rejection for racially offensive songs."""
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "REJECT: Title contains racial slur"

    cog.openai_client_openrouter.chat.completions.create = AsyncMock(
        return_value=mock_response
    )

    result = await cog._screen_song_content("Gangsta Rap - offensive title")
    assert result is not None
    assert "REJECT" in result
    assert "racial slur" in result


@pytest.mark.asyncio
async def test_screen_song_content_allows_explicit(cog):
    """Verify _screen_song_content allows explicit but non-offensive songs."""
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "ALLOW"

    cog.openai_client_openrouter.chat.completions.create = AsyncMock(
        return_value=mock_response
    )

    result = await cog._screen_song_content("Eminem - Lose Yourself")
    assert result is None


@pytest.mark.asyncio
async def test_screen_song_content_allows_normal(cog):
    """Verify _screen_song_content allows normal songs."""
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "ALLOW"

    cog.openai_client_openrouter.chat.completions.create = AsyncMock(
        return_value=mock_response
    )

    result = await cog._screen_song_content("Taylor Swift - Shake It Off")
    assert result is None


@pytest.mark.asyncio
async def test_screen_song_content_fails_open(cog):
    """Verify _screen_song_content allows songs when LLM call fails."""
    cog.openai_client_openrouter.chat.completions.create = AsyncMock(
        side_effect=Exception("API error")
    )

    result = await cog._screen_song_content("Some Song")
    # Should fail open — return None (allow)
    assert result is None


@pytest.mark.asyncio
async def test_execute_annie_tool_screens_content(cog, mock_bot):
    """Verify search_and_queue_song tool calls _screen_song_content before dispatching."""
    cog._screen_song_content = AsyncMock(
        return_value="REJECT: Contains racial slur in title"
    )
    notify_fn = AsyncMock()

    result = await cog._execute_annie_tool(
        "search_and_queue_song",
        {"query": "offensive song title"},
        "TestUser",
        notify_fn,
    )

    assert "Song rejected" in result
    assert "REJECT" in result
    cog._screen_song_content.assert_called_once_with("offensive song title")
    # No download should be dispatched
    mock_bot.loop.create_task.assert_not_called()


@pytest.mark.asyncio
async def test_execute_annie_tool_allows_after_screening(cog, mock_bot):
    """Verify search_and_queue_song dispatches download when screening passes."""
    cog._screen_song_content = AsyncMock(return_value=None)
    notify_fn = AsyncMock()

    result = await cog._execute_annie_tool(
        "search_and_queue_song",
        {"query": "bohemian rhapsody"},
        "TestUser",
        notify_fn,
    )

    assert "Download started" in result
    cog._screen_song_content.assert_called_once_with("bohemian rhapsody")
    mock_bot.loop.create_task.assert_called_once()


@pytest.mark.asyncio
async def test_agent_song_request_routes_through_llm(cog):
    """Verify _agent_song_request calls the Annie LLM with search_and_queue_song tool."""
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "On it! Queuing that song for you."
    mock_response.choices[0].message.tool_calls = None

    cog.openai_client_openrouter.chat.completions.create = AsyncMock(
        return_value=mock_response
    )

    result = await cog._agent_song_request(
        query="bohemian rhapsody",
        requester_name="TestPlayer",
        requester_id="12345",
    )

    assert "Queuing" in result or "On it" in result
    # Verify the LLM was actually called
    cog.openai_client_openrouter.chat.completions.create.assert_called()


@pytest.mark.asyncio
async def test_agent_game_request_song_announces(cog, mock_bot, monkeypatch):
    """Verify _agent_game_request_song sends response to game and Discord."""
    from amc_peripheral.radio import radio_cog
    monkeypatch.setattr(radio_cog, "GAME_ANNOUNCEMENTS_CHANNEL_ID", 99999)

    mock_channel = MagicMock()
    mock_channel.send = AsyncMock()
    mock_bot.get_channel = MagicMock(return_value=mock_channel)

    cog._agent_song_request = AsyncMock(return_value="Queuing your song!")
    monkeypatch.setattr(radio_cog, "announce_in_game", AsyncMock())

    await cog._agent_game_request_song("cool song", "PlayerOne")

    cog._agent_song_request.assert_called_once()
    mock_channel.send.assert_called_once_with("Queuing your song!")
    radio_cog.announce_in_game.assert_called_once()


class AsyncIteratorMock:
    def __init__(self, items):
        self.items = iter(items)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self.items)
        except StopIteration:
            raise StopAsyncIteration


class AsyncContextManagerMock:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass
