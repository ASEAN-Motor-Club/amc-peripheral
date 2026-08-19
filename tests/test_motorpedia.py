"""Tests for the motorpedia lookup module."""

import pytest
from amc_peripheral.bot import motorpedia


@pytest.fixture(autouse=True)
def reset_cache():
    """Reset the module-level article cache between tests (it's path-fixed, but cheap)."""
    motorpedia._cache = None
    yield
    motorpedia._cache = None


class TestLoadAndIndex:
    def test_loads_articles(self):
        articles = motorpedia._load()
        assert len(articles) >= 20
        assert "Police & Violations" in articles
        assert "Wrecked Vehicle Tow Requests" in articles

    def test_index_lists_all_titles(self):
        idx = motorpedia.get_index()
        assert "Motorpedia" in idx
        assert "Police & Violations" in idx
        assert "Fuel Management" in idx


class TestLookup:
    def test_exact_title(self):
        r = motorpedia.lookup("fuel management")
        assert r.startswith("Fuel Management")

    def test_title_substring(self):
        r = motorpedia.lookup("police")
        assert r.startswith("Police & Violations")

    def test_title_keyword_win(self):
        # 'bus route' should land on Bus Driver (title match), not Job Levels.
        r = motorpedia.lookup("bus route")
        assert r.startswith("Bus Driver")

    def test_body_keyword_strong_match(self):
        r = motorpedia.lookup("winch")
        assert r.startswith("Towing & Winch")

    def test_no_match_returns_available(self):
        r = motorpedia.lookup("what is the speed limit")
        assert "No motorpedia article matched" in r
        assert "Available topics:" in r

    def test_empty_topic(self):
        r = motorpedia.lookup("")
        assert "topic required" in r.lower()
