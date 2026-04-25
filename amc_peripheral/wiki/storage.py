"""SQLite storage for Annie's wiki pages, links, sources, and log."""

import sqlite3
import os
import re
from datetime import datetime
from typing import Optional

from amc_peripheral.settings import WIKI_DB_PATH, MEMORY_DATA_DIR


class WikiStorage:
    """Persistent storage for wiki pages, cross-references, sources, and operations log."""

    def __init__(self, db_path: str = WIKI_DB_PATH):
        os.makedirs(os.path.dirname(db_path) or MEMORY_DATA_DIR, exist_ok=True)
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        """Create tables and indexes if they don't exist."""
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS wiki_pages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                slug TEXT NOT NULL UNIQUE,
                category TEXT NOT NULL,
                content TEXT NOT NULL DEFAULT '',
                summary TEXT NOT NULL DEFAULT '',
                source_count INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_wiki_pages_category
                ON wiki_pages(category);
            CREATE INDEX IF NOT EXISTS idx_wiki_pages_updated_at
                ON wiki_pages(updated_at);
            CREATE INDEX IF NOT EXISTS idx_wiki_pages_title
                ON wiki_pages(title);

            CREATE TABLE IF NOT EXISTS wiki_links (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                from_page_id INTEGER NOT NULL,
                to_page_id INTEGER NOT NULL,
                link_type TEXT NOT NULL DEFAULT 'mentions',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(from_page_id, to_page_id, link_type)
            );

            CREATE INDEX IF NOT EXISTS idx_wiki_links_from
                ON wiki_links(from_page_id);
            CREATE INDEX IF NOT EXISTS idx_wiki_links_to
                ON wiki_links(to_page_id);

            CREATE TABLE IF NOT EXISTS wiki_sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                page_id INTEGER NOT NULL,
                source_type TEXT NOT NULL,
                source_id TEXT NOT NULL,
                extracted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_wiki_sources_page_id
                ON wiki_sources(page_id);
            CREATE INDEX IF NOT EXISTS idx_wiki_sources_type_id
                ON wiki_sources(source_type, source_id);

            CREATE TABLE IF NOT EXISTS wiki_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                operation TEXT NOT NULL,
                description TEXT NOT NULL,
                pages_affected TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_wiki_log_timestamp
                ON wiki_log(timestamp);
            CREATE INDEX IF NOT EXISTS idx_wiki_log_operation
                ON wiki_log(operation);

            CREATE TABLE IF NOT EXISTS wiki_index_cache (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                index_content TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
        """)
        self.conn.commit()

    @staticmethod
    def _make_slug(title: str) -> str:
        """Convert a title to a URL-safe slug."""
        slug = title.lower().strip()
        # Replace colons with hyphens first, then remove other special chars
        slug = slug.replace(":", "-")
        slug = re.sub(r"[^\w\s-]", "", slug)
        slug = re.sub(r"[-\s]+", "-", slug)
        return slug[:128]

    def create_page(
        self,
        title: str,
        category: str,
        content: str = "",
        summary: str = "",
        source_count: int = 0,
    ) -> int:
        """Create a new wiki page. Returns the page ID."""
        slug = self._make_slug(title)
        now = datetime.now().isoformat()
        cursor = self.conn.execute(
            """
            INSERT INTO wiki_pages (title, slug, category, content, summary, source_count, updated_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (title, slug, category, content, summary, source_count, now, now),
        )
        self.conn.commit()
        return cursor.lastrowid or 0

    def get_page_by_id(self, page_id: int) -> Optional[dict]:
        """Get a wiki page by ID."""
        cursor = self.conn.execute(
            "SELECT * FROM wiki_pages WHERE id = ?", (page_id,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_page_by_slug(self, title_or_slug: str) -> Optional[dict]:
        """Get a wiki page by slug. Accepts raw titles (will be auto-slugified)."""
        normalized = self._make_slug(title_or_slug)
        cursor = self.conn.execute(
            "SELECT * FROM wiki_pages WHERE slug = ?", (normalized,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_page_by_title(self, title: str) -> Optional[dict]:
        """Get a wiki page by exact title match."""
        cursor = self.conn.execute(
            "SELECT * FROM wiki_pages WHERE title = ?", (title,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    def update_page(
        self,
        page_id: int,
        content: Optional[str] = None,
        summary: Optional[str] = None,
        source_count: Optional[int] = None,
        title: Optional[str] = None,
        category: Optional[str] = None,
    ) -> bool:
        """Update a wiki page. Returns True if the page existed."""
        page = self.get_page_by_id(page_id)
        if not page:
            return False

        fields = []
        params = []
        if content is not None:
            fields.append("content = ?")
            params.append(content)
        if summary is not None:
            fields.append("summary = ?")
            params.append(summary)
        if source_count is not None:
            fields.append("source_count = ?")
            params.append(source_count)
        if title is not None:
            fields.append("title = ?")
            params.append(title)
            fields.append("slug = ?")
            params.append(self._make_slug(title))
        if category is not None:
            fields.append("category = ?")
            params.append(category)

        if not fields:
            return True

        fields.append("updated_at = ?")
        params.append(datetime.now().isoformat())
        params.append(page_id)

        self.conn.execute(
            f"UPDATE wiki_pages SET {', '.join(fields)} WHERE id = ?",
            params,
        )
        self.conn.commit()
        return True

    def delete_page(self, page_id: int) -> bool:
        """Delete a wiki page and its associated links/sources. Returns True if deleted."""
        page = self.get_page_by_id(page_id)
        if not page:
            return False

        self.conn.execute("DELETE FROM wiki_links WHERE from_page_id = ? OR to_page_id = ?", (page_id, page_id))
        self.conn.execute("DELETE FROM wiki_sources WHERE page_id = ?", (page_id,))
        self.conn.execute("DELETE FROM wiki_pages WHERE id = ?", (page_id,))
        self.conn.commit()
        return True

    def list_pages(
        self,
        category: Optional[str] = None,
        keyword: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        """List wiki pages with optional filters."""
        conditions = []
        params = []
        if category:
            conditions.append("category = ?")
            params.append(category)
        if keyword:
            conditions.append("(title LIKE ? OR content LIKE ?)")
            like = f"%{keyword}%"
            params.extend([like, like])

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        query = f"""
            SELECT * FROM wiki_pages
            {where_clause}
            ORDER BY updated_at DESC
            LIMIT ? OFFSET ?
        """
        params.extend([limit, offset])
        cursor = self.conn.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]

    def get_page_count(self, category: Optional[str] = None) -> int:
        """Get total page count, optionally filtered by category."""
        if category:
            cursor = self.conn.execute(
                "SELECT COUNT(*) FROM wiki_pages WHERE category = ?", (category,)
            )
        else:
            cursor = self.conn.execute("SELECT COUNT(*) FROM wiki_pages")
        return cursor.fetchone()[0]

    def add_link(self, from_page_id: int, to_page_id: int, link_type: str = "mentions") -> int:
        """Add a cross-reference between two pages. Returns the link ID."""
        now = datetime.now().isoformat()
        cursor = self.conn.execute(
            """
            INSERT OR IGNORE INTO wiki_links (from_page_id, to_page_id, link_type, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (from_page_id, to_page_id, link_type, now),
        )
        self.conn.commit()
        return cursor.lastrowid or 0

    def get_links_from(self, page_id: int) -> list[dict]:
        """Get all outbound links from a page."""
        cursor = self.conn.execute(
            """
            SELECT l.*, p.title as to_title, p.slug as to_slug, p.category as to_category
            FROM wiki_links l
            JOIN wiki_pages p ON l.to_page_id = p.id
            WHERE l.from_page_id = ?
            """,
            (page_id,),
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_links_to(self, page_id: int) -> list[dict]:
        """Get all inbound links to a page."""
        cursor = self.conn.execute(
            """
            SELECT l.*, p.title as from_title, p.slug as from_slug, p.category as from_category
            FROM wiki_links l
            JOIN wiki_pages p ON l.from_page_id = p.id
            WHERE l.to_page_id = ?
            """,
            (page_id,),
        )
        return [dict(row) for row in cursor.fetchall()]

    def remove_link(self, from_page_id: int, to_page_id: int, link_type: Optional[str] = None) -> bool:
        """Remove a link between two pages."""
        if link_type:
            self.conn.execute(
                "DELETE FROM wiki_links WHERE from_page_id = ? AND to_page_id = ? AND link_type = ?",
                (from_page_id, to_page_id, link_type),
            )
        else:
            self.conn.execute(
                "DELETE FROM wiki_links WHERE from_page_id = ? AND to_page_id = ?",
                (from_page_id, to_page_id),
            )
        self.conn.commit()
        return True

    def add_source(self, page_id: int, source_type: str, source_id: str) -> int:
        """Add a raw source reference to a page. Returns the source ID."""
        now = datetime.now().isoformat()
        cursor = self.conn.execute(
            """
            INSERT INTO wiki_sources (page_id, source_type, source_id, extracted_at)
            VALUES (?, ?, ?, ?)
            """,
            (page_id, source_type, source_id, now),
        )
        self.conn.commit()
        # Update source_count on the page
        self._update_source_count(page_id)
        return cursor.lastrowid or 0

    def get_sources(self, page_id: int) -> list[dict]:
        """Get all raw source references for a page."""
        cursor = self.conn.execute(
            "SELECT * FROM wiki_sources WHERE page_id = ? ORDER BY extracted_at DESC",
            (page_id,),
        )
        return [dict(row) for row in cursor.fetchall()]

    def _update_source_count(self, page_id: int):
        """Recalculate and update source_count for a page."""
        cursor = self.conn.execute(
            "SELECT COUNT(*) FROM wiki_sources WHERE page_id = ?", (page_id,)
        )
        count = cursor.fetchone()[0]
        self.conn.execute(
            "UPDATE wiki_pages SET source_count = ? WHERE id = ?",
            (count, page_id),
        )
        self.conn.commit()

    def log_operation(self, operation: str, description: str, pages_affected: Optional[list[int]] = None) -> int:
        """Append an entry to the wiki log. Returns the log ID."""
        now = datetime.now().isoformat()
        pages_str = ",".join(str(p) for p in pages_affected) if pages_affected else None
        cursor = self.conn.execute(
            """
            INSERT INTO wiki_log (timestamp, operation, description, pages_affected)
            VALUES (?, ?, ?, ?)
            """,
            (now, operation, description, pages_str),
        )
        self.conn.commit()
        return cursor.lastrowid or 0

    def get_log_entries(
        self,
        operation: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        """Get log entries with optional operation filter."""
        if operation:
            cursor = self.conn.execute(
                """
                SELECT * FROM wiki_log WHERE operation = ?
                ORDER BY timestamp DESC LIMIT ? OFFSET ?
                """,
                (operation, limit, offset),
            )
        else:
            cursor = self.conn.execute(
                """
                SELECT * FROM wiki_log
                ORDER BY timestamp DESC LIMIT ? OFFSET ?
                """,
                (limit, offset),
            )
        return [dict(row) for row in cursor.fetchall()]

    def get_orphan_pages(self) -> list[dict]:
        """Get pages with no inbound links."""
        cursor = self.conn.execute(
            """
            SELECT p.* FROM wiki_pages p
            WHERE p.id NOT IN (SELECT DISTINCT to_page_id FROM wiki_links)
            """
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_stale_pages(self, days: int = 30) -> list[dict]:
        """Get pages not updated in the last N days."""
        cursor = self.conn.execute(
            """
            SELECT * FROM wiki_pages
            WHERE updated_at < datetime('now', ? || ' days')
            ORDER BY updated_at ASC
            """,
            (f"-{days}",),
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_index_cache(self) -> Optional[str]:
        """Get the cached wiki index."""
        cursor = self.conn.execute("SELECT index_content FROM wiki_index_cache WHERE id = 1")
        row = cursor.fetchone()
        return row[0] if row else None

    def set_index_cache(self, index_content: str) -> bool:
        """Update the cached wiki index."""
        now = datetime.now().isoformat()
        self.conn.execute(
            """
            INSERT INTO wiki_index_cache (id, index_content, updated_at)
            VALUES (1, ?, ?)
            ON CONFLICT(id) DO UPDATE SET index_content = excluded.index_content, updated_at = excluded.updated_at
            """,
            (index_content, now),
        )
        self.conn.commit()
        return True

    def get_stats(self) -> dict:
        """Get overall wiki statistics."""
        cursor = self.conn.execute("""
            SELECT
                COUNT(*) as total_pages,
                COUNT(DISTINCT category) as total_categories,
                SUM(source_count) as total_sources,
                MIN(created_at) as oldest_page,
                MAX(updated_at) as latest_update
            FROM wiki_pages
        """)
        page_stats = cursor.fetchone()

        cursor = self.conn.execute("SELECT COUNT(*) FROM wiki_links")
        link_count = cursor.fetchone()[0]

        cursor = self.conn.execute("SELECT COUNT(*) FROM wiki_log")
        log_count = cursor.fetchone()[0]

        return {
            "total_pages": page_stats[0],
            "total_categories": page_stats[1],
            "total_sources": page_stats[2],
            "total_links": link_count,
            "total_log_entries": log_count,
            "oldest_page": page_stats[3],
            "latest_update": page_stats[4],
        }

    def close(self):
        """Close the database connection."""
        self.conn.close()
