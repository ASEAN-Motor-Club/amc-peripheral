"""Comments: writing rules, edit window, pagination, moderation state."""

from __future__ import annotations

import pytest

from amc_peripheral.workshop.comments import (
    BODY_MAX,
    EDIT_WINDOW_SECONDS,
    CommentError,
    CommentStore,
)

NOW = "2026-11-18T18:00:00+00:00"
ME = "9001"
OTHER = "1111"


@pytest.fixture
def store(tmp_path):
    return CommentStore(tmp_path / "site.db")


def _add(store, body="Nice paint", *, item=1, member=ME, now=NOW):
    return store.add(workshop_id=item, discord_id=member, body=body, now=now)


def test_add_and_read_back(store):
    comment = _add(store, "Nice paint job")
    assert comment.workshop_id == 1
    assert comment.discord_id == ME
    assert comment.body == "Nice paint job"
    assert comment.edited_at is None
    assert comment.hidden is False


def test_body_keeps_paragraphs(store):
    comment = _add(store, "First line\n\nSecond line")
    assert comment.body == "First line\n\nSecond line"


def test_empty_body_is_refused(store):
    with pytest.raises(CommentError) as err:
        _add(store, "   ")
    assert err.value.code == "invalid_body"


def test_body_length_is_capped(store):
    with pytest.raises(CommentError) as err:
        _add(store, "x" * (BODY_MAX + 1))
    assert err.value.code == "invalid_body"
    assert str(BODY_MAX) in err.value.message


def test_line_count_is_capped(store):
    with pytest.raises(CommentError):
        _add(store, "\n".join(["x"] * 25))


def test_urls_never_reach_storage(store):
    comment = _add(store, "see example.com and https://spam.example for more")
    assert "example" not in comment.body


def test_page_returns_oldest_first(store):
    for index in range(5):
        _add(store, f"comment {index}")
    page = store.for_item(1, limit=3, offset=0)
    assert [c.body for c in page["items"]] == ["comment 2", "comment 3", "comment 4"]
    assert page["total"] == 5

    page_two = store.for_item(1, limit=3, offset=3)
    assert [c.body for c in page_two["items"]] == ["comment 0", "comment 1"]


def test_pages_do_not_overlap(store):
    for index in range(25):
        _add(store, f"comment {index}")
    first = {c.id for c in store.for_item(1, limit=10, offset=0)["items"]}
    second = {c.id for c in store.for_item(1, limit=10, offset=10)["items"]}
    assert not first & second


def test_comments_are_per_item(store):
    _add(store, "on one", item=1)
    _add(store, "on two", item=2)
    assert [c.body for c in store.for_item(1)["items"]] == ["on one"]
    assert store.count(1) == 1
    assert store.count(2) == 1


def test_edit_sets_edited_at(store):
    comment = _add(store)
    edited = store.edit(
        comment_id=comment.id,
        discord_id=ME,
        body="Nice paint, fixed the typo",
        now="2026-11-18T18:05:00+00:00",
    )
    assert edited.body == "Nice paint, fixed the typo"
    assert edited.edited_at is not None


def test_edit_after_the_window_is_refused(store):
    comment = _add(store)
    later = f"2026-11-18T18:{EDIT_WINDOW_SECONDS // 60 + 1:02d}:00+00:00"
    with pytest.raises(CommentError) as err:
        store.edit(comment_id=comment.id, discord_id=ME, body="too late", now=later)
    assert err.value.code == "too_late"
    assert store.get(comment.id).body == "Nice paint"


def test_edit_by_someone_else_is_refused(store):
    comment = _add(store)
    with pytest.raises(CommentError) as err:
        store.edit(
            comment_id=comment.id,
            discord_id=OTHER,
            body="not mine",
            now="2026-11-18T18:01:00+00:00",
        )
    assert err.value.code == "not_owner"


def test_edited_comment_still_validates_the_body(store):
    comment = _add(store)
    with pytest.raises(CommentError) as err:
        store.edit(
            comment_id=comment.id,
            discord_id=ME,
            body="",
            now="2026-11-18T18:01:00+00:00",
        )
    assert err.value.code == "invalid_body"


def test_delete_only_by_author(store):
    comment = _add(store)
    assert store.delete(comment_id=comment.id, discord_id=OTHER) is False
    assert store.get(comment.id) is not None
    assert store.delete(comment_id=comment.id, discord_id=ME) is True
    assert store.get(comment.id) is None


def test_hide_removes_it_from_the_public_side(store):
    comment = _add(store)
    assert store.count(1) == 1
    assert store.hide(comment_id=comment.id, admin_id="admin", now=NOW) is True
    assert store.count(1) == 0
    assert store.for_item(1)["items"] == []
    # The row stays for moderators.
    assert store.get(comment.id).hidden is True
    assert store.recent()[0].id == comment.id


def test_unhide_restores_it(store):
    comment = _add(store)
    store.hide(comment_id=comment.id, admin_id="admin", now=NOW)
    store.hide(comment_id=comment.id, admin_id="admin", now=NOW, hidden=False)
    assert store.count(1) == 1


def test_hidden_comment_cannot_be_edited(store):
    comment = _add(store)
    store.hide(comment_id=comment.id, admin_id="admin", now=NOW)
    with pytest.raises(CommentError) as err:
        store.edit(
            comment_id=comment.id,
            discord_id=ME,
            body="sneak",
            now="2026-11-18T18:01:00+00:00",
        )
    assert err.value.code in {"too_late", "not_owner"}


def test_latest_returns_newest_last(store):
    for index in range(5):
        _add(store, f"c{index}")
    assert [c.body for c in store.latest(1, limit=2)] == ["c3", "c4"]


def test_for_member_lists_their_comments(store):
    _add(store, "mine", member=ME)
    _add(store, "theirs", member=OTHER)
    assert [c.body for c in store.for_member(ME)] == ["mine"]


def test_store_works_standalone(tmp_path):
    """It joins like/tag tables elsewhere, so it must create them itself."""
    store = CommentStore(tmp_path / "fresh.db")
    _add(store, "hello")
    assert store.count(1) == 1


def test_latest_global_respects_limit_and_offset(store):
    for index in range(5):
        store.add(
            workshop_id=index,
            discord_id="9001",
            body=f"body {index}",
            now=NOW,
        )
    newest = store.latest_global(limit=2, offset=0)
    assert [c.body for c in newest] == ["body 4", "body 3"]
    older = store.latest_global(limit=2, offset=2)
    assert [c.body for c in older] == ["body 2", "body 1"]
    assert store.latest_global_count() == 5


def test_latest_global_skips_hidden(store):
    comment = store.add(workshop_id=1, discord_id="9001", body="gone", now=NOW)
    store.add(workshop_id=1, discord_id="9001", body="stays", now=NOW)
    store.hide(comment_id=comment.id, admin_id="mod", now=NOW)
    bodies = [c.body for c in store.latest_global(limit=10)]
    assert bodies == ["stays"]
    assert store.latest_global_count() == 1


def test_most_commented_counts_comments_not_authors(store):
    store.add(workshop_id=1, discord_id="a", body="one", now=NOW)
    store.add(workshop_id=1, discord_id="a", body="two", now=NOW)
    store.add(workshop_id=2, discord_id="b", body="three", now=NOW)
    assert store.most_commented(limit=5) == [(1, 2), (2, 1)]


def test_most_commented_breaks_ties_on_newest_comment(store):
    store.add(workshop_id=2, discord_id="a", body="older", now=NOW)
    store.add(workshop_id=1, discord_id="a", body="newer", now=NOW)
    assert [wid for wid, _ in store.most_commented(limit=5)] == [1, 2]


def test_most_commented_ignores_hidden(store):
    first = store.add(workshop_id=1, discord_id="a", body="one", now=NOW)
    store.add(workshop_id=2, discord_id="a", body="two", now=NOW)
    store.hide(comment_id=first.id, admin_id="mod", now=NOW)
    assert store.most_commented(limit=5) == [(2, 1)]
