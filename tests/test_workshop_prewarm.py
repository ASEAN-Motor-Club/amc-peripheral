"""Prewarm ordering: popularity bands and scanning past already-rendered items."""

from __future__ import annotations

from pathlib import Path

import pytest

from amc_peripheral.workshop.aggregate import (
    _popular_candidates,
    prewarm_popular,
    rank_priority,
)
from amc_peripheral.workshop.config import WorkshopSettings
from amc_peripheral.workshop.snapshots import (
    PRIORITY_POPULAR,
    SnapshotJob,
    SnapshotStore,
    render_key,
)


def _settings(tmp_path: Path, **overrides) -> WorkshopSettings:
    viewer = tmp_path / "vehicles"
    viewer.mkdir(exist_ok=True)
    return WorkshopSettings(
        source_db=tmp_path / "source.db",
        site_db=tmp_path / "site.db",
        viewer_root=viewer,
        snapshot_root=tmp_path / "snapshots",
        **overrides,
    )


def _card(item_id: int, vehicle: str = "hana") -> dict:
    return {
        "id": item_id,
        "vehicleKey": vehicle,
        "configHash": "c" * 64,
    }


def _touch_manifest(settings: WorkshopSettings, vehicle: str) -> None:
    slug = vehicle.lower().replace(" ", "-")
    directory = settings.viewer_root / slug
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{slug}.json").write_text("{}", encoding="utf-8")


class FakeRepo:
    def __init__(self, cards: list[dict]) -> None:
        self.cards = cards
        self.calls: list[tuple[int, int]] = []

    def list_items(self, *, sort: str, limit: int, offset: int = 0) -> dict:
        assert sort == "popular"
        self.calls.append((offset, limit))
        return {"items": self.cards[offset : offset + limit]}


@pytest.mark.parametrize(
    ("rank", "expected"),
    [
        (0, PRIORITY_POPULAR + 40),
        (24, PRIORITY_POPULAR + 40),
        (25, PRIORITY_POPULAR + 30),
        (99, PRIORITY_POPULAR + 30),
        (100, PRIORITY_POPULAR + 20),
        (499, PRIORITY_POPULAR + 20),
        (500, PRIORITY_POPULAR + 10),
        (1_999, PRIORITY_POPULAR + 10),
        (2_000, PRIORITY_POPULAR),
    ],
)
def test_rank_priority_bands(rank: int, expected: int) -> None:
    assert rank_priority(rank) == expected


def test_every_band_stays_below_visible_priority() -> None:
    # A real page view must still jump the speculative queue.
    from amc_peripheral.workshop.snapshots import PRIORITY_VISIBLE

    assert rank_priority(0) < PRIORITY_VISIBLE


def test_candidates_walk_the_popularity_order_in_pages() -> None:
    repo = FakeRepo([_card(i) for i in range(130)])

    seen = [(rank, card["id"]) for rank, card in _popular_candidates(repo, 130)]

    assert seen[0] == (0, 0)
    assert seen[-1] == (129, 129)
    assert len(seen) == 130
    assert all(limit <= 60 for _, limit in repo.calls)


def test_candidates_stop_at_the_scan_limit() -> None:
    repo = FakeRepo([_card(i) for i in range(50)])

    assert len(list(_popular_candidates(repo, 10))) == 10


def test_prewarm_scans_past_items_that_already_have_a_snapshot(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path, prewarm_limit=2, prewarm_queue_limit=50)
    _touch_manifest(settings, "hana")
    repo = FakeRepo([_card(i) for i in range(1, 7)])

    # The two most popular items are already rendered.
    store = SnapshotStore(settings.site_db)
    for item_id in (1, 2):
        key = render_key(
            source_kind="workshop",
            source_id=item_id,
            config_hash="c" * 64,
            asset_version=_version(settings),
        )
        store.enqueue(
            SnapshotJob(
                cache_key=key,
                source_kind="workshop",
                source_id=item_id,
                config_hash="c" * 64,
                asset_version=_version(settings),
                camera="default",
                priority=PRIORITY_POPULAR,
            )
        )
        store.complete(
            key,
            artifact_path=f"items/aa/{key}.webp",
            width=960,
            height=540,
            size=1024,
            sha256="0" * 64,
        )

    enqueued = prewarm_popular(settings, {"popular": []}, repo)  # type: ignore[arg-type]

    assert enqueued == 2
    queued = _queued_sources(settings)
    assert queued == {3, 4}, "should have moved past the rendered head"


def test_prewarm_respects_the_queue_budget(tmp_path: Path) -> None:
    settings = _settings(tmp_path, prewarm_limit=48, prewarm_queue_limit=1)
    _touch_manifest(settings, "hana")
    repo = FakeRepo([_card(i) for i in range(1, 11)])

    assert prewarm_popular(settings, {"popular": []}, repo) == 1  # type: ignore[arg-type]


def _version(settings: WorkshopSettings) -> str:
    from amc_peripheral.workshop.payloads import asset_version_for

    return asset_version_for(settings.viewer_root, "hana")


def _queued_sources(settings: WorkshopSettings) -> set[int]:
    import sqlite3

    with sqlite3.connect(settings.site_db) as conn:
        return {
            int(row[0])
            for row in conn.execute(
                "SELECT source_id FROM snapshot_jobs "
                "WHERE status IN ('pending','retry_pending')"
            )
        }
