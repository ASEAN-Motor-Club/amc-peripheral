"""Tests for the idle-chitchat loop gating and prompt building.

The tasks.loop object can't be awaited directly, so the gating logic is
tested through the cog's mocked environment by driving the real coroutine
hidden in the Loop object (coro()).
"""

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest


def _msg(author_name: str, content: str, minutes_ago: float):
    m = MagicMock()
    m.author.name = author_name
    m.author = MagicMock()
    m.author.name = author_name
    m.content = content
    m.created_at = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    return m


async def _history(msgs):
    for m in msgs:
        yield m


@pytest.fixture
def mod():
    from amc_peripheral.radio import radio_cog as mod

    return mod


@pytest.mark.asyncio
async def test_player_chat_blocks_chitchat(mod):
    """Relayed player chat inside the window → no chitchat."""
    cog = MagicMock()
    cog.ANNIE_IDLE_CHITCHAT_INTERVAL_MINUTES = 30

    ch = MagicMock()
    ch.history = MagicMock(
        return_value=_history(
            [
                _msg("AMC Server", "**freeman:** hello everyone", 5),
                _msg("AMC Server", "📢 New job posting! See /jobs", 4),
            ]
        )
    )
    cog.bot = MagicMock()
    cog.bot.get_channel = MagicMock(return_value=ch)

    called = {"v": False}

    async def fake_chitchat():
        called["v"] = True

    with patch.object(mod.RadioCog, "_annie_idle_chitchat", new=fake_chitchat):
        bound = mod.RadioCog.__dict__["annie_idle_chitchat"].coro.__get__(cog)
        await bound()

    assert not called["v"]


@pytest.mark.asyncio
async def test_no_channel_is_safe(mod):
    """No game-chat channel configured → early return, no crash."""
    cog = MagicMock()
    cog.ANNIE_IDLE_CHITCHAT_INTERVAL_MINUTES = 30
    cog.bot = MagicMock()
    cog.bot.get_channel = MagicMock(return_value=None)

    bound = mod.RadioCog.__dict__["annie_idle_chitchat"].coro.__get__(cog)
    await bound()  # must not raise


@pytest.mark.asyncio
async def test_old_chat_only_triggers_path(mod):
    """Only old player chat (outside window) → gate opens; DB check runs.

    We let it reach the DB check and fail it with an exception — the gate
    returns on failure, so the assert is that _annie_idle_chitchat was NOT
    called but the DB was consulted (via mock).
    """
    cog = MagicMock()
    cog.ANNIE_IDLE_CHITCHAT_INTERVAL_MINUTES = 30

    ch = MagicMock()
    ch.history = MagicMock(
        return_value=_history(
            [
                _msg("AMC Server", "**freeman:** hello", 60),  # 1h old
            ]
        )
    )
    cog.bot = MagicMock()
    cog.bot.get_channel = MagicMock(return_value=ch)

    called = {"v": False}

    async def fake_chitchat():
        called["v"] = True

    db_mod = MagicMock()
    db_mod.execute_query = MagicMock(side_effect=RuntimeError("db down"))

    with (
        patch.object(mod.RadioCog, "_annie_idle_chitchat", new=fake_chitchat),
        patch.dict(
            "sys.modules",
            {
                "amc_peripheral.bot": MagicMock(backend_db=db_mod),
                "amc_peripheral.bot.backend_db": db_mod,
            },
        ),
    ):
        bound = mod.RadioCog.__dict__["annie_idle_chitchat"].coro.__get__(cog)
        await bound()

    assert not called["v"]  # DB failed → gate returns
    assert db_mod.execute_query.called  # but the DB was consulted
