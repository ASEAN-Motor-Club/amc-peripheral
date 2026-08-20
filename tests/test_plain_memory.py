"""Tests for the plain-text, Chroma-free memory store (architecture revamp)."""

import pytest

from amc_peripheral.wiki.plain_memory import PlainTextMemory


@pytest.fixture
def store(tmp_path):
    return PlainTextMemory(root=str(tmp_path))


def test_write_creates_plaintext_file(store, tmp_path):
    store.write_fact("Identity", "I am Annie.", category="self")
    f = tmp_path / "self" / "identity.txt"
    assert f.is_file()
    text = f.read_text(encoding="utf-8")
    assert "====== Identity ======" in text
    assert "I am Annie." in text


def test_write_is_web_renderable_dw_heading(store, tmp_path):
    """Memory pages use DokuWiki ====== headings (render reliably) + markdown body."""
    store.write_fact("Bank Rule", "| key | value |\n| a | b |")
    f = tmp_path / "facts" / "bank-rule.txt"
    assert f.is_file()
    text = f.read_text(encoding="utf-8")
    assert "====== Bank Rule ======" in text
    assert "| key | value |" in text


def test_self_block(store, tmp_path):
    store.write_fact("Identity", "I am the ASEAN club bot.", category="self")
    store.write_fact("Role", "I help with game knowledge.", category="self")
    block = store.self_block()
    assert "I am the ASEAN club bot." in block
    assert "I help with game knowledge." in block


def test_recall_lexical_no_chroma(store):
    store.write_fact("frozenblaze is Commander", "He asked to be called Commander.", summary="rank")
    store.write_fact("Unrelated", "Air City is a bus.", category="fact")
    hits = store.recall("commander")
    assert hits, "recall should find the Commander page lexically"
    assert hits[0]["title"] == "frozenblaze is Commander"
    assert hits[0]["category"] == "fact"


def test_recall_returns_empty_on_no_match(store):
    assert store.recall("zyzzx-nonexistent") == []


def test_list_facts(store):
    store.write_fact("A", "one", category="fact")
    store.write_fact("B", "two", category="fact")
    store.write_fact("S", "three", category="self")
    facts = store.list_facts("fact")
    assert [p["title"] for p in facts] == ["A", "B"]


def test_delete_removes_file(store, tmp_path):
    store.write_fact("Gone Soon", "bye", category="fact")
    assert store.delete("Gone Soon") is True
    assert not (tmp_path / "facts" / "gone-soon.txt").exists()
    assert store.delete("Gone Soon") is False


def test_unknown_category_coerced_to_fact(store, tmp_path):
    store.write_fact("X", "content", category="bogus")
    assert (tmp_path / "facts" / "x.txt").is_file()