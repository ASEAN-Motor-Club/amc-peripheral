import time
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from discord.ext import tasks
from amc_peripheral.bot.utils_cog import UtilsCog


@pytest.fixture
def mock_bot():
    bot = MagicMock()
    bot.tree = MagicMock()
    bot.user.id = 12345
    # Add http_session mock
    bot.http_session = AsyncMock()
    return bot


@pytest.fixture
def cog(mock_bot):
    return UtilsCog(mock_bot)


@pytest.mark.asyncio
async def test_tasks_exist(cog):
    """Verify that background tasks are defined as Loop objects on the Cog."""
    assert hasattr(cog, "regular_announcement")
    assert isinstance(cog.regular_announcement, tasks.Loop)

    assert hasattr(cog, "race_announcement")
    assert isinstance(cog.race_announcement, tasks.Loop)

    assert hasattr(cog, "rent_reminders")
    assert isinstance(cog.rent_reminders, tasks.Loop)

    assert hasattr(cog, "update_time_embed")
    assert isinstance(cog.update_time_embed, tasks.Loop)


@pytest.mark.asyncio
async def test_cog_load_starts_tasks(cog):
    """Verify cog_load starts the tasks."""
    # Mock the start methods
    cog.regular_announcement.start = MagicMock()
    cog.rent_reminders.start = MagicMock()
    cog.update_time_embed.start = MagicMock()

    await cog.cog_load()

    cog.regular_announcement.start.assert_called_once()
    cog.rent_reminders.start.assert_called_once()
    cog.update_time_embed.start.assert_called_once()

    # context menus verification (UtilsCog has 2)
    assert cog.bot.tree.add_command.call_count == 2


@pytest.mark.asyncio
async def test_cog_unload_cancels_tasks(cog):
    """Verify cog_unload cancels the tasks."""
    # Mock the cancel methods
    cog.regular_announcement.cancel = MagicMock()
    cog.rent_reminders.cancel = MagicMock()
    cog.update_time_embed.cancel = MagicMock()

    # Manually populate ctx_menus for unload test
    cog.ctx_menus = [MagicMock(), MagicMock()]

    await cog.cog_unload()

    cog.regular_announcement.cancel.assert_called_once()
    cog.rent_reminders.cancel.assert_called_once()
    cog.update_time_embed.cancel.assert_called_once()


# --- on_message debounce listener tests ---


@pytest.mark.asyncio
async def test_on_message_updates_timestamp_for_game_announcements_channel(cog):
    """on_message should update _last_channel_message_time for messages in GAME_ANNOUNCEMENTS_CHANNEL_ID."""
    from amc_peripheral.settings import GAME_ANNOUNCEMENTS_CHANNEL_ID

    message = MagicMock()
    message.author.bot = False
    message.channel.id = GAME_ANNOUNCEMENTS_CHANNEL_ID

    before = cog._last_channel_message_time
    with patch("amc_peripheral.bot.utils_cog.time.time", return_value=12345.0):
        await cog.on_message(message)
    assert cog._last_channel_message_time == 12345.0
    assert cog._last_channel_message_time != before


@pytest.mark.asyncio
async def test_on_message_ignores_bot_messages(cog):
    """on_message should ignore messages from bots."""
    from amc_peripheral.settings import GAME_ANNOUNCEMENTS_CHANNEL_ID

    message = MagicMock()
    message.author.bot = True
    message.channel.id = GAME_ANNOUNCEMENTS_CHANNEL_ID

    await cog.on_message(message)
    assert cog._last_channel_message_time == 0.0


@pytest.mark.asyncio
async def test_on_message_ignores_other_channels(cog):
    """on_message should not update timestamp for messages in other channels."""
    message = MagicMock()
    message.author.bot = False
    message.channel.id = 999999999  # some other channel

    await cog.on_message(message)
    assert cog._last_channel_message_time == 0.0


# --- regular_announcement debounce tests ---


@pytest.mark.asyncio
async def test_regular_announcement_skips_when_channel_active(cog):
    """regular_announcement should skip if last message was less than 15s ago."""
    cog._last_channel_message_time = time.time()  # just now
    cog.bot.guilds = []

    with patch("amc_peripheral.bot.utils_cog.announce_in_game", new_callable=AsyncMock) as mock_announce:
        await cog.regular_announcement()

    mock_announce.assert_not_called()


@pytest.mark.asyncio
async def test_regular_announcement_proceeds_when_channel_quiet(cog):
    """regular_announcement should proceed if last message was more than 15s ago."""
    cog._last_channel_message_time = time.time() - 60  # 60s ago
    guild = MagicMock()
    guild.scheduled_events = []
    cog.bot.guilds = [guild]
    cog.announcement_index = 0

    with patch("amc_peripheral.bot.utils_cog.announce_in_game", new_callable=AsyncMock) as mock_announce:
        await cog.regular_announcement()

    mock_announce.assert_called_once()
