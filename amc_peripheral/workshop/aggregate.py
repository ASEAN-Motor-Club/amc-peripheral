"""Build the disposable workshop site-state database from the source scrape."""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import time
from datetime import UTC, datetime
from typing import Any

from .config import WorkshopSettings
from .queries import WorkshopRepository

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS aggregate_runs (
    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_run_id INTEGER,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    items INTEGER,
    status TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS home_cache (
    slot TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    run_id INTEGER,
    built_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS vehicle_summary (
    vehicle_key TEXT PRIMARY KEY,
    items INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS author_summary (
    account_id INTEGER PRIMARY KEY,
    display_name TEXT,
    uploads INTEGER NOT NULL,
    installs INTEGER NOT NULL,
    votes INTEGER NOT NULL,
    representative_id INTEGER
);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def build(settings: WorkshopSettings) -> dict[str, Any]:
    settings.site_db.parent.mkdir(parents=True, exist_ok=True)
    repo = WorkshopRepository(settings.source_db)
    home = repo.home(limit=settings.home_limit)
    home["stats"] = repo.stats()
    conn = sqlite3.connect(settings.site_db)
    conn.executescript(SCHEMA)
    started = _now()
    cursor = conn.execute(
        "INSERT INTO aggregate_runs (source_run_id,started_at,status) VALUES (?,?,?)",
        (home.get("runId"), started, "running"),
    )
    aggregate_id = cursor.lastrowid
    try:
        conn.execute(
            "INSERT OR REPLACE INTO home_cache VALUES ('home',?,?,?)",
            (json.dumps(home, separators=(",", ":")), home.get("runId"), started),
        )
        conn.execute("DELETE FROM vehicle_summary")
        conn.executemany(
            "INSERT INTO vehicle_summary VALUES (?,?)",
            [(item["vehicleKey"], item["uploads"]) for item in repo.vehicles()],
        )
        conn.execute("DELETE FROM author_summary")
        conn.executemany(
            "INSERT INTO author_summary VALUES (?,?,?,?,?,?)",
            [
                (
                    item["accountId"],
                    item["displayName"],
                    item["uploads"],
                    item["installs"],
                    item["votes"],
                    item["representativeId"],
                )
                for item in repo.authors(limit=10_000)
            ],
        )
        conn.execute(
            "UPDATE aggregate_runs SET finished_at=?,items=?,status='ready' WHERE run_id=?",
            (_now(), home["stats"]["items"], aggregate_id),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        conn.execute(
            "UPDATE aggregate_runs SET finished_at=?,status='failed' WHERE run_id=?",
            (_now(), aggregate_id),
        )
        conn.commit()
        raise
    finally:
        conn.close()
    return home


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--loop", type=float, default=0.0,
                        help="Repeat every N seconds instead of running once")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    settings = WorkshopSettings.from_env()
    settings.validate()
    while True:
        started = time.monotonic()
        home = build(settings)
        log.info("aggregate ready: %s items, run %s (%.2fs)",
                 home["stats"]["items"], home.get("runId"), time.monotonic() - started)
        if args.loop <= 0:
            return
        time.sleep(max(1.0, args.loop))


if __name__ == "__main__":
    main()
