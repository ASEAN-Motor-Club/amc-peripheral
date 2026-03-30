"""Entry point for the amc-mods build API service."""

import logging

from aiohttp import web

from .api import create_app


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    app = create_app()
    web.run_app(app, host="127.0.0.1", port=7002)


if __name__ == "__main__":
    main()
