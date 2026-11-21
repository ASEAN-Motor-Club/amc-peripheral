"""Read-only Motor Town Workshop browser service."""

from .config import WorkshopSettings
from .routes import create_app

__all__ = ["WorkshopSettings", "create_app"]
