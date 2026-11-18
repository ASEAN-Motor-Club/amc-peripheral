"""Comment pages: who can post, what is rendered, what is escaped."""

from __future__ import annotations

import pytest
from aiohttp.test_utils import TestClient, TestServer

from amc_peripheral.workshop import routes
from amc_peripheral.workshop.auth import SSOSettings, csrf_token, sign_session

GUILD_ID = 424242
SECRET = "session-secret-value"
MEMBER = "9001"
OTHER = "1111"
ITEM = 1


@pytest.fixture
def sso() -> SSOSettings:
    return SSOSettings(
        client_id="123456789",
        client_secret="client-secret",
        session_secret=SECRET,
        guild_id=GUILD_ID,
        public_url="http://example.test",
    )


class FakeIdentity:
    steam_id = 76561198000000000

    def identity_for(self, discord_id):
        from amc_peripheral.workshop.auth import Identity

        return Identity(self.steam_id, frozenset())

    def steam_id_for(self, discord_id):
        return self.steam_id


@pytest.fixture
async def client(settings, sso):
    app = routes.create_app(settings, sso=sso, player_identity=FakeIdentity())  # type: ignore[arg-type]
    test_client = TestClient(TestServer(app))
    await test_client.start_server()
    test_client.workshop_app = app  # type: ignore[attr-defined]
    yield test_client
    await test_client.close()


def _as(member: str = MEMBER) -> tuple[dict, dict]:
    claims = {
        "sub": member,
        "u": "driver",
        "n": "Driver",
        "m": True,
        "iat": 1_700_000_000,
    }
    cookie = sign_session(claims, SECRET, ttl=3600)
    return {"amc_workshop_session": cookie}, {"csrf": csrf_token(claims, SECRET)}


def _relax(client):
    """Tests post faster than a person; keep only the limit test honest."""
    limiter_class = type(client.workshop_app["limiters"]["comment"])
    client.workshop_app["limiters"]["comment"] = limiter_class(limit=999, window=0.0)
    client.workshop_app["limiters"]["comment_burst"] = limiter_class(
        limit=999, window=0.0
    )


async def _post_comment(client, body="Nice paint", *, member=MEMBER):
    _relax(client)
    cookies, form = _as(member)
    return await client.post(
        f"/workshop/items/{ITEM}/comments",
        data={"body": body, **form},
        cookies=cookies,
        allow_redirects=False,
    )


def _store(client):
    return client.workshop_app["comments"]


async def _page(client, *, cookies=None, query=""):
    response = await client.get(
        f"/workshop/items/{ITEM}/{query}", cookies=cookies or {}
    )
    assert response.status == 200
    return await response.text()


async def test_anonymous_sees_comments_but_no_form(client):
    await _post_comment(client, "First post")
    text = await _page(client)
    assert "First post" in text
    assert "Sign in to comment" in text
    assert "Write a comment" not in text


async def test_anonymous_post_is_refused_by_csrf(client):
    """No token, no session: the CSRF gate answers before the login redirect."""
    response = await client.post(
        f"/workshop/items/{ITEM}/comments",
        data={"body": "hi"},
        cookies={},
        allow_redirects=False,
    )
    assert response.status == 403
    assert _store(client).count(ITEM) == 0


async def test_member_posts_and_sees_it(client):
    response = await _post_comment(client, "Lovely offset")
    assert response.status == 303
    assert f"/workshop/items/{ITEM}/" in response.headers["Location"]

    text = await _page(client)
    assert "Lovely offset" in text
    member_view = await _page(client, cookies=_as()[0])
    assert "Write a comment" in member_view


async def test_author_name_comes_from_the_profile(client):
    community = client.workshop_app["community"]
    community.save_profile(
        discord_id=MEMBER, display_name="Radhi", bio="", now="2026-11-18T18:00:00+00:00"
    )
    await _post_comment(client, "hello")
    text = await _page(client)
    assert "Radhi" in text


async def test_html_in_a_comment_is_escaped(client):
    await _post_comment(client, "<script>alert(1)</script> & <b>bold</b>")
    text = await _page(client)
    assert "<script>alert(1)</script>" not in text
    assert "&lt;script&gt;" in text
    assert "&amp;" in text


async def test_newlines_render_as_breaks(client):
    await _post_comment(client, "line one\nline two")
    text = await _page(client)
    assert "line one<br>line two" in text


async def test_urls_are_stripped_before_storage(client):
    await _post_comment(client, "grab it at example.com for free")
    text = await _page(client)
    assert "example.com" not in text


async def test_empty_comment_is_refused_with_the_draft(client):
    response = await _post_comment(client, "   ")
    assert response.status == 200
    assert "Comment is required" in await response.text()
    assert _store(client).count(ITEM) == 0


async def test_rate_limit_stops_the_eleventh_comment(client):
    limiter_class = type(client.workshop_app["limiters"]["comment"])
    client.workshop_app["limiters"]["comment_burst"] = limiter_class(
        limit=999, window=0.0
    )
    for index in range(10):
        cookies, form = _as()
        response = await client.post(
            f"/workshop/items/{ITEM}/comments",
            data={"body": f"comment {index}", **form},
            cookies=cookies,
            allow_redirects=False,
        )
        assert response.status == 303, index
    the_eleventh = await client.post(
        f"/workshop/items/{ITEM}/comments",
        data={"body": "one too many", **form},
        cookies=cookies,
        allow_redirects=False,
    )
    assert the_eleventh.status == 429
    assert _store(client).count(ITEM) == 10


async def test_edit_within_the_window(client):
    await _post_comment(client, "typo here")
    comment = _store(client).for_item(ITEM)["items"][0]
    cookies, form = _as()
    response = await client.post(
        f"/workshop/comments/{comment.id}/edit",
        data={"body": "typo fixed", **form},
        cookies=cookies,
        allow_redirects=False,
    )
    assert response.status == 303
    assert _store(client).get(comment.id).body == "typo fixed"


async def test_edit_by_someone_else_is_refused(client):
    await _post_comment(client, "mine")
    comment = _store(client).for_item(ITEM)["items"][0]
    cookies, form = _as(OTHER)
    response = await client.post(
        f"/workshop/comments/{comment.id}/edit",
        data={"body": "changed", **form},
        cookies=cookies,
        allow_redirects=False,
    )
    # Rendered back with the error rather than silently redirected.
    assert response.status == 200
    assert "Only the author" in await response.text()
    assert _store(client).get(comment.id).body == "mine"


async def test_delete_only_by_author(client):
    await _post_comment(client, "mine")
    comment = _store(client).for_item(ITEM)["items"][0]

    cookies, form = _as(OTHER)
    response = await client.post(
        f"/workshop/comments/{comment.id}/delete",
        data=form,
        cookies=cookies,
        allow_redirects=False,
    )
    assert response.status == 303
    assert _store(client).get(comment.id) is not None

    cookies, form = _as(MEMBER)
    response = await client.post(
        f"/workshop/comments/{comment.id}/delete",
        data=form,
        cookies=cookies,
        allow_redirects=False,
    )
    assert response.status == 303
    assert _store(client).get(comment.id) is None


async def test_pagination_shows_the_older_half(client):
    for index in range(12):
        await _post_comment(client, f"comment {index}")
    first = await _page(client)
    assert "comment 11" in first
    assert "comment 0" not in first
    assert "Page 1 of 2" in first

    second = await _page(client, query="?cpage=2")
    assert "comment 0" in second
    assert "comment 11" not in second


async def test_edit_controls_only_for_the_author(client):
    await _post_comment(client, "mine")
    cookies, _ = _as(OTHER)
    other_view = await _page(client, cookies=cookies)
    assert "/comments/1/edit" not in other_view
    assert "Delete" not in other_view

    mine = await _page(client, cookies=_as(MEMBER)[0])
    assert "/edit" in mine
    assert "Delete" in mine


async def test_hidden_comments_disappear(client):
    await _post_comment(client, "visible one")
    await _post_comment(client, "will be hidden")
    store = _store(client)
    comment = store.for_item(ITEM)["items"][-1]
    store.hide(comment_id=comment.id, admin_id="admin", now="2026-11-18T18:00:00+00:00")

    text = await _page(client)
    assert "will be hidden" not in text
    assert 'Comments <span class="muted">1</span>' in text
