"""SQLite storage for configurable in-game announcements."""

import os
from datetime import datetime, timezone
from sqlite_utils import Database
from amc_peripheral.settings import MEMORY_DATA_DIR


class AnnouncementsDB:
    """Persistent storage for in-game announcements."""

    def __init__(self, db_path: str | None = None):
        if db_path is None:
            db_path = os.path.join(MEMORY_DATA_DIR, "announcements.db")
        os.makedirs(os.path.dirname(db_path) or MEMORY_DATA_DIR, exist_ok=True)
        self.db = Database(db_path)
        self._ensure_tables()

    def _ensure_tables(self):
        """Ensure tables exist with proper structure."""
        if "announcements" not in self.db.table_names():
            # pyrefly: ignore [missing-attribute]
            self.db["announcements"].create(
                {
                    "id": int,
                    "text": str,
                    "enabled": int,  # 1 = enabled, 0 = disabled
                    "created_at": str,
                    "created_by": str,
                },
                pk="id",
            )
            # pyrefly: ignore [missing-attribute]
            self.db["announcements"].create_index(["enabled"])

    def add_announcement(self, text: str, created_by: str) -> int | None:
        """Add a new announcement. Returns the ID."""
        row = {
            "text": text,
            "enabled": 1,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "created_by": created_by,
        }
        try:
            # pyrefly: ignore [missing-attribute]
            return self.db["announcements"].insert(row).last_pk
        except Exception:
            return None

    def remove_announcement(self, announcement_id: int) -> bool:
        """Remove an announcement by ID. Returns True if deleted."""
        try:
            # pyrefly: ignore [missing-attribute]
            self.db["announcements"].delete(announcement_id)
            return True
        except Exception:
            return False

    def toggle_announcement(self, announcement_id: int, enabled: bool) -> bool:
        """Enable or disable an announcement. Returns True if updated."""
        try:
            # pyrefly: ignore [missing-attribute]
            self.db["announcements"].update(announcement_id, {"enabled": 1 if enabled else 0})
            return True
        except Exception:
            return False

    def list_announcements(self, enabled_only: bool = False) -> list[dict]:
        """List all announcements, optionally filtering to enabled only."""
        if enabled_only:
            return list(
                self.db["announcements"].rows_where("enabled = ?", [1], order_by="id")
            )
        return list(self.db["announcements"].rows_where(order_by="id"))

    def get_announcement_count(self, enabled_only: bool = False) -> int:
        """Get the count of announcements."""
        if enabled_only:
            return self.db.execute(
                "SELECT COUNT(*) FROM announcements WHERE enabled = 1"
            ).fetchone()[0]
        return self.db.execute("SELECT COUNT(*) FROM announcements").fetchone()[0]

    def seed_announcements(self, announcements: list[str], created_by: str = "system"):
        """Seed the database with initial announcements if empty."""
        if self.get_announcement_count() == 0:
            for text in announcements:
                self.add_announcement(text, created_by)
