"""Moderation for workshop comments, as an operator tool.

There is no admin role inside the workshop app — takedown of item meta has
always been a database action, not a web route. Comments follow the same
pattern rather than inventing a second, weaker notion of "admin" in the web
layer.

Run it on the host with the deployment's interpreter::

    /var/lib/amc-workshop-releases/current/bin/python \\
        -m amc_peripheral.workshop.moderation list --limit 20

    ... moderation hide 42 --by yumemi
    ... moderation unhide 42 --by yumemi

Hidden comments keep their row: a moderator can still read what was removed.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime

from .comments import CommentStore
from .config import WorkshopSettings

DEFAULT_DB = "/var/lib/amc-workshop/workshop_site.db"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _store(db: str) -> CommentStore:
    return CommentStore(db)


def _shorten(text: str, width: int = 90) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= width else flat[: width - 1] + "…"


def list_comments(store: CommentStore, *, limit: int) -> list[str]:
    lines = []
    for comment in store.recent(limit=limit):
        state = "HIDDEN" if comment.hidden else "      "
        lines.append(
            f"{comment.id:>6} {state} item {comment.workshop_id:<7}"
            f" {comment.discord_id:<20} {_shorten(comment.body)}"
        )
    return lines


def hide(store: CommentStore, comment_id: int, *, by: str) -> bool:
    return store.hide(comment_id=comment_id, admin_id=by, now=_now(), hidden=True)


def unhide(store: CommentStore, comment_id: int, *, by: str) -> bool:
    return store.hide(comment_id=comment_id, admin_id=by, now=_now(), hidden=False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Moderate workshop comments.")
    parser.add_argument(
        "--db",
        default=None,
        help=f"site database (default: {DEFAULT_DB}, or the service setting)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    listing = sub.add_parser("list", help="newest comments, hidden included")
    listing.add_argument("--limit", type=int, default=20)

    for name in ("hide", "unhide"):
        action = sub.add_parser(name, help=f"{name} a comment")
        action.add_argument("comment_id", type=int)
        action.add_argument("--by", default="operator", help="who is doing it")

    args = parser.parse_args(argv)
    db = args.db
    if db is None:
        try:
            db = str(WorkshopSettings.from_env().site_db)
        except Exception:  # noqa: BLE001 - fall back to the deployed path
            db = DEFAULT_DB
    store = _store(db)

    if args.command == "list":
        for line in list_comments(store, limit=args.limit):
            print(line)
        return 0

    action = hide if args.command == "hide" else unhide
    if not action(store, args.comment_id, by=args.by):
        print(f"no comment with id {args.comment_id}")
        return 1
    print(f"{args.command}d comment {args.comment_id}")
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised by hand
    raise SystemExit(main())
