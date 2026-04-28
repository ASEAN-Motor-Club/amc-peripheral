import asyncio
import aiohttp
import logging
import discord
from discord.ext import commands
from ..settings import DISCORD_TOKEN, GUILD_ID
from .knowledge_cog import KnowledgeCog
from .translation_cog import TranslationCog
from .utils_cog import UtilsCog
from .share_cog import ShareCog
from .status_cog import StatusCog
from .auction_cog import AuctionCog
from .economy_cog import EconomyCog
from .youtube_cog import YouTubeCog
from .role_cog import RoleCog

log = logging.getLogger(__name__)


class AMCBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        super().__init__(command_prefix="/", intents=intents)
        self.http_session = None

    async def setup_hook(self):
        self.http_session = aiohttp.ClientSession()
        # Load Cogs
        await self.add_cog(KnowledgeCog(self))
        await self.add_cog(TranslationCog(self))
        await self.add_cog(UtilsCog(self))
        await self.add_cog(ShareCog(self))
        await self.add_cog(YouTubeCog(self))
        await self.add_cog(StatusCog(self))
        await self.add_cog(RoleCog(self))
        await self.add_cog(AuctionCog(self))
        await self.add_cog(EconomyCog(self))

        # Sync tree
        guild = discord.Object(id=GUILD_ID)
        self.tree.copy_global_to(guild=guild)
        synced = await self.tree.sync(guild=guild)
        log.info(f"Synced {len(synced)} commands to guild {GUILD_ID}")

        # Add /sync command
        @commands.is_owner()
        async def sync_prefix(ctx):
            guild = discord.Object(id=GUILD_ID)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            await ctx.send(
                f"✅ Manually synced {len(synced)} commands to guild {GUILD_ID} via /sync"
            )

        self.add_command(commands.Command(sync_prefix, name="sync"))

    async def on_ready(self):
        # pyrefly: ignore [missing-attribute]
        log.info(f"Logged in as {self.user} (ID: {self.user.id})")
        log.info(f"Connected to {len(self.guilds)} guilds")
        for guild in self.guilds:
            log.info(f" - {guild.name} (ID: {guild.id})")
        log.info("------")

        # Tell systemd we're ready (Type=notify)
        import os
        import socket as sock_mod
        addr = os.environ.get("NOTIFY_SOCKET")
        if addr:
            if addr[0] == "@":
                addr = "\0" + addr[1:]
            try:
                s = sock_mod.socket(sock_mod.AF_UNIX, sock_mod.SOCK_DGRAM)
                s.connect(addr)
                s.sendall(b"READY=1")
                s.close()
                log.info("Sent READY=1 to systemd")
            except Exception as e:
                log.warning(f"Failed to send READY=1: {e}")


async def _async_main():
    bot = AMCBot()
    async with bot:
        # pyrefly: ignore [bad-argument-type]
        await bot.start(DISCORD_TOKEN)


def main():
    discord.utils.setup_logging()
    try:
        asyncio.run(_async_main())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
