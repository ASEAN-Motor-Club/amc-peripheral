import logging
from asyncio import Lock

from discord.ext import commands

from .settings import (
    BAN_TRAP_ALLOWED_ROLE_IDS,
    BAN_TRAP_ANNOUNCEMENT,
    BAN_TRAP_AUTO_DELETE_ANNOUNCEMENT,
    BAN_TRAP_CHANNEL_ID,
    BAN_TRAP_CLEANUP_WINDOW_SECONDS,
    BAN_TRAP_DELETE_DELAY_SECONDS,
    GUILD_ID,
)

log = logging.getLogger(__name__)


class BanTrapCog(commands.Cog):
    """Bans users without exempt roles from the configured channel."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._processing: dict[int, Lock] = {}

    async def cog_load(self) -> None:
        if not BAN_TRAP_ALLOWED_ROLE_IDS:
            raise RuntimeError("BAN_TRAP_ALLOWED_ROLE_IDS must not be empty")
        log.info(
            "BanTrapCog loaded: channel=%s, auto_delete=%s",
            BAN_TRAP_CHANNEL_ID,
            BAN_TRAP_AUTO_DELETE_ANNOUNCEMENT,
        )

    @staticmethod
    def _is_exempt(member) -> bool:
        return bool({r.id for r in member.roles} & BAN_TRAP_ALLOWED_ROLE_IDS)

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author == self.bot.user:
            return
        if not message.guild:
            return
        if message.guild.id != GUILD_ID:
            return
        if message.channel.id != BAN_TRAP_CHANNEL_ID:
            return
        # Webhook messages have no banable author — ignore them.
        if message.webhook_id:
            return

        guild = message.guild
        author_id = message.author.id

        member = guild.get_member(author_id)
        if member is None:
            try:
                member = await guild.fetch_member(author_id)
            except Exception:
                member = None
        if member and self._is_exempt(member):
            return

        target = member or message.author
        if author_id not in self._processing:
            self._processing[author_id] = Lock()
        lock = self._processing[author_id]
        if lock.locked():
            return
        try:
            async with lock:
                try:
                    await guild.ban(
                        target,
                        reason="ban trap",
                        delete_message_seconds=BAN_TRAP_CLEANUP_WINDOW_SECONDS,
                    )
                except Exception as e:
                    # Don't announce a ban that didn't happen. The bot may lack
                    # Ban Members, or the target may outrank it (owner/admin).
                    log.warning("Failed to ban %s (id=%s): %s", target, author_id, e)
                    return
                if BAN_TRAP_ANNOUNCEMENT:
                    try:
                        sent = await message.channel.send(BAN_TRAP_ANNOUNCEMENT)
                        if BAN_TRAP_AUTO_DELETE_ANNOUNCEMENT and sent:
                            await sent.delete(delay=BAN_TRAP_DELETE_DELAY_SECONDS)
                    except Exception as e:
                        log.debug("Failed to post announcement: %s", e)
        finally:
            # Drop the per-author lock entry once we're done with it.
            self._processing.pop(author_id, None)
