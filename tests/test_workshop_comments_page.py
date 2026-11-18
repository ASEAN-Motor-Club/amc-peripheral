"""The comments index: newest comments, busiest builds, no dead links."""

from __future__ import annotations

import pytest
from aiohttp.test_utils import TestClient, TestServer

from amc_peripheral.workshop import routes

NOW = "2026-11-18T18:00:00+00:00"


@pytest.fixture
async def client(settings):
    app = routes.create_app(settings)
    test_client = TestClient(TestServer(app))
    await test_client.start_server()
    test_client.workshop_app = app  # type: ignore[attr-defined]
    yield test_client
    await test_client.close()


def _store(client):
    return client.workshop_app["comments"]


def _seed(client, *, workshop_id=1, body="nice build", member="9001", count=1):
    store = _store(client)
    made = []
    for index in range(count):
        made.append(
            store.add(
                workshop_id=workshop_id,
                discord_id=member,
                body=f"{body} {index}" if count > 1 else body,
                now=NOW,
            )
        )
    return made


async def _page(client, path="/workshop/comments/"):
    response = await client.get(path)
    return response.status, await response.text()


async def test_empty_state(client):
    status, text = await _page(client)
    assert status == 200
    assert "Nobody has commented" in text
    assert "comment-feed" not in text


async def test_lists_newest_first(client):
    _seed(client, body="first words")
    _seed(client, body="second words")
    _, text = await _page(client)
    assert "first words" in text and "second words" in text
    assert text.index("second words") < text.index("first words")


async def test_links_land_on_the_comment(client):
    made = _seed(client, body="deep linked")
    _, text = await _page(client)
    assert f"/workshop/items/1/#comment-{made[0].id}" in text


async def test_html_is_escaped(client):
    _seed(client, body="<script>alert(1)</script>")
    _, text = await _page(client)
    assert "&lt;script&gt;" in text
    assert "<script>alert(1)</script>" not in text


async def test_newlines_render_on_one_line(client):
    _seed(client, body="line one\nline two")
    _, text = await _page(client)
    assert "line one line two" in text


async def test_long_body_is_clamped(client):
    _seed(client, body="a" * 900 + "TAILMARKER")
    _, text = await _page(client)
    assert "TAILMARKER" not in text
    assert "…" in text


async def test_hidden_comments_vanish_from_feed_and_counts(client):
    made = _seed(client, body="will be hidden", count=2)
    _store(client).hide(comment_id=made[0].id, admin_id="mod", now=NOW)
    _, text = await _page(client)
    assert "will be hidden 1" in text
    assert "will be hidden 0" not in text
    assert "1 comment" in text


async def test_comment_on_missing_build_is_dropped(client):
    _seed(client, workshop_id=999, body="orphan comment")
    status, text = await _page(client)
    assert status == 200
    assert "orphan comment" not in text


async def test_bad_page_number_is_a_client_error(client):
    _seed(client)
    status, _ = await _page(client, "/workshop/comments/?page=abc")
    assert status == 400


async def test_page_past_the_end_shows_an_empty_page(client):
    _seed(client)
    status, text = await _page(client, "/workshop/comments/?page=99")
    assert status == 200
    assert "Nothing on this page" in text


async def test_pagination_splits_the_feed(client):
    for index in range(31):
        _store(client).add(
            workshop_id=1,
            discord_id="9001",
            body=f"comment number {index}",
            now=NOW,
        )
    _, first = await _page(client)
    assert "comment number 30" in first
    assert "comment number 0" not in first
    assert 'rel="next"' in first

    _, second = await _page(client, "/workshop/comments/?page=2")
    assert "comment number 0" in second
    assert 'rel="prev"' in second


async def test_most_commented_orders_by_count(client):
    _seed(client, workshop_id=1, count=2, body="one")
    _seed(client, workshop_id=3, count=1, body="three")
    _, text = await _page(client)
    busiest = text.split("Most commented", 1)[1]
    assert busiest.index("/workshop/items/1/") < busiest.index("/workshop/items/3/")
    assert "2 comments" in busiest


async def test_most_commented_tie_breaks_on_the_newer_comment(client):
    _seed(client, workshop_id=3, count=1, body="older build chat")
    _seed(client, workshop_id=1, count=1, body="newer build chat")
    _, text = await _page(client)
    busiest = text.split("Most commented", 1)[1]
    assert busiest.index("/workshop/items/1/") < busiest.index("/workshop/items/3/")


async def test_nav_marks_comments_current(client):
    _seed(client)
    _, text = await _page(client)
    assert 'aria-current="page"' in text


async def test_author_name_comes_from_the_profile(client):
    _seed(client, member="9001")
    client.workshop_app["community"].save_profile(
        discord_id="9001", display_name="Radhi", bio="", now=NOW
    )
    _, text = await _page(client)
    assert "Radhi" in text


async def test_anonymous_reader_gets_no_form(client):
    _seed(client)
    _, text = await _page(client)
    assert 'name="body"' not in text
