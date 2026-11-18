"""Decal-similarity index and its item-page presentation."""

from __future__ import annotations

import sqlite3

from amc_peripheral.workshop.queries import WorkshopRepository
from amc_peripheral.workshop.similarity import build, greedy_dice, matched_similarity

from workshop_support import _payload, seed_similarity


async def test_item_page_flags_earlier_identical_build(client):
    response = await client.get("/workshop/items/1/")
    assert response.status == 200
    text = await response.text()
    assert "Potential copy of another workshop item" in text
    assert "/workshop/items/3/" in text
    assert "2025-05-01" in text
    assert "100% match" in text
    # the flagged original is also part of the gallery
    assert 'id="similar-builds"' in text


async def test_earlier_item_is_not_flagged_but_still_lists_the_match(client):
    response = await client.get("/workshop/items/3/")
    assert response.status == 200
    text = await response.text()
    assert "Potential copy of another workshop item" not in text
    assert "Similar builds" in text
    assert "/workshop/items/1/" in text


async def test_item_without_matches_hides_the_gallery(client):
    response = await client.get("/workshop/items/2/")
    assert response.status == 200
    text = await response.text()
    assert "Similar builds" not in text
    assert "Potential copy" not in text


async def test_hidden_matches_never_reach_the_page(client):
    response = await client.get("/workshop/items/1/")
    text = await response.text()
    assert "Hidden" not in text
    assert "/workshop/items/5/" not in text


def test_similar_items_reports_origin_only_for_older_matches(settings):
    repository = WorkshopRepository(
        settings.source_db, site_db=settings.site_db, cache_ttl=0
    )
    later = repository.similar_items({"id": 3, "vehicleKey": "Vamos3",
                                      "createdAt": "2025-05-01 00:00:00"})
    assert later["flagged"] is False
    assert later["origin"] is None
    assert [item["id"] for item in later["items"]] == [1]
    assert later["items"][0]["isEarlier"] is False

    copy = repository.similar_items({"id": 1, "vehicleKey": "Vamos3",
                                     "createdAt": "2026-11-15 12:00:00"})
    assert copy["flagged"] is True
    assert copy["origin"]["id"] == 3
    assert copy["originSimilarity"] == 1.0


def test_similar_items_ignores_index_rows_below_the_minimum(settings, tmp_path):
    site = tmp_path / "site-low.db"
    seed_similarity(site, [
        ("Vamos3", 1, 3, 0.42, "2026-11-15 12:00:00", "2025-05-01 00:00:00"),
    ])
    repository = WorkshopRepository(settings.source_db, site_db=site, cache_ttl=0)
    result = repository.similar_items({"id": 1, "vehicleKey": "Vamos3",
                                       "createdAt": "2026-11-15 12:00:00"})
    assert result["items"] == []
    assert result["flagged"] is False


def test_build_index_detects_duplicate_payloads(tmp_path):
    """Rows sharing a payload on one vehicle must pair at ~1.0."""
    from workshop_support import build_fixture_db

    source = tmp_path / "src.db"
    build_fixture_db(source)
    conn = sqlite3.connect(source)
    # The fixture payload carries one decal layer; the column says otherwise.
    conn.execute("UPDATE workshop SET has_decal = 1, decal_layers = 1 WHERE id IN (1, 3)")
    conn.commit()
    conn.close()

    site = tmp_path / "built-site.db"
    result = build(source, site, min_layers=1)
    assert result["pairs"] >= 1

    conn = sqlite3.connect(site)
    rows = conn.execute(
        "SELECT vehicle_key, a, b, sim FROM similar_pair ORDER BY a, b"
    ).fetchall()
    conn.close()
    pairs = {(a, b): sim for _vehicle, a, b, sim in rows}
    assert (1, 3) in pairs and pairs[(1, 3)] > 0.99
    # hidden (5) and non-public rows must never be indexed
    assert all(5 not in (a, b) for a, b in pairs)


def test_matching_penalises_extra_and_removed_layers():
    base = {
        "key": "Numbers_01_014-number_1", "rgb": (0, 0, 0), "x": 10.0, "y": 20.0,
        "pitch": 0.0, "yaw": 90.0, "roll": 0.0, "scale": 1.0, "stretch": 1.0,
        "flags": 10,
    }
    extra = {**base, "key": "Flame_01_Flame54", "x": 40.0}
    assert matched_similarity([base], [base]) > 0.99
    # one identical layer kept, one added: Dice must land near two thirds
    assert 0.6 < matched_similarity([base, extra], [base]) < 0.75
    assert greedy_dice([base, extra], [base]) > 0.6


def test_payload_roundtrip_matches_fixture_layers():
    from amc_peripheral.workshop.similarity import _layers_from_payload

    layers = _layers_from_payload(_payload())
    assert len(layers) == 1
    assert layers[0]["key"] == "Numbers_01_077-76"
    assert layers[0]["rgb"] == (255, 0, 0)
