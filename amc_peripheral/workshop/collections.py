"""Member-curated collections of workshop builds.

Ownership here is not the point — curation is. Any signed-in member can put
anyone's build in a collection; the only permission rule is that only the owner
may edit or delete their own.

Stored in the workshop's own SQLite (``workshop_site.db``), next to the scrape:
the scrape stays read-only, and a curated list is community data, not game data.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .community import SCHEMA as COMMUNITY_SCHEMA

SCHEMA = """
CREATE TABLE IF NOT EXISTS workshop_collection (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    discord_id  TEXT NOT NULL,
    slug        TEXT NOT NULL,
    title       TEXT NOT NULL,
    description TEXT,
    visibility  TEXT NOT NULL DEFAULT 'public',
    hidden      INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_collection_slug
    ON workshop_collection(discord_id, slug);
CREATE INDEX IF NOT EXISTS ix_collection_owner
    ON workshop_collection(discord_id);

CREATE TABLE IF NOT EXISTS workshop_collection_item (
    collection_id INTEGER NOT NULL,
    workshop_id   INTEGER NOT NULL,
    position      INTEGER NOT NULL,
    added_at      TEXT NOT NULL,
    PRIMARY KEY (collection_id, workshop_id)
);
CREATE INDEX IF NOT EXISTS ix_collection_item_order
    ON workshop_collection_item(collection_id, position);
"""

from .text import clean_text as _clean_text
from .text import slugify

MAX_COLLECTIONS = 50
MAX_ITEMS = 100
TITLE_MAX = 40
DESCRIPTION_MAX = 400
VISIBILITIES = {"public", "unlisted"}


class CollectionError(ValueError):
    """A validation failure with a message that is safe to show a member."""


def clean_text(value: str | None, *, limit: int, field: str) -> str:
    """The shared text rules, reported as a collection validation failure."""
    try:
        return _clean_text(value, limit=limit, field=field)
    except ValueError as exc:
        raise CollectionError(str(exc)) from None


@dataclass(frozen=True)
class Collection:
    id: int
    discord_id: str
    slug: str
    title: str
    description: str | None
    visibility: str
    hidden: int
    created_at: str
    updated_at: str
    item_count: int = 0
    like_total: int = 0

    @property
    def is_public(self) -> bool:
        return self.visibility == "public" and not self.hidden


def _row_to_collection(row: sqlite3.Row) -> Collection:
    keys = row.keys()
    return Collection(
        id=row["id"],
        discord_id=row["discord_id"],
        slug=row["slug"],
        title=row["title"],
        description=row["description"],
        visibility=row["visibility"],
        hidden=row["hidden"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        item_count=row["item_count"] if "item_count" in keys else 0,
        like_total=row["like_total"] if "like_total" in keys else 0,
    )


# A collection is only worth listing once it holds something; an empty list is
# not a page. Likes on the items raise it in the "liked" ordering.
_LIST_SELECT = """
SELECT c.*,
       COUNT(ci.workshop_id) AS item_count,
       COALESCE(SUM((SELECT COUNT(*) FROM workshop_like l
                     WHERE l.workshop_id = ci.workshop_id)), 0) AS like_total
FROM workshop_collection c
JOIN workshop_collection_item ci ON ci.collection_id = c.id
WHERE c.visibility = 'public' AND c.hidden = 0
GROUP BY c.id
"""

_LIST_ORDER = {
    "new": "ORDER BY c.updated_at DESC, c.id DESC",
    "liked": "ORDER BY like_total DESC, c.updated_at DESC, c.id DESC",
}


class CollectionStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            # The like counts are joined from the community tables; both live in
            # the same site DB, so ensure that half of the schema exists too.
            conn.executescript(COMMUNITY_SCHEMA + SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    # -- reads -------------------------------------------------------------

    def get(self, collection_id: int) -> Collection | None:
        with self._connect() as conn:
            row = conn.execute(
                _LIST_SELECT + " HAVING c.id = ?", (int(collection_id),)
            ).fetchone()
            if row is not None:
                return _row_to_collection(row)
            row = conn.execute(
                "SELECT * FROM workshop_collection WHERE id = ?", (int(collection_id),)
            ).fetchone()
        return _row_to_collection(row) if row else None

    def owned(self, discord_id: str) -> list[Collection]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT c.*, COUNT(ci.workshop_id) AS item_count
                FROM workshop_collection c
                LEFT JOIN workshop_collection_item ci ON ci.collection_id = c.id
                WHERE c.discord_id = ? AND c.hidden = 0
                GROUP BY c.id
                ORDER BY c.updated_at DESC, c.id DESC
                """,
                (str(discord_id),),
            ).fetchall()
        return [_row_to_collection(row) for row in rows]

    def listing(
        self, *, sort: str = "new", limit: int = 24, offset: int = 0
    ) -> list[Collection]:
        order = _LIST_ORDER.get(sort, _LIST_ORDER["new"])
        with self._connect() as conn:
            rows = conn.execute(
                _LIST_SELECT + " " + order + " LIMIT ? OFFSET ?",
                (int(limit), int(offset)),
            ).fetchall()
        return [_row_to_collection(row) for row in rows]

    def count_public(self) -> int:
        with self._connect() as conn:
            return int(
                conn.execute(
                    "SELECT COUNT(*) FROM (" + _LIST_SELECT + ") AS listed"
                ).fetchone()[0]
            )

    def item_ids(self, collection_id: int) -> list[int]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT workshop_id FROM workshop_collection_item"
                " WHERE collection_id = ? ORDER BY position, workshop_id",
                (int(collection_id),),
            ).fetchall()
        return [row[0] for row in rows]

    def count_for_item(self, workshop_id: int) -> int:
        with self._connect() as conn:
            return int(
                conn.execute(
                    "SELECT COUNT(DISTINCT ci.collection_id)"
                    " FROM workshop_collection_item ci"
                    " JOIN workshop_collection c ON c.id = ci.collection_id"
                    " WHERE ci.workshop_id = ? AND c.visibility = 'public' AND c.hidden = 0",
                    (int(workshop_id),),
                ).fetchone()[0]
            )

    def all_public(self) -> list[Collection]:
        """Every listed collection — sitemap use, so no pagination."""
        with self._connect() as conn:
            rows = conn.execute(_LIST_SELECT + " " + _LIST_ORDER["new"]).fetchall()
        return [_row_to_collection(row) for row in rows]

    def cover_ids(self, collection_ids: list[int]) -> dict[int, int]:
        """First build of each collection, one query for a whole index page."""
        ids = [int(i) for i in collection_ids]
        if not ids:
            return {}
        placeholders = ",".join("?" for _ in ids)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT ci.collection_id, ci.workshop_id
                FROM workshop_collection_item ci
                JOIN (
                    SELECT collection_id, MIN(position) AS mp
                    FROM workshop_collection_item
                    WHERE collection_id IN ({placeholders})
                    GROUP BY collection_id
                ) f ON f.collection_id = ci.collection_id AND f.mp = ci.position
                """,
                ids,
            ).fetchall()
        return {row[0]: row[1] for row in rows}

    def collections_for_item(
        self, workshop_id: int, limit: int = 5
    ) -> list[Collection]:
        """Public collections this build appears in, newest first."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT c.*, COUNT(ci2.workshop_id) AS item_count
                FROM workshop_collection c
                JOIN workshop_collection_item ci ON ci.collection_id = c.id
                JOIN workshop_collection_item ci2 ON ci2.collection_id = c.id
                WHERE ci.workshop_id = ? AND c.visibility = 'public' AND c.hidden = 0
                GROUP BY c.id
                ORDER BY c.updated_at DESC, c.id DESC
                LIMIT ?
                """,
                (int(workshop_id), int(limit)),
            ).fetchall()
        return [_row_to_collection(row) for row in rows]

    # -- writes ------------------------------------------------------------

    def create(
        self,
        *,
        discord_id: str,
        title: str,
        description: str | None,
        visibility: str,
        now: str,
    ) -> Collection:
        discord_id = str(discord_id)
        clean_title = clean_text(title, limit=TITLE_MAX, field="Title")
        if not clean_title:
            raise CollectionError("Give the collection a title.")
        clean_description = clean_text(
            description, limit=DESCRIPTION_MAX, field="Description"
        )
        visibility = visibility if visibility in VISIBILITIES else "public"

        with self._connect() as conn:
            mine = conn.execute(
                "SELECT COUNT(*) FROM workshop_collection WHERE discord_id = ? AND hidden = 0",
                (discord_id,),
            ).fetchone()[0]
            if mine >= MAX_COLLECTIONS:
                raise CollectionError(
                    f"You already have {MAX_COLLECTIONS} collections. Delete one to make room."
                )
            slug = self._unique_slug(conn, discord_id, slugify(clean_title))
            cursor = conn.execute(
                "INSERT INTO workshop_collection"
                " (discord_id, slug, title, description, visibility, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    discord_id,
                    slug,
                    clean_title,
                    clean_description or None,
                    visibility,
                    now,
                    now,
                ),
            )
            assert cursor.lastrowid is not None
            collection_id = int(cursor.lastrowid)
        return Collection(
            id=collection_id,
            discord_id=discord_id,
            slug=slug,
            title=clean_title,
            description=clean_description or None,
            visibility=visibility,
            hidden=0,
            created_at=now,
            updated_at=now,
        )

    @staticmethod
    def _unique_slug(conn: sqlite3.Connection, discord_id: str, base: str) -> str:
        candidate, suffix = base, 2
        while conn.execute(
            "SELECT 1 FROM workshop_collection WHERE discord_id = ? AND slug = ?",
            (discord_id, candidate),
        ).fetchone():
            candidate = f"{base[:56]}-{suffix}"
            suffix += 1
        return candidate

    def update(
        self,
        *,
        collection_id: int,
        discord_id: str,
        title: str,
        description: str | None,
        visibility: str,
        now: str,
    ) -> bool:
        clean_title = clean_text(title, limit=TITLE_MAX, field="Title")
        if not clean_title:
            raise CollectionError("Give the collection a title.")
        clean_description = clean_text(
            description, limit=DESCRIPTION_MAX, field="Description"
        )
        visibility = visibility if visibility in VISIBILITIES else "public"
        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE workshop_collection"
                " SET title = ?, description = ?, visibility = ?, updated_at = ?"
                " WHERE id = ? AND discord_id = ? AND hidden = 0",
                (
                    clean_title,
                    clean_description or None,
                    visibility,
                    now,
                    int(collection_id),
                    str(discord_id),
                ),
            )
        return cursor.rowcount > 0

    def delete(self, *, collection_id: int, discord_id: str) -> bool:
        with self._connect() as conn:
            owned = conn.execute(
                "SELECT 1 FROM workshop_collection WHERE id = ? AND discord_id = ?",
                (int(collection_id), str(discord_id)),
            ).fetchone()
            if not owned:
                return False
            conn.execute(
                "DELETE FROM workshop_collection_item WHERE collection_id = ?",
                (int(collection_id),),
            )
            conn.execute(
                "DELETE FROM workshop_collection WHERE id = ?", (int(collection_id),)
            )
        return True

    def add_item(
        self, *, collection_id: int, discord_id: str, workshop_id: int, now: str
    ) -> bool:
        """Add a build. False when not the owner, already present, or full."""
        with self._connect() as conn:
            owned = conn.execute(
                "SELECT 1 FROM workshop_collection"
                " WHERE id = ? AND discord_id = ? AND hidden = 0",
                (int(collection_id), str(discord_id)),
            ).fetchone()
            if not owned:
                return False
            exists = conn.execute(
                "SELECT 1 FROM workshop_collection_item"
                " WHERE collection_id = ? AND workshop_id = ?",
                (int(collection_id), int(workshop_id)),
            ).fetchone()
            if exists:
                return False
            count = conn.execute(
                "SELECT COUNT(*) FROM workshop_collection_item WHERE collection_id = ?",
                (int(collection_id),),
            ).fetchone()[0]
            if count >= MAX_ITEMS:
                raise CollectionError(f"A collection holds at most {MAX_ITEMS} builds.")
            position = conn.execute(
                "SELECT COALESCE(MAX(position), -1) + 1 FROM workshop_collection_item"
                " WHERE collection_id = ?",
                (int(collection_id),),
            ).fetchone()[0]
            conn.execute(
                "INSERT INTO workshop_collection_item"
                " (collection_id, workshop_id, position, added_at) VALUES (?, ?, ?, ?)",
                (int(collection_id), int(workshop_id), int(position), now),
            )
            conn.execute(
                "UPDATE workshop_collection SET updated_at = ? WHERE id = ?",
                (now, int(collection_id)),
            )
        return True

    def remove_item(
        self, *, collection_id: int, discord_id: str, workshop_id: int
    ) -> bool:
        with self._connect() as conn:
            owned = conn.execute(
                "SELECT 1 FROM workshop_collection WHERE id = ? AND discord_id = ?",
                (int(collection_id), str(discord_id)),
            ).fetchone()
            if not owned:
                return False
            cursor = conn.execute(
                "DELETE FROM workshop_collection_item"
                " WHERE collection_id = ? AND workshop_id = ?",
                (int(collection_id), int(workshop_id)),
            )
        return cursor.rowcount > 0

    def reorder(
        self, *, collection_id: int, discord_id: str, ordered_ids: list[int]
    ) -> bool:
        """Rewrite positions to match ``ordered_ids``, ignoring ids not present."""
        with self._connect() as conn:
            owned = conn.execute(
                "SELECT 1 FROM workshop_collection WHERE id = ? AND discord_id = ?",
                (int(collection_id), str(discord_id)),
            ).fetchone()
            if not owned:
                return False
            present = {
                row[0]
                for row in conn.execute(
                    "SELECT workshop_id FROM workshop_collection_item WHERE collection_id = ?",
                    (int(collection_id),),
                )
            }
            ordered = [int(i) for i in ordered_ids if int(i) in present]
            ordered += sorted(present - set(ordered))
            for position, workshop_id in enumerate(ordered):
                conn.execute(
                    "UPDATE workshop_collection_item SET position = ?"
                    " WHERE collection_id = ? AND workshop_id = ?",
                    (position, int(collection_id), workshop_id),
                )
        return True

    def hide_all(self, discord_id: str) -> int:
        """Takedown / account deletion: drop the collections, keep nothing dangling."""
        with self._connect() as conn:
            ids = [
                row[0]
                for row in conn.execute(
                    "SELECT id FROM workshop_collection WHERE discord_id = ?",
                    (str(discord_id),),
                )
            ]
            for collection_id in ids:
                conn.execute(
                    "DELETE FROM workshop_collection_item WHERE collection_id = ?",
                    (collection_id,),
                )
            conn.execute(
                "DELETE FROM workshop_collection WHERE discord_id = ?",
                (str(discord_id),),
            )
        return len(ids)
