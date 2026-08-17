"""Tests for syncing canonical player profiles into the wiki."""

from amc_peripheral.memory.player_index import PlayerIndex
from amc_peripheral.memory.storage import MemoryStorage
from amc_peripheral.wiki.ingest import WikiIngest
from amc_peripheral.wiki.storage import WikiStorage

STEAM_ID = "76561198864278343"
DISCORD_ID = "1253991831260237898"


class FakeRetrieval:
    """Minimal retrieval double that records index_page calls (no ChromaDB)."""

    def __init__(self):
        self.indexed = []

    def index_page(self, **kwargs):
        self.indexed.append(kwargs)


def _seed(memory_store):
    memory_store.store_message(
        STEAM_ID,
        "[C10] frozenblaze",
        "ello all",
        "game_chat",
        discord_user_id=DISCORD_ID,
    )
    memory_store.store_message(
        STEAM_ID,
        "frozenblaze",
        "@annie call me commander from now on",
        "game_chat",
        discord_user_id=DISCORD_ID,
    )
    memory_store.store_message(
        STEAM_ID, "commander", "commander out", "game_chat", discord_user_id=DISCORD_ID
    )
    memory_store.store_message(
        DISCORD_ID,
        "frozenblaze",
        "via discord",
        "discord_dm",
        discord_user_id=DISCORD_ID,
    )


def _resolve_profile(tmp_path):
    mem = tmp_path / "mem.db"
    store = MemoryStorage(db_path=str(mem))
    _seed(store)
    store.close()
    idx = PlayerIndex(str(mem))
    return idx.lookup("frozenblaze")[0]


def test_profile_page_created_indexed_and_searchable(tmp_path):
    profile = _resolve_profile(tmp_path)
    wiki = tmp_path / "wiki.db"
    ws = WikiStorage(db_path=str(wiki))
    fr = FakeRetrieval()
    ingest = WikiIngest(ws, fr)

    page_id = ingest.ingest_player_profile(profile)
    assert page_id, "should create a page"

    page = ws.get_page_by_id(page_id)
    assert page["category"] == "player"
    assert page["slug"] == f"player-{STEAM_ID}"
    assert "commander" in page["content"]
    assert "Requested nickname: commander" in page["content"]
    assert str(DISCORD_ID) in page["content"]
    assert "frozenblaze" in page["content"]

    # indexed exactly once into the retrieval layer
    assert len(fr.indexed) == 1
    assert fr.indexed[0]["content"] == page["content"]

    # searchable by substring for the nickname
    hits = ws.search_by_substring("commander")
    assert any(h["id"] == page_id for h in hits)


def test_profile_sync_is_idempotent(tmp_path):
    profile = _resolve_profile(tmp_path)
    ws = WikiStorage(db_path=str(tmp_path / "wiki.db"))
    fr = FakeRetrieval()
    ingest = WikiIngest(ws, fr)

    first = ingest.ingest_player_profile(profile)
    assert first
    # unchanged profile -> no rewrite, and no re-index
    second = ingest.ingest_player_profile(profile)
    assert second == first
    assert len(fr.indexed) == 1
    assert ws.get_page_count(category="player") == 1


def test_profile_updates_on_nickname_change(tmp_path):
    profile = _resolve_profile(tmp_path)
    ws = WikiStorage(db_path=str(tmp_path / "wiki.db"))
    fr = FakeRetrieval()
    ingest = WikiIngest(ws, fr)
    first = ingest.ingest_player_profile(profile)

    changed = dict(profile)
    changed["requested_nickname"] = "Grand Admiral"
    page_id = ingest.ingest_player_profile(changed)
    assert page_id == first
    page = ws.get_page_by_id(page_id)
    assert "Grand Admiral" in page["content"]
    # re-indexed because content changed
    assert len(fr.indexed) == 2


def test_profile_without_ids_uses_name(tmp_path):
    ws = WikiStorage(db_path=str(tmp_path / "wiki.db"))
    fr = FakeRetrieval()
    ingest = WikiIngest(ws, fr)
    page_id = ingest.ingest_player_profile(
        {"name": "somebody", "aliases": ["somebody"]}
    )
    page = ws.get_page_by_id(page_id)
    assert page["slug"] == "player-somebody"
