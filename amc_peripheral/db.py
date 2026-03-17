from sqlite_utils import Database
from datetime import datetime, timezone, timedelta

class RadioDB:
    def __init__(self, db_path: str):
        """Initialize the database and ensure tables exist."""
        self.db = Database(db_path)
        self.db.conn.execute("PRAGMA busy_timeout = 5000")
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

        # Auto-Queued Songs Table (for dedup tracking)
        if "auto_queued_songs" not in self.db.table_names():
            # pyrefly: ignore [missing-attribute]
            self.db["auto_queued_songs"].create({
                "id": int,
                "song_title": str,
                "queued_at": str,
            }, pk="id")
            # pyrefly: ignore [missing-attribute]
            self.db["auto_queued_songs"].create_index(["queued_at"])

        # Generated News Table
        if "generated_news" not in self.db.table_names():
            # pyrefly: ignore [missing-attribute]
            self.db["generated_news"].create({
                "id": int,
                "content": str,
                "audio_filename": str,
                "generated_at": str,
            }, pk="id")
            # pyrefly: ignore [missing-attribute]
            self.db["generated_news"].create_index(["generated_at"])

        # Generated Jingles Table
        if "generated_jingles" not in self.db.table_names():
            # pyrefly: ignore [missing-attribute]
            self.db["generated_jingles"].create({
                "id": int,
                "script": str,
                "audio_filename": str,
                "generated_at": str,
            }, pk="id")
            # pyrefly: ignore [missing-attribute]
            self.db["generated_jingles"].create_index(["generated_at"])

        # User Playlists Table
        if "user_playlists" not in self.db.table_names():
            # pyrefly: ignore [missing-attribute]
            self.db["user_playlists"].create({
                "id": int,
                "discord_id": str,
                "name": str,
                "created_at": str,
            }, pk="id")
            # pyrefly: ignore [missing-attribute]
            self.db["user_playlists"].create_index(["discord_id", "name"], unique=True)

        # Playlist Songs Table
        if "playlist_songs" not in self.db.table_names():
            # pyrefly: ignore [missing-attribute]
            self.db["playlist_songs"].create({
                "id": int,
                "playlist_id": int,
                "song_query": str,
                "song_title": str,
                "position": int,
                "added_at": str,
            }, pk="id")
            # pyrefly: ignore [missing-attribute]
            self.db["playlist_songs"].create_index(["playlist_id"])

        # Downloaded Songs Cache Table
        if "downloaded_songs" not in self.db.table_names():
            # pyrefly: ignore [missing-attribute]
            self.db["downloaded_songs"].create({
                "id": int,
                "video_id": str,
                "title": str,
                "duration": int,
                "local_path": str,
                "webpage_url": str,
                "file_size": int,
                "downloaded_at": str,
                "last_used_at": str,
            }, pk="id")
            # pyrefly: ignore [missing-attribute]
            self.db["downloaded_songs"].create_index(["video_id"], unique=True)

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

    def get_song_like_count(self, song_title: str) -> int:
        """Get the number of active likes for a specific song."""
        result = list(self.db.query(
            "SELECT COUNT(*) as cnt FROM song_likes WHERE song_title = ? AND is_liked = 1",
            [song_title],
        ))
        return result[0]["cnt"] if result else 0

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

    def add_auto_queue(self, song_title: str) -> int | None:
        """Record an auto-queued song for dedup tracking."""
        row = {
            "song_title": song_title,
            "queued_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            # pyrefly: ignore [missing-attribute]
            return self.db["auto_queued_songs"].insert(row).last_pk
        except Exception:
            return None

    def get_recent_auto_queued(self, hours: int = 24) -> list[dict]:
        """Get auto-queued songs from the last N hours."""
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        return list(self.db["auto_queued_songs"].rows_where(
            "queued_at > ?", [cutoff], order_by="queued_at desc"
        ))

    def add_news(self, content: str, audio_filename: str | None = None) -> int | None:
        """Record a generated news segment."""
        row = {
            "content": content,
            "audio_filename": audio_filename,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            # pyrefly: ignore [missing-attribute]
            return self.db["generated_news"].insert(row).last_pk
        except Exception:
            return None

    def get_recent_news(self, limit: int = 5) -> list[dict]:
        """Get recent generated news segments."""
        return list(self.db["generated_news"].rows_where(
            order_by="generated_at desc", limit=limit
        ))

    def add_jingle(self, script: str, audio_filename: str | None = None) -> int | None:
        """Record a generated jingle."""
        row = {
            "script": script,
            "audio_filename": audio_filename,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            # pyrefly: ignore [missing-attribute]
            return self.db["generated_jingles"].insert(row).last_pk
        except Exception:
            return None

    def get_recent_jingles(self, limit: int = 10) -> list[dict]:
        """Get recent generated jingles."""
        return list(self.db["generated_jingles"].rows_where(
            order_by="generated_at desc", limit=limit
        ))

    # --- User Playlists ---

    def create_playlist(self, discord_id: str, name: str) -> int:
        """Create a new playlist. Raises Exception if name already exists for this user."""
        normalized = name.strip().lower()
        row = {
            "discord_id": str(discord_id),
            "name": normalized,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            # pyrefly: ignore [missing-attribute]
            return self.db["user_playlists"].insert(row).last_pk
        except Exception:
            raise Exception(f"Playlist '{normalized}' already exists.")

    def delete_playlist(self, discord_id: str, name: str) -> bool:
        """Delete a playlist and all its songs. Returns True if found and deleted."""
        normalized = name.strip().lower()
        rows = list(self.db["user_playlists"].rows_where(
            "discord_id = ? AND name = ?", [str(discord_id), normalized]
        ))
        if not rows:
            return False
        playlist_id = rows[0]["id"]
        # Delete songs first
        self.db.execute("DELETE FROM playlist_songs WHERE playlist_id = ?", [playlist_id])
        # pyrefly: ignore [missing-attribute]
        self.db["user_playlists"].delete(playlist_id)
        return True

    def get_playlist_by_name(self, discord_id: str, name: str) -> dict | None:
        """Get a playlist by owner and name."""
        normalized = name.strip().lower()
        rows = list(self.db["user_playlists"].rows_where(
            "discord_id = ? AND name = ?", [str(discord_id), normalized]
        ))
        return rows[0] if rows else None

    def get_playlists(self, discord_id: str) -> list[dict]:
        """Get all playlists for a user."""
        query = """
            SELECT p.*, COUNT(s.id) as song_count
            FROM user_playlists p
            LEFT JOIN playlist_songs s ON s.playlist_id = p.id
            WHERE p.discord_id = ?
            GROUP BY p.id
            ORDER BY p.created_at DESC
        """
        return list(self.db.query(query, [str(discord_id)]))

    def add_song_to_playlist(self, playlist_id: int, song_query: str, song_title: str) -> int | None:
        """Add a song to a playlist. Position is auto-assigned."""
        # Get next position
        existing = list(self.db["playlist_songs"].rows_where(
            "playlist_id = ?", [playlist_id], order_by="position desc", limit=1
        ))
        next_pos = (existing[0]["position"] + 1) if existing else 1

        row = {
            "playlist_id": playlist_id,
            "song_query": song_query,
            "song_title": song_title,
            "position": next_pos,
            "added_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            # pyrefly: ignore [missing-attribute]
            return self.db["playlist_songs"].insert(row).last_pk
        except Exception:
            return None

    def remove_song_from_playlist(self, playlist_id: int, song_title: str) -> bool:
        """Remove a song from a playlist by title."""
        rows = list(self.db["playlist_songs"].rows_where(
            "playlist_id = ? AND song_title = ?", [playlist_id, song_title]
        ))
        if not rows:
            return False
        # pyrefly: ignore [missing-attribute]
        self.db["playlist_songs"].delete(rows[0]["id"])
        return True

    def get_playlist_songs(self, playlist_id: int) -> list[dict]:
        """Get all songs in a playlist, ordered by position."""
        return list(self.db["playlist_songs"].rows_where(
            "playlist_id = ?", [playlist_id], order_by="position asc"
        ))

    # --- Download Cache ---

    def get_cached_song(self, video_id: str) -> dict | None:
        """Get a cached song by video_id. Updates last_used_at on hit."""
        rows = list(self.db["downloaded_songs"].rows_where(
            "video_id = ?", [video_id]
        ))
        if not rows:
            return None
        # Update last_used_at
        self.db.execute(
            "UPDATE downloaded_songs SET last_used_at = ? WHERE video_id = ?",
            [datetime.now(timezone.utc).isoformat(), video_id],
        )
        return rows[0]

    def cache_song(self, video_id: str, title: str, duration: int, local_path: str, webpage_url: str, file_size: int) -> int | None:
        """Cache a downloaded song. Returns the row id."""
        now = datetime.now(timezone.utc).isoformat()
        row = {
            "video_id": video_id,
            "title": title,
            "duration": duration,
            "local_path": local_path,
            "webpage_url": webpage_url,
            "file_size": file_size,
            "downloaded_at": now,
            "last_used_at": now,
        }
        try:
            # pyrefly: ignore [missing-attribute]
            return self.db["downloaded_songs"].insert(row, replace=True).last_pk
        except Exception:
            return None

    def get_cache_stats(self) -> dict:
        """Get total file count and total bytes in the cache."""
        result = list(self.db.query(
            "SELECT COUNT(*) as total_files, COALESCE(SUM(file_size), 0) as total_bytes FROM downloaded_songs"
        ))
        return result[0] if result else {"total_files": 0, "total_bytes": 0}

    def get_oldest_cached_songs(self, limit: int = 10) -> list[dict]:
        """Get the least recently used cached songs."""
        return list(self.db["downloaded_songs"].rows_where(
            order_by="last_used_at asc", limit=limit
        ))

    def delete_cached_song(self, video_id: str) -> bool:
        """Delete a cached song entry by video_id."""
        rows = list(self.db["downloaded_songs"].rows_where(
            "video_id = ?", [video_id]
        ))
        if not rows:
            return False
        # pyrefly: ignore [missing-attribute]
        self.db["downloaded_songs"].delete(rows[0]["id"])
        return True
