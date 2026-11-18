"""Read-only workshop queries with stable keyset pagination."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .payloads import vehicle_display_name

PUBLIC_WHERE = "w.deleted_at IS NULL AND COALESCE(w.hidden, 0) = 0 AND w.account_id > 0"
POPULAR_ORDER = "COALESCE(w.installed, 0) DESC, COALESCE(w.votes, 0) DESC, w.id DESC"
NEW_ORDER = "w.created_at DESC, w.id DESC"

CARD_COLUMNS = """
    w.id, w.vehicle_key, w.account_id, w.author_name, w.created_at,
    w.revision, w.votes, w.installed, w.has_paint, w.has_decal,
    w.has_parts, w.has_tunings, w.decal_layers, w.part_count, w.tags,
    w.json_sha256
"""


class QueryError(Exception):
    """Base class for client-visible query failures."""

    status = 400

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class InvalidCursor(QueryError):
    pass


class CursorStale(QueryError):
    status = 409


@dataclass(frozen=True)
class ListFilters:
    vehicle: str | None = None
    account_id: int | None = None
    paint: bool = False
    decal: bool = False
    parts: bool = False
    tuning: bool = False
    club: bool = False

    def key(self, sort: str, limit: int) -> str:
        body = {
            "sort": sort,
            "limit": limit,
            "vehicle": self.vehicle,
            "account_id": self.account_id,
            "paint": self.paint,
            "decal": self.decal,
            "parts": self.parts,
            "tuning": self.tuning,
            "club": self.club,
        }
        return hashlib.sha256(
            json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()[:20]


def _encode_cursor(data: dict[str, Any]) -> str:
    raw = json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(value: str) -> dict[str, Any]:
    if not value or len(value) > 512:
        raise InvalidCursor("invalid_cursor", "Invalid pagination cursor")
    try:
        padded = value + "=" * (-len(value) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded))
    except (ValueError, UnicodeDecodeError, binascii.Error):
        raise InvalidCursor("invalid_cursor", "Invalid pagination cursor") from None
    if not isinstance(data, dict) or data.get("v") != 1:
        raise InvalidCursor("invalid_cursor", "Unsupported pagination cursor")
    return data


def _open(path: Path) -> sqlite3.Connection:
    uri = f"file:{path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    return conn


def _tags(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if not isinstance(value, list):
        return []
    return [str(tag)[:64] for tag in value[:20] if isinstance(tag, (str, int, float))]


def _card(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "vehicleKey": row["vehicle_key"],
        "accountId": row["account_id"],
        "author": row["author_name"],
        "createdAt": row["created_at"],
        "revision": row["revision"],
        "votes": int(row["votes"] or 0),
        "installs": int(row["installed"] or 0),
        "hasPaint": bool(row["has_paint"]),
        "hasDecal": bool(row["has_decal"]),
        "hasParts": bool(row["has_parts"]),
        "hasTunings": bool(row["has_tunings"]),
        "decalLayers": int(row["decal_layers"] or 0),
        "partCount": int(row["part_count"] or 0),
        "tags": _tags(row["tags"]),
        "configHash": row["json_sha256"] or "",
    }


class WorkshopRepository:
    """Thread-safe read-only repository.

    SQLite connections are short-lived; Python-side caches only hold public
    metadata and are keyed by the query arguments.
    """

    def __init__(
        self,
        source_db: Path,
        *,
        site_db: Path | None = None,
        cache_ttl: float = 60.0,
    ):
        self.source_db = source_db
        self.site_db = site_db
        self.cache_ttl = cache_ttl
        self._cache: dict[str, tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def _connect(self) -> sqlite3.Connection:
        return _open(self.source_db)

    def _copy_override(self, item_id: int) -> int | None:
        """Return an editorially reviewed copy origin, if one is configured."""
        if self.site_db is None:
            return None
        path = self.site_db.parent / "copy_overrides.json"
        try:
            raw = path.read_text(encoding="utf-8")
            data = json.loads(raw)
        except (OSError, ValueError):
            return None
        if not isinstance(data, dict):
            return None
        value = data.get(str(item_id))
        if not isinstance(value, (int, str)):
            return None
        try:
            origin = int(value)
        except (TypeError, ValueError):
            return None
        return origin if origin > 0 and origin != item_id else None

    def _site_home(self) -> dict[str, Any] | None:
        if self.site_db is None or not self.site_db.is_file():
            return None
        try:
            conn = sqlite3.connect(
                f"file:{self.site_db}?mode=ro", uri=True, timeout=2.0
            )
            conn.row_factory = sqlite3.Row
            try:
                row = conn.execute(
                    "SELECT payload FROM home_cache WHERE slot='home'"
                ).fetchone()
            finally:
                conn.close()
            if not row:
                return None
            value = json.loads(row["payload"])
            return value if isinstance(value, dict) else None
        except (sqlite3.Error, ValueError):
            return None

    def _site_authors(self, limit: int) -> list[dict[str, Any]] | None:
        if self.site_db is None or not self.site_db.is_file():
            return None
        try:
            conn = sqlite3.connect(
                f"file:{self.site_db}?mode=ro", uri=True, timeout=2.0
            )
            conn.row_factory = sqlite3.Row
            try:
                rows = conn.execute(
                    "SELECT account_id, display_name, uploads, installs, votes, "
                    "representative_id FROM author_summary "
                    "ORDER BY installs DESC, votes DESC, account_id ASC LIMIT ?",
                    (limit,),
                ).fetchall()
            finally:
                conn.close()
        except sqlite3.Error:
            return None
        return [
            {
                "accountId": row["account_id"],
                "displayName": row["display_name"],
                "uploads": int(row["uploads"]),
                "installs": int(row["installs"] or 0),
                "votes": int(row["votes"] or 0),
                "representativeId": row["representative_id"],
            }
            for row in rows
        ]

    def _site_search_authors(
        self, query: str, limit: int
    ) -> list[dict[str, Any]] | None:
        if self.site_db is None or not self.site_db.is_file():
            return None
        escaped = query.replace("!", "!!").replace("%", "!%").replace("_", "!_")
        try:
            conn = sqlite3.connect(
                f"file:{self.site_db}?mode=ro", uri=True, timeout=2.0
            )
            conn.row_factory = sqlite3.Row
            try:
                rows = conn.execute(
                    "SELECT account_id, display_name, uploads, installs, votes, "
                    "representative_id FROM author_summary "
                    "WHERE display_name LIKE ? ESCAPE '!' COLLATE NOCASE "
                    "ORDER BY CASE WHEN display_name = ? COLLATE NOCASE THEN 0 ELSE 1 END, "
                    "installs DESC, votes DESC, account_id ASC LIMIT ?",
                    (f"%{escaped}%", query, limit),
                ).fetchall()
            finally:
                conn.close()
        except sqlite3.Error:
            return None
        return [
            {
                "accountId": row["account_id"],
                "displayName": row["display_name"],
                "uploads": int(row["uploads"]),
                "installs": int(row["installs"] or 0),
                "votes": int(row["votes"] or 0),
                "representativeId": row["representative_id"],
            }
            for row in rows
        ]

    def _site_stats(self) -> dict[str, Any] | None:
        home = self._site_home()
        if not home:
            return None
        stats = home.get("stats")
        return stats if isinstance(stats, dict) else None

    def _cached(self, key: str, factory):
        now = time.monotonic()
        with self._lock:
            hit = self._cache.get(key)
            if hit and now - hit[0] < self.cache_ttl:
                return hit[1]
        value = factory()
        with self._lock:
            self._cache[key] = (time.monotonic(), value)
        return value

    def sync_run(self, conn: sqlite3.Connection | None = None) -> int | None:
        own = conn is None
        conn = conn or self._connect()
        try:
            try:
                row = conn.execute(
                    "SELECT MAX(run_id) FROM sync_runs WHERE finished_at IS NOT NULL"
                ).fetchone()
                return int(row[0]) if row and row[0] is not None else None
            except sqlite3.OperationalError:
                return None
        finally:
            if own:
                conn.close()

    def get_item(self, workshop_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT {CARD_COLUMNS} FROM workshop w "
                f"WHERE w.id = ? AND {PUBLIC_WHERE}",
                (workshop_id,),
            ).fetchone()
        return _card(row) if row else None

    def items_by_ids(self, workshop_ids: list[int]) -> list[dict[str, Any]]:
        """Cards for a given set of ids, in the order asked for.

        Collections store ids, not copies: a build that drops out of the scrape
        simply disappears from the list instead of rendering as a hole.
        """
        ids = [int(i) for i in workshop_ids]
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT {CARD_COLUMNS} FROM workshop w "
                f"WHERE w.id IN ({placeholders}) AND {PUBLIC_WHERE}",
                ids,
            ).fetchall()
        by_id = {row["id"]: _card(row) for row in rows}
        return [by_id[i] for i in ids if i in by_id]

    def get_viewer_row(self, workshop_id: int) -> dict[str, Any] | None:
        """The sole web query allowed to read raw payload columns."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT w.id, w.vehicle_key, w.json_z, w.json_len, w.json_sha256, "
                "w.revision, w.created_at FROM workshop w "
                f"WHERE w.id = ? AND {PUBLIC_WHERE}",
                (workshop_id,),
            ).fetchone()
        return dict(row) if row else None

    def similar_items(
        self,
        item: dict[str, Any],
        *,
        limit: int = 6,
        min_sim: float = 0.60,
        copy_threshold: float = 0.95,
        flag_min_layers: int = 8,
        flag_min_similarity: float = 0.95,
    ) -> dict[str, Any]:
        """Ranked similar builds for ``item`` from the precomputed index.

        The index lives in the site database (see ``similarity.build``); the
        item rows themselves still come from the read-only source database.
        ``flagged`` is true only when the match reaches the higher flag
        threshold, predates this item, belongs to a different author, and the
        smaller of the two builds has enough decal layers to make a copy
        accusation meaningful.
        """
        limit = max(1, min(int(limit), 24))
        empty = {
            "items": [],
            "original": None,
            "flagged": False,
            "origin": None,
            "originSimilarity": None,
            "threshold": copy_threshold,
            "manual": False,
        }
        if self.site_db is None or not self.site_db.is_file():
            return empty

        item_id = int(item["id"])
        vehicle = item["vehicleKey"]
        try:
            conn = sqlite3.connect(
                f"file:{self.site_db}?mode=ro", uri=True, timeout=2.0
            )
            conn.row_factory = sqlite3.Row
            try:
                rows = conn.execute(
                    "SELECT CASE WHEN a = ? THEN b ELSE a END AS other_id, sim "
                    "FROM similar_pair "
                    "WHERE vehicle_key = ? AND (a = ? OR b = ?) AND sim >= ? "
                    "ORDER BY sim DESC, other_id ASC LIMIT ?",
                    (item_id, vehicle, item_id, item_id, min_sim, limit * 4),
                ).fetchall()
            finally:
                conn.close()
        except sqlite3.Error:
            return empty

        ranked = [(int(row["other_id"]), float(row["sim"])) for row in rows]
        if not ranked:
            return empty

        placeholders = ",".join("?" for _ in ranked)
        with self._connect() as source:
            cards = {
                int(row["id"]): _card(row)
                for row in source.execute(
                    f"SELECT {CARD_COLUMNS} FROM workshop w "
                    f"WHERE w.id IN ({placeholders}) AND {PUBLIC_WHERE} AND w.vehicle_key = ?",
                    [*[other for other, _ in ranked], vehicle],
                ).fetchall()
            }

        created = str(item.get("createdAt") or "")
        item_layers = int(item.get("decalLayers") or 0)
        flag_similarity = max(copy_threshold, flag_min_similarity)
        gallery: list[dict[str, Any]] = []
        origin: dict[str, Any] | None = None
        origin_similarity: float | None = None
        for other_id, sim in ranked:
            card = cards.get(other_id)
            if card is None:
                continue
            card["similarity"] = round(sim, 4)
            card["isEarlier"] = bool(card["createdAt"] and card["createdAt"] < created)
            if len(gallery) < limit:
                gallery.append(card)
            smaller_layers = min(item_layers, int(card.get("decalLayers") or 0))
            same_author = bool(
                item.get("accountId")
                and card.get("accountId")
                and int(item["accountId"]) == int(card["accountId"])
            )
            if (
                sim >= flag_similarity
                and smaller_layers >= flag_min_layers
                and card["isEarlier"]
                and not same_author
            ):
                if origin is None or card["createdAt"] < origin["createdAt"]:
                    origin = card
                    origin_similarity = card["similarity"]
        if origin is not None and origin not in gallery:
            gallery.insert(0, origin)
            del gallery[limit:]

        manual = False
        override_id = self._copy_override(item_id)
        if override_id is not None:
            card = cards.get(override_id)
            if card is None:
                with self._connect() as source:
                    row = source.execute(
                        f"SELECT {CARD_COLUMNS} FROM workshop w "
                        f"WHERE w.id = ? AND {PUBLIC_WHERE} AND w.vehicle_key = ?",
                        (override_id, vehicle),
                    ).fetchone()
                card = _card(row) if row is not None else None
            if card is not None:
                cards[override_id] = card
                card["similarity"] = None
                card["isEarlier"] = True
                origin = card
                origin_similarity = None
                manual = True
                if card not in gallery:
                    gallery.insert(0, card)
                    del gallery[limit:]

        earlier = [card for card in cards.values() if card.get("isEarlier")]
        if earlier:
            oldest = min(
                earlier,
                key=lambda card: (str(card.get("createdAt") or ""), int(card["id"])),
            )
            oldest["isOriginal"] = True
            if oldest not in gallery:
                gallery.insert(0, oldest)
                del gallery[limit:]

        original = next(
            (card for card in gallery if card.get("isOriginal")),
            None,
        )
        return {
            "items": gallery,
            "original": original,
            "flagged": origin is not None,
            "origin": origin,
            "originSimilarity": origin_similarity,
            "threshold": flag_similarity,
            "manual": manual,
        }

    def _where(self, filters: ListFilters) -> tuple[str, list[Any]]:
        clauses = [PUBLIC_WHERE]
        args: list[Any] = []
        if filters.vehicle:
            clauses.append("w.vehicle_key = ?")
            args.append(filters.vehicle)
        if filters.account_id is not None:
            clauses.append("w.account_id = ?")
            args.append(filters.account_id)
        for enabled, column in (
            (filters.paint, "has_paint"),
            (filters.decal, "has_decal"),
            (filters.parts, "has_parts"),
            (filters.tuning, "has_tunings"),
        ):
            if enabled:
                clauses.append(f"w.{column} = 1")
        if filters.club:
            clauses.append(
                "EXISTS (SELECT 1 FROM club_character c "
                "WHERE c.character_guid = w.character_guid)"
            )
        return " AND ".join(clauses), args

    def list_items(
        self,
        *,
        sort: str = "popular",
        filters: ListFilters | None = None,
        limit: int = 24,
        cursor: str | None = None,
        offset: int = 0,
    ) -> dict[str, Any]:
        filters = filters or ListFilters()
        if sort not in {"popular", "new"}:
            raise QueryError("invalid_sort", "sort must be popular or new")
        offset = max(0, int(offset))
        where, args = self._where(filters)
        filter_key = filters.key(sort, limit)
        with self._connect() as conn:
            run = self.sync_run(conn)
            cursor_data = _decode_cursor(cursor) if cursor else None
            if cursor_data and offset:
                raise InvalidCursor(
                    "invalid_cursor", "Use either cursor or offset pagination"
                )
            if cursor_data:
                if cursor_data.get("f") != filter_key or cursor_data.get("s") != sort:
                    raise InvalidCursor(
                        "invalid_cursor", "Cursor does not match these filters"
                    )
                if (
                    sort == "popular"
                    and cursor_data.get("run") is not None
                    and run is not None
                    and cursor_data["run"] != run
                ):
                    raise CursorStale(
                        "cursor_stale",
                        "Popularity changed; reload the first page",
                    )
                key = cursor_data.get("k")
                if not isinstance(key, list) or len(key) != (
                    3 if sort == "popular" else 2
                ):
                    raise InvalidCursor("invalid_cursor", "Invalid cursor key")
                if sort == "popular":
                    where += (
                        " AND (COALESCE(w.installed,0),COALESCE(w.votes,0),w.id) "
                        "< (?,?,?)"
                    )
                    args.extend([int(key[0]), int(key[1]), int(key[2])])
                else:
                    where += " AND (w.created_at,w.id) < (?,?)"
                    args.extend([str(key[0]), int(key[1])])
            order = POPULAR_ORDER if sort == "popular" else NEW_ORDER
            sql = (
                f"SELECT {CARD_COLUMNS} FROM workshop w WHERE {where} "
                f"ORDER BY {order} LIMIT ? OFFSET ?"
            )
            rows = conn.execute(sql, [*args, limit + 1, offset]).fetchall()
        has_more = len(rows) > limit
        rows = rows[:limit]
        next_cursor = None
        if has_more and rows:
            last = rows[-1]
            key = (
                [
                    int(last["installed"] or 0),
                    int(last["votes"] or 0),
                    int(last["id"]),
                ]
                if sort == "popular"
                else [last["created_at"], int(last["id"])]
            )
            next_cursor = _encode_cursor(
                {
                    "v": 1,
                    "s": sort,
                    "f": filter_key,
                    "k": key,
                    "run": run if sort == "popular" else None,
                }
            )
        return {
            "items": [_card(row) for row in rows],
            "nextCursor": next_cursor,
            "runId": run,
            "sort": sort,
        }

    def items_for_steam_id(
        self, steam_id: int, limit: int = 24
    ) -> list[dict[str, Any]]:
        """Builds a club member uploaded, resolved through ``club_character``.

        The workshop scrape carries no Steam identity, so Discord → player →
        character GUID is the only trustworthy path to "your builds".
        """
        limit = max(1, min(int(limit), 60))
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT {CARD_COLUMNS} FROM workshop w WHERE {PUBLIC_WHERE} "
                "AND EXISTS (SELECT 1 FROM club_character c "
                "WHERE c.character_guid = w.character_guid AND c.steam_id = ?) "
                f"ORDER BY {NEW_ORDER} LIMIT ?",
                [str(steam_id), limit],
            ).fetchall()
        return [_card(row) for row in rows]

    def items_for_guids(
        self, guids: Any, limit: int = 60
    ) -> list[dict[str, Any]]:
        """Builds uploaded by any of these character GUIDs.

        This is the ownership query: GUIDs come from the game server, not from
        anything the workshop scrape can be talked into believing.
        """
        wanted = sorted({str(guid).upper() for guid in guids if guid})[:500]
        if not wanted:
            return []
        limit = max(1, min(int(limit), 60))
        placeholders = ",".join("?" for _ in wanted)
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT {CARD_COLUMNS}, w.character_guid FROM workshop w "
                f"WHERE {PUBLIC_WHERE} "
                f"AND UPPER(w.character_guid) IN ({placeholders}) "
                f"ORDER BY {NEW_ORDER} LIMIT ?",
                [*wanted, limit],
            ).fetchall()
        items = []
        for row in rows:
            card = _card(row)
            card["characterGuid"] = (row["character_guid"] or "").upper()
            items.append(card)
        return items

    def search_authors(self, query: str, limit: int = 24) -> list[dict[str, Any]]:
        query = " ".join(query.strip().split())[:80]
        if not query:
            return []
        limit = max(1, min(limit, 48))
        site = self._site_search_authors(query, limit)
        if site is not None:
            return site
        escaped = query.replace("!", "!!").replace("%", "!%").replace("_", "!_")
        sql = f"""
            WITH public AS (
              SELECT w.* FROM workshop w
              WHERE {PUBLIC_WHERE} AND w.account_id IN (
                SELECT account_id FROM workshop m
                WHERE m.deleted_at IS NULL AND COALESCE(m.hidden,0)=0
                  AND m.account_id>0 AND m.author_name LIKE ? ESCAPE '!' COLLATE NOCASE
              )
            ), agg AS (
              SELECT account_id, COUNT(*) AS uploads,
                     SUM(COALESCE(installed,0)) AS installs,
                     SUM(COALESCE(votes,0)) AS votes,
                     (SELECT a2.author_name FROM public a2
                       WHERE a2.account_id=p.account_id AND a2.author_name IS NOT NULL
                       ORDER BY a2.created_at DESC,a2.id DESC LIMIT 1) AS display_name,
                     (SELECT a3.id FROM public a3 WHERE a3.account_id=p.account_id
                       ORDER BY COALESCE(a3.installed,0) DESC,COALESCE(a3.votes,0) DESC,
                                a3.id DESC LIMIT 1) AS representative_id
              FROM public p GROUP BY account_id
            )
            SELECT account_id,display_name,uploads,installs,votes,representative_id
            FROM agg
            ORDER BY CASE WHEN display_name=? COLLATE NOCASE THEN 0 ELSE 1 END,
                     installs DESC,votes DESC,account_id ASC LIMIT ?
        """
        with self._connect() as conn:
            rows = conn.execute(sql, (f"%{escaped}%", query, limit)).fetchall()
        return [
            {
                "accountId": row["account_id"],
                "displayName": row["display_name"],
                "uploads": int(row["uploads"]),
                "installs": int(row["installs"] or 0),
                "votes": int(row["votes"] or 0),
                "representativeId": row["representative_id"],
            }
            for row in rows
        ]

    def _site_authors_page(
        self, query: str, limit: int, offset: int
    ) -> tuple[list[dict[str, Any]], int] | None:
        if self.site_db is None or not self.site_db.is_file():
            return None
        where = ""
        params: list[Any] = []
        if query:
            escaped = query.replace("!", "!!").replace("%", "!%").replace("_", "!_")
            where = "WHERE display_name LIKE ? ESCAPE '!' COLLATE NOCASE "
            params.append(f"%{escaped}%")
        try:
            conn = sqlite3.connect(
                f"file:{self.site_db}?mode=ro", uri=True, timeout=2.0
            )
            conn.row_factory = sqlite3.Row
            try:
                total = int(
                    conn.execute(
                        f"SELECT COUNT(*) FROM author_summary {where}", params
                    ).fetchone()[0]
                )
                rows = conn.execute(
                    "SELECT account_id, display_name, uploads, installs, votes, "
                    "representative_id FROM author_summary "
                    f"{where}"
                    "ORDER BY installs DESC, votes DESC, account_id ASC "
                    "LIMIT ? OFFSET ?",
                    [*params, limit, offset],
                ).fetchall()
            finally:
                conn.close()
        except sqlite3.Error:
            return None
        return (
            [
                {
                    "accountId": row["account_id"],
                    "displayName": row["display_name"],
                    "uploads": int(row["uploads"]),
                    "installs": int(row["installs"] or 0),
                    "votes": int(row["votes"] or 0),
                    "representativeId": row["representative_id"],
                }
                for row in rows
            ],
            total,
        )

    def authors_page(
        self, *, query: str = "", limit: int = 24, offset: int = 0
    ) -> dict[str, Any]:
        """One page of public authors, ranked by installs and optionally searched by name."""
        query = " ".join(query.strip().split())[:80]
        limit = max(1, min(int(limit), 60))
        offset = max(0, int(offset))
        site = self._site_authors_page(query, limit, offset)
        if site is not None:
            items, total = site
        else:
            escaped = query.replace("!", "!!").replace("%", "!%").replace("_", "!_")
            where = ""
            args: list[Any] = []
            if query:
                where = "WHERE display_name LIKE ? ESCAPE '!' COLLATE NOCASE"
                args.append(f"%{escaped}%")
            base = f"""
                WITH public AS (
                  SELECT w.* FROM workshop w WHERE {PUBLIC_WHERE}
                ), agg AS (
                  SELECT account_id,
                         COUNT(*) AS uploads,
                         SUM(COALESCE(installed,0)) AS installs,
                         SUM(COALESCE(votes,0)) AS votes,
                         (SELECT a2.author_name FROM public a2
                           WHERE a2.account_id = p.account_id AND a2.author_name IS NOT NULL
                           ORDER BY a2.created_at DESC, a2.id DESC LIMIT 1) AS display_name,
                         (SELECT a3.id FROM public a3
                           WHERE a3.account_id = p.account_id
                           ORDER BY COALESCE(a3.installed,0) DESC,
                                    COALESCE(a3.votes,0) DESC, a3.id DESC LIMIT 1)
                           AS representative_id
                  FROM public p GROUP BY account_id
                )
                SELECT account_id, display_name, uploads, installs, votes,
                       representative_id, COUNT(*) OVER () AS total
                FROM agg {where}
                ORDER BY installs DESC, votes DESC, account_id ASC
                LIMIT ? OFFSET ?
            """
            with self._connect() as conn:
                rows = conn.execute(
                    base, [*args, limit, offset]
                ).fetchall()
            total = int(rows[0]["total"]) if rows else 0
            if not rows and offset:
                count_sql = f"""
                    WITH public AS (
                      SELECT w.* FROM workshop w WHERE {PUBLIC_WHERE}
                    ), agg AS (
                      SELECT account_id,
                             (SELECT a2.author_name FROM public a2
                               WHERE a2.account_id = p.account_id AND a2.author_name IS NOT NULL
                               ORDER BY a2.created_at DESC, a2.id DESC LIMIT 1) AS display_name
                      FROM public p GROUP BY account_id
                    )
                    SELECT COUNT(*) FROM agg {where}
                """
                with self._connect() as conn:
                    total = int(conn.execute(count_sql, args).fetchone()[0])
            items = [
                {
                    "accountId": row["account_id"],
                    "displayName": row["display_name"],
                    "uploads": int(row["uploads"]),
                    "installs": int(row["installs"] or 0),
                    "votes": int(row["votes"] or 0),
                    "representativeId": row["representative_id"],
                }
                for row in rows
            ]
        return {"items": items, "total": total, "query": query}

    def search_vehicles(self, query: str, limit: int = 12) -> list[dict[str, Any]]:
        """Match vehicle keys or display names, with exact/prefix matches first."""
        needle = " ".join(query.strip().split()).casefold()
        if not needle:
            return []
        limit = max(1, min(int(limit), 48))
        matches: list[tuple[int, int, str, str, int]] = []
        for row in self.vehicles(limit=500):
            key = str(row["vehicleKey"])
            name = vehicle_display_name(key)
            haystacks = {name.casefold(), key.replace("_", " ").casefold(), key.casefold()}
            score = 3
            if needle in {n for n in haystacks if n == needle}:
                score = 0
            elif any(n.startswith(needle) for n in haystacks):
                score = 1
            elif any(needle in n for n in haystacks):
                score = 2
            if score < 3:
                matches.append((score, -int(row["uploads"]), name, key, int(row["uploads"])))
        matches.sort()
        return [
            {"vehicleKey": key, "displayName": name, "uploads": uploads}
            for _, _, name, key, uploads in matches[:limit]
        ]

    def authors(self, limit: int = 10) -> list[dict[str, Any]]:
        site = self._site_authors(limit)
        if site is not None:
            return site
        sql = f"""
            WITH public AS (
              SELECT w.* FROM workshop w WHERE {PUBLIC_WHERE}
            ),
            agg AS (
              SELECT account_id,
                     COUNT(*) AS uploads,
                     SUM(COALESCE(installed,0)) AS installs,
                     SUM(COALESCE(votes,0)) AS votes,
                     (SELECT a2.author_name FROM public a2
                       WHERE a2.account_id = p.account_id AND a2.author_name IS NOT NULL
                       ORDER BY a2.created_at DESC, a2.id DESC LIMIT 1) AS display_name,
                     (SELECT a3.id FROM public a3
                       WHERE a3.account_id = p.account_id
                       ORDER BY COALESCE(a3.installed,0) DESC,
                                COALESCE(a3.votes,0) DESC, a3.id DESC LIMIT 1)
                       AS representative_id
              FROM public p GROUP BY account_id
            )
            SELECT account_id, display_name, uploads, installs, votes,
                   representative_id
            FROM agg ORDER BY installs DESC, votes DESC, account_id ASC LIMIT ?
        """
        with self._connect() as conn:
            rows = conn.execute(sql, (limit,)).fetchall()
        return [
            {
                "accountId": row["account_id"],
                "displayName": row["display_name"],
                "uploads": int(row["uploads"]),
                "installs": int(row["installs"] or 0),
                "votes": int(row["votes"] or 0),
                "representativeId": row["representative_id"],
            }
            for row in rows
        ]

    def author(self, account_id: int) -> dict[str, Any] | None:
        sql = f"""
            SELECT COUNT(*) AS uploads,
                   SUM(COALESCE(w.installed,0)) AS installs,
                   SUM(COALESCE(w.votes,0)) AS votes,
                   (SELECT a.author_name FROM workshop a
                     WHERE a.account_id = ? AND a.author_name IS NOT NULL
                       AND a.deleted_at IS NULL AND COALESCE(a.hidden,0)=0
                     ORDER BY a.created_at DESC, a.id DESC LIMIT 1) AS display_name
            FROM workshop w WHERE {PUBLIC_WHERE} AND w.account_id = ?
        """
        with self._connect() as conn:
            row = conn.execute(sql, (account_id, account_id)).fetchone()
        if not row or not int(row["uploads"] or 0):
            return None
        return {
            "accountId": account_id,
            "displayName": row["display_name"],
            "uploads": int(row["uploads"]),
            "installs": int(row["installs"] or 0),
            "votes": int(row["votes"] or 0),
        }

    def count_items(self, filters: ListFilters | None = None) -> int:
        filters = filters or ListFilters()
        where, args = self._where(filters)
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT COUNT(*) AS total FROM workshop w WHERE {where}",
                args,
            ).fetchone()
        return int(row["total"] if row else 0)

    def vehicle_uploads(self, vehicle: str) -> int:
        return self.count_items(ListFilters(vehicle=vehicle))

    def vehicles(self, limit: int = 200) -> list[dict[str, Any]]:
        sql = f"""
            SELECT w.vehicle_key, COUNT(*) AS uploads
            FROM workshop w WHERE {PUBLIC_WHERE}
            GROUP BY w.vehicle_key
            ORDER BY uploads DESC, w.vehicle_key ASC LIMIT ?
        """
        with self._connect() as conn:
            rows = conn.execute(sql, (limit,)).fetchall()
        return [
            {"vehicleKey": row["vehicle_key"], "uploads": int(row["uploads"])}
            for row in rows
        ]

    def home(self, limit: int = 10) -> dict[str, Any]:
        cached_home = self._site_home()
        if cached_home:
            return cached_home

        def build() -> dict[str, Any]:
            popular = self.list_items(sort="popular", limit=limit)
            newest = self.list_items(sort="new", limit=limit)
            return {
                "popular": popular["items"],
                "newest": newest["items"],
                "authors": self.authors(limit=min(limit, 10)),
                "runId": popular["runId"],
            }

        return self._cached(f"home:{limit}", build)

    def stats(self) -> dict[str, Any]:
        cached_stats = self._site_stats()
        if cached_stats is not None:
            return cached_stats

        def build():
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT COUNT(*) AS items, COUNT(DISTINCT account_id) AS accounts, "
                    "COUNT(DISTINCT vehicle_key) AS vehicles, "
                    "MAX(created_at) AS newest_upload FROM workshop w "
                    f"WHERE {PUBLIC_WHERE}"
                ).fetchone()
                return {
                    "items": int(row["items"]),
                    "accounts": int(row["accounts"]),
                    "vehicles": int(row["vehicles"]),
                    "newestUpload": row["newest_upload"],
                    "runId": self.sync_run(conn),
                }

        return self._cached("stats", build)
