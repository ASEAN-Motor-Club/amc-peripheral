"""Claim sync: derived ownership, revocation, and the throttling that keeps it cheap."""

from __future__ import annotations

import pytest

from amc_peripheral.workshop.auth import Identity
from amc_peripheral.workshop.claims import ClaimSynchroniser
from amc_peripheral.workshop.community import CommunityStore

NOW = "2026-11-18T15:00:00Z"
LATER = "2026-11-18T16:00:00Z"
DISCORD = "9001"
GUID_A = "8F14E45FCEEA167A5A36DEDD4BEA2543"
GUID_B = "C9F0F895FB98AB9159F51FD0297E236D"


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class FakeIdentities:
    def __init__(self, identity):
        self.identity = identity
        self.calls = 0

    def identity_for(self, discord_id):
        self.calls += 1
        return self.identity


class FakeRepository:
    """Stands in for the scrape query: guids → cards."""

    def __init__(self, by_guid):
        self.by_guid = by_guid
        self.queries = []

    def items_for_guids(self, guids, limit=60):
        self.queries.append(set(guids))
        return [
            {"id": item_id, "characterGuid": guid.upper()}
            for guid, item_id in self.by_guid.items()
            if guid.upper() in {g.upper() for g in guids}
        ]


@pytest.fixture
def store(tmp_path):
    return CommunityStore(tmp_path / "site.db")


def synchroniser(store, identity, by_guid, clock=None):
    return ClaimSynchroniser(
        store,
        FakeRepository(by_guid),
        FakeIdentities(identity),
        clock=clock or Clock(),
    )


def test_sync_claims_matching_builds(store):
    sync = synchroniser(
        store, Identity(76561198000000000, frozenset({GUID_A})), {GUID_A: 42}
    )

    assert sync.sync(DISCORD, now=NOW) == (1, 0)
    claim = store.claim_for(42)
    assert claim.discord_id == DISCORD
    assert claim.character_guid == GUID_A
    assert store.claim_ids(DISCORD) == {42}


def test_sync_is_throttled(store):
    clock = Clock()
    repo_identity = Identity(1, frozenset({GUID_A}))
    sync = synchroniser(store, repo_identity, {GUID_A: 42}, clock=clock)

    sync.sync(DISCORD, now=NOW)
    clock.now += 10
    assert sync.sync(DISCORD, now=NOW) == (0, 0)
    assert len(sync.repository.queries) == 1

    clock.now += 60
    sync.sync(DISCORD, now=NOW)
    assert len(sync.repository.queries) == 2


def test_force_bypasses_the_throttle(store):
    clock = Clock()
    sync = synchroniser(
        store, Identity(1, frozenset({GUID_A})), {GUID_A: 42}, clock=clock
    )
    sync.sync(DISCORD, now=NOW)
    sync.sync(DISCORD, now=NOW, force=True)
    assert len(sync.repository.queries) == 2


def test_guid_leaving_the_account_revokes(store):
    clock = Clock()
    identity = FakeIdentities(Identity(1, frozenset({GUID_A, GUID_B})))
    sync = ClaimSynchroniser(
        store, FakeRepository({GUID_A: 42, GUID_B: 43}), identity, clock=clock
    )

    sync.sync(DISCORD, now=NOW)
    assert store.claim_ids(DISCORD) == {42, 43}

    # The character that uploaded 43 is gone from the backend.
    identity.identity = Identity(1, frozenset({GUID_A}))
    clock.now += 61
    sync.sync(DISCORD, now=LATER)

    assert store.claim_ids(DISCORD) == {42}
    assert store.claims_for(DISCORD)[43].revoked_at == LATER


def test_claim_moves_when_another_player_owns_the_guid(store):
    """GUIDs are unique per character, so a moved claim is always a real transfer."""
    store.upsert_claim(
        workshop_id=42, discord_id="1111", steam_id="1", character_guid=GUID_A, now=NOW
    )
    sync = synchroniser(store, Identity(2, frozenset({GUID_A})), {GUID_A: 42})
    assert sync.sync(DISCORD, now=LATER) == (1, 0)
    assert store.claim_for(42).discord_id == DISCORD


def test_no_identity_means_no_work(store):
    sync = synchroniser(store, None, {GUID_A: 42})
    assert sync.sync(DISCORD, now=NOW) == (0, 0)
    assert store.claims_for(DISCORD) == {}


def test_identity_without_guids_means_no_work(store):
    sync = synchroniser(store, Identity(1, frozenset()), {GUID_A: 42})
    assert sync.sync(DISCORD, now=NOW) == (0, 0)


def test_backend_failure_does_not_raise(store):
    class Broken:
        def items_for_guids(self, guids, limit=60):
            raise RuntimeError("postgres is down")

    sync = ClaimSynchroniser(
        store, Broken(), FakeIdentities(Identity(1, frozenset({GUID_A}))), clock=Clock()
    )
    assert sync.sync(DISCORD, now=NOW) == (0, 0)


def test_revocation_only_touches_active_claims(store):
    store.upsert_claim(
        workshop_id=99, discord_id=DISCORD, steam_id="1", character_guid="ZZ", now=NOW
    )
    store.revoke_claim(99, NOW)
    sync = synchroniser(store, Identity(1, frozenset({GUID_A})), {GUID_A: 42})
    assert sync.sync(DISCORD, now=LATER) == (1, 0)
    assert store.claims_for(DISCORD)[99].revoked_at == NOW
