"""Community store: claims, profiles and per-item metadata round-trips."""

from __future__ import annotations

import pytest

from amc_peripheral.workshop.community import CommunityStore

NOW = "2026-11-18T15:00:00Z"
LATER = "2026-11-18T16:00:00Z"
DISCORD = "9001"


@pytest.fixture
def store(tmp_path):
    return CommunityStore(tmp_path / "site.db")


def test_claim_round_trip(store):
    created = store.upsert_claim(
        workshop_id=42,
        discord_id=DISCORD,
        steam_id="76561198000000000",
        character_guid="8f14e45fceea167a5a36dedd4bea2543",
        now=NOW,
    )
    assert created is True

    claim = store.claim_for(42)
    assert claim is not None
    assert claim.discord_id == DISCORD
    assert claim.character_guid == "8F14E45FCEEA167A5A36DEDD4BEA2543"
    assert claim.active


def test_second_sync_refreshes_without_duplicating(store):
    for when in (NOW, LATER):
        store.upsert_claim(
            workshop_id=42,
            discord_id=DISCORD,
            steam_id="1",
            character_guid="ab",
            now=when,
        )
    claims = store.claims_for(DISCORD)
    assert list(claims) == [42]
    assert claims[42].claimed_at == NOW
    assert claims[42].last_verified_at == LATER


def test_claim_transfer_reports_created(store):
    store.upsert_claim(
        workshop_id=42, discord_id=DISCORD, steam_id="1", character_guid="ab", now=NOW
    )
    assert (
        store.upsert_claim(
            workshop_id=42,
            discord_id="7777",
            steam_id="2",
            character_guid="ab",
            now=LATER,
        )
        is True
    )


def test_revoked_claim_is_kept_but_not_editable(store):
    store.upsert_claim(
        workshop_id=42, discord_id=DISCORD, steam_id="1", character_guid="ab", now=NOW
    )
    store.revoke_claim(42, LATER)

    assert store.claim_ids(DISCORD) == set()
    assert len(store.claims_for(DISCORD)) == 1
    assert store.claims_for(DISCORD)[42].revoked_at == LATER


def test_reasserting_a_revoked_claim_clears_the_revocation(store):
    store.upsert_claim(
        workshop_id=42, discord_id=DISCORD, steam_id="1", character_guid="ab", now=NOW
    )
    store.revoke_claim(42, LATER)
    store.upsert_claim(
        workshop_id=42, discord_id=DISCORD, steam_id="1", character_guid="ab", now=LATER
    )
    assert store.claim_ids(DISCORD) == {42}


def test_profile_round_trip_and_update(store):
    assert store.profile(DISCORD) is None
    store.save_profile(discord_id=DISCORD, display_name="Driver", bio="hi", now=NOW)
    first = store.profile(DISCORD)
    assert (first.display_name, first.bio, first.hidden) == ("Driver", "hi", False)

    store.save_profile(discord_id=DISCORD, display_name="Driver 2", bio=None, now=LATER)
    second = store.profile(DISCORD)
    assert (second.display_name, second.bio, second.updated_at) == (
        "Driver 2",
        None,
        LATER,
    )


def test_item_meta_round_trip_and_update(store):
    store.save_meta(
        workshop_id=42,
        discord_id=DISCORD,
        title="C1 Tuned",
        description="line one\nline two",
        now=NOW,
    )
    meta = store.meta(42)
    assert meta.title == "C1 Tuned"
    assert meta.description.startswith("line one")
    assert meta.hidden is False

    store.save_meta(
        workshop_id=42, discord_id=DISCORD, title=None, description=None, now=LATER
    )
    assert store.meta(42).title is None


def test_meta_for_handles_empty_and_mixed_lists(store):
    assert store.meta_for([]) == {}
    store.save_meta(
        workshop_id=42, discord_id=DISCORD, title="x", description=None, now=NOW
    )
    found = store.meta_for([42, 43])
    assert list(found) == [42]


def test_set_hidden_requires_exactly_one_target(store):
    with pytest.raises(ValueError):
        store.set_hidden(hidden=True, now=NOW)
    with pytest.raises(ValueError):
        store.set_hidden(hidden=True, workshop_id=1, discord_id=DISCORD, now=NOW)


def test_set_hidden_hides_meta_and_profile(store):
    store.save_profile(discord_id=DISCORD, display_name="D", bio=None, now=NOW)
    store.save_meta(
        workshop_id=42, discord_id=DISCORD, title="t", description=None, now=NOW
    )

    store.set_hidden(hidden=True, workshop_id=42, now=LATER)
    store.set_hidden(hidden=True, discord_id=DISCORD, now=LATER)

    assert store.meta(42).hidden is True
    assert store.profile(DISCORD).hidden is True


def test_events_are_appended(store):
    store.log_event(workshop_id=42, discord_id=DISCORD, action="claim", at=NOW)
    store.log_event(
        workshop_id=42, discord_id=DISCORD, action="edit", at=LATER, detail="title"
    )
    assert store.stats()["claims"] == 0

    import sqlite3

    with sqlite3.connect(store.path) as conn:
        rows = conn.execute(
            "SELECT action, detail FROM workshop_claim_event ORDER BY id"
        ).fetchall()
    assert rows == [("claim", None), ("edit", "title")]


def test_stats_count_active_rows(store):
    store.upsert_claim(
        workshop_id=1, discord_id=DISCORD, steam_id="1", character_guid="ab", now=NOW
    )
    store.upsert_claim(
        workshop_id=2, discord_id=DISCORD, steam_id="1", character_guid="cd", now=NOW
    )
    store.revoke_claim(2, LATER)
    store.save_profile(discord_id=DISCORD, display_name="D", bio=None, now=NOW)
    store.save_meta(
        workshop_id=1, discord_id=DISCORD, title="t", description=None, now=NOW
    )

    assert store.stats() == {"claims": 1, "profiles": 1, "titles": 1}
