import pytest
from unittest.mock import MagicMock, AsyncMock
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
