"""Async HTTP client for Liquidsoap harbor API (localhost:6001)."""

import logging
from typing import Optional
from urllib.parse import quote

import aiohttp

logger = logging.getLogger("liquidsoap_controller")

LIQUIDSOAP_API_BASE = "http://localhost:6001"


class LiquidsoapController:
    """
    Controls Liquidsoap via its harbor HTTP API.

    All methods are async and require an aiohttp.ClientSession.
    """

    def __init__(self, base_url: str = LIQUIDSOAP_API_BASE, timeout: int = 5):
        self.base_url = base_url
        self.timeout = aiohttp.ClientTimeout(total=timeout)

    async def push_to_queue(
        self, session: aiohttp.ClientSession, queue_name: str, uri: str,
        title: str | None = None, requester: str | None = None,
    ) -> bool:
        """Push a URI to the Liquidsoap request queue via HTTP."""
        # Annotate URI with metadata if provided
        annotated_uri = uri
        annotations = []
        if title:
            safe_title = title.replace('"', '\\"')
            annotations.append(f'title="{safe_title}"')
        if requester:
            safe_requester = requester.replace('"', '\\"')
            annotations.append(f'requester="{safe_requester}"')
        if annotations:
            annotated_uri = f"annotate:{','.join(annotations)}:{uri}"

        url = f"{self.base_url}/push?uri={quote(annotated_uri, safe='/:\"=,')}"
        try:
            async with session.post(url, timeout=self.timeout) as resp:
                if resp.status == 200:
                    logger.info(f"Pushed {uri} to {queue_name}")
                    return True
                body = await resp.text()
                logger.warning(
                    f"Failed to push {uri} to {queue_name}: {resp.status} {body}"
                )
                return False
        except Exception as e:
            logger.error(f"Error pushing to queue {queue_name}: {e}")
            return False

    async def get_queue_length(
        self, session: aiohttp.ClientSession, queue_name: str
    ) -> Optional[int]:
        """Get the number of pending items in the request queue."""
        url = f"{self.base_url}/queue_length"
        try:
            async with session.get(url, timeout=self.timeout) as resp:
                data = await resp.json()
                return data.get("length")
        except Exception as e:
            logger.error(f"Error getting queue length for {queue_name}: {e}")
            return None

    async def skip_current_track(
        self, session: aiohttp.ClientSession, source_name: str = "radio"
    ) -> bool:
        """Skip the current track via HTTP."""
        url = f"{self.base_url}/skip"
        try:
            async with session.post(url, timeout=self.timeout) as resp:
                if resp.status == 200:
                    logger.info(f"Skipped current track on {source_name}")
                    return True
                logger.warning(f"Failed to skip track: {resp.status}")
                return False
        except Exception as e:
            logger.error(f"Error skipping track on {source_name}: {e}")
            return False

    async def set_var(
        self, session: aiohttp.ClientSession, name: str, value: str
    ) -> bool:
        """Set a Liquidsoap interactive variable via HTTP."""
        url = f"{self.base_url}/set_var?name={name}&value={value}"
        try:
            async with session.post(url, timeout=self.timeout) as resp:
                if resp.status == 200:
                    logger.info(f"Set {name} = {value}")
                    return True
                logger.warning(f"Failed to set {name}: {resp.status}")
                return False
        except Exception as e:
            logger.error(f"Error setting var {name}: {e}")
            return False
