"""ChromaDB-based semantic retrieval for player memories."""

import logging
from datetime import datetime
from typing import Optional

try:
    import chromadb
    CHROMADB_AVAILABLE = True
except ImportError:
    CHROMADB_AVAILABLE = False

from amc_peripheral.settings import CHROMADB_PATH

log = logging.getLogger(__name__)


class MemoryRetrieval:
    """Semantic search for player conversation memories using ChromaDB."""

    def __init__(self, path: str = CHROMADB_PATH):
        if not CHROMADB_AVAILABLE:
            raise ImportError("chromadb is not installed. Install with: pip install chromadb")
        
        import os
        os.makedirs(path, exist_ok=True)
        
        self.client = chromadb.PersistentClient(path=path)
        self.collection = self.client.get_or_create_collection(
            name="player_memories",
            metadata={"description": "Player conversation memories for semantic search"}
        )
        log.info(f"ChromaDB initialized at {path}")

    def add_memory(
        self,
        player_id: str,
        player_name: str,
        message: str,
        source: str = "game_chat",
        timestamp: Optional[datetime] = None,
        discord_user_id: Optional[str] = None,
        is_bot_response: bool = False,
    ) -> str:
        """Add a memory to ChromaDB for semantic search. Returns the ID."""
        ts = timestamp or datetime.now()
        doc_id = f"{source}_{player_id}_{int(ts.timestamp())}"
        
        self.collection.add(
            documents=[message],
            metadatas=[{
                "player_id": player_id,
                "player_name": player_name,
                "timestamp": ts.isoformat(),
                "source": source,
                "discord_user_id": discord_user_id or "",
                "is_bot_response": is_bot_response,
            }],
            ids=[doc_id]
        )
        return doc_id

    def retrieve_relevant(
        self,
        player_id: str,
        query: str,
        n_results: int = 5,
        sources: Optional[list[str]] = None,
        max_distance: float = 1.5,
    ) -> list[dict]:
        """Retrieve semantically similar memories for a player.
        
        Args:
            player_id: The player to search memories for
            query: The query text to find similar memories
            n_results: Maximum number of results to return
            sources: Optional filter by source types
            max_distance: Maximum distance (lower = more similar)
            
        Returns:
            List of memory dicts with keys: message, player_name, timestamp, distance
        """
        # Build where filter
        where_filter: dict = {"player_id": player_id}
        
        if sources:
            where_filter = {
                "$and": [
                    {"player_id": player_id},
                    {"source": {"$in": sources}}
                ]
            }
        
        results = self.collection.query(
            query_texts=[query],
            n_results=n_results,
            where=where_filter,
            include=["documents", "metadatas", "distances"]
        )
        
        # Format results
        memories = []
        if results["documents"] and results["documents"][0]:
            for i, doc in enumerate(results["documents"][0]):
                distance = results["distances"][0][i] if results["distances"] else 0
                
                # Filter by max distance
                if distance > max_distance:
                    continue
                    
                metadata = results["metadatas"][0][i] if results["metadatas"] else {}
                memories.append({
                    "message": doc,
                    "player_name": metadata.get("player_name", "Unknown"),
                    "timestamp": metadata.get("timestamp", ""),
                    "source": metadata.get("source", ""),
                    "distance": distance,
                    "is_bot_response": metadata.get("is_bot_response", False),
                })
        
        return memories

    def get_memory_count(self, player_id: Optional[str] = None) -> int:
        """Get total memory count, optionally for a specific player."""
        if player_id:
            results = self.collection.get(
                where={"player_id": player_id},
                include=[]
            )
            return len(results["ids"])
        return self.collection.count()

    def delete_player_memories(self, player_id: str) -> int:
        """Delete all memories for a player. Returns count deleted."""
        results = self.collection.get(
            where={"player_id": player_id},
            include=[]
        )
        if results["ids"]:
            self.collection.delete(ids=results["ids"])
            return len(results["ids"])
        return 0
