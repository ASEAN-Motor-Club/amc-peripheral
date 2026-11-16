"""Query correctness and pagination tests."""

from __future__ import annotations

import sqlite3

import pytest

from amc_peripheral.workshop.queries import (
    CursorStale,
    InvalidCursor,
    ListFilters,
    WorkshopRepository,
)


@pytest.fixture
def repo(settings):
    return WorkshopRepository(settings.source_db, cache_ttl=0)


def ids(payload):
    return [item["id"] for item in payload["items"]]


def test_public_rows_exclude_canary_hidden_and_deleted(repo):
    popular = repo.list_items(limit=20)
    assert 999999999 not in ids(popular)
    assert 5 not in ids(popular)  # hidden
    assert 6 not in ids(popular)  # deleted


def test_new_uses_created_at_not_local_id(repo):
    result = repo.list_items(sort="new", limit=10)
    assert ids(result) == [1, 3, 2]


def test_popular_ordering_is_nullsafe(repo):
    result = repo.list_items(sort="popular", limit=10)
    assert ids(result) == [1, 3, 2]


def test_keyset_pages_do_not_duplicate(repo):
    first = repo.list_items(sort="popular", limit=1)
    assert ids(first) == [1]
    assert first["nextCursor"]
    second = repo.list_items(sort="popular", limit=1, cursor=first["nextCursor"])
    assert ids(second) == [3]
    third = repo.list_items(sort="popular", limit=1, cursor=second["nextCursor"])
    assert ids(third) == [2]


def test_new_keyset_ties_on_created_at_use_id(repo):
    first = repo.list_items(sort="new", limit=1)
    assert ids(first) == [1]
    second = repo.list_items(sort="new", limit=1, cursor=first["nextCursor"])
    assert ids(second) == [3]


def test_cursor_is_bound_to_filter_set(repo):
    first = repo.list_items(sort="popular", limit=1)
    with pytest.raises(InvalidCursor):
        repo.list_items(
            sort="popular", limit=1, cursor=first["nextCursor"],
            filters=ListFilters(vehicle="Boxy"),
        )


def test_cursor_is_bound_to_sort(repo):
    first = repo.list_items(sort="popular", limit=1)
    with pytest.raises(InvalidCursor):
        repo.list_items(sort="new", limit=1, cursor=first["nextCursor"])


def test_stale_popular_cursor_is_rejected(settings, repo):
    first = repo.list_items(sort="popular", limit=1)
    with sqlite3.connect(settings.source_db) as conn:
        conn.execute("INSERT INTO sync_runs VALUES (8, '2026-11-16T08:00:00Z')")
        conn.commit()
    fresh = WorkshopRepository(settings.source_db, cache_ttl=0)
    with pytest.raises(CursorStale):
        fresh.list_items(
            sort="popular", limit=1, cursor=first["nextCursor"]
        )


def test_author_identity_is_account_not_name(repo):
    authors = repo.authors(limit=10)
    alice = next(item for item in authors if item["accountId"] == 11)
    assert alice["displayName"] == "Alice"
    assert alice["uploads"] == 2
    assert alice["installs"] == 200


def test_author_lookup(repo):
    author = repo.author(11)
    assert author and author["uploads"] == 2
    assert repo.author(4444) is None


def test_club_filter_does_not_surface_steam_id(repo):
    result = repo.list_items(filters=ListFilters(club=True), limit=10)
    assert set(ids(result)) == {1, 3}
    assert "76561198000000000" not in str(result)


def test_item_and_viewer_row_visibility(repo):
    assert repo.get_item(1)["id"] == 1
    assert repo.get_item(5) is None
    assert repo.get_item(6) is None
    assert repo.get_viewer_row(1)["json_sha256"] == "a" * 64
    assert repo.get_viewer_row(5) is None
