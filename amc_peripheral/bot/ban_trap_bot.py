import logging

import discord
from discord.ext import commands

from .ban_trap_cog import BanTrapCog
from ..settings import DISCORD_TOKEN_MALKUTH

log = logging.getLogger(__name__)


class BanTrapBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        super().__init__(command_prefix="/", intents=intents)

    async def setup_hook(self) -> None:
        await self.add_cog(BanTrapCog(self))

    async def on_ready(self):
        log.info("malkuth online: %s", self.user)


async def _async_main():
    bot = BanTrapBot()
    async with bot:
        await bot.start(DISCORD_TOKEN_MALKUTH)


def main():
    if not DISCORD_TOKEN_MALKUTH:
        raise RuntimeError("DISCORD_TOKEN_MALKUTH not set")
    discord.utils.setup_logging()
    try:
        import asyncio
        asyncio.run(_async_main())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
