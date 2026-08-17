"""Tests for Annie's durable MemoryStore (self/fact memory over the wiki)."""

from amc_peripheral.wiki.memory import MemoryStore
from amc_peripheral.wiki.storage import WikiStorage


class FakeRetrieval:
    """Minimal WikiRetrieval double: records index_page, canned search results."""

    def __init__(self, search_results=None):
        self.indexed = []
        self.search_results = search_results or []

    def index_page(self, **kwargs):
        self.indexed.append(kwargs)

    def search(self, query, n_results=5):
        return self.search_results


def _make(tmp_path):
    ws = WikiStorage(db_path=str(tmp_path / "wiki.db"))
    fr = FakeRetrieval()
    return ws, fr, MemoryStore(ws, fr)


def test_write_fact_creates_and_indexes(tmp_path):
    ws, fr, ms = _make(tmp_path)
    pid = ms.write_fact(
        "frozenblaze is Commander", "He asked to be called Commander", "fact"
    )
    assert pid
    page = ws.get_page_by_id(pid)
    assert page["category"] == "fact"
    assert fr.indexed, "fact should be indexed into ChromaDB"
    assert fr.indexed[-1]["content"] == page["content"]


def test_write_fact_idempotent(tmp_path):
    ws, fr, ms = _make(tmp_path)
    pid1 = ms.write_fact("T", "same content", "fact")
    pid2 = ms.write_fact("T", "same content", "fact")
    assert pid1 == pid2
    # unchanged content -> no re-index
    assert len(fr.indexed) == 1
    assert ws.get_page_count() == 1


def test_write_updates_changed_content(tmp_path):
    ws, fr, ms = _make(tmp_path)
    pid1 = ms.write_fact("T", "v1", "fact")
    pid2 = ms.write_fact("T", "v2", "fact")
    assert pid1 == pid2
    assert ws.get_page_by_id(pid1)["content"] == "v2"
    assert len(fr.indexed) == 2


def test_self_category_fed_into_self_block(tmp_path):
    _, _, ms = _make(tmp_path)
    ms.write_fact("Identity", "I am Annie, the ASEAN Motor Club community bot.", "self")
    block = ms.self_block()
    assert "I am Annie" in block
    # fact-category pages are NOT part of the always-injected self block
    ms.write_fact("A fact", "some on-demand fact", "fact")
    assert "some on-demand fact" not in ms.self_block()


def test_self_block_empty_when_none(tmp_path):
    _, _, ms = _make(tmp_path)
    assert ms.self_block() == ""


def test_recall_uses_retrieval(tmp_path):
    _, fr, ms = _make(tmp_path)
    fr.search_results = [{"title": "Fn", "category": "fact", "content": "content"}]
    results = ms.recall("commander")
    assert results and results[0]["title"] == "Fn"


def test_list_facts_filters_by_category(tmp_path):
    _, _, ms = _make(tmp_path)
    ms.write_fact("Self1", "self content", "self")
    ms.write_fact("Fact1", "fact content", "fact")
    only_self = ms.list_facts(category="self")
    assert [p["title"] for p in only_self] == ["Self1"]
    assert len(ms.list_facts()) == 2


def test_delete(tmp_path):
    ws, _, ms = _make(tmp_path)
    ms.write_fact("T", "content", "fact")
    assert ms.delete("T") is True
    assert ms.delete("T") is False  # already gone
    assert ws.get_page_count() == 0
