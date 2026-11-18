"""Private viewer origin behavior: asset cache policy, traversal, API proxy."""

from __future__ import annotations

from pathlib import Path

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from amc_peripheral.workshop.viewer_origin import (
    BINARY_CACHE,
    DOCUMENT_CACHE,
    ViewerOriginSettings,
    _resolve_asset,
    build_app,
)


def _make_tree(root: Path) -> None:
    (root / "zydro" / "glb").mkdir(parents=True)
    (root / "zydro" / "glb" / "Body.glb").write_bytes(b"glTF" + b"\0" * 32)
    (root / "index.html").write_text("<html>viewer</html>")
    (root / "zydro" / "zydro.json").write_text("{}")
    (root / ".hidden").write_text("dotfile")


async def _client(tmp_path: Path) -> TestClient:
    _make_tree(tmp_path)
    settings = ViewerOriginSettings(
        root=tmp_path,
        upstream="http://127.0.0.1:1",
        bind="127.0.0.1",
        port=0,
    )
    client = TestClient(TestServer(build_app(settings)))
    await client.start_server()
    return client


async def test_binaries_get_long_ttl_and_documents_revalidate(tmp_path):
    client = await _client(tmp_path)
    try:
        glb = await client.get("/vehicles/zydro/glb/Body.glb")
        assert glb.status == 200
        assert glb.headers["Cache-Control"] == BINARY_CACHE
        assert glb.headers["Content-Type"] == "model/gltf-binary"
        assert await glb.read() == b"glTF" + b"\0" * 32

        index = await client.get("/vehicles/")
        assert index.status == 200
        assert index.headers["Cache-Control"] == DOCUMENT_CACHE

        manifest = await client.get("/vehicles/zydro/zydro.json")
        assert manifest.status == 200
        assert manifest.headers["Cache-Control"] == DOCUMENT_CACHE
    finally:
        await client.close()


async def test_missing_asset_is_404_not_a_directory_listing(tmp_path):
    client = await _client(tmp_path)
    try:
        assert (await client.get("/vehicles/nope.glb")).status == 404
        assert (await client.get("/vehicles/zydro/glb")).status == 404
    finally:
        await client.close()


def test_resolve_asset_rejects_escapes_and_dotfiles(tmp_path):
    (tmp_path / "index.html").write_text("x")
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("x")

    assert _resolve_asset(tmp_path, "") == (tmp_path / "index.html").resolve()
    assert _resolve_asset(tmp_path, "../outside.txt") is None
    assert _resolve_asset(tmp_path, "zydro/../../outside.txt") is None
    assert _resolve_asset(tmp_path, ".hidden") is None
    # Absolute paths are treated as tree-relative, never as filesystem paths.
    assert (
        _resolve_asset(tmp_path, "/index.html") == (tmp_path / "index.html").resolve()
    )
    assert _resolve_asset(tmp_path, "/etc/passwd") == (tmp_path / "etc/passwd")


async def test_api_is_proxied_to_the_workshop_app(tmp_path):
    _make_tree(tmp_path)
    seen: list[tuple[str, str]] = []

    async def upstream(request: web.Request) -> web.Response:
        seen.append((request.method, request.path_qs))
        return web.json_response({"id": 260922}, headers={"Cache-Control": "no-store"})

    upstream_app = web.Application()
    upstream_app.router.add_route("*", "/api/{tail:.*}", upstream)
    upstream_client = TestClient(TestServer(upstream_app))
    await upstream_client.start_server()
    try:
        settings = ViewerOriginSettings(
            root=tmp_path,
            upstream=str(upstream_client.server.make_url("")).rstrip("/"),
            bind="127.0.0.1",
            port=0,
        )
        client = TestClient(TestServer(build_app(settings)))
        await client.start_server()
        try:
            response = await client.get("/api/workshop/items/260922/viewer?x=1")
            assert response.status == 200
            assert await response.json() == {"id": 260922}
            assert seen == [("GET", "/api/workshop/items/260922/viewer?x=1")]
        finally:
            await client.close()
    finally:
        await upstream_client.close()


async def test_unreachable_upstream_is_a_bad_gateway(tmp_path):
    client = await _client(tmp_path)
    try:
        assert (await client.get("/api/workshop/home")).status == 502
    finally:
        await client.close()
