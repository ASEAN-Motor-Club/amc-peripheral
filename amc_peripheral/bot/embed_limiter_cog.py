"""Discord Cog for limiting GIF/embed posts per channel."""

import logging
import re
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands, tasks
from sqlite_utils import Database

from amc_peripheral.settings import (
    EMBED_LIMITER_ENABLED,
    EMBED_LIMITER_CHANNELS,
    RADIO_DB_PATH,
)

log = logging.getLogger(__name__)

GIF_URL_PATTERN = re.compile(
    r"https?://\S+\.gif(?:\?\S*)?(?:#\S*)?$", re.IGNORECASE
)
TENOR_PATTERN = re.compile(r"https?://tenor\.com/view/\S+", re.IGNORECASE)
GIPHY_PATTERN = re.compile(r"https?://(?:giphy\.com/gifs/\S+|media\.giphy\.com/\S+)", re.IGNORECASE)


class EmbedLimiterDB:
    def __init__(self, db_path: str):
        self.db = Database(db_path)
        self.db.conn.execute("PRAGMA busy_timeout = 5000")
        self._ensure_tables()

    def _ensure_tables(self):
        if "embed_usage" not in self.db.table_names():
            self.db["embed_usage"].create(
                {
                    "id": int,
                    "channel_id": str,
                    "user_id": str,
                    "message_id": str,
                    "content_type": str,
                    "posted_at": str,
                },
                pk="id",
            )
            self.db["embed_usage"].create_index(["channel_id", "posted_at"])
            self.db["embed_usage"].create_index(
                ["channel_id", "user_id", "posted_at"]
            )

        if "embed_exempt_users" not in self.db.table_names():
            self.db["embed_exempt_users"].create(
                {
                    "user_id": str,
                },
                pk="user_id",
            )

    def record_embed(
        self,
        channel_id: str,
        user_id: str,
        message_id: str,
        content_type: str,
    ) -> int | None:
        row = {
            "channel_id": channel_id,
            "user_id": user_id,
            "message_id": message_id,
            "content_type": content_type,
            "posted_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            return self.db["embed_usage"].insert(row).last_pk
        except Exception:
            return None

    def get_user_count(self, channel_id: str, user_id: str, since: str) -> int:
        rows = list(
            self.db.query(
                "SELECT COUNT(*) as cnt FROM embed_usage "
                "WHERE channel_id = ? AND user_id = ? AND posted_at > ?",
                [channel_id, user_id, since],
            )
        )
        return rows[0]["cnt"] if rows else 0

    def get_global_count(self, channel_id: str, since: str) -> int:
        rows = list(
            self.db.query(
                "SELECT COUNT(*) as cnt FROM embed_usage "
                "WHERE channel_id = ? AND posted_at > ?",
                [channel_id, since],
            )
        )
        return rows[0]["cnt"] if rows else 0

    def get_top_users(self, channel_id: str, since: str, limit: int = 10) -> list[dict]:
        return list(
            self.db.query(
                "SELECT user_id, COUNT(*) as count FROM embed_usage "
                "WHERE channel_id = ? AND posted_at > ? "
                "GROUP BY user_id ORDER BY count DESC LIMIT ?",
                [channel_id, since, limit],
            )
        )

    def prune_old(self, older_than: str) -> int:
        result = self.db.execute(
            "DELETE FROM embed_usage WHERE posted_at < ?", [older_than]
        )
        return result.rowcount or 0

    def is_exempt(self, user_id: str) -> bool:
        rows = list(
            self.db["embed_exempt_users"].rows_where("user_id = ?", [user_id])
        )
        return len(rows) > 0

    def add_exempt(self, user_id: str) -> bool:
        try:
            self.db["embed_exempt_users"].insert({"user_id": user_id}, replace=True)
            return True
        except Exception:
            return False

    def remove_exempt(self, user_id: str) -> bool:
        try:
            self.db.execute(
                "DELETE FROM embed_exempt_users WHERE user_id = ?", [user_id]
            )
            return True
        except Exception:
            return False

    def get_exempt_users(self) -> list[str]:
        return [row["user_id"] for row in self.db["embed_exempt_users"].rows]


def count_gifs_in_message(message: discord.Message) -> int:
    """Count the number of GIFs in a message (attachments + URLs + embeds)."""
    count = 0

    # Check attachments
    for att in message.attachments:
        if att.content_type and "gif" in att.content_type:
            count += 1

    # Check URLs in content
    count += len(GIF_URL_PATTERN.findall(message.content))
    count += len(TENOR_PATTERN.findall(message.content))
    count += len(GIPHY_PATTERN.findall(message.content))

    # Check Discord embeds (e.g. auto-embedded Tenor/Giphy)
    for embed in message.embeds:
        if embed.image and embed.image.url:
            if ".gif" in embed.image.url.lower():
                count += 1
        if embed.video and embed.video.url:
            if ".gif" in embed.video.url.lower():
                count += 1

    return count


class EmbedLimiterCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = EmbedLimiterDB(RADIO_DB_PATH)
        self._channel_configs: dict[str, dict] = {}

    async def cog_load(self):
        if not EMBED_LIMITER_ENABLED:
            log.info("Embed limiter is disabled via EMBED_LIMITER_ENABLED")
            return
        self._load_configs()
        self._prune_loop.start()
        log.info(
            "Embed limiter loaded with %d channel(s): %s",
            len(self._channel_configs),
            list(self._channel_configs.keys()),
        )

    async def cog_unload(self):
        self._prune_loop.cancel()

    def _load_configs(self):
        """Load channel configs from the settings env var."""
        self._channel_configs = {}
        for ch_id, raw in EMBED_LIMITER_CHANNELS.items():
            if not raw.get("enabled", True):
                continue
            self._channel_configs[ch_id] = {
                "per_user": int(raw.get("per_user", 5)),
                "global": int(raw.get("global", 30)),
                "window_hours": int(raw.get("window_hours", 24)),
            }

    def _window_start(self, hours: int) -> str:
        return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()

    def _get_config(self, channel_id: str) -> dict | None:
        return self._channel_configs.get(channel_id)

    @tasks.loop(hours=6)
    async def _prune_loop(self):
        cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        deleted = self.db.prune_old(cutoff)
        if deleted:
            log.info("Embed limiter pruned %d old records", deleted)

    @_prune_loop.before_loop
    async def _before_prune(self):
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not EMBED_LIMITER_ENABLED:
            return
        if message.author.bot:
            return

        channel_id = str(message.channel.id)
        config = self._get_config(channel_id)
        if not config:
            return

        gif_count = count_gifs_in_message(message)
        if gif_count == 0:
            return

        user_id = str(message.author.id)

        if self.db.is_exempt(user_id):
            self.db.record_embed(channel_id, user_id, str(message.id), "gif")
            return

        window_start = self._window_start(config["window_hours"])
        user_count = self.db.get_user_count(channel_id, user_id, window_start)
        global_count = self.db.get_global_count(channel_id, window_start)

        if user_count + gif_count > config["per_user"]:
            await self._reject(
                message,
                f"You've posted {user_count + gif_count}/{config['per_user']} GIFs "
                f"in the last {config['window_hours']}h. Limit is {config['per_user']}.",
            )
            return

        if global_count + gif_count > config["global"]:
            await self._reject(
                message,
                f"Channel GIF limit reached ({global_count + gif_count}/{config['global']}) "
                f"for the last {config['window_hours']}h.",
            )
            return

        for _ in range(gif_count):
            self.db.record_embed(channel_id, user_id, str(message.id), "gif")

    async def _reject(self, message: discord.Message, reason: str):
        try:
            await message.delete()
        except discord.Forbidden:
            log.warning("Missing permissions to delete message in #%s", message.channel.name)
        except discord.NotFound:
            pass

        await message.channel.send(
            f"{message.author.mention} {reason}",
            delete_after=15,
        )

    # --- Admin Commands ---

    embedlimit_group = app_commands.Group(
        name="embedlimit",
        description="Manage GIF/embed rate limits (Admin only)",
        default_permissions=discord.Permissions(administrator=True),
    )

    @embedlimit_group.command(
        name="enable", description="Enable GIF limits on a channel"
    )
    @app_commands.describe(
        channel="The channel to limit",
        per_user="Max GIFs per user in the window (default: 5)",
        global_limit="Max total GIFs in the channel in the window (default: 30)",
        window_hours="Time window in hours (default: 24)",
    )
    async def embedlimit_enable(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        per_user: int = 5,
        global_limit: int = 30,
        window_hours: int = 24,
    ):
        ch_id = str(channel.id)
        self._channel_configs[ch_id] = {
            "per_user": per_user,
            "global": global_limit,
            "window_hours": window_hours,
        }
        await interaction.response.send_message(
            f"Enabled GIF limits on {channel.mention}: "
            f"**{per_user}**/user, **{global_limit}** total per **{window_hours}h** window.",
            ephemeral=True,
        )

    @embedlimit_group.command(
        name="disable", description="Disable GIF limits on a channel"
    )
    @app_commands.describe(channel="The channel to unlimit")
    async def embedlimit_disable(
        self, interaction: discord.Interaction, channel: discord.TextChannel
    ):
        ch_id = str(channel.id)
        if ch_id in self._channel_configs:
            del self._channel_configs[ch_id]
            await interaction.response.send_message(
                f"Disabled GIF limits on {channel.mention}.", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"{channel.mention} was not being limited.", ephemeral=True
            )

    @embedlimit_group.command(
        name="config", description="Update GIF limits on a channel"
    )
    @app_commands.describe(
        channel="The channel to configure",
        per_user="Max GIFs per user",
        global_limit="Max total GIFs in the channel",
        window_hours="Time window in hours",
    )
    async def embedlimit_config(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        per_user: int | None = None,
        global_limit: int | None = None,
        window_hours: int | None = None,
    ):
        ch_id = str(channel.id)
        existing = self._get_config(ch_id)
        if not existing:
            return await interaction.response.send_message(
                f"{channel.mention} is not limited. Use `/embedlimit enable` first.",
                ephemeral=True,
            )
        if per_user is not None:
            existing["per_user"] = per_user
        if global_limit is not None:
            existing["global"] = global_limit
        if window_hours is not None:
            existing["window_hours"] = window_hours
        self._channel_configs[ch_id] = existing
        await interaction.response.send_message(
            f"Updated {channel.mention}: "
            f"**{existing['per_user']}**/user, **{existing['global']}** total per **{existing['window_hours']}h**.",
            ephemeral=True,
        )

    @embedlimit_group.command(
        name="status", description="Show current GIF usage on a channel"
    )
    @app_commands.describe(channel="The channel to check")
    async def embedlimit_status(
        self, interaction: discord.Interaction, channel: discord.TextChannel
    ):
        ch_id = str(channel.id)
        config = self._get_config(ch_id)
        if not config:
            return await interaction.response.send_message(
                f"{channel.mention} is not limited.", ephemeral=True
            )

        window_start = self._window_start(config["window_hours"])
        global_count = self.db.get_global_count(ch_id, window_start)
        top_users = self.db.get_top_users(ch_id, window_start, limit=5)

        embed = discord.Embed(
            title=f"GIF Usage — #{channel.name}",
            color=0x00AAFF,
        )
        embed.add_field(
            name="Global",
            value=f"{global_count} / {config['global']} per {config['window_hours']}h",
            inline=False,
        )
        embed.add_field(
            name="Per-user limit",
            value=f"{config['per_user']} per {config['window_hours']}h",
            inline=False,
        )

        if top_users:
            lines = []
            for row in top_users:
                member = interaction.guild.get_member(int(row["user_id"]))
                name = member.display_name if member else row["user_id"]
                lines.append(f"{name}: {row['count']}")
            embed.add_field(name="Top users", value="\n".join(lines), inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @embedlimit_group.command(
        name="exempt", description="Exempt or un-exempt a user from GIF limits"
    )
    @app_commands.describe(user="The user to toggle exemption for")
    async def embedlimit_exempt(
        self, interaction: discord.Interaction, user: discord.Member
    ):
        uid = str(user.id)
        if self.db.is_exempt(uid):
            self.db.remove_exempt(uid)
            await interaction.response.send_message(
                f"Removed exemption for {user.mention}.", ephemeral=True
            )
        else:
            self.db.add_exempt(uid)
            await interaction.response.send_message(
                f"Exempted {user.mention} from GIF limits.", ephemeral=True
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(EmbedLimiterCog(bot))
