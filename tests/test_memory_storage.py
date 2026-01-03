"""Tests for memory storage module."""

import os
import tempfile
import pytest
from amc_peripheral.memory.storage import MemoryStorage


@pytest.fixture
def memory_storage():
    """Create a temporary memory storage for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    
    storage = MemoryStorage(db_path=db_path)
    yield storage
    
    storage.close()
    os.unlink(db_path)


def test_store_and_retrieve_message(memory_storage):
    """Test storing and retrieving a message."""
    row_id = memory_storage.store_message(
        player_id="123",
        player_name="TestPlayer",
        message="Hello world",
        source="game_chat",
    )
    
    assert row_id > 0
    
    messages = memory_storage.get_recent_messages("123")
    assert len(messages) == 1
    assert messages[0]["player_name"] == "TestPlayer"
    assert messages[0]["message"] == "Hello world"
    assert messages[0]["source"] == "game_chat"


def test_get_recent_messages_order(memory_storage):
    """Test that messages are returned in chronological order."""
    for i in range(5):
        memory_storage.store_message(
            player_id="123",
            player_name="TestPlayer",
            message=f"Message {i}",
            source="game_chat",
        )
    
    messages = memory_storage.get_recent_messages("123", limit=3)
    
    # Should get the 3 most recent, in chronological order
    assert len(messages) == 3
    assert messages[0]["message"] == "Message 2"
    assert messages[1]["message"] == "Message 3"
    assert messages[2]["message"] == "Message 4"


def test_get_recent_messages_with_source_filter(memory_storage):
    """Test filtering messages by source."""
    memory_storage.store_message("123", "Player", "Game msg", source="game_chat")
    memory_storage.store_message("123", "Player", "Discord msg", source="discord_dm")
    memory_storage.store_message("123", "Player", "Another game", source="game_chat")
    
    game_only = memory_storage.get_recent_messages("123", sources=["game_chat"])
    assert len(game_only) == 2
    
    discord_only = memory_storage.get_recent_messages("123", sources=["discord_dm"])
    assert len(discord_only) == 1
    
    all_sources = memory_storage.get_recent_messages("123", sources=["game_chat", "discord_dm"])
    assert len(all_sources) == 3


def test_message_count(memory_storage):
    """Test message count functionality."""
    assert memory_storage.get_message_count() == 0
    
    memory_storage.store_message("123", "Player1", "Msg 1", "game_chat")
    memory_storage.store_message("123", "Player1", "Msg 2", "game_chat")
    memory_storage.store_message("456", "Player2", "Msg 3", "game_chat")
    
    assert memory_storage.get_message_count() == 3
    assert memory_storage.get_message_count("123") == 2
    assert memory_storage.get_message_count("456") == 1


def test_store_bot_response(memory_storage):
    """Test storing bot responses."""
    memory_storage.store_message(
        player_id="123",
        player_name="Bot",
        message="I am a bot response",
        source="game_chat",
        is_bot_response=True,
    )
    
    messages = memory_storage.get_recent_messages("123")
    assert len(messages) == 1
    assert messages[0]["is_bot_response"] == 1


def test_discord_metadata(memory_storage):
    """Test storing Discord-related metadata."""
    memory_storage.store_message(
        player_id="discord_12345",
        player_name="DiscordUser",
        message="Discord message",
        source="discord_channel",
        discord_user_id="12345",
        discord_channel_id="67890",
        discord_message_id="11111",
        guild_id="99999",
    )
    
    messages = memory_storage.get_recent_messages("discord_12345")
    assert len(messages) == 1
    assert messages[0]["discord_user_id"] == "12345"
    assert messages[0]["discord_channel_id"] == "67890"
    assert messages[0]["guild_id"] == "99999"
