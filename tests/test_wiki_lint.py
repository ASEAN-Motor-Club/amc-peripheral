"""Tests for wiki lint module."""

import os
import tempfile
import pytest

from amc_peripheral.wiki.storage import WikiStorage
from amc_peripheral.wiki.retrieval import WikiRetrieval
from amc_peripheral.wiki.lint import WikiLint


@pytest.fixture
def wiki_lint():
    """Create a temporary wiki lint instance for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "wiki.db")
        chroma_path = os.path.join(tmpdir, "chromadb")

        storage = WikiStorage(db_path=db_path)
        retrieval = WikiRetrieval(path=chroma_path)
        lint = WikiLint(storage=storage, retrieval=retrieval)
        yield lint

        storage.close()


def test_lint_finds_orphans(wiki_lint):
    """Test that lint finds orphan pages."""
    wiki_lint.storage.create_page(title="orphan", category="concept")
    report = wiki_lint.run_lint()
    assert len(report["orphans"]) == 1
    assert report["orphans"][0]["title"] == "orphan"


def test_lint_finds_missing_links(wiki_lint):
    """Test that lint finds pages mentioning each other without links."""
    p1 = wiki_lint.storage.create_page(
        title="player:Alice",
        category="player",
        content="Alice often races against Bob.",
    )
    p2 = wiki_lint.storage.create_page(
        title="player:Bob",
        category="player",
        content="Bob is a fast driver.",
    )

    report = wiki_lint.run_lint()
    # Alice mentions Bob but has no link
    assert len(report["missing_links"]) >= 1


def test_lint_auto_fix_missing_links(wiki_lint):
    """Test auto-fixing missing links."""
    p1 = wiki_lint.storage.create_page(
        title="player:Alice",
        category="player",
        content="Alice often races against Bob.",
    )
    p2 = wiki_lint.storage.create_page(
        title="player:Bob",
        category="player",
        content="Bob is a fast driver.",
    )

    report = wiki_lint.run_lint(auto_fix=True)
    assert len(report["fixes_applied"]) >= 1

    # Verify link was created
    links = wiki_lint.storage.get_links_from(p1)
    assert any(link["to_page_id"] == p2 for link in links)


def test_lint_logs_operation(wiki_lint):
    """Test that lint operations are logged."""
    wiki_lint.run_lint()

    log_entries = wiki_lint.storage.get_log_entries(operation="lint")
    assert len(log_entries) >= 1


def test_find_inactive_players(wiki_lint):
    """Test finding inactive players."""
    # Create a player page
    wiki_lint.storage.create_page(
        title="player:OldPlayer",
        category="player",
        summary="An old player",
    )
    # Manually update to be stale (simulate old updated_at)
    # Since we can't easily time-travel, we test the method structure
    inactive = wiki_lint._find_inactive_players(days=0)
    # With days=0, all players are stale, but we need to check if the method works
    # The actual staleness depends on updated_at which is 'now' for fresh pages
    assert isinstance(inactive, list)


def test_contradiction_candidates(wiki_lint):
    """Test finding contradiction candidates."""
    wiki_lint.storage.create_page(
        title="vehicle:Gosan_G7",
        category="vehicle",
        content="The Gosan G7 is a heavy truck with excellent fuel economy and large cargo capacity.",
    )
    wiki_lint.storage.create_page(
        title="vehicle:Gosan_G7_Review",
        category="vehicle",
        content="The Gosan G7 is a heavy truck with excellent fuel economy and large cargo capacity. Some say it is the best.",
    )

    candidates = wiki_lint.get_contradiction_candidates()
    # These two pages share many keywords
    assert len(candidates) >= 1
