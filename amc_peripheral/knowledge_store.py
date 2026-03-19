"""
Agent-managed knowledge store.

A JSON-backed in-memory dict for game knowledge that the agent can read and write.
Replaces the Discord forum as the source of truth for game knowledge.

Keys use `{type}:{id}` format, e.g.:
- vehicle:Gosan_G7
- guide:delivery-tips
- location:Gangjung
"""

import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from typing import Optional

log = logging.getLogger(__name__)


class KnowledgeStore:
    """JSON-backed knowledge store with in-memory dict for fast access."""

    def __init__(self, file_path: str):
        self.file_path = file_path
        self._data: dict[str, dict] = {}
        self._load()

    def _load(self):
        """Load knowledge from JSON file, or create empty if missing."""
        if os.path.exists(self.file_path):
            try:
                with open(self.file_path, "r") as f:
                    self._data = json.load(f)
                log.info(
                    f"Knowledge store loaded: {len(self._data)} entries "
                    f"from {self.file_path}"
                )
            except (json.JSONDecodeError, OSError) as e:
                log.error(f"Failed to load knowledge store: {e}")
                self._data = {}
        else:
            self._data = {}
            self._flush()
            log.info(f"Knowledge store created at {self.file_path}")

    def _flush(self):
        """Atomic write: temp file + os.replace()."""
        dir_path = os.path.dirname(self.file_path) or "."
        os.makedirs(dir_path, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(
            dir=dir_path, suffix=".tmp", prefix=".knowledge_"
        )
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(self._data, f, indent=2, ensure_ascii=False)
            os.replace(tmp_path, self.file_path)
        except Exception:
            # Clean up temp file on failure
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def get(self, key: str) -> Optional[str]:
        """Get content for a key, or None if not found."""
        entry = self._data.get(key)
        return entry["content"] if entry else None

    def get_batch(self, keys: list[str]) -> dict[str, str]:
        """Get content for multiple keys. Returns {key: content} for found keys."""
        result = {}
        for key in keys:
            entry = self._data.get(key)
            if entry:
                result[key] = entry["content"]
        return result

    def save(self, key: str, content: str, source: str = "agent"):
        """Add or update a knowledge entry and flush to disk."""
        self._data[key] = {
            "content": content,
            "source": source,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self._flush()

    def remove(self, key: str) -> bool:
        """Remove a knowledge entry. Returns True if removed, False if not found."""
        if key not in self._data:
            return False
        del self._data[key]
        self._flush()
        return True

    def search(self, query: str) -> list[tuple[str, str]]:
        """Search keys and content by substring. Returns [(key, content), ...]."""
        if not query:
            return []
        q = query.lower()
        results = []
        for key, entry in self._data.items():
            if q in key.lower() or q in entry["content"].lower():
                results.append((key, entry["content"]))
        return results

    def list_keys(self, type_filter: Optional[str] = None) -> list[str]:
        """List all keys, optionally filtered by type prefix."""
        if type_filter:
            prefix = f"{type_filter}:"
            return [k for k in self._data if k.startswith(prefix)]
        return list(self._data.keys())

    def build_index(self) -> str:
        """Build a compact index string for system prompts.

        Groups entries by type and shows counts + sample keys.
        """
        if not self._data:
            return ""

        # Group by type
        types: dict[str, list[str]] = {}
        for key in self._data:
            parts = key.split(":", 1)
            entry_type = parts[0] if len(parts) == 2 else "other"
            types.setdefault(entry_type, []).append(key)

        lines = [
            "Knowledge store (use lookup_knowledge to search, "
            "list_knowledge to browse by type):"
        ]
        for entry_type, keys in sorted(types.items()):
            # Show count + first few keys as examples
            sample = ", ".join(
                k.split(":", 1)[1] for k in sorted(keys)[:5]
            )
            if len(keys) > 5:
                sample += f", ... (+{len(keys) - 5} more)"
            lines.append(f"- {entry_type} ({len(keys)}): {sample}")

        return "\n".join(lines)
