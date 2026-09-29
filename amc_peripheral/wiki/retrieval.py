"""SQLite FTS5-based retrieval for wiki pages.

Replaces the former ChromaDB index: the wiki pages already live in
``annie_wiki.db`` (``wiki_pages`` table), so we index them with SQLite FTS5
in the same database. No embeddings, no extra daemon state, no compaction.

All methods are synchronous — callers on the async event loop MUST wrap them
in ``asyncio.to_thread``.
"""

import logging
import re
import sqlite3
from typing import Optional

from amc_peripheral.settings import WIKI_DB_PATH

log = logging.getLogger(__name__)

_FTS_SCHEMA = """
    CREATE VIRTUAL TABLE IF NOT EXISTS wiki_pages_fts USING fts5(
        page_id UNINDEXED,
        title,
        content,
        category UNINDEXED,
        updated_at UNINDEXED
    );
"""


class WikiRetrieval:
    """Full-text search over Annie's wiki pages (SQLite FTS5)."""

    def __init__(self, path: str = WIKI_DB_PATH):
        self.db_path = path
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(_FTS_SCHEMA)
        self.conn.commit()
        self._backfill_from_wiki_pages()
        count = self.get_indexed_count()
        log.info(f"Wiki FTS5 retrieval initialized at {path} ({count} pages)")

    def _backfill_from_wiki_pages(self) -> None:
        """Index any wiki_pages rows not yet present in the FTS table.

        The SQLite wiki_pages table is the source of truth; the FTS index is
        derived. This makes the migration from the old ChromaDB path
        automatic on first start.
        """
        existing = {
            row[0]
            for row in self.conn.execute("SELECT page_id FROM wiki_pages_fts")
        }
        missing = []
        try:
            missing = self.conn.execute(
                "SELECT id, title, content, category, updated_at FROM wiki_pages"
            ).fetchall()
        except sqlite3.OperationalError:
            pass  # no wiki_pages table (fresh test DB) — nothing to backfill
        added = 0
        for row in missing:
            if row["id"] in existing:
                continue
            self.index_page(
                page_id=row["id"],
                title=row["title"],
                content=row["content"] or "",
                category=row["category"] or "",
                updated_at=row["updated_at"] or "",
            )
            added += 1
        if added:
            log.info(f"Wiki FTS backfill: indexed {added} page(s) from wiki_pages")

    def index_page(
        self,
        page_id: int,
        title: str,
        content: str,
        category: str,
        updated_at: str,
    ) -> str:
        """Add or update a wiki page in the FTS index. Returns the doc ID."""
        doc_id = f"wiki_page_{page_id}"
        self.remove_page(page_id)
        self.conn.execute(
            "INSERT INTO wiki_pages_fts (page_id, title, content, category, updated_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (str(page_id), title or "", content or "", category or "", updated_at or ""),
        )
        self.conn.commit()
        return doc_id

    def remove_page(self, page_id: int) -> bool:
        """Remove a wiki page from the FTS index."""
        self.conn.execute(
            "DELETE FROM wiki_pages_fts WHERE page_id = ?", (str(page_id),)
        )
        self.conn.commit()
        return True

    def search(
        self,
        query: str,
        n_results: int = 5,
        category: Optional[str] = None,
        max_distance: float = 1.5,
    ) -> list[dict]:
        """Search wiki pages by keyword match (FTS5, LIKE fallback).

        Args:
            query: The query text.
            n_results: Maximum number of results.
            category: Optional category filter (applied client-side).
            max_distance: Unused (kept for API compatibility with the old
                ChromaDB signature).

        Returns:
            List of result dicts with keys: page_id, title, category, content,
            distance, updated_at. Best match first.
        """
        query = (query or "").strip()
        if not query:
            return []

        rows: list = []
        try:
            # Sanitize into an FTS query: strip punctuation, AND the terms so
            # more specific queries rank first.
            terms = re.findall(r"[\w']+", query)[:8]
            match = " AND ".join(f'"{t}"' for t in terms)
            rows = self.conn.execute(
                "SELECT page_id, title, content, category, updated_at"
                " FROM wiki_pages_fts WHERE wiki_pages_fts MATCH ?"
                " ORDER BY rank LIMIT ?",
                (match, n_results),
            ).fetchall()
        except sqlite3.OperationalError:
            rows = []

        if not rows:
            # Fallback: substring match on title/content (handles short or
            # punctuation-only queries that FTS5 rejects or can't rank).
            like = f"%{query}%"
            rows = self.conn.execute(
                "SELECT page_id, title, content, category, updated_at"
                " FROM wiki_pages_fts WHERE title LIKE ? OR content LIKE ?"
                " LIMIT ?",
                (like, like, n_results),
            ).fetchall()

        pages = []
        for row in rows:
            if category and (row["category"] or "") != category:
                continue
            pages.append(
                {
                    "page_id": int(row["page_id"]) if row["page_id"] else None,
                    "title": row["title"] or "",
                    "category": row["category"] or "",
                    "content": row["content"] or "",
                    "distance": 0.0,
                    "updated_at": row["updated_at"] or "",
                }
            )
        return pages

    def get_indexed_count(self) -> int:
        """Get the number of indexed pages."""
        return self.conn.execute("SELECT COUNT(*) FROM wiki_pages_fts").fetchone()[0]

    def clear_index(self) -> bool:
        """Clear all indexed pages. Use with caution."""
        try:
            self.conn.execute("DELETE FROM wiki_pages_fts")
            self.conn.commit()
            return True
        except Exception:
            return False
