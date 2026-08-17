"""Ingest orchestrator: raw sources -> wiki updates."""

import logging
from typing import Optional

from amc_peripheral.wiki.storage import WikiStorage
from amc_peripheral.wiki.retrieval import WikiRetrieval

log = logging.getLogger(__name__)


class WikiIngest:
    """Orchestrates the ingestion of raw sources into the wiki."""

    # Prevent pages from growing unbounded via repeated appends
    MAX_CONTENT_LENGTH = 50_000

    def __init__(self, storage: WikiStorage, retrieval: WikiRetrieval):
        self.storage = storage
        self.retrieval = retrieval

    def _merge_content(self, existing: str, new: str) -> str:
        """Append new content with a safeguard against unbounded growth."""
        merged = f"{existing}\n\n---\n\n{new}"
        if len(merged) > self.MAX_CONTENT_LENGTH:
            # Keep the most recent content (end) plus a truncation notice
            truncated = merged[-self.MAX_CONTENT_LENGTH:]
            # Find the first separator after the cutoff to start cleanly
            first_sep = truncated.find("\n\n---\n\n")
            if first_sep != -1:
                truncated = truncated[first_sep + len("\n\n---\n\n"):]
            merged = f"[Earlier content truncated]\n\n---\n\n{truncated}"
            log.warning(f"Page content truncated to {self.MAX_CONTENT_LENGTH} chars")
        return merged

    def ingest_conversation(
        self,
        player_id: str,
        player_name: str,
        messages: list[dict],
        extracted_facts: Optional[list[dict]] = None,
    ) -> list[int]:
        """Ingest a player conversation into the wiki.

        Args:
            player_id: Unique player identifier.
            player_name: Human-readable player name.
            messages: List of message dicts with keys: message, is_bot_response, timestamp.
            extracted_facts: Optional pre-extracted facts from an LLM call.
                Each fact dict should have: title, category, content, summary.

        Returns:
            List of affected page IDs.
        """
        affected_pages: list[int] = []
        source_id = f"conversation_{player_id}_{messages[-1]['timestamp'] if messages else 'unknown'}"

        # Ensure player page exists
        player_slug = f"player:{player_id}"
        player_page = self.storage.get_page_by_slug(player_slug)
        if not player_page:
            page_id = self.storage.create_page(
                title=f"player:{player_id}",
                category="player",
                content=f"Player: {player_name} (ID: {player_id})",
                summary=f"Profile for player {player_name}",
            )
            self.storage.add_source(page_id, "conversation", source_id)
            self.retrieval.index_page(
                page_id=page_id,
                title=f"player:{player_name}",
                content=f"Player: {player_name} (ID: {player_id})",
                category="player",
                updated_at=self.storage.get_page_by_id(page_id)["updated_at"],
            )
            affected_pages.append(page_id)
            log.info(f"Created player page for {player_name}")
        else:
            affected_pages.append(player_page["id"])

        # If pre-extracted facts are provided, create/update pages
        if extracted_facts:
            for fact in extracted_facts:
                page_id = self._apply_fact(fact, source_id)
                if page_id and page_id not in affected_pages:
                    affected_pages.append(page_id)

        # Log the ingest operation
        self.storage.log_operation(
            operation="ingest",
            description=f"Ingested conversation for {player_name} ({len(messages)} messages)",
            pages_affected=affected_pages,
        )
        return affected_pages

    def ingest_event(
        self,
        event_type: str,
        event_id: str,
        title: str,
        description: str,
        participants: Optional[list[str]] = None,
        extracted_facts: Optional[list[dict]] = None,
    ) -> list[int]:
        """Ingest a game or community event into the wiki.

        Args:
            event_type: Type of event (e.g. 'race', 'economy', 'incident').
            event_id: Unique event identifier.
            title: Event title.
            description: Event description.
            participants: Optional list of player IDs involved.
            extracted_facts: Optional pre-extracted facts.

        Returns:
            List of affected page IDs.
        """
        affected_pages: list[int] = []
        source_id = f"event_{event_type}_{event_id}"

        # Create or update event page
        event_slug = f"event:{event_id}"
        event_page = self.storage.get_page_by_slug(event_slug)
        if not event_page:
            page_id = self.storage.create_page(
                title=f"event:{title}",
                category="event",
                content=description,
                summary=f"{event_type} event: {title}",
            )
            self.storage.add_source(page_id, "event", source_id)
            self.retrieval.index_page(
                page_id=page_id,
                title=f"event:{title}",
                content=description,
                category="event",
                updated_at=self.storage.get_page_by_id(page_id)["updated_at"],
            )
            affected_pages.append(page_id)
        else:
            page_id = event_page["id"]
            # Append new description to existing content (with length safeguard)
            new_content = self._merge_content(event_page["content"], description)
            now = self.storage.get_page_by_id(page_id)["updated_at"]
            self.storage.update_page(page_id, content=new_content)
            self.storage.add_source(page_id, "event", source_id)
            self.retrieval.index_page(
                page_id=page_id,
                title=event_page["title"],
                content=new_content,
                category="event",
                updated_at=now,
            )
            affected_pages.append(page_id)

        # Link participant pages
        if participants:
            for player_id in participants:
                player_slug = f"player:{player_id}"
                player_page = self.storage.get_page_by_slug(player_slug)
                if player_page:
                    self.storage.add_link(page_id, player_page["id"], "involves")
                    self.storage.add_link(player_page["id"], page_id, "participated_in")
                    if player_page["id"] not in affected_pages:
                        affected_pages.append(player_page["id"])

        # Apply any extracted facts
        if extracted_facts:
            for fact in extracted_facts:
                fact_page_id = self._apply_fact(fact, source_id)
                if fact_page_id and fact_page_id not in affected_pages:
                    affected_pages.append(fact_page_id)

        self.storage.log_operation(
            operation="ingest",
            description=f"Ingested {event_type} event: {title}",
            pages_affected=affected_pages,
        )
        return affected_pages

    def _apply_fact(self, fact: dict, source_id: str) -> Optional[int]:
        """Apply a single extracted fact to the wiki.

        Args:
            fact: Dict with keys: title, category, content, summary (all optional except title).
            source_id: The source identifier to attribute.

        Returns:
            The affected page ID, or None.
        """
        title = fact.get("title")
        if not title:
            return None

        category = fact.get("category", "concept")
        content = fact.get("content", "")
        summary = fact.get("summary", "")

        slug = self.storage._make_slug(title)
        existing = self.storage.get_page_by_slug(slug)

        if existing:
            page_id = existing["id"]
            # Merge content if new content is provided and different
            if content and content != existing["content"]:
                merged = self._merge_content(existing["content"], content)
                self.storage.update_page(page_id, content=merged, summary=summary or existing["summary"])
            elif summary and summary != existing["summary"]:
                self.storage.update_page(page_id, summary=summary)
            self.storage.add_source(page_id, "fact_extraction", source_id)
            # Re-fetch once for ChromaDB indexing
            refreshed = self.storage.get_page_by_id(page_id)
            self.retrieval.index_page(
                page_id=page_id,
                title=existing["title"],
                content=refreshed["content"] if refreshed else content,
                category=existing["category"],
                updated_at=refreshed["updated_at"] if refreshed else "",
            )
            log.info(f"Updated wiki page: {title}")
        else:
            page_id = self.storage.create_page(
                title=title,
                category=category,
                content=content,
                summary=summary,
            )
            self.storage.add_source(page_id, "fact_extraction", source_id)
            refreshed = self.storage.get_page_by_id(page_id)
            self.retrieval.index_page(
                page_id=page_id,
                title=title,
                content=refreshed["content"] if refreshed else content,
                category=category,
                updated_at=refreshed["updated_at"] if refreshed else "",
            )
            log.info(f"Created wiki page: {title}")

        return page_id

    def ingest_player_profile(self, profile: dict) -> int | None:
        """Create/update a canonical player profile page from a PlayerIndex record.

        Keeps Annie's wiki consistent with the identity/alias index so generic
        wiki recall and the explicit ``player <name>`` lookup agree on who a
        player is and what nickname they asked for.

        Args:
            profile: A PlayerRecord summary dict with keys: name, aliases,
                game_ids, discord_ids, message_count, first_seen, last_seen,
                and optionally requested_nickname.

        Returns:
            The affected page ID, or None if no page could be created/updated.
        """
        canonical = self._player_canonical_id(profile)
        if not canonical:
            return None

        title = f"player:{canonical}"
        content = self._player_profile_content(profile)
        summary = self._player_profile_summary(profile)

        page = self.storage.get_page_by_slug(title)
        if page:
            if page["content"] == content and page["summary"] == summary:
                # Already current -- nothing to write. Ensure a source ref exists.
                self.storage.add_source(page["id"], "player_index", canonical)
                return page["id"]
            self.storage.update_page(page["id"], content=content, summary=summary)
            page_id = page["id"]
            category = page["category"] or "player"
            title_used = page["title"]
        else:
            page_id = self.storage.create_page(
                title=title, category="player", content=content, summary=summary
            )
            category = "player"
            title_used = title

        self.storage.add_source(page_id, "player_index", canonical)
        self._index_profile_page(
            page_id=page_id, title=title_used, content=content, category=category
        )
        self.storage.log_operation(
            operation="player_profile",
            description=f"Synced canonical profile for player {canonical}",
            pages_affected=[page_id],
        )
        return page_id

    @staticmethod
    def _player_canonical_id(profile: dict) -> str | None:
        """Pick a stable id for the profile page (game id, else discord id)."""
        game = profile.get("game_ids") or []
        if game and game[0]:
            return game[0]
        discord = profile.get("discord_ids") or []
        if discord and discord[0]:
            return discord[0]
        name = (profile.get("name") or "").strip()
        return name or None

    @staticmethod
    def _player_profile_summary(profile: dict) -> str:
        name = (profile.get("name") or "unknown").strip()
        nick = (profile.get("requested_nickname") or "").strip()
        if nick:
            return f"Profile for {name} (call me '{nick}')"
        return f"Profile for {name}"

    @staticmethod
    def _player_profile_content(profile: dict) -> str:
        lines = [f"# {profile.get('name') or 'Unknown'}"]
        aliases = profile.get("aliases") or []
        if aliases:
            lines.append(f"**Also known as:** {', '.join(str(a) for a in aliases)}")
        game = profile.get("game_ids") or []
        if game:
            lines.append(f"**Game ID(s):** {', '.join(str(i) for i in game)}")
        discord = profile.get("discord_ids") or []
        if discord:
            lines.append(f"**Discord ID(s):** {', '.join(str(i) for i in discord)}")
        nick = profile.get("requested_nickname")
        if nick:
            lines.append(f"**Requested nickname:** {nick}")
        if profile.get("first_seen") or profile.get("last_seen"):
            span = f"{profile.get('first_seen') or '?'} -> {profile.get('last_seen') or '?'}"
            lines.append(f"**Active window:** {span}")
        if profile.get("message_count") is not None:
            lines.append(f"**Messages in memory:** {profile['message_count']}")
        return "\n".join(lines)

    def _index_profile_page(self, page_id: int, title: str, content: str, category: str):
        """Index the profile page into ChromaDB, tolerating retrieval being absent."""
        try:
            if not self.retrieval:
                return
            pg = self.storage.get_page_by_id(page_id)
            updated_at = pg["updated_at"] if pg else ""
            self.retrieval.index_page(
                page_id=page_id,
                title=title,
                content=content,
                category=category,
                updated_at=updated_at,
            )
        except Exception as e:  # noqa: BLE001 - never block lookup on indexing
            log.warning(f"Failed to index player profile page {page_id}: {e}")

    def batch_ingest_sources(self, sources: list[dict]) -> list[int]:
        """Ingest a batch of raw sources.

        Args:
            sources: List of source dicts. Each should have:
                - source_type: str
                - source_id: str
                - facts: list[dict] (title, category, content, summary)

        Returns:
            List of all affected page IDs.
        """
        all_affected: list[int] = []
        for source in sources:
            source_type = source.get("source_type", "unknown")
            source_id = source.get("source_id", "unknown")
            facts = source.get("facts", [])
            for fact in facts:
                page_id = self._apply_fact(fact, f"{source_type}_{source_id}")
                if page_id and page_id not in all_affected:
                    all_affected.append(page_id)

        if all_affected:
            self.storage.log_operation(
                operation="ingest",
                description=f"Batch ingested {len(sources)} sources",
                pages_affected=all_affected,
            )
        return all_affected
