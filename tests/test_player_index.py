"""Tests for the player identity / alias index."""

import os
import tempfile

import pytest

from amc_peripheral.memory.player_index import PlayerIndex
from amc_peripheral.memory.storage import MemoryStorage

STEAM_ID = "76561198864278343"
DISCORD_ID = "1253991831260237898"


@pytest.fixture
def memory_store():
    """Temporary memory store with known players."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    storage = MemoryStorage(db_path=db_path)
    yield db_path, storage
    storage.close()
    os.unlink(db_path)


def _seed_frozenblaze(storage):
    """A player who appears across two ids and many names, and asks for a nickname."""
    storage.store_message(
        STEAM_ID,
        "[C10] frozenblaze",
        "ello all",
        "game_chat",
        discord_user_id=DISCORD_ID,
    )
    storage.store_message(
        STEAM_ID, "[M] frozenblaze", "back", "game_chat", discord_user_id=DISCORD_ID
    )
    storage.store_message(
        STEAM_ID,
        "frozenblaze",
        "@annie call me commander from now on",
        "game_chat",
        discord_user_id=DISCORD_ID,
    )
    storage.store_message(
        STEAM_ID, "commander", "commander out", "game_chat", discord_user_id=DISCORD_ID
    )
    # the discord-side identity keys the same person under the discord id
    storage.store_message(
        DISCORD_ID,
        "frozenblaze",
        "via discord",
        "discord_dm",
        discord_user_id=DISCORD_ID,
    )
    storage.store_message(
        STEAM_ID,
        "Bot",
        "sure thing!",
        "game_chat",
        discord_user_id=DISCORD_ID,
        is_bot_response=True,
    )


def test_lookup_resolves_aliases_and_links_ids(memory_store):
    db_path, storage = memory_store
    _seed_frozenblaze(storage)
    idx = PlayerIndex(db_path)
    results = idx.lookup("frozenblaze")
    assert results, "should resolve frozenblaze"
    top = results[0]
    assert STEAM_ID in top["game_ids"]
    assert DISCORD_ID in top["discord_ids"]
    # Bot responses must not leak in as aliases
    assert "bot" not in {a.lower() for a in top["aliases"]}
    assert "frozenblaze" in {a.lower() for a in top["aliases"]}


def test_lookup_by_alias_nickname(memory_store):
    db_path, storage = memory_store
    _seed_frozenblaze(storage)
    idx = PlayerIndex(db_path)
    results = idx.lookup("commander")
    assert results, "should resolve the 'commander' alias to the same player"
    assert STEAM_ID in results[0]["game_ids"]


def test_requested_nickname_extracted(memory_store):
    db_path, storage = memory_store
    _seed_frozenblaze(storage)
    idx = PlayerIndex(db_path)
    top = idx.lookup("frozenblaze")[0]
    assert top.get("requested_nickname") == "commander"


def test_lookup_by_id(memory_store):
    db_path, storage = memory_store
    _seed_frozenblaze(storage)
    idx = PlayerIndex(db_path)
    results = idx.lookup("76561198864278343")
    assert results and STEAM_ID in results[0]["game_ids"]


def test_tag_prefixes_ignored_for_matching(memory_store):
    db_path, storage = memory_store
    _seed_frozenblaze(storage)
    idx = PlayerIndex(db_path)
    # query without a tag matches a name stored with a tag
    assert idx.lookup("frozenblaze")
    # and a query *with* a tag matches too
    assert idx.lookup("[M] frozenblaze")


def test_no_match_returns_empty(memory_store):
    db_path, storage = memory_store
    _seed_frozenblaze(storage)
    idx = PlayerIndex(db_path)
    assert idx.lookup("no-such-player-xyz") == []


def test_case_insensitive(memory_store):
    db_path, storage = memory_store
    _seed_frozenblaze(storage)
    idx = PlayerIndex(db_path)
    assert idx.lookup("FROZENBLAZE")[0]["game_ids"] == [STEAM_ID]
