from sqlite_utils import Database
from datetime import datetime, timezone

class RadioDB:
    def __init__(self, db_path: str):
        """Initialize the database and ensure tables exist."""
        self.db = Database(db_path)
        self._ensure_tables()

    def _ensure_tables(self):
        """Ensure tables exist with proper structure. sqlite-utils will handle migrations/creation."""
        # Song Requests Table
        if "song_requests" not in self.db.table_names():
            # pyrefly: ignore [missing-attribute]
            self.db["song_requests"].create({
                "id": int,
                "discord_id": str,
                "song_title": str,
                "song_url": str,
                "requester_name": str,
                "requested_at": str
            }, pk="id")
            # pyrefly: ignore [missing-attribute]
            self.db["song_requests"].create_index(["discord_id"])
            # pyrefly: ignore [missing-attribute]
            self.db["song_requests"].create_index(["song_url"])

        # Song Likes Table
        if "song_likes" not in self.db.table_names():
            # pyrefly: ignore [missing-attribute]
            self.db["song_likes"].create({
                "id": int,
                "discord_id": str,
                "song_title": str,
                "song_url": str,
                "liked_at": str,
                "is_liked": int  # 1 for liked, 0 for disliked
            }, pk="id")
            # pyrefly: ignore [missing-attribute]
            self.db["song_likes"].create_index(["discord_id", "song_title"], unique=True)

        # User Language Preferences Table
        if "user_language_preferences" not in self.db.table_names():
            # pyrefly: ignore [missing-attribute]
            self.db["user_language_preferences"].create({
                "discord_id": str,
                "language": str,  # English, Chinese, Indonesian, Thai, Vietnamese, Japanese
                "updated_at": str
            }, pk="discord_id")

    def add_request(self, discord_id: str | None, song_title: str, song_url: str | None, requester_name: str) -> int | None:
        """Record a song request."""
        row = {
            "discord_id": str(discord_id) if discord_id else None,
            "song_title": song_title,
            "song_url": song_url,
            "requester_name": requester_name,
            "requested_at": datetime.now(timezone.utc).isoformat()
        }
        try:
            # pyrefly: ignore [missing-attribute]
            return self.db["song_requests"].insert(row).last_pk
        except Exception:
            return None

    def get_requests_by_user(self, discord_id: str, limit: int = 50) -> list[dict]:
        """Get recent requests by a specific user."""
        return list(self.db["song_requests"].rows_where(
            "discord_id = ?", [str(discord_id)], order_by="requested_at desc", limit=limit
        ))

    def get_top_requested_songs(self, limit: int = 10) -> list[dict]:
        """Get the most frequently requested songs."""
        query = """
            SELECT song_title, song_url, COUNT(*) as request_count
            FROM song_requests
            GROUP BY song_url, song_title
            ORDER BY request_count DESC
            LIMIT ?
        """
        return list(self.db.query(query, [limit]))

    def add_like(self, discord_id: str, song_title: str, song_url: str | None = None) -> int | None:
        """Add or restore a like for a song."""
        row = {
            "discord_id": str(discord_id),
            "song_title": song_title,
            "song_url": song_url,
            "liked_at": datetime.now(timezone.utc).isoformat(),
            "is_liked": 1
        }
        try:
            # pyrefly: ignore [missing-attribute]
            return self.db["song_likes"].upsert(row, pk=("discord_id", "song_title")).last_pk
        except Exception:
            return None

    def add_dislike(self, discord_id: str, song_title: str) -> bool:
        """Mark a song as disliked."""
        # We need to ensure the row exists because you can dislike without having liked it first?
        # Actually, let's keep it as an upsert to support independent dislikes.
        row = {
            "discord_id": str(discord_id),
            "song_title": song_title,
            "liked_at": datetime.now(timezone.utc).isoformat(),
            "is_liked": 0 # 0 for dislike
        }
        try:
            # pyrefly: ignore [missing-attribute]
            self.db["song_likes"].upsert(row, pk=("discord_id", "song_title"))
            return True
        except Exception:
            return False

    def get_likes_by_user(self, discord_id: str) -> list[dict]:
        """Get all songs liked by a user."""
        return list(self.db["song_likes"].rows_where(
            "discord_id = ?", [str(discord_id)], order_by="liked_at desc"
        ))

    def get_top_liked_songs(self, limit: int = 10) -> list[dict]:
        """Get songs with the most active likes."""
        query = """
            SELECT song_title, song_url, COUNT(*) as like_count
            FROM song_likes
            WHERE is_liked = 1
            GROUP BY song_title, song_url
            ORDER BY like_count DESC
            LIMIT ?
        """
        return list(self.db.query(query, [limit]))

    def get_all_song_stats(self) -> list[dict]:
        """Get stats for all songs that have any likes or unlikes."""
        query = """
            SELECT 
                song_title, 
                SUM(CASE WHEN is_liked = 1 THEN 1 ELSE 0 END) as like_count,
                SUM(CASE WHEN is_liked = 0 THEN 1 ELSE 0 END) as dislike_count
            FROM song_likes
            GROUP BY song_title
            ORDER BY like_count DESC, dislike_count DESC
        """
        return list(self.db.query(query))

    def set_user_language(self, discord_id: str, language: str) -> bool:
        """Set or update user's preferred language."""
        row = {
            "discord_id": str(discord_id),
            "language": language,
            "updated_at": datetime.now(timezone.utc).isoformat()
        }
        try:
            # pyrefly: ignore [missing-attribute]
            self.db["user_language_preferences"].upsert(row, pk="discord_id")
            return True
        except Exception:
            return False

    def get_user_language(self, discord_id: str) -> str | None:
        """Get user's preferred language, returns None if not set."""
        rows = list(self.db["user_language_preferences"].rows_where(
            "discord_id = ?", [str(discord_id)]
        ))
        if rows:
            return rows[0]["language"]
        return None
