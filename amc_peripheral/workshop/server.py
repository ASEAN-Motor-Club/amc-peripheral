"""ASGI entry point for the workshop web process."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from aiohttp import web

from .config import WorkshopSettings
from .routes import create_app


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--source-db", default=None)
    parser.add_argument("--site-db", default=None)
    parser.add_argument("--viewer-root", default=None)
    parser.add_argument("--snapshot-root", default=None)
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    settings = WorkshopSettings.from_env()
    replacements = {
        "host": args.host,
        "port": args.port,
        "source_db": Path(args.source_db) if args.source_db else None,
        "site_db": Path(args.site_db) if args.site_db else None,
        "viewer_root": Path(args.viewer_root) if args.viewer_root else None,
        "snapshot_root": Path(args.snapshot_root) if args.snapshot_root else None,
    }
    settings = WorkshopSettings(
        **{
            **settings.__dict__,
            **{
                key: value
                for key, value in replacements.items()
                if value is not None
            },
        }
    )
    settings.validate()
    app = create_app(settings)
    web.run_app(
        app,
        host=settings.host,
        port=settings.port,
        access_log_format='%a "%r" %s %b %Dus',
    )


if __name__ == "__main__":
    main()
