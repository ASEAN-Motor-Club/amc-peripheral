"""Keep a member's workshop claims in step with what the game server says.

Claims are derived, never requested: the backend knows which character GUIDs
belong to a Discord user, and a workshop row whose GUID is in that set is that
user's build. Editing rights follow the same rule, so a sync that stops seeing
a GUID (character deleted, re-minted, or the account changed) revokes the claim
rather than leaving a stale badge.

The sync runs off page loads, so it is throttled per member — a gallery of
twenty snapshots must not become twenty Postgres queries.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

log = logging.getLogger(__name__)

SYNC_INTERVAL = 60.0


class ClaimSynchroniser:
    """Reconciles stored claims against the player's current characters."""

    def __init__(
        self,
        store: Any,
        repository: Any,
        identities: Any,
        *,
        interval: float = SYNC_INTERVAL,
        clock: Callable[[], float] = time.monotonic,
        limit: int = 60,
    ):
        self.store = store
        self.repository = repository
        self.identities = identities
        self.interval = interval
        self.clock = clock
        self.limit = limit
        self._last: dict[str, float] = {}

    def sync(
        self, discord_id: str, *, now: str, force: bool = False
    ) -> tuple[int, int]:
        """Claim what the member owns, revoke what they no longer do.

        Returns ``(claimed, revoked)``. Never raises: a backend hiccup must not
        turn a gallery page into a 500.
        """
        key = str(discord_id)
        started = self.clock()
        last = self._last.get(key)
        if not force and last is not None and started - last < self.interval:
            return (0, 0)
        self._last[key] = started

        try:
            identity = self.identities.identity_for(key)
            if identity is None or not identity.character_guids:
                return (0, 0)
            owned = self.repository.items_for_guids(
                identity.character_guids, limit=self.limit
            )
        except Exception as exc:  # noqa: BLE001 - page load must survive this
            log.warning("claim sync unavailable for %s: %s", key, exc)
            return (0, 0)

        owned_ids = {int(item["id"]) for item in owned}
        claimed = 0
        for item in owned:
            guid = item.get("characterGuid") or ""
            try:
                if self.store.upsert_claim(
                    workshop_id=int(item["id"]),
                    discord_id=key,
                    steam_id=str(identity.steam_id),
                    character_guid=guid,
                    now=now,
                ):
                    claimed += 1
            except Exception as exc:  # noqa: BLE001
                log.warning("claim write failed for %s/%s: %s", key, item["id"], exc)

        revoked = 0
        for workshop_id, claim in self.store.claims_for(key).items():
            if claim.revoked_at is None and workshop_id not in owned_ids:
                try:
                    self.store.revoke_claim(workshop_id, now)
                    revoked += 1
                except Exception as exc:  # noqa: BLE001
                    log.warning(
                        "claim revoke failed for %s/%s: %s", key, workshop_id, exc
                    )

        if claimed or revoked:
            log.info("claim sync %s: claimed=%d revoked=%d", key, claimed, revoked)
        return (claimed, revoked)
