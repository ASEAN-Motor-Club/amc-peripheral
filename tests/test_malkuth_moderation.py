import os
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import discord
from discord import app_commands
from discord.ext import commands

os.environ.setdefault(
    "BAN_TRAP_ALLOWED_ROLE_IDS", "1395460420189421713,1496482029892669500"
)
os.environ.setdefault("BAN_TRAP_CHANNEL_ID", "1529987241278177352")
os.environ.setdefault("GUILD_ID", "1341775494026231859")
os.environ.setdefault("MOD_ALLOWED_ROLE_IDS", "300000000000000001")

from amc_peripheral.malkuth.cog import BanTrapCog
from amc_peripheral.malkuth.moderation import ModerationCog, parse_duration

GUILD_ID = 1341775494026231859
MOD_ROLE = 300000000000000001
STAFF_ROLE = 1395460420189421713


class MockBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        super().__init__(command_prefix="/", intents=intents)
        self.http_session = AsyncMock()
        self._connection = MagicMock()
        self._connection.user = object()


def make_interaction(mod=True, guild_id=GUILD_ID):
    interaction = MagicMock()
    interaction.guild_id = guild_id
    interaction.guild = MagicMock()
    interaction.guild.owner_id = 111
    interaction.guild.me = MagicMock()
    interaction.guild.me.top_role = 100  # plain int: comparisons work like Role
    interaction.user = MagicMock()
    interaction.user.id = 222
    interaction.user.roles = [MagicMock(id=MOD_ROLE)] if mod else [MagicMock(id=555)]
    interaction.response.send_message = AsyncMock()
    interaction.response.is_done.return_value = False
    interaction.followup.send = AsyncMock()
    return interaction


def make_member(mid=333, bot=False, top_role=50, roles=()):
    m = MagicMock()
    m.id = mid
    m.bot = bot
    m.top_role = top_role  # plain int: comparisons work like Role
    m.roles = [MagicMock(id=r) for r in roles]
    m.mention = f"<@{mid}>"
    m.display_name = f"user{mid}"
    m.timeout = AsyncMock()
    m.kick = AsyncMock()
    return m


@pytest.fixture
def cog():
    return ModerationCog(MockBot())


@pytest.fixture
def mod_interaction():
    return make_interaction(mod=True)


# ----------------------------------------------------------------------
# Duration parsing
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected_seconds",
    [
        ("10", 600),  # bare numbers are minutes
        ("5m", 300),
        ("2h", 7200),
        ("1d", 86400),
        ("1w", 604800),
        ("30s", 30),
        ("  10 m ", 600),
        ("2H", 7200),
    ],
)
def test_parse_duration_valid(text, expected_seconds):
    delta = parse_duration(text)
    assert delta == timedelta(seconds=expected_seconds)


@pytest.mark.parametrize("text", ["abc", "0", "0m", "-5m", "1x", "", "1.5h"])
def test_parse_duration_invalid(text):
    assert parse_duration(text) is None


# ----------------------------------------------------------------------
# Caller-side gate (fail-closed)
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_mod_roles_fails_closed(cog, mod_interaction):
    member = make_member()
    with patch("amc_peripheral.malkuth.moderation.MOD_ALLOWED_ROLE_IDS", set()):
        await cog.timeout_cmd.callback(cog, mod_interaction, member, "10m")
    member.timeout.assert_not_called()
    mod_interaction.response.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_unauthorized_caller_refused(cog):
    interaction = make_interaction(mod=False)
    member = make_member()
    await cog.timeout_cmd.callback(cog, interaction, member, "10m")
    member.timeout.assert_not_called()
    interaction.response.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_dm_or_wrong_guild_refused(cog, mod_interaction):
    member = make_member()
    mod_interaction.guild = None
    await cog.timeout_cmd.callback(cog, mod_interaction, member, "10m")
    member.timeout.assert_not_called()
    mod_interaction.response.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_wrong_guild_id_refused(cog, mod_interaction):
    member = make_member()
    mod_interaction.guild_id = 0
    await cog.kick_cmd.callback(cog, mod_interaction, member)
    member.kick.assert_not_called()
    mod_interaction.response.send_message.assert_awaited_once()


# ----------------------------------------------------------------------
# Target guards
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bot_target_refused(cog, mod_interaction):
    member = make_member(bot=True)
    await cog.kick_cmd.callback(cog, mod_interaction, member)
    member.kick.assert_not_called()
    mod_interaction.response.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_self_target_refused(cog, mod_interaction):
    member = make_member(mid=222)  # same id as interaction.user
    await cog.kick_cmd.callback(cog, mod_interaction, member)
    member.kick.assert_not_called()
    mod_interaction.response.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_owner_target_refused(cog, mod_interaction):
    member = make_member(mid=111)  # same id as guild.owner_id
    await cog.kick_cmd.callback(cog, mod_interaction, member)
    member.kick.assert_not_called()
    mod_interaction.response.send_message.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("top_role", [100, 150])  # equal to / above bot top role
async def test_hierarchy_target_refused(cog, mod_interaction, top_role):
    member = make_member(top_role=top_role)
    await cog.kick_cmd.callback(cog, mod_interaction, member)
    member.kick.assert_not_called()
    mod_interaction.response.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_staff_role_target_refused(cog, mod_interaction):
    member = make_member(roles=[STAFF_ROLE])
    await cog.timeout_cmd.callback(cog, mod_interaction, member, "10m")
    member.timeout.assert_not_called()
    mod_interaction.response.send_message.assert_awaited_once()


# ----------------------------------------------------------------------
# /timeout
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_timeout_happy_path(cog, mod_interaction):
    member = make_member()
    await cog.timeout_cmd.callback(cog, mod_interaction, member, "10m", "be nice")
    member.timeout.assert_awaited_once()
    until = member.timeout.await_args.args[0]
    now = discord.utils.utcnow()
    assert 0 < (until - now).total_seconds() <= 605
    assert "be nice" in member.timeout.await_args.kwargs["reason"]
    mod_interaction.response.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_timeout_over_28d_refused(cog, mod_interaction):
    member = make_member()
    await cog.timeout_cmd.callback(cog, mod_interaction, member, "29d")
    member.timeout.assert_not_called()
    mod_interaction.response.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_timeout_invalid_duration_refused(cog, mod_interaction):
    member = make_member()
    await cog.timeout_cmd.callback(cog, mod_interaction, member, "banana")
    member.timeout.assert_not_called()
    mod_interaction.response.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_timeout_permission_failure_is_friendly(cog, mod_interaction):
    member = make_member()
    member.timeout = AsyncMock(
        side_effect=discord.HTTPException(MagicMock(), "Missing Permissions")
    )
    await cog.timeout_cmd.callback(cog, mod_interaction, member, "10m")
    mod_interaction.response.send_message.assert_awaited_once()
    msg = mod_interaction.response.send_message.await_args.args[0]
    assert "Moderate Members" in msg


# ----------------------------------------------------------------------
# /untimeout
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_untimeout_removes_timeout(cog, mod_interaction):
    member = make_member()
    await cog.untimeout_cmd.callback(cog, mod_interaction, member)
    member.timeout.assert_awaited_once_with(
        None, reason=member.timeout.await_args.kwargs["reason"]
    )
    mod_interaction.response.send_message.assert_awaited_once()


# ----------------------------------------------------------------------
# /kick
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_kick_happy_path(cog, mod_interaction):
    member = make_member()
    await cog.kick_cmd.callback(cog, mod_interaction, member, "trolling")
    member.kick.assert_awaited_once()
    assert "trolling" in member.kick.await_args.kwargs["reason"]
    mod_interaction.response.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_kick_failure_is_friendly(cog, mod_interaction):
    member = make_member()
    member.kick = AsyncMock(
        side_effect=discord.HTTPException(MagicMock(), "Missing Permissions")
    )
    await cog.kick_cmd.callback(cog, mod_interaction, member)
    mod_interaction.response.send_message.assert_awaited_once()
    msg = mod_interaction.response.send_message.await_args.args[0]
    assert "Kick Members" in msg


# ----------------------------------------------------------------------
# /ban
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ban_happy_path(cog, mod_interaction):
    member = make_member()
    mod_interaction.guild.ban = AsyncMock()
    await cog.ban_cmd.callback(cog, mod_interaction, member, "raiding")
    mod_interaction.guild.ban.assert_awaited_once()
    kwargs = mod_interaction.guild.ban.await_args.kwargs
    assert kwargs["delete_message_seconds"] == 0
    assert "raiding" in kwargs["reason"]
    mod_interaction.response.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_ban_with_delete_messages_choice(cog, mod_interaction):
    member = make_member()
    mod_interaction.guild.ban = AsyncMock()
    choice = app_commands.Choice(name="1 hour", value=3600)
    await cog.ban_cmd.callback(cog, mod_interaction, member, None, choice)
    assert mod_interaction.guild.ban.await_args.kwargs["delete_message_seconds"] == 3600


# ----------------------------------------------------------------------
# /unban
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unban_happy_path(cog, mod_interaction):
    mod_interaction.guild.unban = AsyncMock()
    await cog.unban_cmd.callback(cog, mod_interaction, "999888777")
    mod_interaction.guild.unban.assert_awaited_once()
    target = mod_interaction.guild.unban.await_args.args[0]
    assert target.id == 999888777
    mod_interaction.response.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_unban_non_numeric_id_refused(cog, mod_interaction):
    mod_interaction.guild.unban = AsyncMock()
    await cog.unban_cmd.callback(cog, mod_interaction, "not-an-id")
    mod_interaction.guild.unban.assert_not_called()
    mod_interaction.response.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_unban_not_banned_refused(cog, mod_interaction):
    mod_interaction.guild.unban = AsyncMock(
        side_effect=discord.NotFound(MagicMock(), "no ban")
    )
    await cog.unban_cmd.callback(cog, mod_interaction, "999888777")
    mod_interaction.response.send_message.assert_awaited_once()
    msg = mod_interaction.response.send_message.await_args.args[0]
    assert "No ban found" in msg


# ----------------------------------------------------------------------
# Mod-log
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mod_log_embed_sent_when_configured(cog, mod_interaction):
    member = make_member()
    channel = MagicMock(spec=discord.TextChannel)
    channel.send = AsyncMock()
    mod_interaction.guild.get_channel.return_value = channel
    with patch("amc_peripheral.malkuth.moderation.MOD_LOG_CHANNEL_ID", 999):
        await cog.kick_cmd.callback(cog, mod_interaction, member, "spam")
    channel.send.assert_awaited_once()
    embed = channel.send.await_args.kwargs["embed"]
    assert embed.title == "Member kicked"


@pytest.mark.asyncio
async def test_mod_log_skipped_when_unset(cog, mod_interaction):
    member = make_member()
    with patch("amc_peripheral.malkuth.moderation.MOD_LOG_CHANNEL_ID", None):
        await cog.kick_cmd.callback(cog, mod_interaction, member)
    mod_interaction.guild.get_channel.assert_not_called()


# ----------------------------------------------------------------------
# Ban-trap coexistence
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ban_trap_unaffected_by_moderation_cog():
    bot = MockBot()
    ban_cog = BanTrapCog(bot)
    ModerationCog(bot)  # loaded side by side; must not disturb the trap

    message = MagicMock()
    message.author = MagicMock()
    message.author.bot = False
    message.author.id = 2
    message.webhook_id = None
    message.guild = MagicMock()
    message.guild.id = GUILD_ID
    message.channel = AsyncMock()
    message.channel.id = 1529987241278177352
    message.guild.get_member.return_value = None
    message.guild.fetch_member.side_effect = Exception("not cached")
    message.guild.ban = AsyncMock()
    sent = MagicMock()
    sent.delete = AsyncMock()
    message.channel.send.return_value = sent

    await ban_cog.on_message(message)
    message.guild.ban.assert_awaited_once()
    message.channel.send.assert_awaited_once()
