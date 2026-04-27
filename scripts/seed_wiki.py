#!/usr/bin/env python3
"""
Bootstrap Annie's wiki from existing data sources.

Idempotent — safe to run on every startup. Skips already-seeded pages.

Sources:
- Legacy `knowledge.json` file (if present) -> concept:/vehicle:/guide: pages
- player_memories -> player: pages (top players by message count)
- Radio DB -> song: pages (popular songs, frequent requesters)

Note: the legacy `KnowledgeStore` Python module has been removed. This
script reads the raw `knowledge.json` file directly if it still exists on
disk, so one-off migrations keep working until the file is archived.
"""

import json
import os
import sys
import logging

# Add parent directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from amc_peripheral.wiki.storage import WikiStorage
from amc_peripheral.wiki.retrieval import WikiRetrieval
from amc_peripheral.wiki.ingest import WikiIngest
from amc_peripheral.wiki.index import WikiIndex
from amc_peripheral.settings import (
    WIKI_DB_PATH,
    WIKI_CHROMADB_PATH,
    MEMORY_DB_PATH,
    RADIO_DB_PATH,
)
from amc_peripheral.memory.storage import MemoryStorage
from amc_peripheral.db import RadioDB

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


def seed_from_legacy_knowledge_json(wiki_ingest: WikiIngest, knowledge_path: str) -> int:
    """Migrate legacy `knowledge.json` entries into wiki pages.

    The file format is `{key: {content: str, ...}}` where `key` is
    `{type}:{id}`. Idempotent — skips entries already present.
    """
    count = 0
    try:
        with open(knowledge_path, "r") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        log.warning(f"Failed to read legacy knowledge.json at {knowledge_path}: {e}")
        return 0

    if not isinstance(data, dict):
        log.warning(f"Legacy knowledge.json has unexpected shape: {type(data).__name__}")
        return 0

    for key, entry in data.items():
        # Skip if already seeded (use canonical slug)
        if wiki_ingest.storage.get_page_by_slug(key):
            continue

        if not isinstance(entry, dict):
            continue
        content = entry.get("content")
        if not content:
            continue

        # Determine category from key prefix
        parts = key.split(":", 1)
        category = parts[0] if len(parts) == 2 else "concept"
        title = key

        page_id = wiki_ingest.storage.create_page(
            title=title,
            category=category,
            content=content,
            summary=f"Migrated from legacy knowledge.json: {key}",
        )
        wiki_ingest.storage.add_source(page_id, "knowledge_store", key)
        refreshed = wiki_ingest.storage.get_page_by_id(page_id)
        wiki_ingest.retrieval.index_page(
            page_id=page_id,
            title=title,
            content=content,
            category=category,
            updated_at=refreshed["updated_at"] if refreshed else "",
        )
        count += 1
        log.info(f"Seeded {category} page: {title}")

    return count


def seed_from_player_memories(wiki_ingest: WikiIngest, memory_storage: MemoryStorage, top_n: int = 20) -> int:
    """Synthesize top players from player_memories into player: pages."""
    count = 0

    # Get player message counts
    conn = memory_storage.conn
    cursor = conn.execute(
        """
        SELECT player_id, player_name, COUNT(*) as msg_count
        FROM player_memory
        WHERE is_bot_response = 0
        GROUP BY player_id
        ORDER BY msg_count DESC
        LIMIT ?
        """,
        (top_n,),
    )
    top_players = cursor.fetchall()

    for row in top_players:
        player_id = row["player_id"]
        player_name = row["player_name"]
        msg_count = row["msg_count"]

        # Use canonical slug lookup
        if wiki_ingest.storage.get_page_by_slug(f"player:{player_id}"):
            continue

        # Get recent messages for summary
        recent = memory_storage.get_recent_messages(player_id, limit=5)
        recent_snippets = "\n".join(
            f"- {'Bot' if m['is_bot_response'] else player_name}: {m['message'][:100]}"
            for m in recent
        )

        content = (
            f"Player: {player_name} (ID: {player_id})\n\n"
            f"Total interactions: {msg_count}\n\n"
            f"Recent messages:\n{recent_snippets}"
        )

        page_id = wiki_ingest.storage.create_page(
            title=f"player:{player_id}",
            category="player",
            content=content,
            summary=f"Player with {msg_count} interactions",
        )
        wiki_ingest.storage.add_source(page_id, "player_memories", player_id)
        refreshed = wiki_ingest.storage.get_page_by_id(page_id)
        wiki_ingest.retrieval.index_page(
            page_id=page_id,
            title=f"player:{player_id}",
            content=content,
            category="player",
            updated_at=refreshed["updated_at"] if refreshed else "",
        )
        count += 1
        log.info(f"Seeded player page: {player_name} ({msg_count} messages)")

    return count


def seed_from_radio_db(wiki_ingest: WikiIngest, radio_db: RadioDB, top_songs: int = 10) -> int:
    """Ingest radio DB stats into song: pages."""
    count = 0

    # Top requested songs
    top_requested = radio_db.get_top_requested_songs(limit=top_songs)
    for song in top_requested:
        title = song["song_title"]
        request_count = song["request_count"]

        if wiki_ingest.storage.get_page_by_slug(f"song:{title}"):
            continue

        content = (
            f"Song: {title}\n\n"
            f"Request count: {request_count}\n"
            f"Popular on Radio ASEAN."
        )

        page_id = wiki_ingest.storage.create_page(
            title=f"song:{title}",
            category="song",
            content=content,
            summary=f"Requested {request_count} times on the radio",
        )
        wiki_ingest.storage.add_source(page_id, "radio_db", f"song_requests:{title}")
        refreshed = wiki_ingest.storage.get_page_by_id(page_id)
        wiki_ingest.retrieval.index_page(
            page_id=page_id,
            title=f"song:{title}",
            content=content,
            category="song",
            updated_at=refreshed["updated_at"] if refreshed else "",
        )
        count += 1
        log.info(f"Seeded song page: {title} ({request_count} requests)")

    # Top liked songs
    top_liked = radio_db.get_top_liked_songs(limit=top_songs)
    for song in top_liked:
        title = song["song_title"]
        like_count = song["like_count"]

        existing = wiki_ingest.storage.get_page_by_slug(f"song:{title}")
        if existing:
            # Update existing song page with like info
            new_content = (
                f"{existing['content']}\n\n"
                f"Likes: {like_count}"
            )
            wiki_ingest.storage.update_page(existing["id"], content=new_content)
            refreshed = wiki_ingest.storage.get_page_by_id(existing["id"])
            wiki_ingest.retrieval.index_page(
                page_id=existing["id"],
                title=existing["title"],
                content=new_content,
                category="song",
                updated_at=refreshed["updated_at"] if refreshed else "",
            )
        else:
            content = (
                f"Song: {title}\n\n"
                f"Likes: {like_count}\n"
                f"Liked on Radio ASEAN."
            )
            page_id = wiki_ingest.storage.create_page(
                title=f"song:{title}",
                category="song",
                content=content,
                summary=f"Liked {like_count} times on the radio",
            )
            wiki_ingest.storage.add_source(page_id, "radio_db", f"song_likes:{title}")
            refreshed = wiki_ingest.storage.get_page_by_id(page_id)
            wiki_ingest.retrieval.index_page(
                page_id=page_id,
                title=f"song:{title}",
                content=content,
                category="song",
                updated_at=refreshed["updated_at"] if refreshed else "",
            )
            count += 1
            log.info(f"Seeded song page (likes): {title} ({like_count} likes)")

    return count


def main():
    """Run the wiki seeding process."""
    log.info("Starting wiki seed...")

    storage = WikiStorage(db_path=WIKI_DB_PATH)
    retrieval = WikiRetrieval(path=WIKI_CHROMADB_PATH)
    ingest = WikiIngest(storage=storage, retrieval=retrieval)
    index = WikiIndex(storage=storage)

    total_seeded = 0

    # Seed from legacy knowledge.json if available
    knowledge_path = os.path.join(os.path.dirname(WIKI_DB_PATH), "knowledge.json")
    if os.path.exists(knowledge_path):
        log.info(f"Seeding from legacy knowledge.json: {knowledge_path}")
        try:
            total_seeded += seed_from_legacy_knowledge_json(ingest, knowledge_path)
        except Exception as e:
            log.warning(f"Failed to seed from legacy knowledge.json: {e}")
    else:
        log.info("Legacy knowledge.json not found, skipping.")

    # Seed from player_memories if available
    if os.path.exists(MEMORY_DB_PATH):
        log.info(f"Seeding from player_memories: {MEMORY_DB_PATH}")
        try:
            memory_storage = MemoryStorage(db_path=MEMORY_DB_PATH)
            total_seeded += seed_from_player_memories(ingest, memory_storage)
            memory_storage.close()
        except Exception as e:
            log.warning(f"Failed to seed from player_memories: {e}")
    else:
        log.info("player_memories not found, skipping.")

    # Seed from radio DB if available
    if os.path.exists(RADIO_DB_PATH):
        log.info(f"Seeding from radio DB: {RADIO_DB_PATH}")
        try:
            radio_db = RadioDB(RADIO_DB_PATH)
            total_seeded += seed_from_radio_db(ingest, radio_db)
        except Exception as e:
            log.warning(f"Failed to seed from radio DB: {e}")
    else:
        log.info("Radio DB not found, skipping.")

    # Rebuild index
    index.build_index()

    # Log completion
    storage.log_operation(
        operation="seed",
        description=f"Wiki seeded with {total_seeded} pages from existing data",
        pages_affected=None,
    )

    stats = storage.get_stats()
    log.info(f"Wiki seed complete. Total pages: {stats['total_pages']}, categories: {stats['total_categories']}")

    storage.close()


if __name__ == "__main__":
    main()
