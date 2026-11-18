"""Tag normalisation and the tag store."""

from __future__ import annotations

import pytest

from amc_peripheral.workshop.tags import (
    MAX_ITEM_TAGS,
    TagError,
    TagStore,
    normalise_many,
    normalise_tag,
    tag_url,
)

NOW = "2026-11-18T18:00:00Z"
ME = "9001"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("#Cat", "cat"),
        ("  ##RACER!!", "racer"),
        ("land yacht", "land-yacht"),
        ("hanadrift_2026", "hanadrift-2026"),
        ("#a--b", "a-b"),
        ("#", ""),
        ("", ""),
        (None, ""),
        ("#タイヤ", "タイヤ"),
        ("#đường đua", "đường-đua"),
    ],
)
def test_normalise(raw, expected):
    assert normalise_tag(raw) == expected


def test_long_tags_are_capped():
    assert len(normalise_tag("x" * 80)) == 24


def test_normalise_many_splits_and_dedupes():
    assert normalise_many("cat, racer  #cat") == ["cat", "racer"]
    assert normalise_many(["#Cat", "cat", " "]) == ["cat"]
    assert normalise_many(None) == []


def test_tag_url_encodes_unicode():
    assert tag_url("cat") == "/workshop/tags/cat/"
    assert "%" in tag_url("タイヤ")


@pytest.fixture
def store(tmp_path):
    return TagStore(tmp_path / "site.db")


def test_add_and_remove_item_tags(store):
    assert store.add_item_tags(
        workshop_id=1, discord_id=ME, raw_tags="cat, racer", now=NOW
    ) == ["cat", "racer"]
    assert store.item_tags(1) == ["cat", "racer"]

    assert store.remove_item_tag(workshop_id=1, tag="#Cat") is True
    assert store.item_tags(1) == ["racer"]
    assert store.remove_item_tag(workshop_id=1, tag="cat") is False


def test_adding_the_same_tag_twice_is_a_no_op(store):
    store.add_item_tags(workshop_id=1, discord_id=ME, raw_tags="cat", now=NOW)
    store.add_item_tags(workshop_id=1, discord_id=ME, raw_tags="#CAT", now=NOW)
    assert store.item_tags(1) == ["cat"]


def _seed_tags(store, *tags):
    """Pre-create registry rows, so a test is not fighting the new-tag budget."""
    with store._connect() as conn:
        for tag in tags:
            conn.execute(
                "INSERT OR IGNORE INTO workshop_tag (tag, created_at, created_by)"
                " VALUES (?, ?, 'seed')",
                (tag, "2026-01-01T00:00:00Z"),
            )


def test_item_tag_cap(store):
    tags = [f"t{i}" for i in range(MAX_ITEM_TAGS)]
    _seed_tags(store, *tags)
    store.add_item_tags(workshop_id=1, discord_id=ME, raw_tags=tags, now=NOW)
    with pytest.raises(TagError):
        store.add_item_tags(workshop_id=1, discord_id=ME, raw_tags="extra", now=NOW)


def test_new_tag_budget_per_hour(store):
    store.add_item_tags(workshop_id=1, discord_id=ME, raw_tags="a b c", now=NOW)
    with pytest.raises(TagError):
        store.add_item_tags(workshop_id=1, discord_id=ME, raw_tags="d", now=NOW)
    # An existing tag is always fine to reuse, budget or not.
    store.add_item_tags(workshop_id=2, discord_id=ME, raw_tags="a", now=NOW)
    assert store.item_tags(2) == ["a"]


def test_budget_is_per_member(store):
    store.add_item_tags(workshop_id=1, discord_id=ME, raw_tags="a b c", now=NOW)
    store.add_item_tags(workshop_id=1, discord_id="other", raw_tags="d", now=NOW)
    assert store.usage("d") is not None


def test_empty_tag_is_rejected(store):
    with pytest.raises(TagError):
        store.add_item_tags(workshop_id=1, discord_id=ME, raw_tags="#", now=NOW)


def test_item_tags_many_is_one_query(store):
    store.add_item_tags(workshop_id=1, discord_id=ME, raw_tags="cat", now=NOW)
    store.add_item_tags(workshop_id=2, discord_id=ME, raw_tags="dog", now=NOW)
    assert store.item_tags_many([1, 2, 3]) == {1: ["cat"], 2: ["dog"]}
    assert store.item_tags_many([]) == {}


def test_collection_tags_and_cap(store):
    assert store.add_collection_tags(
        collection_id=5, discord_id=ME, raw_tags="drift", now=NOW
    ) == ["drift"]
    with pytest.raises(TagError):
        store.add_collection_tags(
            collection_id=5, discord_id=ME, raw_tags="a b c d e", now=NOW
        )
    assert store.remove_collection_tag(collection_id=5, tag="drift") is True
    assert store.collection_tags(5) == []


def test_index_counts_and_ordering(store):
    store.add_item_tags(workshop_id=1, discord_id=ME, raw_tags="cat racer", now=NOW)
    store.add_item_tags(workshop_id=2, discord_id=ME, raw_tags="cat", now=NOW)
    store.add_collection_tags(collection_id=1, discord_id=ME, raw_tags="cat drift", now=NOW)

    popular = store.index()
    assert popular[0].tag == "cat"
    assert (popular[0].items, popular[0].collections) == (2, 1)
    assert [c.tag for c in store.index(sort="az")] == ["cat", "drift", "racer"]


def test_index_hides_tags_with_no_live_use(store):
    store.add_item_tags(workshop_id=1, discord_id=ME, raw_tags="ghost", now=NOW)
    store.remove_item_tag(workshop_id=1, tag="ghost")
    assert store.index() == []
    assert store.count_tags() == 0


def test_usage_returns_none_for_unknown(store):
    assert store.usage("nothing") is None
    store.add_item_tags(workshop_id=1, discord_id=ME, raw_tags="cat", now=NOW)
    assert store.usage("#Cat").items == 1


def test_related_tags_share_builds(store):
    store.add_item_tags(workshop_id=1, discord_id=ME, raw_tags="cat racer", now=NOW)
    store.add_item_tags(workshop_id=2, discord_id=ME, raw_tags="cat drift", now=NOW)

    related = [c.tag for c in store.related("cat")]
    assert set(related) == {"racer", "drift"}
    assert "cat" not in related


def test_search_prefers_prefix_matches(store):
    store.add_item_tags(workshop_id=1, discord_id=ME, raw_tags="cat concat", now=NOW)
    results = [c.tag for c in store.search("cat")]
    assert results[0] == "cat"
    assert "concat" in results
    assert store.search("#") == []


def test_collection_tags_can_be_deleted_wholesale(store):
    store.add_collection_tags(collection_id=1, discord_id=ME, raw_tags="drift", now=NOW)
    store.delete_collection_tags(1)
    assert store.collection_tags(1) == []
