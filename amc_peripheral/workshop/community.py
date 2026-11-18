"""Community-authored data for the workshop site.

The scrape database is opened read-only by ``queries.WorkshopRepository``.
This store owns the *writes* that live alongside it in the same site database:
which builds belong to which signed-in member, their profile, and the
title/description overrides they put on their own builds.

Three processes share the file (web, aggregate tick, snapshot worker), so every
connection is short-lived, WAL is on and ``busy_timeout`` is generous: writes
are human-scale, and a lock timeout means a bug, not load.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS workshop_claim (
    workshop_id      INTEGER PRIMARY KEY,
    discord_id       TEXT NOT NULL,
    steam_id         TEXT NOT NULL,
    character_guid   TEXT NOT NULL,
    claimed_at       TEXT NOT NULL,
    last_verified_at TEXT NOT NULL,
    revoked_at       TEXT
);
CREATE INDEX IF NOT EXISTS ix_claim_discord ON workshop_claim(discord_id);

CREATE TABLE IF NOT EXISTS workshop_profile (
    discord_id    TEXT PRIMARY KEY,
    display_name  TEXT,
    bio           TEXT,
    hidden        INTEGER NOT NULL DEFAULT 0,
    updated_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS workshop_item_meta (
    workshop_id  INTEGER PRIMARY KEY,
    title        TEXT,
    description  TEXT,
    hidden       INTEGER NOT NULL DEFAULT 0,
    updated_by   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS workshop_claim_event (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    workshop_id  INTEGER NOT NULL,
    discord_id   TEXT NOT NULL,
    action       TEXT NOT NULL,
    detail       TEXT,
    at           TEXT NOT NULL
);
"""


@dataclass(frozen=True)
class Claim:
    workshop_id: int
    discord_id: str
    steam_id: str
    character_guid: str
    claimed_at: str
    last_verified_at: str
    revoked_at: str | None = None

    @property
    def active(self) -> bool:
        return self.revoked_at is None


@dataclass(frozen=True)
class Profile:
    discord_id: str
    display_name: str | None
    bio: str | None
    hidden: bool
    updated_at: str


@dataclass(frozen=True)
class ItemMeta:
    workshop_id: int
    title: str | None
    description: str | None
    hidden: bool
    updated_by: str
    updated_at: str


class CommunityStore:
    """Reads and writes for claims, profiles and per-item metadata."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(SCHEMA)

    # -- plumbing ---------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=3000")
        return conn

    # -- claims -----------------------------------------------------------

    def claim_for(self, workshop_id: int) -> Claim | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM workshop_claim WHERE workshop_id = ?", (workshop_id,)
            ).fetchone()
        return _claim(row) if row else None

    def claims_for(self, discord_id: str) -> dict[int, Claim]:
        """Every claim row for a member, revoked ones included."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM workshop_claim WHERE discord_id = ?", (str(discord_id),)
            ).fetchall()
        return {row["workshop_id"]: _claim(row) for row in rows}

    def claim_ids(self, discord_id: str) -> set[int]:
        """Ids of the builds this member can currently edit."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT workshop_id FROM workshop_claim "
                "WHERE discord_id = ? AND revoked_at IS NULL",
                (str(discord_id),),
            ).fetchall()
        return {row["workshop_id"] for row in rows}

    def upsert_claim(
        self,
        *,
        workshop_id: int,
        discord_id: str,
        steam_id: str,
        character_guid: str,
        now: str,
    ) -> bool:
        """Record or refresh a claim. Returns True when it was newly created."""
        discord_id = str(discord_id)
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT discord_id FROM workshop_claim WHERE workshop_id = ?",
                (workshop_id,),
            ).fetchone()
            conn.execute(
                "INSERT INTO workshop_claim (workshop_id, discord_id, steam_id,"
                " character_guid, claimed_at, last_verified_at, revoked_at)"
                " VALUES (?, ?, ?, ?, ?, ?, NULL)"
                " ON CONFLICT(workshop_id) DO UPDATE SET"
                "   discord_id = excluded.discord_id,"
                "   steam_id = excluded.steam_id,"
                "   character_guid = excluded.character_guid,"
                "   last_verified_at = excluded.last_verified_at,"
                "   revoked_at = NULL",
                (
                    workshop_id,
                    discord_id,
                    str(steam_id),
                    str(character_guid).upper(),
                    now,
                    now,
                ),
            )
        return existing is None or existing["discord_id"] != discord_id

    def revoke_claim(self, workshop_id: int, now: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE workshop_claim SET revoked_at = ? "
                "WHERE workshop_id = ? AND revoked_at IS NULL",
                (now, workshop_id),
            )

    # -- profiles ---------------------------------------------------------

    def profile(self, discord_id: str) -> Profile | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM workshop_profile WHERE discord_id = ?",
                (str(discord_id),),
            ).fetchone()
        return _profile(row) if row else None

    def save_profile(
        self,
        *,
        discord_id: str,
        display_name: str | None,
        bio: str | None,
        now: str,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO workshop_profile (discord_id, display_name, bio,"
                " hidden, updated_at) VALUES (?, ?, ?, 0, ?)"
                " ON CONFLICT(discord_id) DO UPDATE SET"
                "   display_name = excluded.display_name,"
                "   bio = excluded.bio,"
                "   updated_at = excluded.updated_at",
                (str(discord_id), display_name, bio, now),
            )

    # -- item metadata ----------------------------------------------------

    def meta(self, workshop_id: int) -> ItemMeta | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM workshop_item_meta WHERE workshop_id = ?",
                (workshop_id,),
            ).fetchone()
        return _meta(row) if row else None

    def meta_for(self, workshop_ids: list[int]) -> dict[int, ItemMeta]:
        if not workshop_ids:
            return {}
        placeholders = ",".join("?" for _ in workshop_ids)
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM workshop_item_meta WHERE workshop_id IN ({placeholders})",
                list(workshop_ids),
            ).fetchall()
        return {row["workshop_id"]: _meta(row) for row in rows}

    def save_meta(
        self,
        *,
        workshop_id: int,
        discord_id: str,
        title: str | None,
        description: str | None,
        now: str,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO workshop_item_meta (workshop_id, title, description,"
                " hidden, updated_by, updated_at) VALUES (?, ?, ?, 0, ?, ?)"
                " ON CONFLICT(workshop_id) DO UPDATE SET"
                "   title = excluded.title,"
                "   description = excluded.description,"
                "   updated_by = excluded.updated_by,"
                "   updated_at = excluded.updated_at",
                (workshop_id, title, description, str(discord_id), now),
            )

    # -- moderation -------------------------------------------------------

    def set_hidden(
        self,
        *,
        hidden: bool,
        workshop_id: int | None = None,
        discord_id: str | None = None,
        now: str,
    ) -> None:
        if (workshop_id is None) == (discord_id is None):
            raise ValueError("pass exactly one of workshop_id / discord_id")
        value = 1 if hidden else 0
        with self._connect() as conn:
            if workshop_id is not None:
                conn.execute(
                    "UPDATE workshop_item_meta SET hidden = ? WHERE workshop_id = ?",
                    (value, workshop_id),
                )
            else:
                conn.execute(
                    "UPDATE workshop_profile SET hidden = ? WHERE discord_id = ?",
                    (value, str(discord_id)),
                )

    def log_event(
        self,
        *,
        workshop_id: int,
        discord_id: str,
        action: str,
        at: str,
        detail: str | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO workshop_claim_event (workshop_id, discord_id, action,"
                " detail, at) VALUES (?, ?, ?, ?, ?)",
                (workshop_id, str(discord_id), action, detail, at),
            )

    def stats(self) -> dict[str, int]:
        with self._connect() as conn:
            return {
                "claims": conn.execute(
                    "SELECT COUNT(*) FROM workshop_claim WHERE revoked_at IS NULL"
                ).fetchone()[0],
                "profiles": conn.execute(
                    "SELECT COUNT(*) FROM workshop_profile"
                ).fetchone()[0],
                "titles": conn.execute(
                    "SELECT COUNT(*) FROM workshop_item_meta WHERE title IS NOT NULL"
                ).fetchone()[0],
            }


def _claim(row: sqlite3.Row) -> Claim:
    return Claim(
        workshop_id=row["workshop_id"],
        discord_id=row["discord_id"],
        steam_id=row["steam_id"],
        character_guid=row["character_guid"],
        claimed_at=row["claimed_at"],
        last_verified_at=row["last_verified_at"],
        revoked_at=row["revoked_at"],
    )


def _profile(row: sqlite3.Row) -> Profile:
    return Profile(
        discord_id=row["discord_id"],
        display_name=row["display_name"],
        bio=row["bio"],
        hidden=bool(row["hidden"]),
        updated_at=row["updated_at"],
    )


def _meta(row: sqlite3.Row) -> ItemMeta:
    return ItemMeta(
        workshop_id=row["workshop_id"],
        title=row["title"],
        description=row["description"],
        hidden=bool(row["hidden"]),
        updated_by=row["updated_by"],
        updated_at=row["updated_at"],
    )
