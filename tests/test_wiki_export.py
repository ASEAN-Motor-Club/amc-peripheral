"""Tests for wiki markdown export."""

import os
import re
import tempfile

import pytest

from amc_peripheral.wiki.export import WikiExporter
from amc_peripheral.wiki.storage import WikiStorage


@pytest.fixture
def storage():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "wiki.db")
        s = WikiStorage(db_path=db_path)
        yield s
        s.close()


@pytest.fixture
def exporter(storage):
    # Skip ChromaDB dependency by passing storage only; WikiExporter will
    # construct its own WikiIndex which only needs storage.
    return WikiExporter(storage)


def _seed_basic_pages(storage: WikiStorage) -> dict:
    """Create a small cross-linked wiki for use in tests."""
    player_id = storage.create_page(
        title="player:freemanlatif",
        category="player",
        content="Plays the Gosan G7 a lot.",
        summary="Frequent Gosan driver.",
    )
    vehicle_id = storage.create_page(
        title="vehicle:Gosan_G7",
        category="vehicle",
        content="A popular truck in ASEAN Motor Club.",
        summary="Favourite truck.",
    )
    concept_id = storage.create_page(
        title="concept:steel-coil-curse",
        category="concept",
        content="Steel coils are notoriously hard to deliver.",
        summary="Hard cargo.",
    )
    storage.add_link(player_id, vehicle_id, "mentions")
    storage.add_link(player_id, concept_id, "mentions")
    storage.add_source(player_id, "conversation", "test-src-1")
    storage.log_operation(
        operation="ingest",
        description="Seeded test fixture",
        pages_affected=[player_id, vehicle_id, concept_id],
    )
    return {
        "player_id": player_id,
        "vehicle_id": vehicle_id,
        "concept_id": concept_id,
    }


def test_export_creates_expected_layout(exporter, storage, tmp_path):
    _seed_basic_pages(storage)
    out_dir = str(tmp_path / "export")

    summary = exporter.export_all(out_dir)

    assert summary["pages_exported"] == 3
    assert os.path.isdir(out_dir)
    assert os.path.isfile(os.path.join(out_dir, "index.md"))
    assert os.path.isfile(os.path.join(out_dir, "log.md"))
    assert os.path.isdir(os.path.join(out_dir, "players"))
    assert os.path.isdir(os.path.join(out_dir, "vehicles"))
    assert os.path.isdir(os.path.join(out_dir, "concepts"))

    # One file per page in its category directory
    assert os.path.isfile(os.path.join(out_dir, "players", "freemanlatif.md"))
    assert os.path.isfile(os.path.join(out_dir, "vehicles", "gosan_g7.md"))
    assert os.path.isfile(
        os.path.join(out_dir, "concepts", "steel-coil-curse.md")
    )


def test_page_has_yaml_front_matter(exporter, storage, tmp_path):
    _seed_basic_pages(storage)
    out_dir = str(tmp_path / "export")
    exporter.export_all(out_dir)

    with open(os.path.join(out_dir, "players", "freemanlatif.md"), encoding="utf-8") as f:
        body = f.read()

    # Starts with YAML front matter delimiter
    assert body.startswith("---\n")
    # Contains required fields
    assert 'title: "player:freemanlatif"' in body
    assert 'slug: "player-freemanlatif"' in body
    assert 'category: "player"' in body
    assert "source_count:" in body
    assert 'tags: ["player"]' in body
    # Front matter closes before the title
    fm_end = body.find("\n---\n", 4)
    assert fm_end > 0
    heading_start = body.find("# player:freemanlatif", fm_end)
    assert heading_start > fm_end


def test_page_renders_outbound_and_inbound_links(exporter, storage, tmp_path):
    ids = _seed_basic_pages(storage)
    out_dir = str(tmp_path / "export")
    exporter.export_all(out_dir)

    with open(os.path.join(out_dir, "players", "freemanlatif.md"), encoding="utf-8") as f:
        player_body = f.read()
    with open(os.path.join(out_dir, "vehicles", "gosan_g7.md"), encoding="utf-8") as f:
        vehicle_body = f.read()

    # The player page lists the vehicle as an outbound link
    assert "## Links" in player_body
    assert "**Outbound:**" in player_body
    assert "vehicle:Gosan_G7" in player_body
    # Outbound link should be a relative markdown link
    assert "../vehicles/gosan_g7.md" in player_body

    # The vehicle page should list the player as inbound
    assert "**Inbound:**" in vehicle_body
    assert "player:freemanlatif" in vehicle_body
    assert "../players/freemanlatif.md" in vehicle_body

    # The ids should still exist in DB to confirm fixture ran
    assert storage.get_page_by_id(ids["player_id"]) is not None


def test_index_file_groups_by_category(exporter, storage, tmp_path):
    _seed_basic_pages(storage)
    out_dir = str(tmp_path / "export")
    exporter.export_all(out_dir)

    with open(os.path.join(out_dir, "index.md"), encoding="utf-8") as f:
        index = f.read()

    assert "# Annie's Wiki" in index
    assert "### player" in index
    assert "### vehicle" in index
    assert "### concept" in index
    # The links should point to the per-category md files
    assert "players/freemanlatif.md" in index
    assert "vehicles/gosan_g7.md" in index


def test_log_file_uses_karpathy_style_prefix(exporter, storage, tmp_path):
    _seed_basic_pages(storage)
    out_dir = str(tmp_path / "export")
    exporter.export_all(out_dir)

    with open(os.path.join(out_dir, "log.md"), encoding="utf-8") as f:
        log_body = f.read()

    # Each entry starts with "## [YYYY-MM-DD] operation | ..."
    matches = re.findall(r"^## \[\d{4}-\d{2}-\d{2}\] \S+ \|", log_body, re.MULTILINE)
    assert matches, "expected at least one '## [YYYY-MM-DD] op |' entry"
    # The ingest entry seeded in the fixture must appear (the current export
    # operation is logged after log.md is written, so it appears in the *next*
    # export — covered by `test_export_records_log_operation`).
    ops = re.findall(r"^## \[\d{4}-\d{2}-\d{2}\] (\S+) \|", log_body, re.MULTILINE)
    assert "ingest" in ops


def test_export_is_atomic_via_tmp_dir(exporter, storage, tmp_path):
    """The temp directory should not linger after a successful export."""
    _seed_basic_pages(storage)
    out_dir = str(tmp_path / "export")
    exporter.export_all(out_dir)

    # Parent directory should contain only the final export dir, no leftover
    # `.tmp` siblings.
    siblings = os.listdir(tmp_path)
    assert "export" in siblings
    assert not any(s.endswith(".tmp") for s in siblings)


def test_export_overwrites_existing_directory(exporter, storage, tmp_path):
    _seed_basic_pages(storage)
    out_dir = str(tmp_path / "export")

    # First export
    exporter.export_all(out_dir)
    stale_file = os.path.join(out_dir, "players", "old_ghost.md")
    with open(stale_file, "w") as f:
        f.write("# Ghost page that should vanish")

    # Second export should remove the stale file
    exporter.export_all(out_dir)
    assert not os.path.exists(stale_file)


def test_export_records_log_operation(exporter, storage, tmp_path):
    _seed_basic_pages(storage)
    out_dir = str(tmp_path / "export")
    exporter.export_all(out_dir)

    entries = storage.get_log_entries(operation="export")
    assert entries
    assert "pages" in entries[0]["description"].lower()


def test_sanitize_component_drops_unsafe_chars():
    assert WikiExporter._sanitize_component("Hello World!") == "hello-world"
    assert WikiExporter._sanitize_component("player:freeman/latif") == "player-freeman-latif"
    assert WikiExporter._sanitize_component("") == "untitled"
    assert WikiExporter._sanitize_component("already-safe_name.md") == "already-safe_name.md"


def test_slug_to_filename_stem_strips_category_prefix():
    assert WikiExporter._slug_to_filename_stem("player:freemanlatif") == "freemanlatif"
    assert WikiExporter._slug_to_filename_stem("player-freemanlatif") == "freemanlatif"
    assert WikiExporter._slug_to_filename_stem("vehicle-gosan_g7") == "gosan_g7"
    # Unknown prefix: keep as-is
    assert WikiExporter._slug_to_filename_stem("mystery-thing") == "mystery-thing"


def test_category_dir_pluralizes():
    assert WikiExporter._category_dir("player") == "players"
    assert WikiExporter._category_dir("vehicle") == "vehicles"
    # Already plural
    assert WikiExporter._category_dir("news") == "news"
    assert WikiExporter._category_dir("") == "misc"
