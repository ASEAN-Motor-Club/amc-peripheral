"""Tests for wiki storage module."""

import os
import tempfile
import pytest
from amc_peripheral.wiki.storage import WikiStorage


@pytest.fixture
def wiki_storage():
    """Create a temporary wiki storage for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    storage = WikiStorage(db_path=db_path)
    yield storage

    storage.close()
    os.unlink(db_path)


def test_create_and_get_page(wiki_storage):
    """Test creating and retrieving a wiki page."""
    page_id = wiki_storage.create_page(
        title="player:TestPlayer",
        category="player",
        content="Test player content",
        summary="A test player",
    )
    assert page_id > 0

    page = wiki_storage.get_page_by_id(page_id)
    assert page is not None
    assert page["title"] == "player:TestPlayer"
    assert page["category"] == "player"
    assert page["content"] == "Test player content"
    assert page["summary"] == "A test player"
    assert page["slug"] == "player-testplayer"


def test_get_page_by_slug(wiki_storage):
    """Test retrieving a page by slug."""
    wiki_storage.create_page(title="vehicle:Gosan_G7", category="vehicle")
    page = wiki_storage.get_page_by_slug("vehicle-gosan_g7")
    assert page is not None
    assert page["title"] == "vehicle:Gosan_G7"


def test_get_page_by_title(wiki_storage):
    """Test retrieving a page by exact title."""
    wiki_storage.create_page(title="concept:steel-coil-curse", category="concept")
    page = wiki_storage.get_page_by_title("concept:steel-coil-curse")
    assert page is not None
    assert page["category"] == "concept"


def test_update_page(wiki_storage):
    """Test updating a wiki page."""
    page_id = wiki_storage.create_page(
        title="event:great-race",
        category="event",
        content="Old content",
    )
    success = wiki_storage.update_page(page_id, content="New content", summary="Updated")
    assert success is True

    page = wiki_storage.get_page_by_id(page_id)
    assert page["content"] == "New content"
    assert page["summary"] == "Updated"


def test_update_page_not_found(wiki_storage):
    """Test updating a non-existent page."""
    success = wiki_storage.update_page(9999, content="New content")
    assert success is False


def test_delete_page(wiki_storage):
    """Test deleting a wiki page and its links/sources."""
    page_id = wiki_storage.create_page(title="song:highway-to-hell", category="song")
    wiki_storage.add_source(page_id, "radio", "request_123")

    success = wiki_storage.delete_page(page_id)
    assert success is True
    assert wiki_storage.get_page_by_id(page_id) is None
    assert wiki_storage.get_sources(page_id) == []


def test_delete_page_not_found(wiki_storage):
    """Test deleting a non-existent page."""
    success = wiki_storage.delete_page(9999)
    assert success is False


def test_list_pages(wiki_storage):
    """Test listing pages with filters."""
    wiki_storage.create_page(title="player:Alice", category="player")
    wiki_storage.create_page(title="player:Bob", category="player")
    wiki_storage.create_page(title="vehicle:Gosan_G7", category="vehicle")

    all_pages = wiki_storage.list_pages()
    assert len(all_pages) == 3

    players = wiki_storage.list_pages(category="player")
    assert len(players) == 2

    filtered = wiki_storage.list_pages(keyword="Alice")
    assert len(filtered) == 1
    assert filtered[0]["title"] == "player:Alice"


def test_page_count(wiki_storage):
    """Test page counting."""
    assert wiki_storage.get_page_count() == 0
    wiki_storage.create_page(title="a", category="player")
    wiki_storage.create_page(title="b", category="player")
    wiki_storage.create_page(title="c", category="vehicle")
    assert wiki_storage.get_page_count() == 3
    assert wiki_storage.get_page_count(category="player") == 2


def test_add_and_get_links(wiki_storage):
    """Test adding and retrieving cross-references."""
    p1 = wiki_storage.create_page(title="player:Alice", category="player")
    p2 = wiki_storage.create_page(title="player:Bob", category="player")

    link_id = wiki_storage.add_link(p1, p2, "friends")
    assert link_id > 0

    outbound = wiki_storage.get_links_from(p1)
    assert len(outbound) == 1
    assert outbound[0]["to_title"] == "player:Bob"
    assert outbound[0]["link_type"] == "friends"

    inbound = wiki_storage.get_links_to(p2)
    assert len(inbound) == 1
    assert inbound[0]["from_title"] == "player:Alice"


def test_remove_link(wiki_storage):
    """Test removing a cross-reference."""
    p1 = wiki_storage.create_page(title="a", category="concept")
    p2 = wiki_storage.create_page(title="b", category="concept")
    wiki_storage.add_link(p1, p2)

    wiki_storage.remove_link(p1, p2)
    assert wiki_storage.get_links_from(p1) == []


def test_add_and_get_sources(wiki_storage):
    """Test adding and retrieving raw source references."""
    page_id = wiki_storage.create_page(title="guide:test", category="guide")
    source_id = wiki_storage.add_source(page_id, "conversation", "conv_123")
    assert source_id > 0

    sources = wiki_storage.get_sources(page_id)
    assert len(sources) == 1
    assert sources[0]["source_type"] == "conversation"
    assert sources[0]["source_id"] == "conv_123"

    # source_count should be updated
    page = wiki_storage.get_page_by_id(page_id)
    assert page["source_count"] == 1


def test_log_operation(wiki_storage):
    """Test appending to the wiki log."""
    log_id = wiki_storage.log_operation("ingest", "Test ingest", [1, 2, 3])
    assert log_id > 0

    entries = wiki_storage.get_log_entries()
    assert len(entries) == 1
    assert entries[0]["operation"] == "ingest"
    assert entries[0]["pages_affected"] == "1,2,3"


def test_get_log_entries_filtered(wiki_storage):
    """Test filtering log entries by operation."""
    wiki_storage.log_operation("ingest", "Ingest 1")
    wiki_storage.log_operation("lint", "Lint 1")
    wiki_storage.log_operation("ingest", "Ingest 2")

    ingest_entries = wiki_storage.get_log_entries(operation="ingest")
    assert len(ingest_entries) == 2

    lint_entries = wiki_storage.get_log_entries(operation="lint")
    assert len(lint_entries) == 1


def test_orphan_pages(wiki_storage):
    """Test finding orphan pages."""
    p1 = wiki_storage.create_page(title="a", category="concept")
    p2 = wiki_storage.create_page(title="b", category="concept")
    wiki_storage.add_link(p1, p2)

    orphans = wiki_storage.get_orphan_pages()
    # p1 has outbound link but no inbound; p2 has inbound link
    # Orphans = no inbound links, so only p1 is an orphan
    orphan_ids = {p["id"] for p in orphans}
    assert p1 in orphan_ids
    assert p2 not in orphan_ids


def test_stale_pages(wiki_storage):
    """Test finding stale pages."""
    # Fresh page
    wiki_storage.create_page(title="fresh", category="concept")
    # All pages are fresh, so no stale pages with 0 days threshold
    stale = wiki_storage.get_stale_pages(days=0)
    # SQLite datetime('now', '0 days') is effectively now, so nothing should be stale
    assert len(stale) == 0


def test_index_cache(wiki_storage):
    """Test index cache get/set."""
    assert wiki_storage.get_index_cache() is None

    wiki_storage.set_index_cache("Test index content")
    assert wiki_storage.get_index_cache() == "Test index content"


def test_get_stats(wiki_storage):
    """Test wiki statistics."""
    stats = wiki_storage.get_stats()
    assert stats["total_pages"] == 0
    assert stats["total_links"] == 0

    p1 = wiki_storage.create_page(title="a", category="player")
    p2 = wiki_storage.create_page(title="b", category="vehicle")
    wiki_storage.add_link(p1, p2)
    wiki_storage.add_source(p1, "test", "src1")
    wiki_storage.log_operation("ingest", "Test")

    stats = wiki_storage.get_stats()
    assert stats["total_pages"] == 2
    assert stats["total_categories"] == 2
    assert stats["total_sources"] == 1
    assert stats["total_links"] == 1
    assert stats["total_log_entries"] == 1


def test_slug_generation(wiki_storage):
    """Test slug generation from titles."""
    assert wiki_storage._make_slug("Hello World!") == "hello-world"
    assert wiki_storage._make_slug("player:Test Player") == "player-test-player"
    assert wiki_storage._make_slug("  Spaces  ") == "spaces"
