"""The moderation tool: list, hide, unhide. There is no web admin surface."""

from __future__ import annotations

import pytest

from amc_peripheral.workshop.comments import CommentStore
from amc_peripheral.workshop.moderation import hide, list_comments, main, unhide

NOW = "2026-11-18T18:00:00+00:00"


@pytest.fixture
def store(tmp_path):
    store = CommentStore(tmp_path / "site.db")
    store.add(workshop_id=1, discord_id="9001", body="a build comment", now=NOW)
    return store


def test_list_shows_state_and_body(store):
    lines = list_comments(store, limit=10)
    assert len(lines) == 1
    assert "item 1" in lines[0]
    assert "a build comment" in lines[0]
    assert "HIDDEN" not in lines[0]


def test_hide_then_unhide(store):
    comment = store.recent()[0]
    assert hide(store, comment.id, by="yumemi") is True
    assert store.count(1) == 0
    assert "HIDDEN" in list_comments(store, limit=10)[0]

    assert unhide(store, comment.id, by="yumemi") is True
    assert store.count(1) == 1


def test_hiding_a_missing_comment_reports_it(store, tmp_path, capsys):
    code = main(["--db", str(tmp_path / "site.db"), "hide", "999", "--by", "yumemi"])
    assert code == 1
    assert "no comment" in capsys.readouterr().out


def test_cli_list_works(store, tmp_path, capsys):
    code = main(["--db", str(tmp_path / "site.db"), "list", "--limit", "5"])
    assert code == 0
    assert "a build comment" in capsys.readouterr().out
