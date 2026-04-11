import logging
import aiohttp
import discord
from discord.ext import commands, tasks
from amc_peripheral.settings import (
    GAME_SERVER_API_URL,
    BACKEND_API_URL,
    STATUS_CHANNEL_ID,
)

log = logging.getLogger(__name__)

# Channel name constants
STATUS_ONLINE = "🟢-status"
STATUS_OFFLINE = "🔴-status"

# How many consecutive failures before we consider the server offline
FAILURE_THRESHOLD = 3

# Health check timeout in seconds
HEALTH_CHECK_TIMEOUT = 5


class StatusCog(commands.Cog):
    """Monitors connectivity to asean-mt-server and updates a Discord channel name."""

    def __init__(self, bot):
        self.bot = bot
        self.is_online = True  # Assume online at start
        self.consecutive_failures = 0

    async def cog_load(self):
        self.check_server_status.start()

    async def cog_unload(self):
        self.check_server_status.cancel()

    async def _check_endpoint(self, url: str) -> bool:
        """Check if a single endpoint is reachable and returns 2xx."""
        timeout = aiohttp.ClientTimeout(total=HEALTH_CHECK_TIMEOUT)
        try:
            async with self.bot.http_session.get(url, timeout=timeout) as resp:
                return resp.status < 400
        except Exception:
            return False

    async def _check_health(self) -> bool:
        """Check if game server and backend are both reachable."""
        game_ok = await self._check_endpoint(
            f"{GAME_SERVER_API_URL}/status/general"
        )
        backend_ok = await self._check_endpoint(
            f"{BACKEND_API_URL}/api/status/"
        )

        if not game_ok:
            log.debug("Health check failed: game server unreachable")
        if not backend_ok:
            log.debug("Health check failed: backend API unreachable")

        return game_ok and backend_ok

    async def _update_channel_name(self, name: str):
        """Update the status channel name."""
        channel = self.bot.get_channel(STATUS_CHANNEL_ID)
        if not channel:
            log.warning(f"Status channel {STATUS_CHANNEL_ID} not found")
            return

        if channel.name == name:
            return  # Already correct, skip API call

        # DISABLED: Channel renaming triggers Discord 429 rate limits, 
        # which heavily sleep the main event loop and cause translation delays.
        log.info(f"Status channel would have updated to: {name} (disabled to prevent rate limit)")
        # try:
        #     await channel.edit(name=name)
        #     log.info(f"Status channel updated to: {name}")
        # except discord.HTTPException as e:
        #     log.error(f"Failed to update status channel name: {e}")

    @tasks.loop(seconds=30)
    async def check_server_status(self):
        healthy = await self._check_health()

        if healthy:
            self.consecutive_failures = 0
            if not self.is_online:
                # Transition: offline → online
                self.is_online = True
                log.info("Server is back online")
                await self._update_channel_name(STATUS_ONLINE)
        else:
            self.consecutive_failures += 1
            if self.is_online and self.consecutive_failures >= FAILURE_THRESHOLD:
                # Transition: online → offline (after sustained failures)
                self.is_online = False
                log.warning(
                    f"Server marked offline after {self.consecutive_failures} "
                    f"consecutive failures"
                )
                await self._update_channel_name(STATUS_OFFLINE)

    @check_server_status.before_loop
    async def before_check_server_status(self):
        await self.bot.wait_until_ready()
