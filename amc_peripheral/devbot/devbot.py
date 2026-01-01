"""
JARVIS - AMC Dev Bot

Main entry point for the JARVIS Discord bot.
"""

import asyncio
import aiohttp
import logging
import discord
from discord.ext import commands
from amc_peripheral.settings import DISCORD_TOKEN_DEV, GUILD_ID
from .devbot_cog import DevBotCog

log = logging.getLogger(__name__)


class AMCDevBot(commands.Bot):
    """JARVIS Discord Bot instance."""

    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(command_prefix="!", intents=intents)
        self.http_session = None

    async def setup_hook(self):
        """Initialize bot resources and load cogs."""
        self.http_session = aiohttp.ClientSession()

        # Load JARVIS Cog
        await self.add_cog(DevBotCog(self))

        # Sync slash commands to guild
        guild = discord.Object(id=GUILD_ID)
        self.tree.copy_global_to(guild=guild)
        synced = await self.tree.sync(guild=guild)
        log.info(f"JARVIS synced {len(synced)} commands to guild {GUILD_ID}")

    async def on_ready(self):
        """Called when bot is ready."""
        # pyrefly: ignore [missing-attribute]
        log.info(f"JARVIS logged in as {self.user} (ID: {self.user.id})")
        log.info(f"Connected to {len(self.guilds)} guilds")
        for guild in self.guilds:
            log.info(f" - {guild.name} (ID: {guild.id})")
        log.info("JARVIS is online and ready to assist!")


async def _async_main():
    """Async main entry point."""
    bot = AMCDevBot()
    async with bot:
        # pyrefly: ignore [bad-argument-type]
        await bot.start(DISCORD_TOKEN_DEV)


def main():
    """Main entry point for amc_jarvis command."""
    discord.utils.setup_logging()
    try:
        asyncio.run(_async_main())
    except KeyboardInterrupt:
        log.info("JARVIS shutting down...")


if __name__ == "__main__":
    main()
