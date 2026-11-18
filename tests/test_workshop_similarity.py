"""Decal-similarity index and its item-page presentation."""

from __future__ import annotations

import sqlite3

from amc_peripheral.workshop.queries import WorkshopRepository
from amc_peripheral.workshop.similarity import (
    _mirror_layer,
    _transformed_similarity,
    build,
    greedy_dice,
    matched_similarity,
    pair_token_set,
)

from workshop_support import _payload, build_fixture_db, seed_similarity


async def test_item_page_does_not_flag_same_author_work(client):
    response = await client.get("/workshop/items/1/")
    assert response.status == 200
    text = await response.text()
    assert "Potential copy of another workshop item" not in text
    assert "/workshop/items/3/" in text
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
    later = repository.similar_items(
        {
            "id": 3,
            "vehicleKey": "Vamos3",
            "createdAt": "2025-05-01 00:00:00",
            "decalLayers": 8,
        }
    )
    assert later["flagged"] is False
    assert later["origin"] is None
    assert [item["id"] for item in later["items"]] == [1]
    assert later["items"][0]["isEarlier"] is False

    same_author = repository.similar_items(
        {
            "id": 1,
            "vehicleKey": "Vamos3",
            "createdAt": "2026-11-15 12:00:00",
            "decalLayers": 9,
            "accountId": 11,
        }
    )
    assert same_author["flagged"] is False
    assert same_author["origin"] is None
    assert [item["id"] for item in same_author["items"]] == [3]

    copy = repository.similar_items(
        {
            "id": 1,
            "vehicleKey": "Vamos3",
            "createdAt": "2026-11-15 12:00:00",
            "decalLayers": 9,
            "accountId": 99,
        }
    )
    assert copy["flagged"] is True
    assert copy["origin"]["id"] == 3
    assert copy["originSimilarity"] == 1.0


def test_copy_flag_requires_enough_layers(settings):
    repository = WorkshopRepository(
        settings.source_db, site_db=settings.site_db, cache_ttl=0
    )
    result = repository.similar_items(
        {
            "id": 1,
            "vehicleKey": "Vamos3",
            "createdAt": "2026-11-15 12:00:00",
            "decalLayers": 7,
        }
    )
    assert result["flagged"] is False
    assert [item["id"] for item in result["items"]] == [3]


def test_copy_flag_requires_high_similarity(settings, tmp_path):
    site = tmp_path / "site-096.db"
    seed_similarity(
        site,
        [
            (
                "Vamos3",
                1,
                3,
                0.96,
                "2026-11-15 12:00:00",
                "2025-05-01 00:00:00",
            ),
        ],
    )
    repository = WorkshopRepository(settings.source_db, site_db=site, cache_ttl=0)
    result = repository.similar_items(
        {
            "id": 1,
            "vehicleKey": "Vamos3",
            "createdAt": "2026-11-15 12:00:00",
            "decalLayers": 9,
        }
    )
    assert result["flagged"] is False
    assert [item["id"] for item in result["items"]] == [3]


def test_similar_items_ignores_index_rows_below_the_minimum(settings, tmp_path):
    site = tmp_path / "site-low.db"
    seed_similarity(
        site,
        [
            ("Vamos3", 1, 3, 0.42, "2026-11-15 12:00:00", "2025-05-01 00:00:00"),
        ],
    )
    repository = WorkshopRepository(settings.source_db, site_db=site, cache_ttl=0)
    result = repository.similar_items(
        {"id": 1, "vehicleKey": "Vamos3", "createdAt": "2026-11-15 12:00:00"}
    )
    assert result["items"] == []
    assert result["flagged"] is False


def test_build_index_detects_duplicate_payloads(tmp_path):
    """Rows sharing a payload on one vehicle must pair at ~1.0."""
    from workshop_support import build_fixture_db

    source = tmp_path / "src.db"
    build_fixture_db(source)
    conn = sqlite3.connect(source)
    # The fixture payload carries one decal layer; the column says otherwise.
    conn.execute(
        "UPDATE workshop SET has_decal = 1, decal_layers = 1 WHERE id IN (1, 3)"
    )
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


def test_incremental_build_only_scores_changed_items(tmp_path):
    """A new upload must not force a rebuild of unchanged pairs."""
    source = tmp_path / "src.db"
    build_fixture_db(source)
    conn = sqlite3.connect(source)
    conn.execute(
        "UPDATE workshop SET has_decal = 1, decal_layers = 1 WHERE id IN (1, 3)"
    )
    conn.commit()

    site = tmp_path / "site.db"
    first = build(source, site, min_layers=1)
    assert first["changed"] == 3
    assert first["stale"] == 0

    names = [row[1] for row in conn.execute("PRAGMA table_info(workshop)")]
    row = dict(
        zip(names, conn.execute("SELECT * FROM workshop WHERE id = 1").fetchone())
    )
    row.update(id=7, json_sha256="f" * 64, created_at="2024-02-01 00:00:00")
    conn.execute(
        f"INSERT INTO workshop ({','.join(names)}) VALUES "
        f"({','.join('?' for _ in names)})",
        [row[name] for name in names],
    )
    conn.commit()
    conn.close()

    second = build(source, site, min_layers=1)
    assert second["changed"] == 1
    assert second["stale"] == 0

    conn = sqlite3.connect(site)
    pairs = conn.execute("SELECT a, b FROM similar_pair ORDER BY a, b").fetchall()
    assert (1, 3) in pairs
    assert (1, 7) in pairs
    assert (3, 7) in pairs
    conn.close()

    conn = sqlite3.connect(source)
    conn.execute("UPDATE workshop SET hidden = 1 WHERE id = 7")
    conn.commit()
    conn.close()

    third = build(source, site, min_layers=1)
    assert third["changed"] == 0
    assert third["stale"] == 1

    conn = sqlite3.connect(site)
    assert conn.execute("SELECT a, b FROM similar_pair ORDER BY a, b").fetchall() == [
        (1, 3)
    ]
    assert conn.execute(
        "SELECT workshop_id FROM similar_item ORDER BY workshop_id"
    ).fetchall() == [
        (1,),
        (2,),
        (3,),
    ]
    conn.close()


def test_parallel_build_matches_serial(tmp_path):
    source = tmp_path / "src.db"
    build_fixture_db(source)
    conn = sqlite3.connect(source)
    conn.execute(
        "UPDATE workshop SET has_decal = 1, decal_layers = 1 WHERE id IN (1, 3)"
    )
    conn.commit()
    conn.close()

    serial = tmp_path / "serial.db"
    parallel = tmp_path / "parallel.db"
    build(source, serial, min_layers=1)
    build(source, parallel, min_layers=1, workers=2)

    def rows(path):
        conn = sqlite3.connect(path)
        try:
            return conn.execute(
                "SELECT vehicle_key, a, b, sim FROM similar_pair ORDER BY vehicle_key, a, b"
            ).fetchall()
        finally:
            conn.close()

    assert rows(parallel) == rows(serial)


def test_pair_hash_scores_transformed_copies():
    base = [
        _test_layer("Numbers_01_014-number_1", 10, 20),
        _test_layer("Flame_01_Flame54", 40, 20, yaw=10),
        _test_layer("Shape_01_Shape2", 25, 50, yaw=90),
        _test_layer("Stripe_01_Stripe7", 70, 60),
    ]

    def shifted(dx=0.0, dy=0.0, dyaw=0.0, scale=1.0):
        out = [dict(layer) for layer in base]
        for layer in out:
            layer["x"] += dx
            layer["y"] += dy
            layer["yaw"] = (layer["yaw"] + dyaw) % 360.0
            layer["scale"] *= scale
        return out

    variants = {
        "drag": shifted(40, 40),
        "rotate": shifted(dyaw=12),
        "scale": shifted(scale=1.15),
        "mirror": [_mirror_layer(layer) for layer in base],
    }
    for name, other in variants.items():
        shared = pair_token_set(base) & pair_token_set(other)
        assert len(shared) >= 3, name
        assert _transformed_similarity(base, other, shared) > 0.95, name


def _test_layer(key, x, y, yaw=0.0):
    return {
        "key": key,
        "rgb": (100, 100, 100),
        "alpha": 255.0,
        "coverage": 1.0,
        "x": x,
        "y": y,
        "pitch": 0.0,
        "yaw": yaw,
        "roll": 0.0,
        "scale": 1.0,
        "stretch": 1.0,
        "flags": 10,
    }


def test_alpha_and_coverage_affect_similarity():
    base = _test_layer("Numbers_01_014-number_1", 10, 20)
    dim = {**base, "alpha": 127.0}
    covered = {**base, "coverage": 0.5}
    assert matched_similarity([base], [dim]) < 0.99
    assert matched_similarity([base], [covered]) < 0.99


def test_matching_penalises_extra_and_removed_layers():
    base = {
        "key": "Numbers_01_014-number_1",
        "rgb": (0, 0, 0),
        "x": 10.0,
        "y": 20.0,
        "pitch": 0.0,
        "yaw": 90.0,
        "roll": 0.0,
        "scale": 1.0,
        "stretch": 1.0,
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
