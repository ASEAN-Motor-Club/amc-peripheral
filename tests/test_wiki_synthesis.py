"""Tests for wiki weekly synthesis."""

import os
import tempfile
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import pytest

from amc_peripheral.wiki.retrieval import WikiRetrieval
from amc_peripheral.wiki.storage import WikiStorage
from amc_peripheral.wiki.synthesis import WikiSynthesizer


@pytest.fixture
def wiki_env():
    """Create a wiki storage + retrieval in a temp dir."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "wiki.db")
        chroma_path = os.path.join(tmpdir, "chromadb")

        storage = WikiStorage(db_path=db_path)
        retrieval = WikiRetrieval(path=chroma_path)
        yield storage, retrieval
        storage.close()


def _make_llm_mock(content: str):
    """Build an AsyncOpenAI-style mock that returns `content`."""
    choice = SimpleNamespace(message=SimpleNamespace(content=content))
    completion = SimpleNamespace(choices=[choice])
    create = AsyncMock(return_value=completion)

    client = MagicMock()
    client.chat = MagicMock()
    client.chat.completions = MagicMock()
    client.chat.completions.create = create
    return client, create


def _seed_recent_activity(storage: WikiStorage, when: datetime) -> dict:
    """Seed a few recently-updated pages + matching log entries."""
    pid = storage.create_page(
        title="player:freemanlatif",
        category="player",
        content="Frequent Gosan driver.",
        summary="Active this week.",
    )
    vid = storage.create_page(
        title="vehicle:Gosan_G7",
        category="vehicle",
        content="Community favourite.",
        summary="Popular truck.",
    )
    storage.log_operation(
        operation="ingest",
        description="Ingested conversation with freemanlatif",
        pages_affected=[pid, vid],
    )
    # Also seed an older entry that should NOT be in the window
    old_entry_id = storage.log_operation(
        operation="ingest",
        description="Older ingest",
        pages_affected=[pid],
    )
    old_ts = (when - timedelta(days=30)).isoformat()
    storage.conn.execute(
        "UPDATE wiki_log SET timestamp = ? WHERE id = ?",
        (old_ts, old_entry_id),
    )
    storage.conn.commit()
    return {"player_id": pid, "vehicle_id": vid}


@pytest.mark.asyncio
async def test_generate_weekly_synthesis_creates_page(wiki_env):
    storage, retrieval = wiki_env
    now = datetime(2026, 4, 27, 9, 0, 0)  # Monday
    _seed_recent_activity(storage, now)

    client, create = _make_llm_mock(
        "This week the community rallied around the Gosan G7. "
        "freemanlatif kept the logs busy."
    )
    synth = WikiSynthesizer(
        storage=storage, retrieval=retrieval, llm_client=client, model="test-model"
    )

    page = await synth.generate_weekly_synthesis(now=now)

    assert page is not None
    assert page["title"] == "synthesis:community-week-2026-W18"
    assert page["category"] == "synthesis"
    assert "Gosan" in page["content"]

    # LLM was actually invoked once
    create.assert_called_once()
    call_kwargs = create.call_args.kwargs
    assert call_kwargs["model"] == "test-model"
    messages = call_kwargs["messages"]
    # Prompt should reference the recent pages
    joined = "\n".join(m["content"] for m in messages)
    assert "player:freemanlatif" in joined
    assert "vehicle:Gosan_G7" in joined


@pytest.mark.asyncio
async def test_synthesis_cross_links_cited_pages(wiki_env):
    storage, retrieval = wiki_env
    now = datetime(2026, 4, 27, 9, 0, 0)
    ids = _seed_recent_activity(storage, now)

    client, _ = _make_llm_mock("Great week for everyone.")
    synth = WikiSynthesizer(storage, retrieval, client, "test-model")

    page = await synth.generate_weekly_synthesis(now=now)
    assert page is not None

    outbound = storage.get_links_from(page["id"])
    targets = {link["to_page_id"] for link in outbound}
    assert ids["player_id"] in targets
    assert ids["vehicle_id"] in targets
    # All links should be 'cites'
    assert all(link["link_type"] == "cites" for link in outbound)


@pytest.mark.asyncio
async def test_synthesis_upserts_existing_page(wiki_env):
    storage, retrieval = wiki_env
    now = datetime(2026, 4, 27, 9, 0, 0)
    _seed_recent_activity(storage, now)

    client_a, _ = _make_llm_mock("First pass.")
    synth_a = WikiSynthesizer(storage, retrieval, client_a, "test-model")
    page_a = await synth_a.generate_weekly_synthesis(now=now)

    client_b, _ = _make_llm_mock("Second pass, more detail.")
    synth_b = WikiSynthesizer(storage, retrieval, client_b, "test-model")
    page_b = await synth_b.generate_weekly_synthesis(now=now)

    assert page_a is not None and page_b is not None
    assert page_a["id"] == page_b["id"]
    assert page_b["content"] == "Second pass, more detail."


@pytest.mark.asyncio
async def test_synthesis_returns_none_when_no_activity(wiki_env):
    storage, retrieval = wiki_env
    now = datetime(2026, 4, 27, 9, 0, 0)
    # No pages, no log entries seeded

    client, create = _make_llm_mock("Shouldn't be called.")
    synth = WikiSynthesizer(storage, retrieval, client, "test-model")

    page = await synth.generate_weekly_synthesis(now=now)
    assert page is None
    create.assert_not_called()


@pytest.mark.asyncio
async def test_synthesis_returns_none_on_empty_llm_output(wiki_env):
    storage, retrieval = wiki_env
    now = datetime(2026, 4, 27, 9, 0, 0)
    _seed_recent_activity(storage, now)

    client, _ = _make_llm_mock("   ")
    synth = WikiSynthesizer(storage, retrieval, client, "test-model")

    page = await synth.generate_weekly_synthesis(now=now)
    assert page is None


@pytest.mark.asyncio
async def test_synthesis_excludes_previous_synthesis_pages(wiki_env):
    """Prior synthesis pages must not feed themselves into the next run."""
    storage, retrieval = wiki_env
    now = datetime(2026, 4, 27, 9, 0, 0)
    _seed_recent_activity(storage, now)
    # Seed an existing synthesis page to ensure it is filtered out of top_pages
    storage.create_page(
        title="synthesis:community-week-2026-W17",
        category="synthesis",
        content="Prior synthesis narrative.",
        summary="Last week.",
    )

    client, create = _make_llm_mock("Narrative output.")
    synth = WikiSynthesizer(storage, retrieval, client, "test-model")

    await synth.generate_weekly_synthesis(now=now)

    call_kwargs = create.call_args.kwargs
    joined = "\n".join(m["content"] for m in call_kwargs["messages"])
    assert "synthesis:community-week-2026-W17" not in joined


@pytest.mark.asyncio
async def test_synthesis_logs_operation(wiki_env):
    storage, retrieval = wiki_env
    now = datetime(2026, 4, 27, 9, 0, 0)
    _seed_recent_activity(storage, now)

    client, _ = _make_llm_mock("Summary text.")
    synth = WikiSynthesizer(storage, retrieval, client, "test-model")

    await synth.generate_weekly_synthesis(now=now)

    entries = storage.get_log_entries(operation="synthesis")
    assert entries
    assert "2026-W18" in entries[0]["description"]


@pytest.mark.asyncio
async def test_synthesis_handles_tz_aware_now(wiki_env):
    """The scheduled task passes a tz-aware `now` but DB timestamps are naive.

    Regression test for a TypeError when comparing tz-aware cutoff against
    naive `datetime.fromisoformat(db_ts)` in `_recent_ingest_log` /
    `_top_updated_pages`.
    """
    storage, retrieval = wiki_env
    aware_now = datetime(2026, 4, 27, 9, 0, 0, tzinfo=ZoneInfo("Asia/Bangkok"))
    # Seed activity based on the naive-equivalent time so DB timestamps land
    # within the 7-day window.
    _seed_recent_activity(storage, aware_now.replace(tzinfo=None))

    client, create = _make_llm_mock("Aware week narrative.")
    synth = WikiSynthesizer(storage, retrieval, client, "test-model")

    page = await synth.generate_weekly_synthesis(now=aware_now)

    # No TypeError, page written, LLM actually called
    assert page is not None
    assert page["title"] == "synthesis:community-week-2026-W18"
    create.assert_called_once()


def test_align_tz_helper_normalizes_both_directions():
    naive = datetime(2026, 4, 20, 12, 0, 0)
    aware = datetime(2026, 4, 20, 12, 0, 0, tzinfo=timezone.utc)

    # Naive -> aware to match aware reference
    out = WikiSynthesizer._align_tz(naive, aware)
    assert out.tzinfo is not None
    # Aware -> naive to match naive reference
    out = WikiSynthesizer._align_tz(aware, naive)
    assert out.tzinfo is None
    # Same-kind: unchanged
    assert WikiSynthesizer._align_tz(naive, naive) == naive
    assert WikiSynthesizer._align_tz(aware, aware) == aware
