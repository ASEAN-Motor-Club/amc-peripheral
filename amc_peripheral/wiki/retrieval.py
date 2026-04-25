"""ChromaDB-based semantic retrieval for wiki pages."""

import logging
from typing import Optional

try:
    import chromadb
    CHROMADB_AVAILABLE = True
except ImportError:
    CHROMADB_AVAILABLE = False

from amc_peripheral.settings import WIKI_CHROMADB_PATH

log = logging.getLogger(__name__)


class WikiRetrieval:
    """Semantic search for wiki pages using ChromaDB."""

    def __init__(self, path: str = WIKI_CHROMADB_PATH):
        if not CHROMADB_AVAILABLE:
            raise ImportError("chromadb is not installed. Install with: pip install chromadb")

        import os
        os.makedirs(path, exist_ok=True)

        self.client = chromadb.PersistentClient(path=path)
        self.collection = self.client.get_or_create_collection(
            name="wiki_pages",
            metadata={"description": "Annie's wiki pages for semantic search"}
        )
        log.info(f"Wiki ChromaDB initialized at {path}")

    def index_page(
        self,
        page_id: int,
        title: str,
        content: str,
        category: str,
        updated_at: str,
    ) -> str:
        """Add or update a wiki page in the ChromaDB index. Returns the doc ID."""
        doc_id = f"wiki_page_{page_id}"
        self.collection.upsert(
            documents=[content],
            metadatas=[{
                "page_id": page_id,
                "title": title,
                "category": category,
                "updated_at": updated_at,
            }],
            ids=[doc_id]
        )
        return doc_id

    def remove_page(self, page_id: int) -> bool:
        """Remove a wiki page from the ChromaDB index."""
        doc_id = f"wiki_page_{page_id}"
        try:
            self.collection.delete(ids=[doc_id])
            return True
        except Exception:
            return False

    def search(
        self,
        query: str,
        n_results: int = 5,
        category: Optional[str] = None,
        max_distance: float = 1.5,
    ) -> list[dict]:
        """Search wiki pages by semantic similarity.

        Args:
            query: The query text.
            n_results: Maximum number of results.
            category: Optional category filter.
            max_distance: Maximum distance (lower = more similar).

        Returns:
            List of result dicts with keys: page_id, title, category, content, distance.
        """
        where_filter = None
        if category:
            where_filter = {"category": category}

        results = self.collection.query(
            query_texts=[query],
            n_results=n_results,
            where=where_filter,
            include=["documents", "metadatas", "distances"]
        )

        pages = []
        if results["documents"] and results["documents"][0]:
            for i, doc in enumerate(results["documents"][0]):
                distance = results["distances"][0][i] if results["distances"] else 0
                if distance > max_distance:
                    continue
                metadata = results["metadatas"][0][i] if results["metadatas"] else {}
                pages.append({
                    "page_id": metadata.get("page_id"),
                    "title": metadata.get("title", ""),
                    "category": metadata.get("category", ""),
                    "content": doc,
                    "distance": distance,
                    "updated_at": metadata.get("updated_at", ""),
                })
        return pages

    def get_indexed_count(self) -> int:
        """Get the number of indexed pages."""
        return self.collection.count()

    def clear_index(self) -> bool:
        """Clear all indexed pages. Use with caution."""
        try:
            self.client.delete_collection("wiki_pages")
            self.collection = self.client.get_or_create_collection(
                name="wiki_pages",
                metadata={"description": "Annie's wiki pages for semantic search"}
            )
            return True
        except Exception:
            return False
