"""Comments on workshop builds.

Flat and chronological: a build page gets a handful of comments, not a thread
tree, and threads cost more in moderation than they return at this volume.

Rows are keyed by ``workshop_id``, exactly like ``workshop_like`` and
``workshop_item_tag``: a build that leaves the scrape stops showing its comments
because nothing renders that row any more, and if it comes back the conversation
comes back with it.

Authors can edit for a quarter of an hour — enough for a typo, not enough to
rewrite something other people have already read. After that it is history, and
an admin can hide it.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime

from .community import SCHEMA as COMMUNITY_SCHEMA
from .text import clean_multiline

BODY_MAX = 1000
LINES_MAX = 20
EDIT_WINDOW_SECONDS = 15 * 60

HIDDEN_TEXT = "This comment was removed by an admin."

SCHEMA = """
CREATE TABLE IF NOT EXISTS workshop_comment (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    workshop_id  INTEGER NOT NULL,
    discord_id   TEXT NOT NULL,
    body         TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    edited_at    TEXT,
    hidden       INTEGER NOT NULL DEFAULT 0,
    hidden_by    TEXT,
    hidden_at    TEXT
);
CREATE INDEX IF NOT EXISTS ix_comment_item ON workshop_comment(workshop_id, id);
CREATE INDEX IF NOT EXISTS ix_comment_member ON workshop_comment(discord_id, created_at);
"""


class CommentError(Exception):
    """A comment the caller may not write, or not write that way."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _parse(stamp: str) -> datetime:
    # Python 3.11 reads a trailing "Z" itself.
    return datetime.fromisoformat(stamp)


@dataclass(frozen=True)
class Comment:
    id: int
    workshop_id: int
    discord_id: str
    body: str
    created_at: str
    edited_at: str | None
    hidden: bool

    def can_edit(self, discord_id: str, now: str) -> bool:
        if str(discord_id) != self.discord_id or self.hidden:
            return False
        age = (_parse(now) - _parse(self.created_at)).total_seconds()
        return age <= EDIT_WINDOW_SECONDS


class CommentStore:
    def __init__(self, path):
        self.path = path
        with self._connect() as conn:
            conn.executescript(COMMUNITY_SCHEMA)
            conn.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=3000")
        return conn

    @staticmethod
    def _row(row: sqlite3.Row) -> Comment:
        return Comment(
            id=int(row["id"]),
            workshop_id=int(row["workshop_id"]),
            discord_id=str(row["discord_id"]),
            body=row["body"],
            created_at=row["created_at"],
            edited_at=row["edited_at"],
            hidden=bool(row["hidden"]),
        )

    def add(self, *, workshop_id: int, discord_id: str, body: str, now: str) -> Comment:
        try:
            clean = clean_multiline(
                body, limit=BODY_MAX, field="Comment", lines_limit=LINES_MAX
            )
        except ValueError as exc:
            raise CommentError("invalid_body", str(exc)) from None
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO workshop_comment (workshop_id, discord_id, body, created_at)"
                " VALUES (?, ?, ?, ?)",
                (int(workshop_id), str(discord_id), clean, now),
            )
            comment_id = int(cursor.lastrowid or 0)
        return self.get(comment_id)  # type: ignore[return-value]

    def get(self, comment_id: int) -> Comment | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM workshop_comment WHERE id = ?", (int(comment_id),)
            ).fetchone()
        return self._row(row) if row else None

    def for_item(self, workshop_id: int, *, limit: int = 10, offset: int = 0) -> dict:
        """One page of visible comments, oldest first, plus the total."""
        with self._connect() as conn:
            total = int(
                conn.execute(
                    "SELECT COUNT(*) FROM workshop_comment"
                    " WHERE workshop_id = ? AND hidden = 0",
                    (int(workshop_id),),
                ).fetchone()[0]
            )
            # Page from the newest end so a new comment cannot shift a reader
            # onto a row they already saw, then hand back chronological order.
            rows = conn.execute(
                "SELECT * FROM workshop_comment"
                " WHERE workshop_id = ? AND hidden = 0"
                " ORDER BY id DESC LIMIT ? OFFSET ?",
                (int(workshop_id), int(limit), int(offset)),
            ).fetchall()
        return {"items": [self._row(r) for r in reversed(rows)], "total": total}

    def latest(self, workshop_id: int, *, limit: int = 3) -> list[Comment]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM workshop_comment"
                " WHERE workshop_id = ? AND hidden = 0"
                " ORDER BY id DESC LIMIT ?",
                (int(workshop_id), int(limit)),
            ).fetchall()
        return [self._row(r) for r in reversed(rows)]

    def count(self, workshop_id: int) -> int:
        with self._connect() as conn:
            return int(
                conn.execute(
                    "SELECT COUNT(*) FROM workshop_comment"
                    " WHERE workshop_id = ? AND hidden = 0",
                    (int(workshop_id),),
                ).fetchone()[0]
            )

    def edit(self, *, comment_id: int, discord_id: str, body: str, now: str) -> Comment:
        comment = self.get(comment_id)
        if comment is None:
            raise CommentError("missing", "No such comment.")
        if comment.discord_id != str(discord_id):
            raise CommentError("not_owner", "Only the author can edit a comment.")
        if not comment.can_edit(discord_id, now):
            raise CommentError(
                "too_late", "Comments can only be edited for 15 minutes."
            )
        try:
            clean = clean_multiline(
                body, limit=BODY_MAX, field="Comment", lines_limit=LINES_MAX
            )
        except ValueError as exc:
            raise CommentError("invalid_body", str(exc)) from None
        with self._connect() as conn:
            conn.execute(
                "UPDATE workshop_comment SET body = ?, edited_at = ? WHERE id = ?",
                (clean, now, int(comment_id)),
            )
        return self.get(comment_id)  # type: ignore[return-value]

    def delete(self, *, comment_id: int, discord_id: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM workshop_comment WHERE id = ? AND discord_id = ?",
                (int(comment_id), str(discord_id)),
            )
        return cursor.rowcount > 0

    def hide(
        self, *, comment_id: int, admin_id: str, now: str, hidden: bool = True
    ) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE workshop_comment SET hidden = ?, hidden_by = ?, hidden_at = ?"
                " WHERE id = ?",
                (1 if hidden else 0, str(admin_id), now, int(comment_id)),
            )
        return cursor.rowcount > 0

    def latest_global(self, *, limit: int = 30, offset: int = 0) -> list[Comment]:
        """Newest visible comments across every build, newest first."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM workshop_comment WHERE hidden = 0"
                " ORDER BY id DESC LIMIT ? OFFSET ?",
                (int(limit), int(offset)),
            ).fetchall()
        return [self._row(row) for row in rows]

    def latest_global_count(self) -> int:
        with self._connect() as conn:
            return int(
                conn.execute(
                    "SELECT COUNT(*) FROM workshop_comment WHERE hidden = 0"
                ).fetchone()[0]
            )

    def most_commented(self, *, limit: int = 24) -> list[tuple[int, int]]:
        """(workshop_id, visible comment count), busiest first.

        Ties break on the newest comment, so a build that just got busy
        outranks one that went quiet with the same total.
        """
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT workshop_id, COUNT(*) AS n, MAX(id) AS newest"
                " FROM workshop_comment WHERE hidden = 0"
                " GROUP BY workshop_id ORDER BY n DESC, newest DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
        return [(int(row["workshop_id"]), int(row["n"])) for row in rows]

    def recent(self, *, limit: int = 100) -> list[Comment]:
        """Newest first, hidden included — for the moderation list."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM workshop_comment ORDER BY id DESC LIMIT ?", (int(limit),)
            ).fetchall()
        return [self._row(r) for r in rows]

    def for_member(self, discord_id: str, *, limit: int = 100) -> list[Comment]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM workshop_comment WHERE discord_id = ?"
                " ORDER BY id DESC LIMIT ?",
                (str(discord_id), int(limit)),
            ).fetchall()
        return [self._row(r) for r in rows]
