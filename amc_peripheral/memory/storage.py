"""SQLite storage for player conversation memories."""

import sqlite3
import os
from datetime import datetime
from typing import Optional
from amc_peripheral.settings import MEMORY_DB_PATH, MEMORY_DATA_DIR


class MemoryStorage:
    """Persistent storage for player messages and bot responses."""

    def __init__(self, db_path: str = MEMORY_DB_PATH):
        # Ensure data directory exists
        os.makedirs(os.path.dirname(db_path) or MEMORY_DATA_DIR, exist_ok=True)
        
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        """Create tables if they don't exist."""
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS player_memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                
                -- Player identity
                player_id TEXT NOT NULL,
                player_name TEXT NOT NULL,
                
                -- Message content
                message TEXT NOT NULL,
                is_bot_response INTEGER DEFAULT 0,
                timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
                
                -- Source context (future-proof)
                source TEXT NOT NULL,
                discord_user_id TEXT,
                discord_channel_id TEXT,
                discord_message_id TEXT,
                guild_id TEXT,
                
                -- Memory management
                relevance_score REAL DEFAULT 1.0
            );

            CREATE INDEX IF NOT EXISTS idx_memory_player_id 
                ON player_memory(player_id);
            CREATE INDEX IF NOT EXISTS idx_memory_timestamp 
                ON player_memory(timestamp);
            CREATE INDEX IF NOT EXISTS idx_memory_source 
                ON player_memory(source);
        """)
        self.conn.commit()

    def store_message(
        self,
        player_id: str,
        player_name: str,
        message: str,
        source: str = "game_chat",
        is_bot_response: bool = False,
        timestamp: Optional[datetime] = None,
        discord_user_id: Optional[str] = None,
        discord_channel_id: Optional[str] = None,
        discord_message_id: Optional[str] = None,
        guild_id: Optional[str] = None,
    ) -> int:
        """Store a message in the database. Returns the row ID."""
        ts = (timestamp or datetime.now()).isoformat()
        
        cursor = self.conn.execute(
            """
            INSERT INTO player_memory (
                player_id, player_name, message, is_bot_response, timestamp,
                source, discord_user_id, discord_channel_id, discord_message_id, guild_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                player_id, player_name, message, int(is_bot_response), ts,
                source, discord_user_id, discord_channel_id, discord_message_id, guild_id
            ),
        )
        self.conn.commit()
        return cursor.lastrowid or 0

    def get_recent_messages(
        self,
        player_id: str,
        limit: int = 10,
        sources: Optional[list[str]] = None,
    ) -> list[dict]:
        """Get recent messages for a player, optionally filtered by source."""
        if sources:
            placeholders = ",".join("?" * len(sources))
            query = f"""
                SELECT * FROM player_memory
                WHERE player_id = ? AND source IN ({placeholders})
                ORDER BY timestamp DESC
                LIMIT ?
            """
            params = [player_id, *sources, limit]
        else:
            query = """
                SELECT * FROM player_memory
                WHERE player_id = ?
                ORDER BY timestamp DESC
                LIMIT ?
            """
            params = [player_id, limit]

        cursor = self.conn.execute(query, params)
        rows = cursor.fetchall()
        # Reverse to get chronological order
        return [dict(row) for row in reversed(rows)]

    def get_message_count(self, player_id: Optional[str] = None) -> int:
        """Get total message count, optionally for a specific player."""
        if player_id:
            cursor = self.conn.execute(
                "SELECT COUNT(*) FROM player_memory WHERE player_id = ?",
                (player_id,),
            )
        else:
            cursor = self.conn.execute("SELECT COUNT(*) FROM player_memory")
        return cursor.fetchone()[0]

    def cleanup_old_memories(self, days: int = 90, min_relevance: float = 0.3) -> int:
        """Delete old memories with low relevance. Returns count deleted."""
        cursor = self.conn.execute(
            """
            DELETE FROM player_memory
            WHERE timestamp < datetime('now', ? || ' days')
              AND relevance_score < ?
            """,
            (f"-{days}", min_relevance),
        )
        self.conn.commit()
        return cursor.rowcount

    def decay_relevance_scores(self, decay_rate: float = 0.95) -> int:
        """Apply time-based decay to relevance scores. 
        
        Uses exponential decay: score *= decay_rate ^ days_since_last_update
        Default 0.95 = 5% decay per day.
        
        Returns count of updated rows.
        """
        cursor = self.conn.execute(
            """
            UPDATE player_memory
            SET relevance_score = relevance_score * POWER(?, 
                MAX(1, julianday('now') - julianday(timestamp)))
            WHERE relevance_score > 0.01
            """,
            (decay_rate,),
        )
        self.conn.commit()
        return cursor.rowcount

    def get_memory_stats(self) -> dict:
        """Get statistics about stored memories."""
        cursor = self.conn.execute("""
            SELECT 
                COUNT(*) as total_count,
                COUNT(DISTINCT player_id) as unique_players,
                SUM(CASE WHEN is_bot_response = 1 THEN 1 ELSE 0 END) as bot_responses,
                AVG(relevance_score) as avg_relevance,
                MIN(timestamp) as oldest_memory,
                MAX(timestamp) as newest_memory
            FROM player_memory
        """)
        row = cursor.fetchone()
        return {
            "total_count": row[0],
            "unique_players": row[1],
            "bot_responses": row[2],
            "avg_relevance": row[3],
            "oldest_memory": row[4],
            "newest_memory": row[5],
        }

    def get_low_relevance_count(self, threshold: float = 0.3) -> int:
        """Count memories below relevance threshold (candidates for cleanup)."""
        cursor = self.conn.execute(
            "SELECT COUNT(*) FROM player_memory WHERE relevance_score < ?",
            (threshold,),
        )
        return cursor.fetchone()[0]

    def close(self):
        """Close the database connection."""
        self.conn.close()

