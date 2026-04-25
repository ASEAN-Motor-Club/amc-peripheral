"""Tests for wiki index module."""

import os
import tempfile
import pytest

from amc_peripheral.wiki.storage import WikiStorage
from amc_peripheral.wiki.index import WikiIndex


@pytest.fixture
def wiki_index():
    """Create a temporary wiki index for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    storage = WikiStorage(db_path=db_path)
    index = WikiIndex(storage=storage)
    yield index

    storage.close()
    os.unlink(db_path)


def test_build_index(wiki_index):
    """Test building the wiki index."""
    wiki_index.storage.create_page(title="player:Alice", category="player", summary="Alice summary")
    wiki_index.storage.create_page(title="player:Bob", category="player", summary="Bob summary")
    wiki_index.storage.create_page(title="vehicle:Gosan_G7", category="vehicle", summary="Truck summary")

    index = wiki_index.build_index()
    assert "player (2)" in index
    assert "vehicle (1)" in index
    assert "Alice" in index
    assert "Gosan_G7" in index

    # Should be cached
    cached = wiki_index.storage.get_index_cache()
    assert cached == index


def test_get_index_rebuild(wiki_index):
    """Test getting index with force rebuild."""
    wiki_index.storage.create_page(title="concept:test", category="concept")

    # First build
    idx1 = wiki_index.get_index()
    assert "concept" in idx1

    # Add another page
    wiki_index.storage.create_page(title="concept:test2", category="concept")

    # Without force, should return cached
    idx2 = wiki_index.get_index()
    assert idx2 == idx1

    # With force, should rebuild
    idx3 = wiki_index.get_index(force_rebuild=True)
    assert "test2" in idx3


def test_get_category_summary(wiki_index):
    """Test getting a category summary."""
    wiki_index.storage.create_page(title="player:Alice", category="player", content="Alice content", summary="Alice")
    wiki_index.storage.create_page(title="player:Bob", category="player", content="Bob content", summary="Bob")

    summary = wiki_index.get_category_summary("player")
    assert "Category: player" in summary
    assert "Alice" in summary
    assert "Bob" in summary


def test_get_category_summary_empty(wiki_index):
    """Test category summary for empty category."""
    summary = wiki_index.get_category_summary("nonexistent")
    assert "No pages found" in summary


def test_get_page_context(wiki_index):
    """Test building context for a single page."""
    page_id = wiki_index.storage.create_page(
        title="player:Alice",
        category="player",
        content="Alice is a great driver.",
        summary="Alice summary",
    )
    ctx = wiki_index.get_page_context(page_id)
    assert "Wiki Page: player:Alice" in ctx
    assert "Alice is a great driver." in ctx
    assert "Category: player" in ctx


def test_get_page_context_with_links(wiki_index):
    """Test page context including links."""
    p1 = wiki_index.storage.create_page(title="player:Alice", category="player")
    p2 = wiki_index.storage.create_page(title="player:Bob", category="player")
    wiki_index.storage.add_link(p1, p2, "friends")

    ctx = wiki_index.get_page_context(p1)
    assert "Links to: player:Bob" in ctx


def test_get_multi_page_context(wiki_index):
    """Test building context for multiple pages."""
    p1 = wiki_index.storage.create_page(title="a", category="concept", content="Content A")
    p2 = wiki_index.storage.create_page(title="b", category="concept", content="Content B")

    ctx = wiki_index.get_multi_page_context([p1, p2])
    assert "Content A" in ctx
    assert "Content B" in ctx
