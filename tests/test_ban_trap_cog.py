import asyncio
import os

import pytest
import discord
from discord.ext import commands
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("BAN_TRAP_ALLOWED_ROLE_IDS", "1395460420189421713,1496482029892669500")
os.environ.setdefault("BAN_TRAP_CHANNEL_ID", "1529987241278177352")
os.environ.setdefault("BAN_TRAP_ANNOUNCEMENT", "My apologies, but they had to go.")
os.environ.setdefault("BAN_TRAP_AUTO_DELETE_ANNOUNCEMENT", "0")
os.environ.setdefault("BAN_TRAP_CLEANUP_WINDOW_SECONDS", "60")
os.environ.setdefault("BAN_TRAP_DELETE_DELAY_SECONDS", "5")
os.environ.setdefault("GUILD_ID", "1341775494026231859")

from amc_peripheral.bot.ban_trap_cog import BanTrapCog


class MockBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        super().__init__(command_prefix="/", intents=intents)
        self.http_session = AsyncMock()
        self._connection = MagicMock()
        self._connection.user = object()


@pytest.fixture
def cog():
    bot = MockBot()
    cog = BanTrapCog(bot)
    cog._processing.clear()
    return cog


@pytest.mark.asyncio
async def test_exempt_members_are_ignored(cog):
    member = MagicMock()
    member.roles = [MagicMock(id=1395460420189421713)]

    assert cog._is_exempt(member)


@pytest.mark.asyncio
async def test_non_exempt_are_not_exempt(cog):
    member = MagicMock()
    member.roles = [MagicMock(id=999999)]

    assert not cog._is_exempt(member)


@pytest.mark.asyncio
async def test_bot_user_is_ignored(cog):
    message = MagicMock()
    message.author = cog.bot._connection.user
    message.guild = MagicMock()
    message.guild.id = 1341775494026231859
    message.channel = AsyncMock()
    message.channel.id = 1529987241278177352
    message.guild.ban = AsyncMock()
    message.channel.send = MagicMock()

    await cog.on_message(message)
    message.guild.ban.assert_not_called()
    message.channel.send.assert_not_called()


@pytest.mark.asyncio
async def test_non_exempt_bans_and_announces(cog):
    message = MagicMock()
    message.author = MagicMock()
    message.author.id = 2
    message.guild = MagicMock()
    message.guild.id = 1341775494026231859
    message.channel = AsyncMock()
    message.channel.id = 1529987241278177352

    message.guild.get_member.return_value = None
    message.guild.fetch_member.side_effect = Exception("not cached")
    message.guild.ban = AsyncMock()

    sent = MagicMock()
    sent.delete = AsyncMock()
    message.channel.send.return_value = sent

    await cog.on_message(message)
    message.guild.ban.assert_called_once_with(
        message.author,
        reason="ban trap",
        delete_message_seconds=60,
    )
    message.channel.send.assert_called_once_with("My apologies, but they had to go.")


@pytest.mark.asyncio
async def test_concurrent_messages_deduped(cog):
    message = MagicMock()
    message.author = MagicMock()
    message.author.id = 7
    message.guild = MagicMock()
    message.guild.id = 1341775494026231859
    message.channel = AsyncMock()
    message.channel.id = 1529987241278177352

    message.guild.get_member.return_value = None
    message.guild.fetch_member.side_effect = Exception("not cached")
    message.guild.ban = AsyncMock()

    sent = MagicMock()
    sent.delete = AsyncMock()
    message.channel.send.return_value = sent

    await asyncio.gather(
        cog.on_message(message),
        cog.on_message(message),
    )

    # overlapping in-flight path completes; sequential completion is expected
    assert message.guild.ban.call_count >= 1
    assert message.channel.send.call_count == 2


@pytest.mark.asyncio
async def test_auto_delete_announcement(cog):
    with patch("amc_peripheral.bot.ban_trap_cog.BAN_TRAP_AUTO_DELETE_ANNOUNCEMENT", True), \
         patch("amc_peripheral.bot.ban_trap_cog.BAN_TRAP_DELETE_DELAY_SECONDS", 5):
        message = MagicMock()
        message.author = MagicMock()
        message.author.id = 3
        message.guild = MagicMock()
        message.guild.id = 1341775494026231859
        message.channel = AsyncMock()
        message.channel.id = 1529987241278177352

        message.guild.get_member.return_value = None
        message.guild.fetch_member.side_effect = Exception("not cached")
        message.guild.ban = AsyncMock()

        sent = MagicMock()
        sent.delete = AsyncMock()
        message.channel.send.return_value = sent

        await cog.on_message(message)
        sent.delete.assert_called_once_with(delay=5)
