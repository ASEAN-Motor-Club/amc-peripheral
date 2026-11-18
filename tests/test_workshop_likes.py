"""Likes: member-scoped, idempotent, and counted in one query per page."""

from __future__ import annotations

import pytest

from amc_peripheral.workshop.community import CommunityStore

NOW = "2026-11-18T17:00:00Z"
DISCORD = "9001"


@pytest.fixture
def store(tmp_path):
    return CommunityStore(tmp_path / "site.db")


def test_first_like_adds_and_second_removes(store):
    assert store.toggle_like(workshop_id=42, discord_id=DISCORD, now=NOW) == (True, 1)
    assert store.toggle_like(workshop_id=42, discord_id=DISCORD, now=NOW) == (False, 0)


def test_likes_are_per_member(store):
    store.toggle_like(workshop_id=42, discord_id=DISCORD, now=NOW)
    assert store.toggle_like(workshop_id=42, discord_id="1111", now=NOW) == (True, 2)
    assert store.like_count(42) == 2

    store.toggle_like(workshop_id=42, discord_id=DISCORD, now=NOW)
    assert store.like_count(42) == 1


def test_a_replayed_like_cannot_double(store):
    store.toggle_like(workshop_id=42, discord_id=DISCORD, now=NOW)
    # Simulate a duplicate row insert attempt: the primary key refuses it.
    import sqlite3

    with sqlite3.connect(store.path) as conn, pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO workshop_like (workshop_id, discord_id, created_at)"
            " VALUES (42, ?, ?)",
            (DISCORD, NOW),
        )
    assert store.like_count(42) == 1


def test_counts_are_batched(store):
    for wid in (1, 2):
        store.toggle_like(workshop_id=wid, discord_id=DISCORD, now=NOW)
    store.toggle_like(workshop_id=2, discord_id="1111", now=NOW)

    assert store.like_counts([1, 2, 3]) == {1: 1, 2: 2}
    assert store.like_counts([]) == {}


def test_liked_ids_is_viewer_scoped(store):
    store.toggle_like(workshop_id=1, discord_id=DISCORD, now=NOW)
    store.toggle_like(workshop_id=2, discord_id="1111", now=NOW)

    assert store.liked_ids(DISCORD, [1, 2, 3]) == {1}
    assert store.liked_ids("1111", [1, 2, 3]) == {2}
    assert store.liked_ids(DISCORD, []) == set()
