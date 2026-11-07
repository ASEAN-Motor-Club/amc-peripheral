"""Tests for the AMC dev bridge hub (store + HTTP surface)."""

from __future__ import annotations

import time

import pytest
from aiohttp.test_utils import TestClient, TestServer

from amc_peripheral.devbridge.server import create_app
from amc_peripheral.devbridge.store import BridgeStore

ADMIN = "admin-secret"
APPROVER = "1155069673512120341"
FP = "m0123456789abcdef"


@pytest.fixture()
def store(tmp_path):
    return BridgeStore(tmp_path / "bridge.db")


async def start(app):
    client = TestClient(TestServer(app))
    await client.start_server()
    return client


def make_app(store, **kw):
    kw.setdefault("admin_token", ADMIN)
    kw.setdefault("approvers", [APPROVER])
    return create_app(store, **kw)


# ---------------------------------------------------------------- store ----
def test_enrollment_is_idempotent_per_fingerprint(store):
    a = store.enroll(FP, "DESKTOP-X", "0.3.0")
    b = store.enroll(FP, "DESKTOP-X", "0.3.0")
    assert a["code"] == b["code"]
    assert a["secret"] == b["secret"]
    assert a["status"] == "pending"


def test_approve_issues_a_token_that_resolves(store):
    e = store.enroll(FP, "DESKTOP-X", "0.3.0")
    out = store.approve(e["code"], "freeman", actor=APPROVER)
    assert out and out["label"] == "freeman"
    row = store.member_by_token(out["token"])
    assert row is not None and row["label"] == "freeman"


def test_token_plaintext_is_cleared_after_first_use(store):
    e = store.enroll(FP, "DESKTOP-X", "0.3.0")
    token = store.approve(e["code"], "freeman", actor=APPROVER)["token"]
    assert store.enrollment(e["secret"])["token"] == token  # still claimable
    store.member_by_token(token)                             # mod used it
    assert "token" not in store.enrollment(e["secret"])      # now gone


def test_lost_state_after_approval_needs_a_human(store):
    e = store.enroll(FP, "DESKTOP-X", "0.3.0")
    store.approve(e["code"], "freeman", actor=APPROVER)
    again = store.enroll(FP, "DESKTOP-X", "0.3.0")
    assert again["status"] == "approved"
    assert "token" not in again  # never silently reissue a credential


def test_revoked_member_is_refused_and_cannot_re_enrol(store):
    e = store.enroll(FP, "DESKTOP-X", "0.3.0")
    token = store.approve(e["code"], "freeman", actor=APPROVER)["token"]
    assert store.revoke("freeman", actor=APPROVER) is True
    assert store.member_by_token(token) is None
    e2 = store.enroll("mffffffffffffffff", "DESKTOP-X", "0.3.0")  # new enrolment
    # a *revoked* machine cannot be re-approed without clearing the revocation
    store.approve(e2["code"], "someone", actor=APPROVER)
    store.revoke("someone", actor=APPROVER)
    e3 = store.enroll("maaaaaaaaaaaaaaaa", "DESKTOP-X", "0.3.0")
    assert store.approve(e3["code"], "x", actor=APPROVER) is not None


def test_queue_cap_and_expiry(store):
    e = store.enroll(FP, "DESKTOP-X", "0.3.0")
    store.approve(e["code"], "freeman", actor=APPROVER)
    m = store.member("freeman")
    for _ in range(store.queue_cap):
        store.queue_command(int(m["id"]), "return 1")
    with pytest.raises(ValueError):
        store.queue_command(int(m["id"]), "return 1")

    # expire everything by pushing created_at into the past
    import sqlite3

    with sqlite3.connect(store.path) as c:
        c.execute("UPDATE commands SET created_at = ?", (time.time() - store.command_ttl - 5,))
    assert store.next_command(int(m["id"]), 0) is None


def test_one_in_flight_command_is_delivered_once(store):
    e = store.enroll(FP, "DESKTOP-X", "0.3.0")
    store.approve(e["code"], "freeman", actor=APPROVER)
    m = store.member("freeman")
    cid = store.queue_command(int(m["id"]), "return 42")
    first = store.next_command(int(m["id"]), 0)
    assert first == {"id": cid, "code": "return 42"}
    assert store.next_command(int(m["id"]), 0) is None  # not re-sent


# ------------------------------------------------------------ auto-open ----
def test_auto_approve_issues_a_token_immediately(store):
    out = store.enroll(FP, "DESKTOP-X", "0.3.0", auto_approve=True)
    assert out["status"] == "approved"
    assert store.member_by_token(out["token"])["label"] == "desktop-x"


def test_auto_approve_re_enrol_rotates_the_token(store):
    first = store.enroll(FP, "DESKTOP-X", "0.3.0", auto_approve=True)["token"]
    second = store.enroll(FP, "DESKTOP-X", "0.3.1", auto_approve=True)
    assert second["token"] != first
    assert store.member_by_token(first) is None      # old credential dead
    assert store.member_by_token(second["token"]) is not None
    assert len(store.members()) == 1                 # same machine, one row


def test_auto_approve_never_resurrects_a_revoked_machine(store):
    token = store.enroll(FP, "DESKTOP-X", "0.3.0", auto_approve=True)["token"]
    store.revoke("desktop-x", actor="self")
    assert store.member_by_token(token) is None
    out = store.enroll(FP, "DESKTOP-X", "0.3.0", auto_approve=True)
    assert out == {"status": "revoked"}
    assert "token" not in out


def test_auto_approve_labels_are_unique_per_machine(store):
    a = store.enroll("m1111111111111111", "GAMING-PC", "0.3.0", auto_approve=True)
    b = store.enroll("m2222222222222222", "GAMING-PC", "0.3.0", auto_approve=True)
    labels = sorted(m["label"] for m in store.members())
    assert labels == ["gaming-pc", "gaming-pc-2"]
    assert a["token"] and b["token"]


def test_rename(store):
    store.enroll(FP, "desktop-x", "0.3.0", auto_approve=True)
    assert store.rename("desktop-x", "Freeman Desktop", actor="admin") is True
    assert [m["label"] for m in store.members()] == ["freeman-desktop"]
    with pytest.raises(ValueError):
        store.rename("freeman-desktop", "freeman-desktop", actor="admin")


# --------------------------------------------------------------- server ----
@pytest.mark.asyncio
async def test_full_mod_lifecycle(store):
    client = await start(make_app(store))
    try:
        r = await client.post("/api/enroll", json={"fingerprint": FP, "host": "DESKTOP-X",
                                                   "mod": "0.3.0"})
        e = await r.json()
        assert e["status"] == "pending"

        r = await client.get("/api/enroll/{}".format(e["secret"]))
        assert (await r.json())["status"] == "pending"

        r = await client.post("/api/admin/approve",
                              json={"code": e["code"], "member": "freeman",
                                    "approver": APPROVER},
                              headers={"X-AMC-Admin": ADMIN})
        out = await r.json()
        token = out["token"]

        r = await client.get("/api/enroll/{}".format(e["secret"]))
        got = await r.json()
        assert got["status"] == "approved" and got["token"] == token

        r = await client.post("/api/admin/exec", json={"member": "freeman", "code": "return 42"},
                              headers={"X-AMC-Admin": ADMIN})
        cmd_id = (await r.json())["id"]

        r = await client.get(f"/api/dev/{token}/poll?after=0")
        cmd = await r.json()
        assert cmd == {"id": cmd_id, "code": "return 42"}

        r = await client.post(f"/api/dev/{token}/result",
                              json={"id": cmd_id, "ok": True, "result": 42, "output": []})
        assert (await r.json())["ok"] is True

        r = await client.get("/api/admin/results?member=freeman",
                             headers={"X-AMC-Admin": ADMIN})
        res = (await r.json())["results"]
        assert res[0]["result"] == 42 and res[0]["status"] == "done"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_auto_approve_needs_no_operator_at_all(store):
    client = await start(make_app(store, auto_approve=True))
    try:
        r = await client.post("/api/enroll", json={"fingerprint": FP, "host": "DESKTOP-X",
                                                   "mod": "0.3.0"})
        e = await r.json()
        assert e["status"] == "approved"
        token = e["token"]

        # straight to work: no approve call, no admin token
        r = await client.post("/api/admin/exec", json={"member": "desktop-x", "code": "return 1"},
                              headers={"X-AMC-Admin": ADMIN})
        assert (await r.json())["id"] == 1
        r = await client.get(f"/api/dev/{token}/poll?after=0")
        assert (await r.json())["code"] == "return 1"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_auto_approve_enrol_returns_revoked_for_a_revoked_machine(store):
    first = await _enrol(store, FP)
    store.revoke("desktop-x", actor="self")
    client = await start(make_app(store, auto_approve=True))
    try:
        r = await client.post("/api/enroll", json={"fingerprint": FP, "host": "DESKTOP-X"})
        assert (await r.json()) == {"status": "revoked"}
    finally:
        await client.close()
        assert first


async def _enrol(store, fp):
    client = await start(make_app(store, auto_approve=True))
    try:
        return (await (await client.post("/api/enroll", json={"fingerprint": fp,
                                                              "host": "DESKTOP-X"})).json())["token"]
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_revoked_token_gets_a_body_not_a_status(store):
    e = store.enroll(FP, "DESKTOP-X", "0.3.0")
    token = store.approve(e["code"], "freeman", actor=APPROVER)["token"]
    store.revoke("freeman", actor=APPROVER)
    client = await start(make_app(store))
    try:
        r = await client.get(f"/api/dev/{token}/poll?after=0")
        assert r.status == 200
        assert (await r.json()) == {"error": "revoked"}
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_admin_endpoints_require_the_token_and_the_allowlist(store):
    e = store.enroll(FP, "DESKTOP-X", "0.3.0")
    client = await start(make_app(store))
    try:
        r = await client.post("/api/admin/approve",
                              json={"code": e["code"], "member": "freeman", "approver": APPROVER})
        assert r.status == 403

        r = await client.post("/api/admin/approve",
                              json={"code": e["code"], "member": "freeman", "approver": "999"},
                              headers={"X-AMC-Admin": ADMIN})
        assert r.status == 403  # not an approver

        r = await client.get("/api/admin/members")
        assert r.status == 403
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_oversized_result_is_rejected(store):
    client = await start(make_app(store, max_result_bytes=1024))
    try:
        e = await (await client.post("/api/enroll", json={"fingerprint": FP})).json()
        token = (await (await client.post(
            "/api/admin/approve",
            json={"code": e["code"], "member": "freeman", "approver": APPROVER},
            headers={"X-AMC-Admin": ADMIN},
        )).json())["token"]
        r = await client.post(f"/api/dev/{token}/result",
                              json={"id": 1, "ok": True, "result": "x" * 4096})
        assert r.status == 413
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_token_in_a_header_works_and_keeps_it_out_of_the_url(store):
    token = store.enroll(FP, "DESKTOP-X", "0.3.0", auto_approve=True)["token"]
    client = await start(make_app(store))
    try:
        r = await client.post("/api/admin/exec", json={"member": "desktop-x", "code": "return 7"},
                              headers={"X-AMC-Admin": ADMIN})
        assert (await r.json())["id"] == 1
        # no token anywhere in the path
        r = await client.get("/api/dev/poll?after=0", headers={"X-AMC-Token": token})
        assert (await r.json())["code"] == "return 7"
        # result post over the bare path too
        r = await client.post("/api/dev/result", json={"id": 1, "ok": True, "result": 7},
                              headers={"X-AMC-Token": token})
        assert (await r.json())["ok"] is True
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_legacy_token_in_path_still_works(store):
    token = store.enroll(FP, "DESKTOP-X", "0.3.0", auto_approve=True)["token"]
    client = await start(make_app(store))
    try:
        r = await client.get(f"/api/dev/{token}/poll?after=0")
        assert await r.json() == {}
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_unknown_token_poll_says_revoked(store):
    client = await start(make_app(store))
    try:
        r = await client.get("/api/dev/nope/poll?after=0")
        assert (await r.json()) == {"error": "revoked"}
    finally:
        await client.close()
