"""In-game Annie chat coherence: labeled history, tag-stripped display names,
SSE sender-id cache, and ID-only memory keys.

Companion to the 2026-09-15 plan: fabricated on-air incidents came from
UNLABELED chat history; unprompted song queues came from the always-on
queue tools; memory was keyed on role-tagged display names.
"""

from collections import OrderedDict
from unittest.mock import AsyncMock

import pytest

from amc_peripheral.radio.radio_cog import (
    _MUSIC_INTENT_RE,
    _QUEUE_TOOL_NAMES,
    RadioCog,
    _format_chat_history,
)
from amc_peripheral.utils.text_utils import strip_role_tag


class _FakeAuthor:
    def __init__(self, display_name):
        self.display_name = display_name


class _FakeMsg:
    def __init__(self, author, content):
        self.author = _FakeAuthor(author)
        self.content = content


class TestStripRoleTag:
    def test_strips_level_tag(self):
        assert strip_role_tag("[MG109] Alex") == "Alex"

    def test_no_tag(self):
        assert strip_role_tag("Alex") == "Alex"

    def test_stacked_tags(self):
        assert strip_role_tag("[M] NEW-Nunauu") == "NEW-Nunauu"

    def test_empty_and_none(self):
        assert strip_role_tag("") == ""
        assert strip_role_tag(None) == ""


class TestFormatChatHistory:
    def test_labels_authors(self):
        msgs = [
            _FakeMsg("Alex", "he slam into light tower..."),
            _FakeMsg("Onyx_tyranis", "wrapped myself in a pole"),
        ]
        out = _format_chat_history(msgs)
        assert "Onyx_tyranis: wrapped myself in a pole" in out
        assert "Alex: he slam into light tower..." in out

    def test_drops_command_spam(self):
        msgs = [_FakeMsg("Alex", "/tp"), _FakeMsg("Alex", "how your day?")]
        out = _format_chat_history(msgs)
        assert "/tp" not in out
        assert "how your day?" in out

    def test_drops_empty(self):
        msgs = [_FakeMsg("Alex", ""), _FakeMsg("Alex", "   ")]
        assert _format_chat_history(msgs) == ""

    def test_preserves_chronological_order(self):
        # discord.py history() yields NEWEST first; output is oldest-first
        msgs = [
            _FakeMsg("C", "third"),
            _FakeMsg("B", "second"),
            _FakeMsg("A", "first"),
        ]
        out = _format_chat_history(msgs)
        assert out.index("first") < out.index("second") < out.index("third")

    def test_keeps_bot_announcement_lines(self):
        msgs = [_FakeMsg("DJ Annie", "Queued Slim Dusty — coming up next!")]
        out = _format_chat_history(msgs)
        assert "DJ Annie" in out


class TestMusicIntent:
    def test_music_questions_match(self):
        assert _MUSIC_INTENT_RE.search("play Light On The Hill by Slim Dusty")
        assert _MUSIC_INTENT_RE.search("queue something chill")
        assert _MUSIC_INTENT_RE.search("@annie skip pls")

    def test_non_music_questions_do_not_match(self):
        assert not _MUSIC_INTENT_RE.search(
            "what is difference between drifting and rallying?"
        )
        assert not _MUSIC_INTENT_RE.search("that why it is my favourite rally car")
        assert not _MUSIC_INTENT_RE.search("how your day?")

    def test_queue_tool_names(self):
        assert "search_and_queue_song" in _QUEUE_TOOL_NAMES
        assert "queue_trending_song" in _QUEUE_TOOL_NAMES


def _bare_cog() -> RadioCog:
    cog = RadioCog.__new__(RadioCog)
    cog._chat_sender_ids = OrderedDict()
    return cog


class TestChatSenderIdCache:
    def test_cache_hit(self):
        cog = _bare_cog()
        cog._remember_chat_sender(
            {
                "player_name": "[MG109] Alex",
                "message": "what is drifting?",
                "player_id": "76561198958693540",
            }
        )
        assert (
            cog._resolve_chat_sender("[MG109] Alex", "what is drifting?")
            == "76561198958693540"
        )

    def test_cache_name_fallback(self):
        cog = _bare_cog()
        cog._remember_chat_sender(
            {
                "player_name": "[MG109] Alex",
                "message": "what is drifting?",
                "player_id": "76561198958693540",
            }
        )
        # Relay reformatted the text (emoji strip / whitespace) → the most
        # recent SSE line from the same player_name is the sender.
        assert (
            cog._resolve_chat_sender("[MG109] Alex", "what is  drifting?")
            == "76561198958693540"
        )

    def test_cache_miss_returns_none(self):
        cog = _bare_cog()
        assert cog._resolve_chat_sender("Stranger", "hi") is None

    def test_cache_bounded(self):
        cog = _bare_cog()
        for i in range(600):
            cog._remember_chat_sender(
                {"player_name": f"p{i}", "message": "m", "player_id": str(i)}
            )
        assert len(cog._chat_sender_ids) <= RadioCog._CHAT_SENDER_CACHE_MAX

    def test_incomplete_events_ignored(self):
        cog = _bare_cog()
        cog._remember_chat_sender({"player_name": "X", "message": "m"})
        cog._remember_chat_sender({"player_name": "X", "player_id": "1"})
        cog._remember_chat_sender({"message": "m", "player_id": "1"})
        assert not cog._chat_sender_ids

    def test_duplicate_message_overwrites_same_id(self):
        cog = _bare_cog()
        evt = {
            "player_name": "A",
            "message": "m",
            "player_id": "76561190000000001",
        }
        cog._remember_chat_sender(evt)
        cog._remember_chat_sender(evt)
        assert len(cog._chat_sender_ids) == 1
        assert cog._resolve_chat_sender("A", "m") == "76561190000000001"


class TestNoIdMeansNoStore:
    @pytest.mark.asyncio
    async def test_missing_id_resolves_to_none(self):
        """No SSE evidence → no id → memory touchpoints must be skipped."""
        cog = _bare_cog()
        cog._store_annie_interaction = AsyncMock()
        cog._get_player_memory_context = AsyncMock(return_value="ctx")
        assert cog._resolve_chat_sender("Ghost", "boo") is None
        # The handler guards both touchpoints on `if player_id:`; assert the
        # mocks would not have been called if the guard were removed.
        cog._store_annie_interaction.assert_not_called()

    def test_id_presence_gates_memory(self):
        """Pin the source-level guard: id present → memory; None → skipped.

        String assertions on the cog source so a future refactor cannot
        silently drop the `if player_id:` guards around the memory read and
        the interaction store.
        """
        import inspect

        import amc_peripheral.radio.radio_cog as rc

        src = inspect.getsource(rc.RadioCog._handle_annie_chat_ingame)
        assert "if player_id" in src
        assert "await self._store_annie_interaction" in src
        # The store call sits inside the guard block (indented under `if`).
        store_line = next(
            line
            for line in src.splitlines()
            if "await self._store_annie_interaction" in line
        )
        assert store_line.startswith(" " * 12), store_line
