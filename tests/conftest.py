"""Shared workshop test fixtures.

The fixtures themselves live in ``workshop_support`` so they can be reused by
tests that build an app directly; importing them here registers them with
pytest for the whole suite without duplicating the definitions.
"""

from __future__ import annotations

from workshop_support import client, settings  # noqa: F401

__all__ = ["client", "settings"]
