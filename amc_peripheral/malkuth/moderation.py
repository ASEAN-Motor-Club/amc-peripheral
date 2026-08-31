"""Malkuth ModerationCog — slash-command Discord member moderation.

Purely additive to the BanTrapCog: a separate cog with no shared state, so the
ban trap's ``on_message`` listener is untouched. Both cogs load side by side
(see bot.py) and a failure in this cog cannot disable the trap.

Commands (guild-scoped, role-gated, fail-closed):
  /timeout   <member> <duration> [reason] — Discord native timeout (temp-mute)
  /untimeout <member> [reason]
  /kick      <member> [reason]
  /ban       <member> [reason] [delete_messages]
  /unban     <user_id> [reason]

Safety model:
  - Caller must hold a role in MOD_ALLOWED_ROLE_IDS. If that set is empty the
    cog refuses EVERY command (fail-closed) — an unconfigured deployment can
    never moderate.
  - Refused targets: bots, the caller themself, the guild owner, holders of a
    staff role (MOD_ALLOWED_ROLE_IDS ∪ BAN_TRAP_ALLOWED_ROLE_IDS), and anyone
    ranked at/above the bot's own top role.
  - Every action is echoed to MOD_LOG_CHANNEL_ID when that env var is set
    (optional), best-effort — a logging failure never blocks the action.
"""

import logging
import re
from datetime import timedelta
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from .settings import (
    BAN_TRAP_ALLOWED_ROLE_IDS,
    GUILD_ID,
    MOD_ALLOWED_ROLE_IDS,
    MOD_LOG_CHANNEL_ID,
)

log = logging.getLogger(__name__)

_DURATION_RE = re.compile(r"^(\d+)\s*([smhdw]?)$", re.IGNORECASE)
# Bare numbers are minutes (the most intuitive unit for a mod typing /timeout).
_UNIT_SECONDS = {"": 60, "s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
MAX_TIMEOUT = timedelta(days=28)  # Discord's hard cap

DELETE_CHOICES = [
    app_commands.Choice(name="none", value=0),
    app_commands.Choice(name="1 hour", value=3600),
    app_commands.Choice(name="6 hours", value=21600),
    app_commands.Choice(name="24 hours", value=86400),
    app_commands.Choice(name="7 days", value=604800),
]


def parse_duration(text: str) -> Optional[timedelta]:
    """Parse '10', '5m', '2h', '1d', '1w', '30s' into a timedelta (None = invalid)."""
    match = _DURATION_RE.match(text.strip())
    if match is None:
        return None
    seconds = int(match.group(1)) * _UNIT_SECONDS[match.group(2).lower()]
    if seconds <= 0:
        return None
    return timedelta(seconds=seconds)


def _human(delta: timedelta) -> str:
    total = int(delta.total_seconds())
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    return " ".join(parts) or "0m"


def _audit_reason(interaction: discord.Interaction, reason: Optional[str]) -> str:
    base = reason or "No reason provided"
    return f"By {interaction.user} ({interaction.user.id}): {base}"


class ModerationCog(commands.Cog):
    """Role-gated Discord member moderation: timeout, kick, ban, unban."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ------------------------------------------------------------------
    # Guards (fail-closed)
    # ------------------------------------------------------------------

    async def _refuse(self, interaction: discord.Interaction, message: str) -> None:
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)

    async def _precheck(
        self, interaction: discord.Interaction
    ) -> Optional[discord.Guild]:
        """Caller-side gate: right guild + holds a configured mod role.

        Returns the guild on success, None after refusing (reply already sent).
        """
        if interaction.guild is None or interaction.guild_id != GUILD_ID:
            await self._refuse(
                interaction, "This command only works in the AMC server."
            )
            return None
        if not MOD_ALLOWED_ROLE_IDS:
            await self._refuse(
                interaction,
                "Moderation is not configured (no mod roles set) — refusing.",
            )
            return None
        user_roles = {r.id for r in getattr(interaction.user, "roles", ())}
        if not user_roles & MOD_ALLOWED_ROLE_IDS:
            await self._refuse(
                interaction, "You don't have permission to use moderation commands."
            )
            return None
        return interaction.guild

    def _is_protected(self, member: discord.Member) -> bool:
        staff = MOD_ALLOWED_ROLE_IDS | BAN_TRAP_ALLOWED_ROLE_IDS
        return bool({r.id for r in member.roles} & staff)

    async def _target_guard(
        self,
        interaction: discord.Interaction,
        guild: discord.Guild,
        member: discord.Member,
    ) -> bool:
        if member.bot:
            await self._refuse(interaction, "Bots can't be moderated.")
        elif member.id == interaction.user.id:
            await self._refuse(interaction, "You can't moderate yourself.")
        elif guild.owner_id == member.id:
            await self._refuse(interaction, "You can't moderate the server owner.")
        elif guild.me.top_role <= member.top_role:
            await self._refuse(
                interaction,
                "That member's highest role is at or above mine — I can't act on them.",
            )
        elif self._is_protected(member):
            await self._refuse(
                interaction, "That member holds a staff role and is protected."
            )
        else:
            return True
        return False

    # ------------------------------------------------------------------
    # Best-effort mod-log
    # ------------------------------------------------------------------

    async def _mod_log(
        self,
        interaction: discord.Interaction,
        title: str,
        description: str,
    ) -> None:
        guild = interaction.guild
        if MOD_LOG_CHANNEL_ID is None or guild is None:
            return
        channel = guild.get_channel(MOD_LOG_CHANNEL_ID)
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            log.warning(
                "MOD_LOG_CHANNEL_ID=%s not found or not a text channel; "
                "skipping audit embed",
                MOD_LOG_CHANNEL_ID,
            )
            return
        embed = discord.Embed(
            title=title,
            description=description,
            color=0xD9534F,
            timestamp=discord.utils.utcnow(),
        )
        embed.set_footer(text=f"Moderator: {interaction.user} ({interaction.user.id})")
        try:
            await channel.send(embed=embed)
        except discord.HTTPException as exc:
            log.warning("Failed to post mod-log embed: %s", exc)

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    @app_commands.command(
        name="timeout",
        description=(
            "Timeout (temp-mute) a member: 10, 5m, 2h, 1d — bare numbers are minutes"
        ),
    )
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.describe(
        member="Member to time out",
        duration="e.g. 10, 5m, 2h, 1d (max 28d; bare numbers = minutes)",
        reason="Why (goes to the audit log and the mod-log channel)",
    )
    async def timeout_cmd(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        duration: str,
        reason: Optional[str] = None,
    ) -> None:
        if not (guild := await self._precheck(interaction)):
            return
        delta = parse_duration(duration)
        if delta is None:
            await self._refuse(
                interaction, "Invalid duration — use e.g. 10, 5m, 2h, 1d."
            )
            return
        if delta > MAX_TIMEOUT:
            await self._refuse(interaction, "Discord caps timeouts at 28 days.")
            return
        if not await self._target_guard(interaction, guild, member):
            return
        until = discord.utils.utcnow() + delta
        try:
            await member.timeout(until, reason=_audit_reason(interaction, reason))
        except discord.HTTPException as exc:
            await self._refuse(
                interaction,
                f"Failed to time out {member.mention}: {exc} "
                "(does the bot have the Moderate Members permission?)",
            )
            return
        await interaction.response.send_message(
            f"⏳ Timed out {member.mention} until <t:{int(until.timestamp())}:f> "
            f"({_human(delta)}). Reason: {reason or 'not given'}",
            ephemeral=True,
        )
        await self._mod_log(
            interaction,
            "Member timed out",
            f"{member.mention} ({member.id}) until <t:{int(until.timestamp())}:f> "
            f"— {reason or 'No reason provided'}",
        )

    @app_commands.command(name="untimeout", description="Remove a member's timeout")
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.describe(member="Member to un-timeout", reason="Why (audit log only)")
    async def untimeout_cmd(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        reason: Optional[str] = None,
    ) -> None:
        if not (guild := await self._precheck(interaction)):
            return
        if not await self._target_guard(interaction, guild, member):
            return
        try:
            await member.timeout(None, reason=_audit_reason(interaction, reason))
        except discord.HTTPException as exc:
            await self._refuse(
                interaction, f"Failed to remove the timeout on {member.mention}: {exc}"
            )
            return
        await interaction.response.send_message(
            f"✅ Timeout removed for {member.mention}.", ephemeral=True
        )
        await self._mod_log(
            interaction,
            "Timeout removed",
            f"{member.mention} ({member.id}) — {reason or 'No reason provided'}",
        )

    @app_commands.command(name="kick", description="Kick a member from the server")
    @app_commands.default_permissions(kick_members=True)
    @app_commands.describe(member="Member to kick", reason="Why (audit log only)")
    async def kick_cmd(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        reason: Optional[str] = None,
    ) -> None:
        if not (guild := await self._precheck(interaction)):
            return
        if not await self._target_guard(interaction, guild, member):
            return
        try:
            await member.kick(reason=_audit_reason(interaction, reason))
        except discord.HTTPException as exc:
            await self._refuse(
                interaction,
                f"Failed to kick {member.mention}: {exc} "
                "(does the bot have the Kick Members permission?)",
            )
            return
        await interaction.response.send_message(
            f"👢 Kicked {member.mention}. Reason: {reason or 'not given'}",
            ephemeral=True,
        )
        await self._mod_log(
            interaction,
            "Member kicked",
            f"{member.mention} ({member.id}) — {reason or 'No reason provided'}",
        )

    @app_commands.command(name="ban", description="Ban a member from the server")
    @app_commands.default_permissions(ban_members=True)
    @app_commands.describe(
        member="Member to ban",
        reason="Why (audit log only)",
        delete_messages="How much recent message history to delete",
    )
    @app_commands.choices(delete_messages=DELETE_CHOICES)
    async def ban_cmd(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        reason: Optional[str] = None,
        delete_messages: Optional[app_commands.Choice[int]] = None,
    ) -> None:
        if not (guild := await self._precheck(interaction)):
            return
        if not await self._target_guard(interaction, guild, member):
            return
        if isinstance(delete_messages, app_commands.Choice):
            delete_seconds = delete_messages.value
        else:
            delete_seconds = int(delete_messages or 0)
        try:
            await interaction.guild.ban(
                member,
                delete_message_seconds=delete_seconds,
                reason=_audit_reason(interaction, reason),
            )
        except discord.HTTPException as exc:
            await self._refuse(
                interaction,
                f"Failed to ban {member.mention}: {exc} "
                "(does the bot have the Ban Members permission?)",
            )
            return
        await interaction.response.send_message(
            f"🔨 Banned {member.mention}. Reason: {reason or 'not given'}",
            ephemeral=True,
        )
        await self._mod_log(
            interaction,
            "Member banned",
            f"{member.mention} ({member.id}) — {reason or 'No reason provided'} "
            f"(deleted {delete_seconds}s of messages)",
        )

    @app_commands.command(
        name="unban", description="Unban a user by their Discord user ID"
    )
    @app_commands.default_permissions(ban_members=True)
    @app_commands.describe(
        user_id="Discord user ID of the banned user",
        reason="Why (audit log only)",
    )
    async def unban_cmd(
        self,
        interaction: discord.Interaction,
        user_id: str,
        reason: Optional[str] = None,
    ) -> None:
        if not (guild := await self._precheck(interaction)):
            return
        try:
            uid = int(user_id.strip())
        except ValueError:
            await self._refuse(
                interaction, "user_id must be a numeric Discord user ID."
            )
            return
        try:
            await guild.unban(
                discord.Object(id=uid), reason=_audit_reason(interaction, reason)
            )
        except discord.NotFound:
            await self._refuse(interaction, f"No ban found for user ID {uid}.")
            return
        except discord.HTTPException as exc:
            await self._refuse(interaction, f"Failed to unban {uid}: {exc}")
            return
        await interaction.response.send_message(
            f"✅ Unbanned user ID {uid}.", ephemeral=True
        )
        await self._mod_log(
            interaction,
            "User unbanned",
            f"<@{uid}> ({uid}) — {reason or 'No reason provided'}",
        )

    # ------------------------------------------------------------------
    # Error surface
    # ------------------------------------------------------------------

    async def cog_app_command_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        if isinstance(error, app_commands.MissingPermissions):
            message = "You don't have permission to use this command."
        elif isinstance(error, app_commands.CheckFailure):
            message = "You're not allowed to use this command here."
        else:
            log.exception("Moderation command failed: %s", error)
            message = f"Command failed: {error}"
        try:
            await self._refuse(interaction, message)
        except discord.HTTPException:
            log.warning("Could not deliver moderation error reply: %s", error)


async def setup(bot: commands.Bot) -> None:  # pragma: no cover - loaded manually
    await bot.add_cog(ModerationCog(bot))
