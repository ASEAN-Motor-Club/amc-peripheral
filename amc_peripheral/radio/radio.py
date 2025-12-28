import asyncio
import aiohttp
import logging
import discord
from discord.ext import commands
from amc_peripheral.settings import DISCORD_TOKEN, GUILD_ID
from amc_peripheral.radio.radio_cog import RadioCog

log = logging.getLogger(__name__)

class AMCBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.messages = True
        intents.message_content = True
        intents.members = True
        intents.voice_states = True
        super().__init__(command_prefix="/", intents=intents)
        self.http_session = None

    async def setup_hook(self):
        self.http_session = aiohttp.ClientSession()
        
        # Load Cog
        await self.add_cog(RadioCog(self))
        
        # Sync tree
        guild = discord.Object(id=GUILD_ID)
        self.tree.copy_global_to(guild=guild)
        synced = await self.tree.sync(guild=guild)
        log.info(f"Synced {len(synced)} commands to guild {GUILD_ID}")

    async def on_ready(self):
        log.info(f'Logged in as {self.user} (ID: {self.user.id})')
        log.info(f'Connected to {len(self.guilds)} guilds')
        for guild in self.guilds:
            log.info(f' - {guild.name} (ID: {guild.id})')
        log.info('------')

async def _async_main():
    bot = AMCBot()
    async with bot:
        await bot.start(DISCORD_TOKEN)

def main():
    discord.utils.setup_logging()
    try:
        asyncio.run(_async_main())
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    main()
