"""CLI request shaping.

The hub sits behind Cloudflare, which answers the default urllib user-agent
with "error code: 1010" -- a 403 the operator sees as a hub error. These tests
pin the headers the CLI must send.
"""

import argparse
import urllib.request

import pytest

from amc_peripheral.devbridge import cli


class _FakeResponse:
    def __init__(self, payload: bytes):
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture()
def captured(monkeypatch):
    seen = {}

    def fake_urlopen(req, timeout=None):
        seen["headers"] = {k.lower(): v for k, v in req.header_items()}
        seen["url"] = req.full_url
        seen["method"] = req.get_method()
        return _FakeResponse(b'{"ok": true}')

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setenv("AMC_BRIDGE_ADMIN_TOKEN", "test-token")
    return seen


def _args(**over):
    ns = argparse.Namespace(url="https://hub.test", token_file=None, timeout=5)
    for k, v in over.items():
        setattr(ns, k, v)
    return ns


def test_call_sends_a_user_agent(captured):
    out = cli._call(_args(), "GET", "/api/admin/members")
    assert out == {"ok": True}
    ua = captured["headers"].get("user-agent", "")
    assert ua.startswith("amcb/"), f"got user-agent {ua!r}"
    assert "python-urllib" not in ua.lower()


def test_call_sends_the_admin_token(captured):
    cli._call(_args(), "GET", "/api/admin/members")
    assert captured["headers"].get("x-amc-admin") == "test-token"


def test_call_joins_url_without_doubling_slashes(captured):
    cli._call(_args(url="https://hub.test/"), "GET", "/api/admin/members")
    assert captured["url"] == "https://hub.test/api/admin/members"
