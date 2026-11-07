"""HTTP surface for the AMC dev bridge.

Two very different clients speak to this app:

  the mod   -- unauthenticated enrolment, then a bearer-ish token in the path
              (UE4SS's `fetch` cannot send headers, so the token rides in the URL;
              nginx MUST NOT log that location -- see the NixOS module)
  operators -- the admin endpoints, behind a single shared token plus an
              allowlist of approver Discord IDs

Nothing here executes anything. The hub only relays code that an operator wrote.
"""

from __future__ import annotations

import hmac
from collections.abc import Iterable

from aiohttp import web

from .store import BridgeStore

STORE_KEY = web.AppKey("store", object)

MAX_CODE_BYTES = 64 * 1024


def _json(data, status: int = 200) -> web.Response:
    return web.json_response(data, status=status)


def _err(msg: str, status: int = 400) -> web.Response:
    return _json({"error": msg}, status=status)


def create_app(
    store: BridgeStore,
    *,
    admin_token: str,
    approvers: Iterable[str] = (),
    max_result_bytes: int = 512 * 1024,
    auto_approve: bool = False,
) -> web.Application:
    approvers = {str(a) for a in approvers if str(a).strip()}

    def admin_ok(request: web.Request) -> bool:
        got = request.headers.get("X-AMC-Admin", "")
        return bool(admin_token) and hmac.compare_digest(got, admin_token)

    def authed_member(request: web.Request):
        member = store.member_by_token(token=request.match_info["token"])
        return member

    # -- mod ------------------------------------------------------------
    async def enroll(request: web.Request) -> web.Response:
        body = await request.json()
        try:
            out = store.enroll(
                str(body.get("fingerprint") or ""),
                body.get("host"),
                body.get("mod"),
                auto_approve=auto_approve,
                label=body.get("name"),
            )
        except ValueError as e:
            return _err(str(e))
        return _json(out)

    async def enrollment(request: web.Request) -> web.Response:
        out = store.enrollment(request.match_info["secret"])
        if out is None:
            return _json({"status": "unknown"}, status=404)
        return _json(out)

    async def poll(request: web.Request) -> web.Response:
        member = authed_member(request)
        if member is None:
            # 200 + body on purpose: the mod only ever sees bodies, never status
            # codes, and it must distinguish "revoked" from "network down".
            return _json({"error": "revoked"})
        after = int(request.query.get("after", "0") or 0)
        cmd = store.next_command(int(member["id"]), after)
        return _json(cmd or {})

    async def result(request: web.Request) -> web.Response:
        member = authed_member(request)
        if member is None:
            return _err("unknown token", 401)
        body = await request.json()
        if not isinstance(body, dict):
            return _err("bad payload")
        if not store.save_result(int(member["id"]), body):
            return _err("unknown command id", 404)
        return _json({"ok": True})

    # -- operator -------------------------------------------------------
    async def admin_approve(request: web.Request) -> web.Response:
        if not admin_ok(request):
            return _err("forbidden", 403)
        body = await request.json()
        approver = str(body.get("approver") or "")
        # fail closed: an empty allowlist approves nobody, it does not open up
        if approver not in approvers:
            return _err("approver not in the allowlist", 403)
        try:
            out = store.approve(
                str(body.get("code") or ""),
                str(body.get("member") or "").strip(),
                actor=approver or "admin",
                discord_id=body.get("discord_id"),
            )
        except ValueError as e:
            return _err(str(e))
        if out is None:
            return _err("no pending enrolment with that code", 404)
        return _json(out)

    async def admin_deny(request: web.Request) -> web.Response:
        if not admin_ok(request):
            return _err("forbidden", 403)
        body = await request.json()
        ok = store.deny(str(body.get("code") or ""), actor=str(body.get("approver") or "admin"))
        return _json({"ok": ok})

    async def admin_exec(request: web.Request) -> web.Response:
        if not admin_ok(request):
            return _err("forbidden", 403)
        body = await request.json()
        member = store.member(str(body.get("member") or ""))
        if member is None:
            return _err("unknown member", 404)
        if member["revoked_at"] is not None:
            return _err("member is revoked", 409)
        code = str(body.get("code") or "")
        if not code:
            return _err("code required")
        if len(code.encode()) > MAX_CODE_BYTES:
            return _err("code too large", 413)
        try:
            cmd_id = store.queue_command(int(member["id"]), code)
        except ValueError as e:
            return _err(str(e), 409)
        return _json({"id": cmd_id})

    async def admin_results(request: web.Request) -> web.Response:
        if not admin_ok(request):
            return _err("forbidden", 403)
        label = request.query.get("member")
        after = int(request.query.get("after", "0") or 0)
        member_id = None
        if label:
            m = store.member(label)
            if m is None:
                return _err("unknown member", 404)
            member_id = int(m["id"])
        return _json({"results": store.results(member_id, after)})

    async def admin_members(request: web.Request) -> web.Response:
        if not admin_ok(request):
            return _err("forbidden", 403)
        out = []
        for m in store.members():
            row = store.member(m["label"])
            m["pending"] = store.pending(int(row["id"])) if row else 0
            out.append(m)
        return _json({"members": out})

    async def admin_rename(request: web.Request) -> web.Response:
        if not admin_ok(request):
            return _err("forbidden", 403)
        body = await request.json()
        try:
            ok = store.rename(
                str(body.get("member") or ""),
                str(body.get("to") or ""),
                actor=str(body.get("approver") or "admin"),
            )
        except ValueError as e:
            return _err(str(e), 409)
        return _json({"ok": ok})

    async def admin_revoke(request: web.Request) -> web.Response:
        if not admin_ok(request):
            return _err("forbidden", 403)
        body = await request.json()
        ok = store.revoke(str(body.get("member") or ""), actor=str(body.get("approver") or "admin"))
        return _json({"ok": ok})

    async def admin_unrevoke(request: web.Request) -> web.Response:
        if not admin_ok(request):
            return _err("forbidden", 403)
        body = await request.json()
        ok = store.unrevoke(str(body.get("member") or ""), actor=str(body.get("approver") or "admin"))
        return _json({"ok": ok})

    async def healthz(request: web.Request) -> web.Response:
        return _json({"ok": True, "members": len(store.members())})

    app = web.Application(client_max_size=max_result_bytes * 2)
    app[STORE_KEY] = store
    app.add_routes([
        web.get("/healthz", healthz),
        web.post("/api/enroll", enroll),
        web.get("/api/enroll/{secret}", enrollment),
        web.get("/api/dev/{token}/poll", poll),
        web.post("/api/dev/{token}/result", result),
        web.post("/api/admin/approve", admin_approve),
        web.post("/api/admin/deny", admin_deny),
        web.post("/api/admin/exec", admin_exec),
        web.get("/api/admin/results", admin_results),
        web.get("/api/admin/members", admin_members),
        web.post("/api/admin/rename", admin_rename),
        web.post("/api/admin/revoke", admin_revoke),
        web.post("/api/admin/unrevoke", admin_unrevoke),
    ])
    return app


def load_approvers(raw: str | None) -> list[str]:
    """APPROVERS is a comma-separated list of Discord user IDs."""
    if not raw:
        return []
    return [p.strip() for p in raw.split(",") if p.strip()]


def main() -> None:  # pragma: no cover - exercised by the systemd unit
    import os

    from aiohttp import web as _web

    db = os.environ.get("AMC_BRIDGE_DB", "/var/lib/amc-bot-devbridge/bridge.db")
    admin = os.environ.get("AMC_BRIDGE_ADMIN_TOKEN", "")
    if not admin:
        raise SystemExit("AMC_BRIDGE_ADMIN_TOKEN is not set")
    port = int(os.environ.get("AMC_BRIDGE_PORT", "7010"))
    store = BridgeStore(db)
    app = create_app(
        store,
        admin_token=admin,
        approvers=load_approvers(os.environ.get("AMC_BRIDGE_APPROVERS")),
        max_result_bytes=int(os.environ.get("AMC_BRIDGE_MAX_RESULT", "524288")),
        auto_approve=os.environ.get("AMC_BRIDGE_AUTO_APPROVE", "0") == "1",
    )
    _web.run_app(app, host="127.0.0.1", port=port, print=lambda *a, **k: None)


if __name__ == "__main__":  # pragma: no cover
    main()
