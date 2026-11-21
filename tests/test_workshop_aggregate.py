"""Derived site state and index-plan tests."""

from __future__ import annotations

import sqlite3
from dataclasses import replace

from amc_peripheral.workshop.aggregate import build
from amc_peripheral.workshop.queries import ListFilters, WorkshopRepository


def test_aggregate_build_is_read_through(settings):
    home = build(settings)
    assert home["stats"]["items"] == 3
    assert settings.site_db.is_file()
    repo = WorkshopRepository(settings.source_db, site_db=settings.site_db,
                              cache_ttl=0)
    assert repo.home() == home
    assert repo.stats()["items"] == 3
    body = repo.authors(limit=1)
    assert body[0]["accountId"] == 11
    assert body[0]["representativeId"] == 1

    with sqlite3.connect(settings.site_db) as conn:
        status = conn.execute(
            "SELECT status, items FROM aggregate_runs ORDER BY run_id DESC LIMIT 1"
        ).fetchone()
    assert status == ("ready", 3)

    from amc_peripheral.workshop.snapshots import SnapshotStore

    store = SnapshotStore(settings.site_db)
    assert store.health()["queueDepth"] == 2
    with sqlite3.connect(settings.site_db) as conn:
        priorities = conn.execute(
            "SELECT priority FROM snapshot_jobs ORDER BY cache_key"
        ).fetchall()
    assert priorities == [(-10,), (-10,)]


def test_prewarm_never_exceeds_queue_budget(settings):
    from amc_peripheral.workshop.snapshots import SnapshotStore

    build(replace(settings, prewarm_queue_limit=1))
    assert SnapshotStore(settings.site_db).health()["queueDepth"] == 1


def test_public_indexes_avoid_temp_sort(settings):
    with sqlite3.connect(settings.source_db) as conn:
        queries = [
            ("SELECT id FROM workshop w WHERE w.deleted_at IS NULL "
            "AND COALESCE(w.hidden,0)=0 AND w.account_id>0 "
            "ORDER BY COALESCE(w.installed,0) DESC,COALESCE(w.votes,0) DESC,"
            "w.id DESC LIMIT 24"),
            ("SELECT id FROM workshop w WHERE w.deleted_at IS NULL "
            "AND COALESCE(w.hidden,0)=0 AND w.account_id>0 "
            "ORDER BY w.created_at DESC,w.id DESC LIMIT 24"),
        ]
        plans = [
            "\n".join(row[3] for row in conn.execute("EXPLAIN QUERY PLAN " + sql))
            for sql in queries
        ]
    assert all("TEMP B-TREE" not in plan for plan in plans), plans
    assert any("ix_ws_site_popular" in plan for plan in plans), plans
    assert any("ix_ws_site_new" in plan for plan in plans), plans


def test_vehicle_filter_uses_vehicle_index(settings):
    repo = WorkshopRepository(settings.source_db, cache_ttl=0)
    page = repo.list_items(filters=ListFilters(vehicle="Vamos3"), limit=10)
    assert {item["id"] for item in page["items"]} == {1, 3}
    with sqlite3.connect(settings.source_db) as conn:
        plan = "\n".join(
            row[3]
            for row in conn.execute(
                "EXPLAIN QUERY PLAN SELECT id FROM workshop w "
                "WHERE w.deleted_at IS NULL AND COALESCE(w.hidden,0)=0 "
                "AND w.account_id>0 AND w.vehicle_key=? "
                "ORDER BY w.created_at DESC,w.id DESC LIMIT 10",
                ("Vamos3",),
            )
        )
    assert "TEMP B-TREE" not in plan, plan
