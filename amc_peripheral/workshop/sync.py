"""Scrape the in-game workshop API into the read-only source database.

The workshop (garage paint / decal / parts sharing) is not Steam Workshop and has
no web page: it is a service at ``https://www.racers.co.kr:8282``. This module is
the only writer of ``settings.source_db``; every other workshop process opens that
database read-only.

Two facts about the API shape everything here:

* **Pagination is lossy.** The endpoint pages with a drifting sort, so pages
  overlap and the tail is unreachable (a key reporting ``pages=5`` yields ~70% of
  its rows over five paginated requests). Asking for ``count >= total`` returns the
  whole key in one response with ``pages=1``. Never page.
* **A few payloads are malformed server-side.** Those rows are stored in
  ``quarantine`` instead of being dropped.

Usage::

    amc_workshop_sync --mode delta     # newest N per vehicle key, hourly
    amc_workshop_sync --mode full      # whole key per request, tombstones removals
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import random
import sqlite3
import time
import urllib.error
import urllib.request
import zlib
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import WorkshopSettings

log = logging.getLogger(__name__)

API_URL = "https://www.racers.co.kr:8282/workshop/list"
USER_AGENT = "amc-workshop-sync/1.0 (+https://aseanmotorclub.com)"
CATEGORY = "Garage"
RETRIES = 6
REQUEST_DELAY = 0.4
FULL_COUNT = 200_000
# delta probes the newest rows only. Global upload volume is ~150/day, so 120 rows
# per key covers a day of headroom; a key with more new ids than that widens once
# to CATCHUP_COUNT before writing.
PROBE_COUNT = 120
CATCHUP_COUNT = 2_000
VEHICLE_KEYS_FILE = Path(__file__).with_name("vehicle_keys.json")

SCHEMA = """
CREATE TABLE IF NOT EXISTS workshop (
  id             INTEGER PRIMARY KEY,
  vehicle_key    TEXT    NOT NULL,
  category       TEXT    NOT NULL,
  account_id     INTEGER NOT NULL,
  character_guid TEXT    NOT NULL,
  created_at     TEXT    NOT NULL,
  json_sha256    TEXT    NOT NULL,
  json_len       INTEGER NOT NULL,
  json_z         BLOB    NOT NULL,
  has_paint      INTEGER NOT NULL,
  has_decal      INTEGER NOT NULL,
  has_parts      INTEGER NOT NULL,
  has_tunings    INTEGER NOT NULL,
  decal_layers   INTEGER NOT NULL DEFAULT 0,
  part_count     INTEGER NOT NULL DEFAULT 0,
  paint_slots    TEXT,
  tags           TEXT,
  revision       INTEGER NOT NULL DEFAULT 1,
  first_seen     TEXT    NOT NULL,
  last_seen      TEXT    NOT NULL,
  deleted_at     TEXT,
  author_name    TEXT,
  votes          INTEGER,
  reports        INTEGER,
  installed      INTEGER,
  hidden         INTEGER,
  hot            REAL,
  duplicate_key  TEXT
);
CREATE INDEX IF NOT EXISTS ix_ws_vehicle ON workshop(vehicle_key, created_at);
CREATE INDEX IF NOT EXISTS ix_ws_account ON workshop(account_id);
CREATE INDEX IF NOT EXISTS ix_ws_created ON workshop(created_at);
CREATE INDEX IF NOT EXISTS ix_ws_live    ON workshop(deleted_at);
CREATE INDEX IF NOT EXISTS ix_ws_author  ON workshop(author_name);
CREATE INDEX IF NOT EXISTS ix_ws_installed ON workshop(installed);

CREATE TABLE IF NOT EXISTS workshop_part (
  workshop_id INTEGER NOT NULL,
  slot        TEXT    NOT NULL,
  part_key    TEXT    NOT NULL,
  PRIMARY KEY (workshop_id, slot)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS workshop_decal_layer (
  workshop_id INTEGER NOT NULL,
  idx         INTEGER NOT NULL,
  decal_key   TEXT    NOT NULL,
  r INTEGER, g INTEGER, b INTEGER, a INTEGER,
  x REAL, y REAL,
  pitch REAL, yaw REAL, roll REAL,
  scale REAL, stretch REAL, coverage REAL, flags INTEGER,
  PRIMARY KEY (workshop_id, idx)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS workshop_tuning (
  workshop_id INTEGER NOT NULL,
  param       TEXT    NOT NULL,
  target_id   INTEGER,
  value       REAL,
  PRIMARY KEY (workshop_id, param, target_id)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS sync_state (
  vehicle_key   TEXT PRIMARY KEY,
  max_id        INTEGER NOT NULL DEFAULT 0,
  last_probe_at TEXT,
  last_new_at   TEXT
);

CREATE TABLE IF NOT EXISTS quarantine (
  id          INTEGER PRIMARY KEY,
  vehicle_key TEXT NOT NULL,
  created_at  TEXT,
  account_id  INTEGER,
  reason      TEXT NOT NULL,
  raw_z       BLOB NOT NULL,
  found_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sync_runs (
  run_id      INTEGER PRIMARY KEY AUTOINCREMENT,
  mode        TEXT NOT NULL,
  started_at  TEXT NOT NULL,
  finished_at TEXT,
  keys_total  INTEGER, keys_ok INTEGER, keys_failed INTEGER,
  inserted    INTEGER, updated INTEGER, unchanged INTEGER,
  quarantined INTEGER, deleted INTEGER, errors TEXT
);

CREATE TABLE IF NOT EXISTS workshop_event (
  seq         INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id      INTEGER NOT NULL,
  workshop_id INTEGER NOT NULL,
  action      TEXT    NOT NULL,
  at          TEXT    NOT NULL,
  old_sha     TEXT,
  new_sha     TEXT
);
CREATE INDEX IF NOT EXISTS ix_ws_events_run ON workshop_event(run_id);

CREATE VIEW IF NOT EXISTS workshop_live AS
  SELECT * FROM workshop WHERE deleted_at IS NULL;
"""


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def vehicle_keys(path: Path = VEHICLE_KEYS_FILE) -> list[str]:
    """Vehicle keys the workshop is keyed by (see the module's JSON file)."""
    return list(json.loads(path.read_text()))


# --------------------------------------------------------------------------- #
# API
# --------------------------------------------------------------------------- #
def fetch(vehicle_key: str, count: int, timeout: int = 300) -> dict[str, Any]:
    """One request for one vehicle key. ``count >= total`` avoids pagination."""
    body = json.dumps(
        {
            "character_guid": "0",
            "category": CATEGORY,
            "vehicle_key": vehicle_key,
            "count": count,
            "page": 1,
        }
    ).encode()
    last = "unknown error"
    for attempt in range(RETRIES):
        request = urllib.request.Request(
            API_URL,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": USER_AGENT,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode())
        except urllib.error.HTTPError as error:
            last = f"HTTP {error.code}"
            if error.code not in (429, 500, 502, 503, 504):
                raise
        except Exception as error:  # noqa: BLE001 - timeouts, resets, partial reads
            # Large keys (~120 MB) are regularly cut short mid-body; a retry is
            # the documented recovery, not a real failure.
            last = f"{type(error).__name__}: {str(error)[:80]}"
        wait = (2**attempt) * 2 + random.random()
        log.warning(
            "retry %s/%s for %s (%s) in %.1fs",
            attempt + 1,
            RETRIES,
            vehicle_key,
            last,
            wait,
        )
        time.sleep(wait)
    raise RuntimeError(f"fetch failed for {vehicle_key}: {last}")


# --------------------------------------------------------------------------- #
# payload decoding
# --------------------------------------------------------------------------- #
def decode_payload(json_data: str) -> dict[str, Any]:
    """Flatten one ``json_data`` blob into its queryable columns."""
    payload = json.loads(json_data)
    if not isinstance(payload, dict):
        raise ValueError("json_data root is not an object")

    paint = payload.get("paint") or {}
    slots = []
    for slot in paint.get("bodyColors") or []:
        color = slot.get("color") or {}
        red, green, blue, alpha = (
            int(color.get(key) or 0) for key in ("r", "g", "b", "a")
        )
        slots.append(
            {
                "slot": slot.get("materialSlotName"),
                "rgba": f"#{red:02x}{green:02x}{blue:02x}{alpha:02x}",
                "metallic": slot.get("metallic"),
                "roughness": slot.get("roughness"),
            }
        )

    decal = (payload.get("decal") or {}).get("decal") or {}
    layers = decal.get("decalLayers") or []
    parts = (payload.get("parts") or {}).get("parts") or []
    tunings = payload.get("tunings") or []
    tags = payload.get("workshopTags") or payload.get("WorkshopTags") or []

    return {
        "has_paint": int(bool(payload.get("bHasPaint"))),
        "has_decal": int(bool(payload.get("bHasDecal"))),
        "has_parts": int(bool(payload.get("bHasParts"))),
        "has_tunings": int(bool(payload.get("bHasTunings"))),
        "decal_layers": len(layers),
        "part_count": len(parts),
        "paint_slots": json.dumps(slots, separators=(",", ":")) if slots else None,
        "tags": json.dumps(tags, separators=(",", ":")) if tags else None,
        "parts": [
            (part.get("slot"), part.get("key")) for part in parts if part.get("slot")
        ],
        "layers": layers,
        "tunings": tunings,
    }


# --------------------------------------------------------------------------- #
# store
# --------------------------------------------------------------------------- #
class SyncStore:
    """Writer for the source database. Only this module writes it."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=60)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        connection.execute("PRAGMA cache_size=-262144")
        connection.execute("PRAGMA temp_store=MEMORY")
        connection.executescript(SCHEMA)
        return connection

    # -- watermarks ---------------------------------------------------------
    def watermark(self, connection: sqlite3.Connection, vehicle_key: str) -> int:
        """Highest workshop id already stored for this key (0 when unknown)."""
        row = connection.execute(
            "SELECT max_id FROM sync_state WHERE vehicle_key=?", (vehicle_key,)
        ).fetchone()
        return int(row[0]) if row else 0

    def set_watermark(
        self, connection: sqlite3.Connection, vehicle_key: str, max_id: int
    ) -> None:
        stamp = _now()
        connection.execute(
            """INSERT INTO sync_state (vehicle_key, max_id, last_probe_at, last_new_at)
               VALUES (?,?,?,?)
               ON CONFLICT(vehicle_key) DO UPDATE SET
                 max_id=MAX(sync_state.max_id, excluded.max_id),
                 last_probe_at=excluded.last_probe_at,
                 last_new_at=CASE WHEN excluded.max_id > sync_state.max_id
                                  THEN excluded.last_new_at ELSE sync_state.last_new_at END""",
            (vehicle_key, max_id, stamp, stamp),
        )
        connection.commit()

    def mark_probed(self, connection: sqlite3.Connection, vehicle_key: str) -> None:
        """Record a probe that found nothing new, without touching the watermark."""
        connection.execute(
            """INSERT INTO sync_state (vehicle_key, max_id, last_probe_at)
               VALUES (?,0,?)
               ON CONFLICT(vehicle_key) DO UPDATE SET last_probe_at=excluded.last_probe_at""",
            (vehicle_key, _now()),
        )
        connection.commit()

    def bootstrap_watermarks(self, connection: sqlite3.Connection) -> int:
        """Seed watermarks from rows already stored (first delta after a migration).

        Without this, a database populated before watermarks existed would report
        every stored id as "new" on the first run and re-read a catch-up window per
        key for nothing.
        """
        cursor = connection.execute(
            """INSERT INTO sync_state (vehicle_key, max_id)
               SELECT vehicle_key, MAX(id) FROM workshop
               WHERE vehicle_key NOT IN (SELECT vehicle_key FROM sync_state)
               GROUP BY vehicle_key"""
        )
        connection.commit()
        return cursor.rowcount if cursor.rowcount and cursor.rowcount > 0 else 0

    # -- run bookkeeping ----------------------------------------------------
    def start_run(self, connection: sqlite3.Connection, mode: str) -> int:
        cursor = connection.execute(
            "INSERT INTO sync_runs (mode, started_at) VALUES (?,?)", (mode, _now())
        )
        connection.commit()
        return int(cursor.lastrowid)

    def finish_run(
        self,
        connection: sqlite3.Connection,
        run_id: int,
        *,
        keys_total: int,
        keys_ok: int,
        keys_failed: int,
        stats: dict[str, int],
        errors: list[str],
    ) -> None:
        connection.execute(
            """UPDATE sync_runs SET finished_at=?, keys_total=?, keys_ok=?, keys_failed=?,
                   inserted=?, updated=?, unchanged=?, quarantined=?, deleted=?, errors=?
               WHERE run_id=?""",
            (
                _now(),
                keys_total,
                keys_ok,
                keys_failed,
                stats.get("inserted", 0),
                stats.get("updated", 0),
                stats.get("unchanged", 0),
                stats.get("quarantined", 0),
                stats.get("deleted", 0),
                json.dumps(errors)[:4000],
                run_id,
            ),
        )
        connection.commit()

    # -- row writes ---------------------------------------------------------
    def _children(
        self, connection: sqlite3.Connection, workshop_id: int, decoded: dict[str, Any]
    ) -> None:
        if decoded["parts"]:
            connection.executemany(
                "INSERT OR REPLACE INTO workshop_part(workshop_id, slot, part_key) VALUES (?,?,?)",
                [(workshop_id, slot, key) for slot, key in decoded["parts"]],
            )
        if decoded["layers"]:
            rows = []
            for index, layer in enumerate(decoded["layers"]):
                color = layer.get("color") or {}
                position = layer.get("position") or {}
                rotation = layer.get("rotation") or {}
                rows.append(
                    (
                        workshop_id,
                        index,
                        layer.get("decalKey") or "",
                        color.get("r"),
                        color.get("g"),
                        color.get("b"),
                        color.get("a"),
                        position.get("x"),
                        position.get("y"),
                        rotation.get("pitch"),
                        rotation.get("yaw"),
                        rotation.get("roll"),
                        layer.get("decalScale"),
                        layer.get("stretch"),
                        layer.get("coverage"),
                        layer.get("flags"),
                    )
                )
            connection.executemany(
                """INSERT OR REPLACE INTO workshop_decal_layer
                   (workshop_id, idx, decal_key, r,g,b,a, x,y, pitch,yaw,roll,
                    scale, stretch, coverage, flags)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                rows,
            )
        if decoded["tunings"]:
            connection.executemany(
                """INSERT OR REPLACE INTO workshop_tuning
                   (workshop_id, param, target_id, value) VALUES (?,?,?,?)""",
                [
                    (
                        workshop_id,
                        tuning.get("param") or "",
                        tuning.get("targetId"),
                        tuning.get("value"),
                    )
                    for tuning in decoded["tunings"]
                    if tuning.get("param")
                ],
            )

    def _drop_children(self, connection: sqlite3.Connection, workshop_id: int) -> None:
        for table in ("workshop_part", "workshop_decal_layer", "workshop_tuning"):
            connection.execute(
                f"DELETE FROM {table} WHERE workshop_id=?", (workshop_id,)
            )

    def _quarantine(
        self,
        connection: sqlite3.Connection,
        row: dict[str, Any],
        vehicle_key: str,
        reason: str,
        stamp: str,
    ) -> bool:
        """Store a malformed payload. True only when the record is new/changed."""
        row_id = row.get("id")
        if row_id is None:
            return False
        previous = connection.execute(
            "SELECT reason FROM quarantine WHERE id=?", (row_id,)
        ).fetchone()
        if previous and previous[0] == reason[:300]:
            return False
        connection.execute(
            """INSERT OR REPLACE INTO quarantine
               (id, vehicle_key, created_at, account_id, reason, raw_z, found_at)
               VALUES (?,?,?,?,?,?,?)""",
            (
                row_id,
                vehicle_key,
                row.get("created_at"),
                row.get("account_id"),
                reason[:300],
                zlib.compress((row.get("json_data") or "").encode()),
                stamp,
            ),
        )
        return True

    def upsert_rows(
        self,
        connection: sqlite3.Connection,
        vehicle_key: str,
        rows: list[dict[str, Any]],
        run_id: int,
        seen: set[int] | None = None,
    ) -> dict[str, int]:
        stats = {"inserted": 0, "updated": 0, "unchanged": 0, "quarantined": 0}
        stamp = _now()
        existing = {
            row[0]: row[1]
            for row in connection.execute(
                "SELECT id, json_sha256 FROM workshop WHERE vehicle_key=?",
                (vehicle_key,),
            )
        }
        events: list[tuple[int, int, str, str, str | None, str]] = []
        for row in rows:
            workshop_id = row.get("id")
            if workshop_id is None:
                continue
            if seen is not None:
                if workshop_id in seen:
                    continue
                seen.add(workshop_id)

            json_data = row.get("json_data") or ""
            digest = hashlib.sha256(json_data.encode()).hexdigest()
            meta = (
                row.get("author_name"),
                row.get("votes"),
                row.get("reports"),
                row.get("installed"),
                row.get("hidden"),
                row.get("hot"),
                row.get("duplicate_key"),
            )
            previous = existing.get(int(workshop_id))
            if previous is not None and previous == digest:
                # The payload is unchanged but the counters and display name move
                # independently of an edit, so refresh them anyway.
                connection.execute(
                    """UPDATE workshop SET last_seen=?, author_name=?, votes=?, reports=?,
                         installed=?, hidden=?, hot=?, duplicate_key=? WHERE id=?""",
                    (stamp, *meta, workshop_id),
                )
                stats["unchanged"] += 1
                continue

            try:
                decoded = decode_payload(json_data)
            except Exception as error:  # noqa: BLE001 - malformed upstream payload
                if self._quarantine(
                    connection,
                    row,
                    vehicle_key,
                    f"{type(error).__name__}: {error}",
                    stamp,
                ):
                    stats["quarantined"] += 1
                continue

            if previous is None:
                connection.execute(
                    """INSERT INTO workshop
                       (id, vehicle_key, category, account_id, character_guid, created_at,
                        json_sha256, json_len, json_z, has_paint, has_decal, has_parts,
                        has_tunings, decal_layers, part_count, paint_slots, tags, revision,
                        first_seen, last_seen, deleted_at,
                        author_name, votes, reports, installed, hidden, hot, duplicate_key)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?,?,NULL,?,?,?,?,?,?,?)""",
                    (
                        workshop_id,
                        vehicle_key,
                        row.get("category") or CATEGORY,
                        row.get("account_id") or 0,
                        row.get("character_guid") or "",
                        row.get("created_at") or "",
                        digest,
                        len(json_data),
                        zlib.compress(json_data.encode()),
                        decoded["has_paint"],
                        decoded["has_decal"],
                        decoded["has_parts"],
                        decoded["has_tunings"],
                        decoded["decal_layers"],
                        decoded["part_count"],
                        decoded["paint_slots"],
                        decoded["tags"],
                        stamp,
                        stamp,
                        *meta,
                    ),
                )
                self._children(connection, int(workshop_id), decoded)
                stats["inserted"] += 1
                events.append((run_id, workshop_id, "inserted", stamp, None, digest))
            else:
                connection.execute(
                    """UPDATE workshop SET vehicle_key=?, category=?, account_id=?,
                         character_guid=?, created_at=?, json_sha256=?, json_len=?, json_z=?,
                         has_paint=?, has_decal=?, has_parts=?, has_tunings=?,
                         decal_layers=?, part_count=?, paint_slots=?, tags=?,
                         author_name=?, votes=?, reports=?, installed=?, hidden=?, hot=?,
                         duplicate_key=?, revision=revision+1, last_seen=?, deleted_at=NULL
                       WHERE id=?""",
                    (
                        vehicle_key,
                        row.get("category") or CATEGORY,
                        row.get("account_id") or 0,
                        row.get("character_guid") or "",
                        row.get("created_at") or "",
                        digest,
                        len(json_data),
                        zlib.compress(json_data.encode()),
                        decoded["has_paint"],
                        decoded["has_decal"],
                        decoded["has_parts"],
                        decoded["has_tunings"],
                        decoded["decal_layers"],
                        decoded["part_count"],
                        decoded["paint_slots"],
                        decoded["tags"],
                        *meta,
                        stamp,
                        workshop_id,
                    ),
                )
                self._drop_children(connection, int(workshop_id))
                self._children(connection, int(workshop_id), decoded)
                stats["updated"] += 1
                events.append((run_id, workshop_id, "updated", stamp, previous, digest))

        if events:
            connection.executemany(
                """INSERT INTO workshop_event
                   (run_id, workshop_id, action, at, old_sha, new_sha) VALUES (?,?,?,?,?,?)""",
                events,
            )
        connection.commit()
        return stats

    def tombstone_missing(
        self,
        connection: sqlite3.Connection,
        seen: set[int],
        run_id: int,
        vehicle_keys: list[str],
    ) -> int:
        """Mark rows the API no longer serves as deleted, scoped to the keys read."""
        stamp = _now()
        placeholders = ",".join("?" * len(vehicle_keys))
        missing = [
            row[0]
            for row in connection.execute(
                f"""SELECT id FROM workshop WHERE deleted_at IS NULL
                    AND vehicle_key IN ({placeholders})""",
                vehicle_keys,
            )
            if row[0] not in seen
        ]
        if not missing:
            return 0
        connection.executemany(
            "UPDATE workshop SET deleted_at=? WHERE id=?",
            [(stamp, row_id) for row_id in missing],
        )
        connection.executemany(
            "INSERT INTO workshop_event (run_id, workshop_id, action, at) VALUES (?,?,?,?)",
            [(run_id, row_id, "deleted", stamp) for row_id in missing],
        )
        connection.commit()
        return len(missing)


# --------------------------------------------------------------------------- #
# driver
# --------------------------------------------------------------------------- #
def sync(
    settings: WorkshopSettings,
    *,
    mode: str,
    keys: list[str] | None = None,
    probe_count: int = PROBE_COUNT,
    catchup_count: int = CATCHUP_COUNT,
) -> dict[str, int]:
    """Merge the workshop API into the source database.

    ``full`` re-reads every key whole and tombstones anything the API no longer
    serves. ``delta`` is watermark-driven: it asks each key for its newest
    ``probe_count`` rows only, and when nothing in that window is above the key's
    stored watermark the key costs one small request and no writes. When it does
    see new ids it pulls a bounded catch-up window and writes only rows above the
    watermark — ids already stored are never re-examined.

    The API has no "since id" parameter, so the probe window is unavoidable; what
    the watermark buys is skipping the large fetch and all the comparison work for
    the ~99% of keys that did not move.
    """
    if mode not in ("delta", "full"):
        raise ValueError(f"unknown mode {mode!r}")
    keys = keys or vehicle_keys()
    store = SyncStore(settings.source_db)
    connection = store.connect()
    run_id = store.start_run(
        connection, f"{mode}/probe{probe_count}" if mode == "delta" else mode
    )
    if mode == "delta":
        seeded = store.bootstrap_watermarks(connection)
        if seeded:
            log.info("seeded watermarks for %s keys from existing rows", seeded)
    stats = {
        "inserted": 0,
        "updated": 0,
        "unchanged": 0,
        "quarantined": 0,
        "deleted": 0,
        "new_ids": 0,
        "keys_skipped": 0,
    }
    errors: list[str] = []
    seen: set[int] = set()
    ok = failed = 0
    try:
        for index, vehicle_key in enumerate(keys, start=1):
            try:
                if mode == "full":
                    payload = fetch(vehicle_key, FULL_COUNT)
                    rows = payload.get("workshops") or []
                    result = store.upsert_rows(
                        connection, vehicle_key, rows, run_id, seen
                    )
                    store.set_watermark(
                        connection,
                        vehicle_key,
                        max((row["id"] for row in rows), default=0),
                    )
                else:
                    watermark = store.watermark(connection, vehicle_key)
                    probe = fetch(vehicle_key, probe_count).get("workshops") or []
                    fresh = [row for row in probe if row.get("id", 0) > watermark]
                    if not fresh:
                        store.mark_probed(connection, vehicle_key)
                        stats["keys_skipped"] += 1
                        ok += 1
                        log.info(
                            "[%s/%s] %s: no new ids (watermark %s)",
                            index,
                            len(keys),
                            vehicle_key,
                            watermark,
                        )
                        time.sleep(REQUEST_DELAY)
                        continue
                    # The probe saturated: there may be more new ids below it than
                    # fit in one page, so widen once before writing.
                    if len(fresh) == len(probe):
                        rows = [
                            row
                            for row in (
                                fetch(vehicle_key, catchup_count).get("workshops") or []
                            )
                            if row.get("id", 0) > watermark
                        ]
                    else:
                        rows = fresh
                    result = store.upsert_rows(connection, vehicle_key, rows, run_id)
                    store.set_watermark(
                        connection, vehicle_key, max(row["id"] for row in rows)
                    )
                    stats["new_ids"] += len(rows)
                ok += 1
                for key in ("inserted", "updated", "unchanged", "quarantined"):
                    stats[key] += result.get(key, 0)
                changed = {
                    key: result[key]
                    for key in ("inserted", "updated", "quarantined")
                    if result.get(key)
                }
                log.info(
                    "[%s/%s] %s: %s new ids %s",
                    index,
                    len(keys),
                    vehicle_key,
                    len(rows),
                    changed or "",
                )
            except Exception as error:  # noqa: BLE001 - one bad key must not end the run
                failed += 1
                errors.append(f"{vehicle_key}: {error}")
                log.error("[%s/%s] %s failed: %s", index, len(keys), vehicle_key, error)
            time.sleep(REQUEST_DELAY)
        if mode == "full":
            stats["deleted"] = store.tombstone_missing(connection, seen, run_id, keys)
    finally:
        store.finish_run(
            connection,
            run_id,
            keys_total=len(keys),
            keys_ok=ok,
            keys_failed=failed,
            stats=stats,
            errors=errors,
        )
        connection.close()
    log.info("sync %s done: %s", mode, stats)
    return stats


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=("delta", "full"),
        default="delta",
        help="delta reads the newest entries per key; full re-reads every key and tombstones removals",
    )
    parser.add_argument(
        "--db", type=Path, help="Source database path (default: settings)"
    )
    parser.add_argument(
        "--probe-count",
        type=int,
        default=PROBE_COUNT,
        help="Newest rows delta inspects per key before deciding there is nothing new",
    )
    parser.add_argument("--catchup-count", type=int, default=CATCHUP_COUNT)
    parser.add_argument("--vehicle-key", action="append", dest="vehicle_keys")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    settings = WorkshopSettings.from_env()
    if args.db is not None:
        settings = replace(settings, source_db=args.db)
    stats = sync(
        settings,
        mode=args.mode,
        keys=args.vehicle_keys,
        probe_count=args.probe_count,
        catchup_count=args.catchup_count,
    )
    log.info(
        "inserted=%s updated=%s unchanged=%s quarantined=%s deleted=%s",
        stats["inserted"],
        stats["updated"],
        stats["unchanged"],
        stats["quarantined"],
        stats["deleted"],
    )


if __name__ == "__main__":
    main()
