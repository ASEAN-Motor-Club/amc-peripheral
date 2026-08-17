"""Annie's durable memory: an agent-writable fact layer over the wiki.

Mirrors Hermes' memory model (see the `hermes-context-architecture` skill):
the agent can deliberately persist compact durable facts that outlive the
current conversation, and a small set of *standing* self-facts are injected
into every turn so core truths are always present.

Backed by Annie's wiki so facts get the wiki's persistence + ChromaDB semantic
recall for free:

- ``self`` category pages = Annie's standing/self memory (always injected).
- ``fact`` category pages = durable community/player/entity facts (recalled on
  demand via semantic search).

MemoryStore is a thin, idempotent layer over WikiStorage/WikiRetrieval. It is
the storage half of the ``memory`` KnowledgeCog tool.
"""

import logging

from amc_peripheral.wiki.retrieval import WikiRetrieval
from amc_peripheral.wiki.storage import WikiStorage

log = logging.getLogger(__name__)


class MemoryStore:
    """Durable, agent-writable memory over Annie's wiki."""

    SELF_CATEGORY = "self"
    FACT_CATEGORY = "fact"

    def __init__(self, storage: WikiStorage, retrieval: WikiRetrieval):
        self.storage = storage
        self.retrieval = retrieval

    def write_fact(
        self,
        title: str,
        content: str,
        category: str = FACT_CATEGORY,
        summary: str = "",
    ) -> int:
        """Upsert a durable fact page (create or update, idempotent).

        Returns the page id. Re-indexes into ChromaDB when the content changes
        so the fact stays semantically retrievable.
        """
        if not title or not content:
            raise ValueError("'title' and 'content' are required")
        if category not in (self.SELF_CATEGORY, self.FACT_CATEGORY):
            category = self.FACT_CATEGORY

        slug = self.storage._make_slug(title)
        existing = self.storage.get_page_by_slug(slug)

        if existing:
            if existing["content"] == content and (summary or "") == (
                existing.get("summary") or ""
            ):
                return existing["id"]
            self.storage.update_page(existing["id"], content=content, summary=summary)
            page_id = existing["id"]
        else:
            page_id = self.storage.create_page(
                title=title, category=category, content=content, summary=summary
            )

        self._index(page_id, title, content, category)
        self.storage.log_operation(
            operation="memory_write",
            description=f"Memory {category}:{title}",
            pages_affected=[page_id],
        )
        return page_id

    def delete(self, title: str) -> bool:
        """Delete a memory/fact page by title. Returns True if deleted."""
        slug = self.storage._make_slug(title)
        page = self.storage.get_page_by_slug(slug)
        if not page:
            return False
        return self.storage.delete_page(page["id"])

    def list_facts(self, category: str | None = None, limit: int = 50) -> list[dict]:
        """List memory pages, optionally filtered by category."""
        return self.storage.list_pages(category=category, limit=limit)

    def recall(self, query: str, n_results: int = 5) -> list[dict]:
        """Semantically retrieve memory/fact pages relevant to the query."""
        if not query:
            return []
        return self.retrieval.search(query, n_results=n_results)

    def self_block(self, limit_chars: int = 1500) -> str:
        """Render Annie's standing self-facts as a compact always-injected block.

        Reads ``self`` category pages and returns a short, digestible summary.
        Empty string when there is nothing stored.
        """
        pages = self.storage.list_pages(category=self.SELF_CATEGORY, limit=50)
        if not pages:
            return ""

        lines: list[str] = []
        budget = limit_chars
        for p in pages:  # pyrefly: ignore [bad-argument-type]
            text = (p.get("content") or "").strip()
            if not text:
                continue
            entry = text
            if budget <= 0:
                break
            if len(entry) > budget:
                entry = entry[:budget]
                budget = 0
            else:
                budget -= len(entry) + 1
            lines.append(entry)

        if not lines:
            return ""
        return "\n".join(lines).strip()

    def _index(self, page_id: int, title: str, content: str, category: str) -> None:
        try:
            pg = self.storage.get_page_by_id(page_id)
            updated_at = pg["updated_at"] if pg else ""
            self.retrieval.index_page(
                page_id=page_id,
                title=title,
                content=content,
                category=category,
                updated_at=updated_at,
            )
        except Exception as e:  # noqa: BLE001 - never block a fact write on indexing
            log.warning(f"Failed to index memory page {page_id}: {e}")
