"""Workshop service configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class WorkshopSettings:
    """Runtime paths and limits.

    The source database is always opened read-only. Writes belong to the scraper
    and, separately, to the site-state database used by snapshot/aggregate jobs.
    """

    source_db: Path
    site_db: Path
    viewer_root: Path
    snapshot_root: Path
    host: str = "127.0.0.1"
    port: int = 7003
    page_size: int = 24
    max_page_size: int = 60
    max_payload_bytes: int = 2 * 1024 * 1024
    home_limit: int = 10
    prewarm_limit: int = 48
    prewarm_queue_limit: int = 50
    # How far down the popularity order a prewarm pass may look for items that
    # have no snapshot yet. Bounds the work an aggregate run does on a library
    # whose top items are already rendered.
    prewarm_scan_limit: int = 500
    cache_ttl_seconds: float = 60.0
    similarity_min: float = 0.60
    similarity_copy_threshold: float = 0.95
    similarity_flag_min_layers: int = 8
    similarity_flag_min_similarity: float = 0.95
    similarity_limit: int = 6
    character_vehicle_dsn: str | None = None
    character_vehicle_public: bool = False
    player_dsn: str | None = None

    @classmethod
    def from_env(cls) -> WorkshopSettings:
        return cls(
            source_db=Path(
                os.environ.get(
                    "AMC_WORKSHOP_DB",
                    "/opt/data/workspace/mt-workshop-scrape/workshop.db",
                )
            ),
            site_db=Path(
                os.environ.get(
                    "AMC_WORKSHOP_SITE_DB",
                    "/opt/data/workshop-site/workshop_site.db",
                )
            ),
            viewer_root=Path(
                os.environ.get(
                    "AMC_WORKSHOP_VIEWER_ROOT",
                    "/var/www/www.aseanmotorclub.com/vehicles",
                )
            ),
            snapshot_root=Path(
                os.environ.get(
                    "AMC_WORKSHOP_SNAPSHOT_ROOT",
                    "/opt/data/workshop-site/snapshots",
                )
            ),
            host=os.environ.get("AMC_WORKSHOP_HOST", "127.0.0.1"),
            port=int(os.environ.get("AMC_WORKSHOP_PORT", "7003")),
            page_size=int(os.environ.get("AMC_WORKSHOP_PAGE_SIZE", "24")),
            max_page_size=int(os.environ.get("AMC_WORKSHOP_MAX_PAGE_SIZE", "60")),
            home_limit=int(os.environ.get("AMC_WORKSHOP_HOME_LIMIT", "10")),
            prewarm_limit=int(os.environ.get("AMC_WORKSHOP_PREWARM_LIMIT", "48")),
            prewarm_queue_limit=int(
                os.environ.get("AMC_WORKSHOP_PREWARM_QUEUE_LIMIT", "50")
            ),
            prewarm_scan_limit=int(
                os.environ.get("AMC_WORKSHOP_PREWARM_SCAN_LIMIT", "500")
            ),
            cache_ttl_seconds=float(os.environ.get("AMC_WORKSHOP_CACHE_SECONDS", "60")),
            similarity_min=float(os.environ.get("AMC_WORKSHOP_SIMILARITY_MIN", "0.60")),
            similarity_copy_threshold=float(
                os.environ.get("AMC_WORKSHOP_SIMILARITY_COPY", "0.95")
            ),
            similarity_flag_min_layers=int(
                os.environ.get("AMC_WORKSHOP_SIMILARITY_FLAG_LAYERS", "8")
            ),
            similarity_flag_min_similarity=float(
                os.environ.get("AMC_WORKSHOP_SIMILARITY_FLAG_MIN", "0.95")
            ),
            similarity_limit=int(os.environ.get("AMC_WORKSHOP_SIMILARITY_LIMIT", "6")),
            character_vehicle_dsn=os.environ.get("AMC_CHARACTER_VEHICLE_DSN"),
            character_vehicle_public=os.environ.get(
                "AMC_CHARACTER_VEHICLE_PUBLIC", ""
            ).lower()
            in {"1", "true", "yes"},
            player_dsn=os.environ.get("AMC_WORKSHOP_PLAYER_DSN") or None,
        )

    def validate(self) -> None:
        if not self.source_db.is_file():
            raise RuntimeError(f"workshop source database not found: {self.source_db}")
        if self.page_size < 1 or self.max_page_size < self.page_size:
            raise RuntimeError("invalid workshop page-size configuration")
