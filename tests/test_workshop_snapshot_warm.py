"""Remote renderer handshake tests (``POST /warm`` client side)."""

from __future__ import annotations

import urllib.error
from email.message import Message
from pathlib import Path

import pytest

from amc_peripheral.workshop.snapshot_worker import RemoteRenderer, SnapshotSettings


class _Response:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *exc: object) -> None:
        return None


def _settings(tmp_path: Path) -> SnapshotSettings:
    return SnapshotSettings(
        site_db=tmp_path / "site.db",
        snapshot_root=tmp_path / "snapshots",
        viewer_url="http://100.126.244.10:7004/vehicles/index.html",
        chrome=None,
        remote_url="http://127.0.0.1:18099",
    )


def test_warm_reports_render_time(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    seen: dict[str, str] = {}

    def fake_urlopen(request, timeout=None):
        seen["url"] = request.full_url
        seen["body"] = request.data.decode()
        return _Response(b'{"warm": true, "ms": 1218}')

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    renderer = RemoteRenderer(_settings(tmp_path), "http://127.0.0.1:18099")

    assert renderer.warm() == "1218 ms"
    assert seen["url"].endswith("/warm")
    assert '"force": false' in seen["body"]


def test_warm_says_already_warm(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda request, timeout=None: _Response(b'{"warm": true, "skipped": true}'),
    )
    renderer = RemoteRenderer(_settings(tmp_path), "http://127.0.0.1:18099")

    assert renderer.warm() == "already warm"
    assert renderer.available() is True


def test_warm_404_is_not_a_renderer_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    def fake_urlopen(request, timeout=None):
        raise urllib.error.HTTPError(
            request.full_url, 404, "Not Found", Message(), None
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    renderer = RemoteRenderer(_settings(tmp_path), "http://127.0.0.1:18099")

    assert renderer.warm() is None
    # An older agent without /warm still renders fine: no cooldown.
    assert renderer.available() is True


def test_warm_transport_failure_arms_cooldown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    def fake_urlopen(request, timeout=None):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    renderer = RemoteRenderer(_settings(tmp_path), "http://127.0.0.1:18099")

    assert renderer.warm() is None
    assert renderer.available() is False
