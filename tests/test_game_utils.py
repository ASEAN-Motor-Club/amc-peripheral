"""Tests for game_utils.announce_in_game — emoji stripping at the game-chat chokepoint."""

from urllib.parse import parse_qs, urlparse

import pytest

from amc_peripheral.utils.game_utils import announce_in_game


class _FakeResp:
    status = 200

    async def json(self):
        return {"succeeded": True, "message": "message sent"}


class _FakePostCtx:
    async def __aenter__(self):
        return _FakeResp()

    async def __aexit__(self, *exc):
        return False


class FakeSession:
    def __init__(self):
        self.urls = []

    def post(self, url):
        self.urls.append(str(url))
        return _FakePostCtx()


def _posted_message(url: str) -> str:
    return parse_qs(urlparse(url).query, keep_blank_values=True)["message"][0]


@pytest.mark.asyncio
async def test_announce_strips_emoji():
    """Radio-cog style reply with emoji must reach game chat emoji-free."""
    session = FakeSession()
    await announce_in_game(session, "On it! 🎵 'Song' is downloading now 📻✨")
    msg = _posted_message(session.urls[0])
    assert "🎵" not in msg
    assert "📻" not in msg
    assert "✨" not in msg
    assert "On it!" in msg
    assert "'Song' is downloading now" in msg


@pytest.mark.asyncio
async def test_announce_keeps_ascii_emoticons():
    """ASCII emoticons are preserved (same rule as strip_emoji / PR #34)."""
    session = FakeSession()
    await announce_in_game(session, "Good luck out there! :)")
    assert _posted_message(session.urls[0]) == "Good luck out there! :)"


@pytest.mark.asyncio
async def test_announce_plain_text_untouched():
    session = FakeSession()
    await announce_in_game(session, "plain message, no emoji")
    assert _posted_message(session.urls[0]) == "plain message, no emoji"


@pytest.mark.asyncio
async def test_announce_none_message_no_crash():
    session = FakeSession()
    await announce_in_game(session, None)
    assert _posted_message(session.urls[0]) == ""


@pytest.mark.asyncio
async def test_announce_preserves_type_and_color_params():
    session = FakeSession()
    await announce_in_game(session, "hello 🎤", type="jingle", color="FEE75C")
    query = parse_qs(urlparse(session.urls[0]).query)
    assert query["type"] == ["jingle"]
    assert query["color"] == ["FEE75C"]
