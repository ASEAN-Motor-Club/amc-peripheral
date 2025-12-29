import asyncio
import aiohttp
import logging
import discord
from discord.ext import commands
from ..settings import DISCORD_TOKEN, GUILD_ID
from .knowledge_cog import KnowledgeCog
from .utils_cog import UtilsCog

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
        await self.add_cog(UtilsCog(self))

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
