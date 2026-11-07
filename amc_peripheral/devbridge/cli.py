"""`amcb` -- operator CLI for the AMC dev bridge.

Deliberately dependency-free (stdlib urllib) so it runs from the container, the
NixOS host, or a laptop with nothing installed.

The admin token is read from, in order: --token-file, $AMC_BRIDGE_ADMIN_TOKEN, or
~/.config/amcb/token. It is never taken from argv, because argv is visible in `ps`
to every user on the box.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_URL = "https://bridge.aseanmotorclub.com"


def _token(args) -> str:
    if getattr(args, "token_file", None):
        return Path(args.token_file).read_text().strip()
    env = os.environ.get("AMC_BRIDGE_ADMIN_TOKEN")
    if env:
        return env.strip()
    p = Path.home() / ".config" / "amcb" / "token"
    if p.exists():
        return p.read_text().strip()
    raise SystemExit("no admin token: set AMC_BRIDGE_ADMIN_TOKEN or write ~/.config/amcb/token")


def _call(args, method: str, path: str, body: dict | None = None):
    url = args.url.rstrip("/") + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("X-AMC-Admin", _token(args))
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=getattr(args, "timeout", 30)) as r:
            return json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        payload = e.read().decode()
        try:
            msg = json.loads(payload).get("error", payload)
        except (ValueError, TypeError):
            msg = payload
        raise SystemExit(f"hub error {e.code}: {msg}")


def _wait(args, member: str, cmd_id: int, timeout: float = 60.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        out = _call(args, "GET", f"/api/admin/results?member={member}&after={cmd_id - 1}")
        for r in out.get("results", []):
            if r["id"] == cmd_id:
                return r
        time.sleep(0.7)
    return {"id": cmd_id, "status": "timeout", "error": f"no result in {timeout}s"}


def _print_result(r: dict) -> None:
    for line in r.get("output") or []:
        print(line)
    if r.get("error"):
        print("error: {}".format(r["error"]), file=sys.stderr)
    if r.get("status") == "done" and r.get("result") is not None:
        print("=> {}".format(json.dumps(r["result"])))


def cmd_members(args):
    out = _call(args, "GET", "/api/admin/members")
    for m in out.get("members", []):
        seen = time.strftime("%Y-%m-%d %H:%M", time.localtime(m["last_seen_at"])) if m.get("last_seen_at") else "never"
        print(f"{m['label']:<16} {'REVOKED' if m['revoked'] else 'ok':<6} "
              f"{(m.get('mod') or '-'):<9} pending={m.get('pending', 0)} "
              f"last_seen={seen}  {m.get('host') or '-'}")


def cmd_approve(args):
    out = _call(args, "POST", "/api/admin/approve", {
        "code": args.code, "member": args.member, "approver": args.approver,
        "discord_id": args.discord_id,
    })
    print("approved {} (fingerprint {})".format(out["label"], out["fingerprint"]))
    print("token is only delivered to the machine itself; nothing to copy.")


def cmd_exec(args):
    if args.file:
        code = Path(args.file).read_text()
    elif args.code:
        code = args.code
    else:
        code = sys.stdin.read()
    out = _call(args, "POST", "/api/admin/exec", {"member": args.member, "code": code})
    if not args.wait:
        print(out["id"])
        return
    _print_result(_wait(args, args.member, out["id"], args.timeout))


def cmd_results(args):
    suffix = f"&member={args.member}" if args.member else ""
    out = _call(args, "GET", f"/api/admin/results?after={args.after}{suffix}")
    for r in out.get("results", []):
        print("[{}] {}".format(r["id"], r["code"]))
        _print_result(r)


def cmd_shell(args):
    print(f"amcb shell -> {args.member} (blank line runs, Ctrl-D exits)")
    buf: list[str] = []
    while True:
        try:
            line = input("lua> " if not buf else "...> ")
        except EOFError:
            break
        if line.strip() == "" and buf:
            code = "\n".join(buf)
            buf = []
            try:
                out = _call(args, "POST", "/api/admin/exec", {"member": args.member, "code": code})
                _print_result(_wait(args, args.member, out["id"], args.timeout))
            except SystemExit as e:
                print(e, file=sys.stderr)
            continue
        if line.strip().startswith("=") and not buf:
            line = "return " + line.strip()[1:].strip()
        buf.append(line)


def cmd_revoke(args):
    out = _call(args, "POST", "/api/admin/revoke" if not args.undo else "/api/admin/unrevoke",
                {"member": args.member, "approver": args.approver})
    print("ok" if out.get("ok") else "no change")


def main(argv=None) -> None:
    p = argparse.ArgumentParser(prog="amcb", description="AMC dev bridge operator CLI")
    p.add_argument("--url", default=os.environ.get("AMC_BRIDGE_URL", DEFAULT_URL))
    p.add_argument("--token-file")
    p.add_argument("--timeout", type=float, default=60.0)
    p.add_argument("--approver", default=os.environ.get("AMC_BRIDGE_APPROVER", ""),
                   help="your Discord user ID (must be in the hub allowlist)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("members", help="list machines").set_defaults(func=cmd_members)

    a = sub.add_parser("approve", help="approve a claim code")
    a.add_argument("code")
    a.add_argument("--member", required=True, help="label, e.g. freeman")
    a.add_argument("--discord-id")
    a.set_defaults(func=cmd_approve)

    for name, fn in (("revoke", cmd_revoke), ("unrevoke", cmd_revoke)):
        r = sub.add_parser(name)
        r.add_argument("member")
        r.set_defaults(func=fn, undo=(name == "unrevoke"))

    e = sub.add_parser("exec", help="run Lua on a machine")
    e.add_argument("member")
    e.add_argument("-f", "--file")
    e.add_argument("-c", "--code")
    e.add_argument("-n", "--no-wait", dest="wait", action="store_false")
    e.set_defaults(func=cmd_exec, wait=True)

    r = sub.add_parser("results", help="show recent results")
    r.add_argument("member", nargs="?")
    r.add_argument("--after", type=int, default=0)
    r.set_defaults(func=cmd_results)

    s = sub.add_parser("shell", help="interactive Lua prompt on a machine")
    s.add_argument("member")
    s.set_defaults(func=cmd_shell)

    args = p.parse_args(argv)
    args.func(args)


if __name__ == "__main__":  # pragma: no cover
    main()
