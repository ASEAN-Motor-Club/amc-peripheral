"""Tests for the idle-chitchat loop gating.

The tasks.loop object can't be awaited directly, so the gating logic is
tested by driving the real coroutine hidden in the Loop object (coro()).
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest


def _msg(author_name: str, content: str, minutes_ago: float):
    m = MagicMock()
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


def _cog(history_msgs=None):
    cog = MagicMock()
    cog.ANNIE_IDLE_CHITCHAT_INTERVAL_MINUTES = 15
    cog._last_idle_chitchat_at = None

    ch = MagicMock()
    ch.history = MagicMock(return_value=_history(history_msgs or []))
    cog.bot = MagicMock()
    cog.bot.get_channel = MagicMock(return_value=ch)
    return cog


def _bind_and_run(mod, cog):
    bound = mod.RadioCog.__dict__["annie_idle_chitchat"].coro.__get__(cog)
    return bound()


def _db(results):
    db_mod = MagicMock()
    db_mod.execute_query = MagicMock(return_value=results)
    return db_mod


def _db_ctx(db_mod):
    return patch.dict(
        "sys.modules",
        {
            "amc_peripheral.bot": MagicMock(backend_db=db_mod),
            "amc_peripheral.bot.backend_db": db_mod,
        },
    )


@pytest.mark.asyncio
async def test_player_chat_blocks_chitchat(mod):
    """Relayed player chat inside the window → no chitchat."""
    cog = _cog(
        [
            _msg("AMC Server", "**freeman:** hello everyone", 5),
            _msg("AMC Server", "📢 New job posting! See /jobs", 4),
        ]
    )

    called = {"v": False}

    async def fake_chitchat():
        called["v"] = True

    cog._annie_idle_chitchat = fake_chitchat

    with _db_ctx(_db({"results": [{"n": 0}]})):
        await _bind_and_run(mod, cog)

    assert not called["v"]


@pytest.mark.asyncio
async def test_no_channel_is_safe(mod):
    """No game-chat channel configured → early return, no crash."""
    cog = _cog()
    cog.bot.get_channel = MagicMock(return_value=None)

    await _bind_and_run(mod, cog)  # must not raise


@pytest.mark.asyncio
async def test_db_gate_runs_when_relay_quiet(mod):
    """Only old player chat (outside window) → gate opens; DB check runs.

    The DB check fails with an exception and the gate returns on failure:
    _annie_idle_chitchat must NOT run, but the DB must have been consulted
    with the configured interval.
    """
    cog = _cog([_msg("AMC Server", "**freeman:** hello", 60)])  # 1h old

    called = {"v": False}

    async def fake_chitchat():
        called["v"] = True

    cog._annie_idle_chitchat = fake_chitchat

    db_mod = MagicMock()
    db_mod.execute_query = MagicMock(side_effect=RuntimeError("db down"))

    with _db_ctx(db_mod):
        await _bind_and_run(mod, cog)

    assert not called["v"]  # DB failed → gate returns
    assert db_mod.execute_query.called  # but the DB was consulted
    sql = db_mod.execute_query.call_args[0][0]
    assert "15 minutes" in sql  # interval comes from the class constant


@pytest.mark.asyncio
async def test_db_silence_fires_chitchat(mod):
    """DB reports zero chat rows in the window → chitchat fires."""
    cog = _cog([])  # nothing in relay history

    called = {"v": False}

    async def fake_chitchat():
        called["v"] = True

    cog._annie_idle_chitchat = fake_chitchat

    with _db_ctx(_db({"results": [{"n": 0}]})):
        await _bind_and_run(mod, cog)

    assert called["v"]
    # Timestamp recorded for the self-talk guard
    assert cog._last_idle_chitchat_at is not None


@pytest.mark.asyncio
async def test_recent_chitchat_suppresses_repeat(mod):
    """Self-talk guard: chitchat fired < 2x interval ago → no repeat."""
    cog = _cog([])
    cog._last_idle_chitchat_at = datetime.now(timezone.utc) - timedelta(
        minutes=20  # > 15min interval, < 2x interval
    )

    called = {"v": False}

    async def fake_chitchat():
        called["v"] = True

    cog._annie_idle_chitchat = fake_chitchat

    with _db_ctx(_db({"results": [{"n": 0}]})):
        await _bind_and_run(mod, cog)

    assert not called["v"]


@pytest.mark.asyncio
async def test_annie_ping_does_not_block_chitchat(mod):
    """A player→Annie ping inside the window does NOT suppress chitchat —
    pings are handled by the regular chat handler, not the idle loop.

    (Regression guard: '@annie' exclusion in the relayed-chat filter.)
    """
    cog = _cog([_msg("AMC Server", "**freeman:** @annie play something", 3)])

    called = {"v": False}

    async def fake_chitchat():
        called["v"] = True

    cog._annie_idle_chitchat = fake_chitchat

    with _db_ctx(_db({"results": [{"n": 0}]})):
        await _bind_and_run(mod, cog)

    assert called["v"]
