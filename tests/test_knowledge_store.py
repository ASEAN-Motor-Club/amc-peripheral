import json
import os
import pytest

from amc_peripheral.knowledge_store import KnowledgeStore


@pytest.fixture
def store(tmp_path):
    """Create a KnowledgeStore with a temp file."""
    return KnowledgeStore(str(tmp_path / "knowledge.json"))


@pytest.fixture
def seeded_store(tmp_path):
    """Create a KnowledgeStore pre-seeded with test data."""
    path = str(tmp_path / "knowledge.json")
    store = KnowledgeStore(path)
    store.save("vehicle:Gosan_G7", "Best value heavy truck for long-haul deliveries.", "seed")
    store.save("vehicle:Kira_Van", "Affordable mid-size van, great for beginners.", "seed")
    store.save("guide:delivery-tips", "Always check subsidies before picking cargo.", "agent")
    store.save("location:Gangjung", "The capital city with the main port.", "seed")
    return store


# --- Basic CRUD ---


def test_save_and_get(store):
    store.save("vehicle:TestCar", "A fast car.")
    assert store.get("vehicle:TestCar") == "A fast car."


def test_get_missing(store):
    assert store.get("nonexistent") is None


def test_save_overwrites(store):
    store.save("vehicle:TestCar", "Old description.")
    store.save("vehicle:TestCar", "New description.")
    assert store.get("vehicle:TestCar") == "New description."


def test_remove(seeded_store):
    assert seeded_store.remove("guide:delivery-tips") is True
    assert seeded_store.get("guide:delivery-tips") is None


def test_remove_missing(store):
    assert store.remove("nonexistent") is False


def test_get_batch(seeded_store):
    result = seeded_store.get_batch(["vehicle:Gosan_G7", "vehicle:Kira_Van", "missing:key"])
    assert "vehicle:Gosan_G7" in result
    assert "vehicle:Kira_Van" in result
    assert "missing:key" not in result


# --- Search ---


def test_search_by_key(seeded_store):
    results = seeded_store.search("Gosan")
    assert len(results) == 1
    assert results[0][0] == "vehicle:Gosan_G7"


def test_search_by_content(seeded_store):
    results = seeded_store.search("subsidies")
    assert len(results) == 1
    assert results[0][0] == "guide:delivery-tips"


def test_search_case_insensitive(seeded_store):
    results = seeded_store.search("KIRA")
    assert len(results) == 1


def test_search_multiple_matches(seeded_store):
    results = seeded_store.search("vehicle")
    # Matches both vehicle: keys
    assert len(results) >= 2


def test_search_empty(store):
    assert store.search("") == []


# --- List Keys ---


def test_list_keys_all(seeded_store):
    keys = seeded_store.list_keys()
    assert len(keys) == 4


def test_list_keys_filtered(seeded_store):
    keys = seeded_store.list_keys("vehicle")
    assert len(keys) == 2
    assert all(k.startswith("vehicle:") for k in keys)


def test_list_keys_no_match(seeded_store):
    keys = seeded_store.list_keys("nonexistent")
    assert keys == []


# --- Index Building ---


def test_build_index_empty(store):
    assert store.build_index() == ""


def test_build_index_grouped(seeded_store):
    index = seeded_store.build_index()
    assert "vehicle (2)" in index
    assert "guide (1)" in index
    assert "location (1)" in index
    assert "lookup_knowledge" in index


# --- File Persistence ---


def test_persistence(tmp_path):
    path = str(tmp_path / "knowledge.json")
    store1 = KnowledgeStore(path)
    store1.save("vehicle:Test", "Persisted content.")

    # Load from same file in a new instance
    store2 = KnowledgeStore(path)
    assert store2.get("vehicle:Test") == "Persisted content."


def test_atomic_write(tmp_path):
    """Verify the file is valid JSON after save."""
    path = str(tmp_path / "knowledge.json")
    store = KnowledgeStore(path)
    store.save("vehicle:Test", "Some content.")

    with open(path) as f:
        data = json.load(f)
    assert "vehicle:Test" in data


def test_creates_parent_dirs(tmp_path):
    path = str(tmp_path / "subdir" / "deep" / "knowledge.json")
    store = KnowledgeStore(path)
    store.save("test:key", "value")
    assert os.path.exists(path)


def test_source_metadata(store):
    store.save("vehicle:Test", "Content", source="admin")
    # Verify source is stored internally
    assert store._data["vehicle:Test"]["source"] == "admin"
    assert "updated_at" in store._data["vehicle:Test"]
