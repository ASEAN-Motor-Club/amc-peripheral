"""Discord Cog for Sharry file sharing integration."""

import logging
import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timedelta
from ..settings import SHARRY_API_URL, SHARRY_ACCOUNT, SHARRY_PASSWORD

log = logging.getLogger(__name__)


class SharryClient:
    """Async client for Sharry REST API."""

    def __init__(self, session, base_url: str):
        self.session = session
        self.base_url = base_url.rstrip("/")
        self.token = None

    async def login(self, account: str, password: str) -> bool:
        """Login to Sharry and store the auth token."""
        url = f"{self.base_url}/api/v2/open/auth/login"
        payload = {"account": account, "password": password}
        async with self.session.post(url, json=payload) as resp:
            if resp.status != 200:
                log.error(f"Sharry login failed: {resp.status}")
                return False
            data = await resp.json()
            if data.get("success"):
                self.token = data.get("token")
                return True
            log.error(f"Sharry login failed: {data.get('message')}")
            return False

    def _headers(self) -> dict:
        """Return headers with auth token."""
        return {"Sharry-Auth": self.token} if self.token else {}

    async def create_alias(
        self, name: str, validity_ms: int = 172800000
    ) -> str | None:
        """Create a temporary alias for file uploads.

        Args:
            name: Name for the alias
            validity_ms: How long files are valid (default 48 hours)

        Returns:
            Alias ID if successful, None otherwise
        """
        url = f"{self.base_url}/api/v2/sec/alias"
        payload = {
            "name": name,
            "validity": validity_ms,
            "enabled": True,
            "members": [],
        }
        async with self.session.post(
            url, json=payload, headers=self._headers()
        ) as resp:
            if resp.status != 200:
                log.error(f"Sharry create alias failed: {resp.status}")
                return None
            data = await resp.json()
            if data.get("success"):
                return data.get("id")
            log.error(f"Sharry create alias failed: {data.get('message')}")
            return None

    async def upload_file(
        self, alias_id: str, filename: str, content: bytes, content_type: str
    ) -> str | None:
        """Upload a file to an alias.

        Args:
            alias_id: The alias ID to upload to
            filename: Name of the file
            content: File content as bytes
            content_type: MIME type of the file

        Returns:
            Share ID if successful, None otherwise
        """
        url = f"{self.base_url}/api/v2/alias/upload"
        headers = {"Sharry-Alias": alias_id}

        # Create multipart form data
        data = discord.utils.MISSING
        form = discord.utils.MISSING
        try:
            import aiohttp

            form = aiohttp.FormData()
            form.add_field(
                "file", content, filename=filename, content_type=content_type
            )
            async with self.session.post(url, data=form, headers=headers) as resp:
                if resp.status != 200:
                    log.error(f"Sharry upload failed: {resp.status}")
                    return None
                data = await resp.json()
                if data.get("success"):
                    return data.get("id")
                log.error(f"Sharry upload failed: {data.get('message')}")
                return None
        except Exception as e:
            log.error(f"Sharry upload error: {e}")
            return None

    async def publish_share(self, share_id: str) -> str | None:
        """Publish a share and get the public URL.

        Args:
            share_id: The share ID to publish

        Returns:
            Public URL if successful, None otherwise
        """
        url = f"{self.base_url}/api/v2/sec/share/{share_id}/publish"
        async with self.session.post(url, headers=self._headers()) as resp:
            if resp.status != 200:
                log.error(f"Sharry publish failed: {resp.status}")
                return None
            data = await resp.json()
            if data.get("success"):
                publish_id = data.get("id")
                return f"{self.base_url}/app/open/{publish_id}"
            log.error(f"Sharry publish failed: {data.get('message')}")
            return None

    async def get_share_details(self, share_id: str) -> dict | None:
        """Get details about a share."""
        url = f"{self.base_url}/api/v2/sec/share/{share_id}"
        async with self.session.get(url, headers=self._headers()) as resp:
            if resp.status != 200:
                return None
            return await resp.json()


class ShareCog(commands.Cog):
    """Discord commands for Sharry file sharing integration."""

    def __init__(self, bot):
        self.bot = bot
        self.sharry = None

    async def _ensure_client(self) -> SharryClient | None:
        """Ensure we have an authenticated Sharry client."""
        if self.sharry is None:
            self.sharry = SharryClient(self.bot.http_session, SHARRY_API_URL)

        if self.sharry.token is None:
            if not SHARRY_ACCOUNT or not SHARRY_PASSWORD:
                log.warning("Sharry credentials not configured")
                return None
            if not await self.sharry.login(SHARRY_ACCOUNT, SHARRY_PASSWORD):
                return None

        return self.sharry

    @app_commands.command(name="share", description="Upload a file and get a share link")
    @app_commands.describe(
        file="The file to upload and share",
        description="Optional description for the share",
        validity_days="How long the share link is valid (default: 7 days)",
    )
    async def share_cmd(
        self,
        interaction: discord.Interaction,
        file: discord.Attachment,
        description: str | None = None,
        validity_days: int = 7,
    ):
        """Upload a file to Sharry and return a public share link."""
        await interaction.response.defer(ephemeral=True)

        # Validate file size (100MB limit)
        max_size = 100 * 1024 * 1024  # 100MB
        if file.size > max_size:
            await interaction.followup.send(
                f"❌ File too large. Maximum size is 100MB, your file is {file.size / (1024*1024):.1f}MB.",
                ephemeral=True,
            )
            return

        client = await self._ensure_client()
        if client is None:
            await interaction.followup.send(
                "❌ Sharry service is not configured. Please contact an administrator.",
                ephemeral=True,
            )
            return

        try:
            # Create alias for this upload
            alias_name = f"discord-{interaction.user.name}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
            validity_ms = validity_days * 24 * 60 * 60 * 1000
            alias_id = await client.create_alias(alias_name, validity_ms)
            if not alias_id:
                await interaction.followup.send(
                    "❌ Failed to create upload link. Please try again.",
                    ephemeral=True,
                )
                return

            # Download file from Discord
            file_content = await file.read()

            # Upload to Sharry
            share_id = await client.upload_file(
                alias_id, file.filename, file_content, file.content_type or "application/octet-stream"
            )
            if not share_id:
                await interaction.followup.send(
                    "❌ Failed to upload file. Please try again.",
                    ephemeral=True,
                )
                return

            # Publish the share
            public_url = await client.publish_share(share_id)
            if not public_url:
                await interaction.followup.send(
                    "❌ Failed to publish share. Please try again.",
                    ephemeral=True,
                )
                return

            # Create response embed
            expiry_date = datetime.now() + timedelta(days=validity_days)
            embed = discord.Embed(
                title="📤 File Shared Successfully",
                color=discord.Color.green(),
            )
            embed.add_field(name="File", value=file.filename, inline=True)
            embed.add_field(
                name="Size", value=f"{file.size / 1024:.1f} KB", inline=True
            )
            embed.add_field(
                name="Expires",
                value=f"<t:{int(expiry_date.timestamp())}:R>",
                inline=True,
            )
            embed.add_field(name="Link", value=public_url, inline=False)
            if description:
                embed.add_field(name="Description", value=description, inline=False)
            embed.set_footer(text=f"Shared by {interaction.user.display_name}")

            await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            log.exception(f"Error in /share command: {e}")
            await interaction.followup.send(
                f"❌ An error occurred: {str(e)}",
                ephemeral=True,
            )


async def setup(bot):
    await bot.add_cog(ShareCog(bot))
