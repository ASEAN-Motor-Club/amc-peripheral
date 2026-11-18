"""Collections: member-curated lists, owner-gated writes, honest limits."""

from __future__ import annotations

import pytest

from amc_peripheral.workshop.collections import (
    MAX_COLLECTIONS,
    MAX_ITEMS,
    CollectionError,
    CollectionStore,
    clean_text,
    slugify,
)

NOW = "2026-11-18T18:00:00Z"
ME = "9001"
OTHER = "1111"


@pytest.fixture
def store(tmp_path):
    return CollectionStore(tmp_path / "site.db")


def _make(store, *, owner=ME, title="Hana drift", visibility="public", now=NOW):
    return store.create(
        discord_id=owner,
        title=title,
        description=None,
        visibility=visibility,
        now=now,
    )


def test_create_and_read_back(store):
    collection = _make(store)
    assert collection.slug == "hana-drift"

    fetched = store.get(collection.id)
    assert fetched is not None
    assert fetched.title == "Hana drift"
    assert fetched.visibility == "public"
    assert fetched.item_count == 0


def test_empty_collection_is_not_listed_but_is_readable(store):
    collection = _make(store)
    assert store.listing() == []
    assert store.get(collection.id) is not None


def test_slug_collisions_are_per_owner(store):
    mine = _make(store)
    other = _make(store, owner=OTHER)
    assert mine.slug == other.slug == "hana-drift"

    second = _make(store, title="Hana drift")
    assert second.slug == "hana-drift-2"


def test_title_is_required_and_capped(store):
    with pytest.raises(CollectionError):
        _make(store, title="   ")
    with pytest.raises(CollectionError):
        _make(store, title="x" * 41)


def test_urls_and_control_chars_are_stripped():
    assert clean_text("see https://example.com/a for more", limit=200, field="D") == (
        "see for more"
    )
    assert clean_text("a\x00b", limit=10, field="D") == "ab"
    assert slugify("Hana Drift / Night!!") == "hana-drift-night"
    assert slugify("!!!") == "collection"


def test_collection_limit(store):
    for i in range(MAX_COLLECTIONS):
        _make(store, title=f"List {i}")
    with pytest.raises(CollectionError):
        _make(store, title="One too many")


def test_add_item_is_owner_gated(store):
    collection = _make(store)
    assert (
        store.add_item(
            collection_id=collection.id, discord_id=OTHER, workshop_id=1, now=NOW
        )
        is False
    )
    assert (
        store.add_item(
            collection_id=collection.id, discord_id=ME, workshop_id=1, now=NOW
        )
        is True
    )
    assert store.item_ids(collection.id) == [1]


def test_adding_twice_is_a_no_op(store):
    collection = _make(store)
    store.add_item(collection_id=collection.id, discord_id=ME, workshop_id=1, now=NOW)
    assert (
        store.add_item(
            collection_id=collection.id, discord_id=ME, workshop_id=1, now=NOW
        )
        is False
    )
    assert store.item_ids(collection.id) == [1]


def test_item_limit(store):
    collection = _make(store)
    for wid in range(MAX_ITEMS):
        store.add_item(
            collection_id=collection.id, discord_id=ME, workshop_id=wid + 1, now=NOW
        )
    with pytest.raises(CollectionError):
        store.add_item(
            collection_id=collection.id, discord_id=ME, workshop_id=9999, now=NOW
        )


def test_reorder_ignores_foreign_ids_and_keeps_them_present(store):
    collection = _make(store)
    for wid in (1, 2, 3):
        store.add_item(
            collection_id=collection.id, discord_id=ME, workshop_id=wid, now=NOW
        )

    assert (
        store.reorder(collection_id=collection.id, discord_id=ME, ordered_ids=[3, 1])
        is True
    )
    assert store.item_ids(collection.id) == [3, 1, 2]

    assert (
        store.reorder(
            collection_id=collection.id, discord_id=OTHER, ordered_ids=[2, 1, 3]
        )
        is False
    )
    assert store.item_ids(collection.id) == [3, 1, 2]


def test_remove_item(store):
    collection = _make(store)
    store.add_item(collection_id=collection.id, discord_id=ME, workshop_id=1, now=NOW)
    assert (
        store.remove_item(collection_id=collection.id, discord_id=ME, workshop_id=1)
        is True
    )
    assert store.item_ids(collection.id) == []
    assert (
        store.remove_item(collection_id=collection.id, discord_id=OTHER, workshop_id=1)
        is False
    )


def test_update_requires_owner(store):
    collection = _make(store)
    assert (
        store.update(
            collection_id=collection.id,
            discord_id=OTHER,
            title="Hijacked",
            description=None,
            visibility="public",
            now=NOW,
        )
        is False
    )
    assert store.get(collection.id).title == "Hana drift"

    assert (
        store.update(
            collection_id=collection.id,
            discord_id=ME,
            title="Renamed",
            description="night runs",
            visibility="unlisted",
            now=NOW,
        )
        is True
    )
    updated = store.get(collection.id)
    assert (updated.title, updated.visibility) == ("Renamed", "unlisted")


def test_delete_removes_items_with_it(store):
    collection = _make(store)
    store.add_item(collection_id=collection.id, discord_id=ME, workshop_id=1, now=NOW)
    assert store.delete(collection_id=collection.id, discord_id=OTHER) is False
    assert store.delete(collection_id=collection.id, discord_id=ME) is True
    assert store.get(collection.id) is None


def test_listing_excludes_unlisted(store):
    public = _make(store, title="Public one")
    hidden = _make(store, title="Hidden one", visibility="unlisted")
    for collection in (public, hidden):
        store.add_item(
            collection_id=collection.id, discord_id=ME, workshop_id=1, now=NOW
        )

    listed = store.listing()
    assert [c.id for c in listed] == [public.id]
    assert store.count_public() == 1


def test_liked_ordering_uses_item_likes(store, tmp_path):
    from amc_peripheral.workshop.community import CommunityStore

    community = CommunityStore(tmp_path / "site.db")
    quiet = _make(store, title="Quiet")
    lively = _make(store, title="Lively")
    store.add_item(collection_id=quiet.id, discord_id=ME, workshop_id=10, now=NOW)
    store.add_item(collection_id=lively.id, discord_id=ME, workshop_id=20, now=NOW)
    community.toggle_like(workshop_id=20, discord_id="a", now=NOW)
    community.toggle_like(workshop_id=20, discord_id="b", now=NOW)

    assert [c.id for c in store.listing(sort="new")] == [lively.id, quiet.id]
    assert [c.id for c in store.listing(sort="liked")] == [lively.id, quiet.id]

    community.toggle_like(workshop_id=10, discord_id="a", now=NOW)
    community.toggle_like(workshop_id=10, discord_id="b", now=NOW)
    community.toggle_like(workshop_id=10, discord_id="c", now=NOW)
    assert [c.id for c in store.listing(sort="liked")] == [quiet.id, lively.id]


def test_cover_ids_are_the_first_build(store):
    collection = _make(store)
    for wid in (7, 8, 9):
        store.add_item(
            collection_id=collection.id, discord_id=ME, workshop_id=wid, now=NOW
        )
    store.reorder(collection_id=collection.id, discord_id=ME, ordered_ids=[9, 8, 7])
    assert store.cover_ids([collection.id]) == {collection.id: 9}
