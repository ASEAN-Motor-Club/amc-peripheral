"""Async HTTP client for Liquidsoap harbor API (localhost:6001)."""

import contextlib
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

    @contextlib.asynccontextmanager
    async def _fresh_post(self, url: str):
        """POST with a disposable connection.

        Liquidsoap's harbor HTTP server doesn't support keep-alive
        reliably — reusing connections from the shared aiohttp session
        causes 'Server disconnected' errors.  This creates a one-shot
        connector so each POST gets a fresh TCP connection.
        """
        conn = aiohttp.TCPConnector(force_close=True)
        async with aiohttp.ClientSession(connector=conn) as s:
            async with s.post(url, timeout=self.timeout) as resp:
                yield resp

    @staticmethod
    def _sanitize_annotation(value: str) -> str:
        """Remove chars that break Liquidsoap annotate: syntax.

        Double-quotes in values cause Liquidsoap to misparse the URI
        (e.g., requester="freeman":/path is read as protocol "freeman").
        """
        return value.replace('"', '').replace(',', ' ').replace(':', ' ')

    async def push_to_queue(
        self, session: aiohttp.ClientSession, queue_name: str, uri: str,
        title: str | None = None, requester: str | None = None,
    ) -> bool:
        """Push a URI to the Liquidsoap request queue via HTTP.

        Metadata is sent via Liquidsoap's annotate: protocol. The annotated
        URI is URL-encoded so that '=' signs in annotations don't confuse
        Liquidsoap's query-string parser (which would split on them).
        """
        annotated_uri = uri
        annotations = []
        if title:
            safe_title = self._sanitize_annotation(title)
            annotations.append(f'title="{safe_title}"')
        if requester:
            safe_requester = self._sanitize_annotation(requester)
            annotations.append(f'requester="{safe_requester}"')
        if annotations:
            annotated_uri = f"annotate:{','.join(annotations)}:{uri}"

        # Do NOT include '=' in safe chars — Liquidsoap's harbor query
        # parser splits on bare '=' and corrupts annotate key=value pairs.
        url = f"{self.base_url}/push?uri={quote(annotated_uri, safe='/:')}"
        try:
            async with self._fresh_post(url) as resp:
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
            async with self._fresh_post(url) as resp:
                if resp.status == 200:
                    logger.info(f"Skipped current track on {source_name}")
                    return True
                logger.warning(f"Failed to skip track: {resp.status}")
                return False
        except Exception as e:
            logger.error(f"Error skipping track on {source_name}: {e}")
            return False

    async def push_announcement(
        self, session: aiohttp.ClientSession, uri: str,
    ) -> bool:
        """Push a URI to the Liquidsoap announcements queue via HTTP.

        This queue is overlaid on top of the main radio using smooth_add,
        ducking the music volume while the announcement plays.
        """
        url = f"{self.base_url}/push_announcement?uri={quote(uri, safe='/:')}"
        try:
            async with self._fresh_post(url) as resp:
                if resp.status == 200:
                    logger.info(f"Pushed announcement: {uri}")
                    return True
                body = await resp.text()
                logger.warning(
                    f"Failed to push announcement: {resp.status} {body}"
                )
                return False
        except Exception as e:
            logger.error(f"Error pushing announcement: {e}")
            return False

    async def push_segment(
        self, session: aiohttp.ClientSession, uri: str,
    ) -> bool:
        """Push a URI to the Liquidsoap segments queue via HTTP.

        This queue takes priority over the talkshows_or_jingles rotation,
        ensuring generated segments play in the talking slot (not the music slot).
        """
        url = f"{self.base_url}/push_segment?uri={quote(uri, safe='/:')}"
        try:
            async with self._fresh_post(url) as resp:
                if resp.status == 200:
                    logger.info(f"Pushed segment: {uri}")
                    return True
                body = await resp.text()
                logger.warning(
                    f"Failed to push segment: {resp.status} {body}"
                )
                return False
        except Exception as e:
            logger.error(f"Error pushing segment: {e}")
            return False

    async def get_current_source(
        self, session: aiohttp.ClientSession,
    ) -> str | None:
        """Get the current source type ('music' or 'talking').

        Returns None on error.
        """
        url = f"{self.base_url}/current_source"
        try:
            async with session.get(url, timeout=self.timeout) as resp:
                data = await resp.json()
                return data.get("source_type")
        except Exception as e:
            logger.error(f"Error getting current source: {e}")
            return None

    async def set_var(
        self, session: aiohttp.ClientSession, name: str, value: str
    ) -> bool:
        """Set a Liquidsoap interactive variable via HTTP."""
        url = f"{self.base_url}/set_var?name={name}&value={value}"
        try:
            async with self._fresh_post(url) as resp:
                if resp.status == 200:
                    logger.info(f"Set {name} = {value}")
                    return True
                logger.warning(f"Failed to set {name}: {resp.status}")
                return False
        except Exception as e:
            logger.error(f"Error setting var {name}: {e}")
            return False
