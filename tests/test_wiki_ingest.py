"""Tests for wiki ingest module."""

import os
import tempfile
import pytest

from amc_peripheral.wiki.storage import WikiStorage
from amc_peripheral.wiki.retrieval import WikiRetrieval
from amc_peripheral.wiki.ingest import WikiIngest


@pytest.fixture
def wiki_ingest():
    """Create a temporary wiki ingest instance for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "wiki.db")
        chroma_path = os.path.join(tmpdir, "chromadb")

        storage = WikiStorage(db_path=db_path)
        retrieval = WikiRetrieval(path=chroma_path)
        ingest = WikiIngest(storage=storage, retrieval=retrieval)
        yield ingest

        storage.close()


def test_ingest_conversation_creates_player_page(wiki_ingest):
    """Test that ingesting a conversation creates a player page."""
    messages = [
        {"message": "Hello Annie!", "is_bot_response": False, "timestamp": "2026-04-20T10:00:00"},
        {"message": "Hi there!", "is_bot_response": True, "timestamp": "2026-04-20T10:01:00"},
    ]
    affected = wiki_ingest.ingest_conversation(
        player_id="123",
        player_name="TestPlayer",
        messages=messages,
    )
    assert len(affected) >= 1

    page = wiki_ingest.storage.get_page_by_slug("player-123")
    assert page is not None
    assert page["category"] == "player"
    assert page["title"] == "player:123"


def test_ingest_conversation_with_facts(wiki_ingest):
    """Test ingesting with pre-extracted facts."""
    messages = [
        {"message": "I love the Gosan G7", "is_bot_response": False, "timestamp": "2026-04-20T10:00:00"},
    ]
    facts = [
        {
            "title": "vehicle:Gosan_G7",
            "category": "vehicle",
            "content": "Player 123 loves this truck.",
            "summary": "Popular with player 123",
        }
    ]
    affected = wiki_ingest.ingest_conversation(
        player_id="123",
        player_name="TestPlayer",
        messages=messages,
        extracted_facts=facts,
    )

    vehicle_page = wiki_ingest.storage.get_page_by_slug("vehicle-gosan_g7")
    assert vehicle_page is not None
    assert vehicle_page["category"] == "vehicle"
    assert "Player 123 loves this truck." in vehicle_page["content"]


def test_ingest_event(wiki_ingest):
    """Test ingesting a community event."""
    affected = wiki_ingest.ingest_event(
        event_type="race",
        event_id="2026-04-20-great-race",
        title="2026-04-20 Great Race",
        description="An epic race between Alice and Bob.",
        participants=["alice", "bob"],
    )
    assert len(affected) >= 1

    event_page = wiki_ingest.storage.get_page_by_slug("event-2026-04-20-great-race")
    assert event_page is not None
    assert event_page["category"] == "event"


def test_ingest_event_links_participants(wiki_ingest):
    """Test that event ingestion links participant pages."""
    # Pre-create player pages
    alice_id = wiki_ingest.storage.create_page(title="player:Alice", category="player")
    bob_id = wiki_ingest.storage.create_page(title="player:Bob", category="player")

    wiki_ingest.ingest_event(
        event_type="race",
        event_id="race-1",
        title="Race 1",
        description="A race.",
        participants=["alice", "bob"],
    )

    event_page = wiki_ingest.storage.get_page_by_slug("event-race-1")
    event_id = event_page["id"]

    outbound = wiki_ingest.storage.get_links_from(event_id)
    to_ids = {link["to_page_id"] for link in outbound}
    assert alice_id in to_ids
    assert bob_id in to_ids


def test_batch_ingest_sources(wiki_ingest):
    """Test batch ingestion of multiple sources."""
    sources = [
        {
            "source_type": "conversation",
            "source_id": "conv_1",
            "facts": [
                {"title": "concept:steel-coil-curse", "category": "concept", "content": "A running joke."},
            ],
        },
        {
            "source_type": "conversation",
            "source_id": "conv_2",
            "facts": [
                {"title": "location:Gangjung", "category": "location", "content": "The capital city."},
            ],
        },
    ]
    affected = wiki_ingest.batch_ingest_sources(sources)
    assert len(affected) == 2

    concept_page = wiki_ingest.storage.get_page_by_slug("concept-steel-coil-curse")
    assert concept_page is not None

    location_page = wiki_ingest.storage.get_page_by_slug("location-gangjung")
    assert location_page is not None


def test_ingest_logs_operation(wiki_ingest):
    """Test that ingest operations are logged."""
    wiki_ingest.ingest_conversation(
        player_id="123",
        player_name="TestPlayer",
        messages=[{"message": "Hi", "is_bot_response": False, "timestamp": "2026-04-20T10:00:00"}],
    )

    log_entries = wiki_ingest.storage.get_log_entries(operation="ingest")
    assert len(log_entries) >= 1
    assert "TestPlayer" in log_entries[0]["description"]
