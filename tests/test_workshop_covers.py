from pathlib import Path

from PIL import Image

from amc_peripheral.workshop.covers import (
    cover_weight,
    sample_cover_items,
    write_author_cover,
    write_site_cover,
)


def test_cover_sampling_is_stable_unique_and_weighted():
    items = [
        {"id": index, "votes": index, "installs": index * 2, "hasDecal": index % 2 == 0}
        for index in range(1, 11)
    ]
    first = sample_cover_items(items, 747928)
    second = sample_cover_items(items, 747928)
    assert [item["id"] for item in first] == [item["id"] for item in second]
    assert len(first) == 6
    assert len({item["id"] for item in first}) == 6
    assert cover_weight({"votes": 20, "installs": 10, "hasDecal": True}) > cover_weight(
        {"votes": 20, "installs": 10, "hasDecal": False}
    )
    assert cover_weight({"votes": 20, "installs": 10}) > cover_weight({"votes": 1, "installs": 1})


def test_author_cover_is_six_panel_webp_and_content_addressed(tmp_path: Path):
    candidates = []
    for index in range(6):
        relative = Path("items") / f"{index}.webp"
        (tmp_path / relative).parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (960, 540), (index * 35, 50, 100)).save(tmp_path / relative)
        candidates.append({
            "id": index,
            "votes": 20 - index,
            "installs": 30 - index,
            "hasDecal": True,
            "snapshot": {
                "key": f"snapshot-{index}",
                "sha256": f"{index:064d}",
                "url": f"/workshop/snapshots/{relative.as_posix()}",
            },
        })
    url = write_author_cover(747928, candidates, tmp_path)
    assert url is not None
    assert url == write_author_cover(747928, candidates, tmp_path)
    output = tmp_path / url.removeprefix("/workshop/snapshots/")
    with Image.open(output) as cover:
        assert cover.size == (1200, 630)
        assert cover.format == "WEBP"

    candidates[0]["snapshot"]["key"] = "new-render"
    assert write_author_cover(747928, candidates, tmp_path) != url


def test_author_cover_skips_missing_render_files(tmp_path: Path):
    candidate = {
        "id": 1, "votes": 1, "installs": 1, "hasDecal": False,
        "snapshot": {"key": "missing", "url": "/workshop/snapshots/items/missing.webp"},
    }
    assert write_author_cover(1, [candidate], tmp_path) is None


def test_site_cover_uses_the_most_installed_decaled_items(tmp_path: Path):
    candidates = []
    for index in range(6):
        relative = Path("items") / f"site-{index}.webp"
        (tmp_path / relative).parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (960, 540), (index * 30, 80, 120)).save(tmp_path / relative)
        candidates.append({
            "id": index,
            "votes": index,
            "installs": (index + 1) * 100,
            "hasDecal": index != 0,
            "snapshot": {
                "key": f"site-{index}",
                "sha256": f"{index:064d}",
                "url": f"/workshop/snapshots/{relative.as_posix()}",
            },
        })

    url = write_site_cover(candidates, tmp_path)
    assert url is not None
    assert "/home/popular-" in url
    assert url == write_site_cover(candidates, tmp_path)
    output = tmp_path / url.removeprefix("/workshop/snapshots/")
    with Image.open(output) as cover:
        assert cover.size == (1200, 630)
        assert cover.format == "WEBP"

    candidates[1]["snapshot"]["key"] = "new-render"
    assert write_site_cover(candidates, tmp_path) != url
