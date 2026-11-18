"""Tags: free-form labels on builds and collections, authorised by ownership.

A tag is an assertion about a build ("this is a drift car"), so only someone who
owns the build — an active claim — may add one. Collection tags are owner-only
for the same reason. The vocabulary is the club's, not ours: no curated list,
just limits and normalisation.
"""

from __future__ import annotations

import re
import sqlite3
import unicodedata
from dataclasses import dataclass
from datetime import UTC
from pathlib import Path

MAX_ITEM_TAGS = 5
MAX_COLLECTION_TAGS = 5
TAG_MAX = 24
TAGS_PER_HOUR = 3
RELATED_LIMIT = 8

SCHEMA = """
CREATE TABLE IF NOT EXISTS workshop_tag (
    tag        TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    created_by TEXT
);

CREATE TABLE IF NOT EXISTS workshop_item_tag (
    workshop_id INTEGER NOT NULL,
    tag         TEXT NOT NULL,
    added_by    TEXT NOT NULL,
    added_at    TEXT NOT NULL,
    PRIMARY KEY (workshop_id, tag)
);
CREATE INDEX IF NOT EXISTS ix_item_tag_tag ON workshop_item_tag(tag);

CREATE TABLE IF NOT EXISTS workshop_collection_tag (
    collection_id INTEGER NOT NULL,
    tag           TEXT NOT NULL,
    added_by      TEXT NOT NULL,
    added_at      TEXT NOT NULL,
    PRIMARY KEY (collection_id, tag)
);
CREATE INDEX IF NOT EXISTS ix_collection_tag_tag ON workshop_collection_tag(tag);
"""

_WS = re.compile(r"[\s_]+")
_DASHES = re.compile(r"-{2,}")
_NOT_ALLOWED = re.compile(r"[^\w-]", flags=re.UNICODE)


class TagError(ValueError):
    """A validation failure with a message safe to show a member."""


@dataclass(frozen=True)
class TagCount:
    tag: str
    items: int
    collections: int

    @property
    def total(self) -> int:
        return self.items + self.collections


def normalise_tag(raw: str | None) -> str:
    """Canonical form: NFKC, casefolded, hyphenated, letters/digits only.

    Unicode is deliberate — a club spanning Vietnam, Thailand and Japan should
    not have to romanise its own words to tag a car. Homoglyphs (Cyrillic а vs
    Latin a) are not deduplicated; that is a known, documented gap.
    """
    text = unicodedata.normalize("NFKC", (raw or "").strip())
    text = text.lstrip("#").strip()
    text = text.casefold()
    text = _WS.sub("-", text)
    text = _NOT_ALLOWED.sub("", text)
    text = _DASHES.sub("-", text).strip("-")
    return text[:TAG_MAX]


def normalise_many(raw_values: list[str] | str | None) -> list[str]:
    """Split on commas/whitespace, normalise, dedupe, drop empties."""
    if raw_values is None:
        return []
    if isinstance(raw_values, str):
        raw_values = raw_values.replace(",", " ").split()
    seen: list[str] = []
    for raw in raw_values:
        tag = normalise_tag(raw)
        if tag and tag not in seen:
            seen.append(tag)
    return seen


def tag_url(tag: str) -> str:
    from urllib.parse import quote

    return f"/workshop/tags/{quote(tag, safe='')}/"


class TagStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    # -- registry ----------------------------------------------------------

    def _register(self, conn: sqlite3.Connection, tags: list[str], member: str, now: str) -> None:
        """Record first use, enforcing how many *new* tags a member may mint."""
        if not tags:
            return
        placeholders = ",".join("?" for _ in tags)
        existing = {
            row[0]
            for row in conn.execute(
                f"SELECT tag FROM workshop_tag WHERE tag IN ({placeholders})", tags
            )
        }
        fresh = [tag for tag in tags if tag not in existing]
        if not fresh:
            return
        cutoff = _hour_before(now)
        recent = conn.execute(
            "SELECT COUNT(*) FROM workshop_tag WHERE created_by = ? AND created_at > ?",
            (str(member), cutoff),
        ).fetchone()[0]
        if recent + len(fresh) > TAGS_PER_HOUR:
            allowed = max(0, TAGS_PER_HOUR - recent)
            raise TagError(
                f"You can start {TAGS_PER_HOUR} new tags an hour "
                f"({allowed} left). Use an existing tag or try later."
            )
        for tag in fresh:
            conn.execute(
                "INSERT OR IGNORE INTO workshop_tag (tag, created_at, created_by)"
                " VALUES (?, ?, ?)",
                (tag, now, str(member)),
            )

    # -- item tags ---------------------------------------------------------

    def item_tags(self, workshop_id: int) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT tag FROM workshop_item_tag WHERE workshop_id = ? ORDER BY tag",
                (int(workshop_id),),
            ).fetchall()
        return [row[0] for row in rows]

    def item_tags_many(self, workshop_ids: list[int]) -> dict[int, list[str]]:
        """One query for a whole page — never per card."""
        ids = [int(i) for i in workshop_ids]
        if not ids:
            return {}
        placeholders = ",".join("?" for _ in ids)
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT workshop_id, tag FROM workshop_item_tag"
                f" WHERE workshop_id IN ({placeholders}) ORDER BY tag",
                ids,
            ).fetchall()
        grouped: dict[int, list[str]] = {}
        for row in rows:
            grouped.setdefault(row[0], []).append(row[1])
        return grouped

    def add_item_tags(
        self, *, workshop_id: int, discord_id: str, raw_tags, now: str
    ) -> list[str]:
        tags = normalise_many(raw_tags)
        if not tags:
            raise TagError("That is not a tag.")
        with self._connect() as conn:
            current = {
                row[0]
                for row in conn.execute(
                    "SELECT tag FROM workshop_item_tag WHERE workshop_id = ?",
                    (int(workshop_id),),
                )
            }
            room = MAX_ITEM_TAGS - len(current)
            if room <= 0:
                raise TagError(f"A build holds at most {MAX_ITEM_TAGS} tags.")
            accepted = [tag for tag in tags if tag not in current][:room]
            if not accepted:
                return sorted(current)
            self._register(conn, accepted, discord_id, now)
            for tag in accepted:
                conn.execute(
                    "INSERT OR IGNORE INTO workshop_item_tag"
                    " (workshop_id, tag, added_by, added_at) VALUES (?, ?, ?, ?)",
                    (int(workshop_id), tag, str(discord_id), now),
                )
        return self.item_tags(workshop_id)

    def remove_item_tag(self, *, workshop_id: int, tag: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM workshop_item_tag WHERE workshop_id = ? AND tag = ?",
                (int(workshop_id), normalise_tag(tag)),
            )
        return cursor.rowcount > 0

    # -- collection tags ---------------------------------------------------

    def collection_tags(self, collection_id: int) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT tag FROM workshop_collection_tag WHERE collection_id = ? ORDER BY tag",
                (int(collection_id),),
            ).fetchall()
        return [row[0] for row in rows]

    def add_collection_tags(
        self, *, collection_id: int, discord_id: str, raw_tags, now: str
    ) -> list[str]:
        tags = normalise_many(raw_tags)
        if not tags:
            raise TagError("That is not a tag.")
        with self._connect() as conn:
            current = {
                row[0]
                for row in conn.execute(
                    "SELECT tag FROM workshop_collection_tag WHERE collection_id = ?",
                    (int(collection_id),),
                )
            }
            room = MAX_COLLECTION_TAGS - len(current)
            if room <= 0:
                raise TagError(f"A collection holds at most {MAX_COLLECTION_TAGS} tags.")
            accepted = [tag for tag in tags if tag not in current][:room]
            if not accepted:
                return sorted(current)
            self._register(conn, accepted, discord_id, now)
            for tag in accepted:
                conn.execute(
                    "INSERT OR IGNORE INTO workshop_collection_tag"
                    " (collection_id, tag, added_by, added_at) VALUES (?, ?, ?, ?)",
                    (int(collection_id), tag, str(discord_id), now),
                )
        return self.collection_tags(collection_id)

    def remove_collection_tag(self, *, collection_id: int, tag: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM workshop_collection_tag WHERE collection_id = ? AND tag = ?",
                (int(collection_id), normalise_tag(tag)),
            )
        return cursor.rowcount > 0

    # -- browsing ----------------------------------------------------------

    def index(self, *, sort: str = "popular", limit: int = 60, offset: int = 0) -> list[TagCount]:
        """Tags with at least one use, in either popularity or alphabetical order."""
        order = (
            "(SUM(items) + SUM(collections)) DESC, tag"
            if sort != "az"
            else "tag"
        )
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT tag, SUM(items) AS items, SUM(collections) AS collections
                FROM (
                    SELECT tag, COUNT(*) AS items, 0 AS collections
                    FROM workshop_item_tag GROUP BY tag
                    UNION ALL
                    SELECT tag, 0 AS items, COUNT(*) AS collections
                    FROM workshop_collection_tag GROUP BY tag
                )
                GROUP BY tag
                HAVING items + collections > 0
                ORDER BY {order}
                LIMIT ? OFFSET ?
                """,
                (int(limit), int(offset)),
            ).fetchall()
        return [
            TagCount(tag=row["tag"], items=row["items"], collections=row["collections"])
            for row in rows
        ]

    def count_tags(self) -> int:
        with self._connect() as conn:
            return int(
                conn.execute(
                    "SELECT COUNT(*) FROM ("
                    "  SELECT tag FROM workshop_item_tag"
                    "  UNION SELECT tag FROM workshop_collection_tag"
                    ") "
                ).fetchone()[0]
            )

    def usage(self, tag: str) -> TagCount | None:
        tag = normalise_tag(tag)
        with self._connect() as conn:
            items = conn.execute(
                "SELECT COUNT(*) FROM workshop_item_tag WHERE tag = ?", (tag,)
            ).fetchone()[0]
            collections = conn.execute(
                "SELECT COUNT(*) FROM workshop_collection_tag WHERE tag = ?", (tag,)
            ).fetchone()[0]
        if not items and not collections:
            return None
        return TagCount(tag=tag, items=items, collections=collections)

    def item_ids(self, tag: str, *, limit: int = 200) -> list[int]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT workshop_id FROM workshop_item_tag WHERE tag = ?"
                " ORDER BY workshop_id DESC LIMIT ?",
                (normalise_tag(tag), int(limit)),
            ).fetchall()
        return [row[0] for row in rows]

    def collection_ids(self, tag: str, *, limit: int = 12) -> list[int]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT collection_id FROM workshop_collection_tag WHERE tag = ?"
                " ORDER BY collection_id DESC LIMIT ?",
                (normalise_tag(tag), int(limit)),
            ).fetchall()
        return [row[0] for row in rows]

    def related(self, tag: str, *, limit: int = RELATED_LIMIT) -> list[TagCount]:
        """Tags that share builds with this one — the reason a tag page is not a dead end."""
        canonical = normalise_tag(tag)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT other.tag AS tag, COUNT(*) AS items, 0 AS collections
                FROM workshop_item_tag mine
                JOIN workshop_item_tag other ON other.workshop_id = mine.workshop_id
                WHERE mine.tag = ? AND other.tag <> ?
                GROUP BY other.tag
                ORDER BY items DESC, other.tag
                LIMIT ?
                """,
                (canonical, canonical, int(limit)),
            ).fetchall()
        return [
            TagCount(tag=row["tag"], items=row["items"], collections=0) for row in rows
        ]

    def search(self, query: str, *, limit: int = 12) -> list[TagCount]:
        """Prefix matches first, then substring — for the main-page typeahead."""
        needle = normalise_tag(query)
        if not needle:
            return []
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT tag, SUM(items) AS items, SUM(collections) AS collections
                FROM (
                    SELECT tag, COUNT(*) AS items, 0 AS collections
                    FROM workshop_item_tag GROUP BY tag
                    UNION ALL
                    SELECT tag, 0 AS items, COUNT(*) AS collections
                    FROM workshop_collection_tag GROUP BY tag
                )
                WHERE tag LIKE ?
                GROUP BY tag
                ORDER BY (tag = ?) DESC, (tag LIKE ?) DESC, items DESC, tag
                LIMIT ?
                """,
                (f"%{needle}%", needle, f"{needle}%", int(limit)),
            ).fetchall()
        return [
            TagCount(tag=row["tag"], items=row["items"], collections=row["collections"])
            for row in rows
        ]

    def delete_collection_tags(self, collection_id: int) -> None:
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM workshop_collection_tag WHERE collection_id = ?",
                (int(collection_id),),
            )


def _hour_before(now_iso: str) -> str:
    """``now`` is an ISO-8601 UTC stamp; return one hour earlier in the same shape."""
    from datetime import datetime, timedelta

    try:
        stamp = datetime.fromisoformat(now_iso)
    except ValueError:  # pragma: no cover - callers pass our own stamps
        return now_iso
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=UTC)
    return (stamp - timedelta(hours=1)).isoformat(timespec="seconds")
