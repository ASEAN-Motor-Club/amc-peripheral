"""Tests for amc_peripheral.bot.wiki_kb (DokuWiki page-store knowledge reader)."""

import pytest

from amc_peripheral.bot import wiki_kb

# Fixture page store: minimal vehicles/cargos/parts/delivery_points pages that
# mirror the real DokuWiki structure (main page + sub-pages + [[link|Label]]
# markup + ^/| tables).


@pytest.fixture
def page_store(tmp_path, monkeypatch):
    pages = tmp_path / "pages"
    # vehicles/tuscan
    v = pages / "vehicles" / "tuscan"
    (pages / "vehicles").mkdir(parents=True)
    v.mkdir()
    (v / "auto_infobox.txt").write_text(
        "{{infobox>\nname = Tuscan\nType = Small\nCost = 10,000\n}}\n",
        encoding="utf-8",
    )
    (v / "auto_details.txt").write_text(
        "===== Specifications =====\n"
        "^ Stat ^ Value ^\n"
        "| Engine | [[parts:smallblock_140hp|V8 140HP]] (140 HP) |\n"
        "| Drivetrain | Rear-wheel drive |\n"
        "\n"
        "===== Capabilities =====\n"
        "  * Taxi\n",
        encoding="utf-8",
    )
    (pages / "vehicles" / "tuscan.txt").write_text(
        "{{page>vehicles:tuscan:auto_infobox&nodate&nomdate}}\n\n"
        "====== Tuscan ======\n\n**Tuscan** is a small vehicle in Motor Town.\n",
        encoding="utf-8",
    )
    # cargos/steelcoil
    c = pages / "cargos" / "steelcoil_10t"
    (pages / "cargos").mkdir(parents=True)
    c.mkdir()
    (c / "auto_infobox.txt").write_text(
        "{{infobox>\nname = Steel Coil\nCargo Type = None\nVolume = 14\nWeight = 14,000 kg\n}}\n",
        encoding="utf-8",
    )
    (c / "auto_details.txt").write_text(
        "===== Specifications =====\n"
        "^ Stat ^ Value ^\n"
        "| Fragile | No |\n"
        "\n"
        "===== Production =====\n"
        "\n"
        "==== Produced At ====\n"
        "^ Location ^ Inputs ^ Time ^\n"
        "| [[delivery_points:steel_mill|Steel Mill]] | 5x [[cargos:coal|Coal]] | 2m |\n",
        encoding="utf-8",
    )
    (pages / "cargos" / "steelcoil_10t.txt").write_text(
        "{{page>cargos:steelcoil_10t:auto_infobox&nodate&nomdate}}\n\n"
        "====== Steel Coil ======\n",
        encoding="utf-8",
    )
    # parts/101
    (pages / "parts").mkdir(parents=True)
    (pages / "parts" / "101.txt").write_text(
        "====== 2.73 (Final Drive Ratio) ======\n",
        encoding="utf-8",
    )
    (pages / "parts" / "101").mkdir()
    (pages / "parts" / "101" / "auto_infobox.txt").write_text(
        "{{infobox>\nname = 2.73\nPart Type = Final Drive Ratio\nCost = 500\n}}\n",
        encoding="utf-8",
    )
    (pages / "parts" / "101" / "auto_details.txt").write_text(
        "===== Stats =====\n\n==== Final Drive Ratio ====\n"
        "^ Stat ^ Value ^\n| Final Drive Ratio | 2.73 |\n",
        encoding="utf-8",
    )
    # delivery_points
    (pages / "delivery_points").mkdir(parents=True)
    (pages / "delivery_points" / "1100_rest_area.txt").write_text(
        "====== 1100 Rest Area ======\n",
        encoding="utf-8",
    )
    (pages / "delivery_points" / "1100_rest_area").mkdir()
    (pages / "delivery_points" / "1100_rest_area" / "auto_infobox.txt").write_text(
        "{{infobox>\nname = 1100 Rest Area\nLocation = Jeju\n}}\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(wiki_kb, "WIKI_PAGES_PATH", str(pages))
    # reset the module-level index cache
    monkeypatch.setattr(wiki_kb, "_INDEX", None)
    return pages


def test_lookup_vehicle(page_store):
    r = wiki_kb.lookup_vehicle("tuscan")
    assert "error" not in r
    assert r["name"] == "Tuscan"
    assert r["infobox"]["Cost"] == "10,000"
    spec = r["details"]["Specifications"]
    assert spec[0]["Stat"] == "Engine"
    # [[parts:smallblock_140hp|V8 140HP]] -> V8 140HP
    assert spec[0]["Value"] == "V8 140HP (140 HP)"
    assert r["details"]["Capabilities"] == ["Taxi"]


def test_lookup_vehicle_fuzzy_substring(page_store):
    r = wiki_kb.lookup_vehicle("tuscanZZ")  # meaningful substring "tuscan"
    # expecting a hit via substring on slug/name
    assert "error" not in r


def test_lookup_vehicle_miss(page_store):
    r = wiki_kb.lookup_vehicle("zzz_nonexistent")
    assert "error" in r


def test_lookup_cargo_production_subheadings(page_store):
    r = wiki_kb.lookup_cargo("steel coil")
    assert "error" not in r
    assert r["name"] == "Steel Coil"
    prod = r["details"]["Production"]
    # Produced At is a nested sub-heading with a table; link-label cleaned
    produced = prod["Produced At"]
    assert produced[0]["Location"] == "Steel Mill"
    # link-cleaned cell: "5x Coal"
    assert "Coal" in produced[0]["Inputs"]


def test_lookup_part(page_store):
    r = wiki_kb.lookup_part("2.73")
    assert "error" not in r
    assert r["infobox"]["Part Type"] == "Final Drive Ratio"
    # nested sub-heading ==== Final Drive Ratio ==== under the Stats section
    stats = r["details"]["Stats"]
    assert isinstance(stats, dict)
    row = stats["Final Drive Ratio"][0]
    assert row["Value"] == "2.73"


def test_lookup_delivery_point(page_store):
    r = wiki_kb.lookup_delivery_point("1100 rest area")
    assert "error" not in r
    assert r["infobox"]["Location"] == "Jeju"


def test_compare_vehicles_drops_misses(page_store):
    out = wiki_kb.compare_vehicles(["tuscan", "zzz_missing"])
    assert len(out) == 1
    assert out[0]["name"] == "Tuscan"


def test_validate_schema_true(page_store):
    assert wiki_kb.validate_schema() is True
