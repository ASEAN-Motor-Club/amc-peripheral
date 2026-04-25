"""Tests for wiki retrieval (ChromaDB) module."""

import os
import tempfile
import pytest

from amc_peripheral.wiki.storage import WikiStorage
from amc_peripheral.wiki.retrieval import WikiRetrieval


@pytest.fixture
def wiki_retrieval():
    """Create a temporary wiki retrieval instance for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        chroma_path = os.path.join(tmpdir, "chromadb")
        retrieval = WikiRetrieval(path=chroma_path)
        yield retrieval


def test_index_and_search(wiki_retrieval):
    """Test indexing a page and searching for it."""
    wiki_retrieval.index_page(
        page_id=1,
        title="vehicle:Gosan_G7",
        content="The Gosan G7 is a heavy truck excellent for long haul deliveries.",
        category="vehicle",
        updated_at="2026-04-20T00:00:00",
    )

    results = wiki_retrieval.search("heavy truck for deliveries", n_results=3)
    assert len(results) >= 1
    assert results[0]["page_id"] == 1
    assert results[0]["title"] == "vehicle:Gosan_G7"


def test_search_with_category_filter(wiki_retrieval):
    """Test searching with a category filter."""
    wiki_retrieval.index_page(
        page_id=1,
        title="vehicle:Gosan_G7",
        content="A heavy truck.",
        category="vehicle",
        updated_at="2026-04-20T00:00:00",
    )
    wiki_retrieval.index_page(
        page_id=2,
        title="player:Alice",
        content="Alice loves driving trucks.",
        category="player",
        updated_at="2026-04-20T00:00:00",
    )

    vehicle_results = wiki_retrieval.search("truck", category="vehicle")
    assert len(vehicle_results) == 1
    assert vehicle_results[0]["category"] == "vehicle"


def test_remove_page(wiki_retrieval):
    """Test removing a page from the index."""
    wiki_retrieval.index_page(
        page_id=1,
        title="song:test",
        content="A test song.",
        category="song",
        updated_at="2026-04-20T00:00:00",
    )
    assert wiki_retrieval.get_indexed_count() == 1

    success = wiki_retrieval.remove_page(1)
    assert success is True
    assert wiki_retrieval.get_indexed_count() == 0


def test_clear_index(wiki_retrieval):
    """Test clearing the entire index."""
    wiki_retrieval.index_page(
        page_id=1,
        title="a",
        content="Content A",
        category="concept",
        updated_at="2026-04-20T00:00:00",
    )
    wiki_retrieval.index_page(
        page_id=2,
        title="b",
        content="Content B",
        category="concept",
        updated_at="2026-04-20T00:00:00",
    )
    assert wiki_retrieval.get_indexed_count() == 2

    success = wiki_retrieval.clear_index()
    assert success is True
    assert wiki_retrieval.get_indexed_count() == 0


def test_search_max_distance(wiki_retrieval):
    """Test that max_distance filters out distant results."""
    wiki_retrieval.index_page(
        page_id=1,
        title="vehicle:Gosan_G7",
        content="Heavy truck for long hauls.",
        category="vehicle",
        updated_at="2026-04-20T00:00:00",
    )

    # Very restrictive distance should return nothing
    results = wiki_retrieval.search("pizza recipe", max_distance=0.1)
    assert len(results) == 0
