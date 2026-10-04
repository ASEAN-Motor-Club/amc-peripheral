"""Async HTTP client for Liquidsoap harbor API (localhost:6001)."""

import contextlib
import json
import logging
from urllib.parse import quote

import aiohttp

logger = logging.getLogger("liquidsoap_controller")

LIQUIDSOAP_API_BASE = "http://localhost:6001"


class QueuePushError(Exception):
    """The liquidsoap queue rejected the request — the song did NOT queue.

    Raised by push_to_queue when the harbor answers non-200 (bad URI,
    resolve failure, queue error) or when the HTTP call itself fails.
    The message carries liquidsoap's own resolve trace when available.
    """

    def __init__(self, status: int | None, detail: str):
        self.status = status
        self.detail = detail
        super().__init__(f"liquidsoap /push failed ({status}): {detail}")


class LiquidsoapController:
    """
    Controls Liquidsoap via its harbor HTTP API.

    All methods are async and require an aiohttp.ClientSession.
    """

    def __init__(
        self, base_url: str = LIQUIDSOAP_API_BASE, timeout: int = 30
    ):
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
        intro: str | None = None,
    ) -> str | None:
        """Push a URI to the Liquidsoap request queue via HTTP.

        Metadata is sent via Liquidsoap's annotate: protocol. The annotated
        URI is URL-encoded so that '=' signs in annotations don't confuse
        Liquidsoap's query-string parser (which would split on them).

        `intro` is a path to an audio file that Liquidsoap's insert_intro
        transition plays immediately before this track (see radio/liquidsoap.nix).

        The harbor handler resolves the request (parse + local-file +
        decodability check) BEFORE queueing: a 200 means the request is
        verified queueable and the response body carries its request ID
        (RID); anything else raises QueuePushError with the resolve trace.
        Returns the RID on success, None if the response predates the RID
        field.

        Raises:
            QueuePushError: the request was not accepted (or the harbor
                could not be reached) — callers should surface this to the
                requester instead of silently dropping the song.
        """
        annotated_uri = uri
        annotations = []
        if title:
            safe_title = self._sanitize_annotation(title)
            annotations.append(f'title="{safe_title}"')
        if requester:
            safe_requester = self._sanitize_annotation(requester)
            annotations.append(f'requester="{safe_requester}"')
        if intro:
            safe_intro = self._sanitize_annotation(intro)
            annotations.append(f'intro="{safe_intro}"')
        if annotations:
            annotated_uri = f"annotate:{','.join(annotations)}:{uri}"

        # Single-encode the value: the harbor decodes the query value once.
        # PR #97's double-encode broke every push on Liquidsoap 2.3.0 — the
        # extra layer left the annotate keys unreadable ("Unknown protocol
        # \"requester=...\"") and every request died with Fetch failed.
        # Single encoding also survives '?' in titles (verified live).
        uri_value = quote(annotated_uri, safe="/:")
        url = f"{self.base_url}/push?uri={uri_value}"
        try:
            async with self._fresh_post(url) as resp:
                body = await resp.text()
                if resp.status != 200:
                    logger.error(
                        f"Push rejected by {queue_name} ({resp.status}): {body}"
                    )
                    raise QueuePushError(resp.status, body)
                try:
                    data = json.loads(body)
                except ValueError:
                    logger.warning(
                        f"Push to {queue_name} returned unparseable body: {body}"
                    )
                    return None
                rid = data.get("id")
                logger.info(
                    f"Pushed {uri} to {queue_name}"
                    + (f" (rid={rid})" if rid else "")
                )
                return str(rid) if rid is not None else None
        except QueuePushError:
            raise
        except Exception as e:
            logger.error(f"Error pushing to queue {queue_name}: {e}")
            raise QueuePushError(None, f"harbor unreachable: {e}") from e

    async def get_queue_length(
        self, session: aiohttp.ClientSession, queue_name: str
    ) -> int | None:
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
