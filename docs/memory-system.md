# Memory System

Long-term memory for the Discord bot, enabling personalized conversations with players.

## Overview

The memory system stores all in-game chat messages and bot responses, enabling the bot to:
- Remember past conversations per player
- Provide context-aware responses
- Track interaction history across sessions

## Architecture

```
┌──────────────────┐     SSE      ┌─────────────────┐
│  amc-backend     │ ──────────▶  │  amc-peripheral │
│ /api/bot_events/ │              │  KnowledgeCog   │
└──────────────────┘              └────────┬────────┘
                                           │
                    ┌──────────────────────┼──────────────────────┐
                    ▼                      ▼                      ▼
            ┌───────────────┐     ┌───────────────┐     ┌────────────────┐
            │ SQLite        │     │ ChromaDB      │     │ In-Memory      │
            │ (raw storage) │     │ (semantic)    │     │ (recent msgs)  │
            └───────────────┘     └───────────────┘     └────────────────┘
```

## Configuration

Set via environment variables (NixOS: use `StateDirectory`):

```bash
# Data directory (NixOS: /var/lib/amc-peripheral)
MEMORY_DATA_DIR=/var/lib/amc-peripheral

# Derived paths (auto-configured)
# MEMORY_DB_PATH   = $MEMORY_DATA_DIR/player_memories.db
# CHROMADB_PATH    = $MEMORY_DATA_DIR/chromadb
```

**NixOS Service Configuration:**
```nix
systemd.services.amc-peripheral = {
  serviceConfig.StateDirectory = "amc-peripheral";
  environment.MEMORY_DATA_DIR = "/var/lib/amc-peripheral";
};
```

## Database Schema

```sql
CREATE TABLE player_memory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id TEXT NOT NULL,          -- Game player_id or Discord user_id
    player_name TEXT NOT NULL,
    message TEXT NOT NULL,
    is_bot_response INTEGER DEFAULT 0,
    timestamp TEXT,
    source TEXT NOT NULL,             -- 'game_chat', 'discord_dm', 'discord_channel'
    discord_user_id TEXT,             -- For linking game/Discord identities
    discord_channel_id TEXT,
    discord_message_id TEXT,
    guild_id TEXT,
    relevance_score REAL DEFAULT 1.0
);
```

## Usage

### Storing Messages

Messages are automatically stored when received via SSE from the backend:

```python
from amc_peripheral.memory.storage import MemoryStorage

storage = MemoryStorage()
storage.store_message(
    player_id="123",
    player_name="PlayerName",
    message="Hello bot!",
    source="game_chat",
    discord_user_id="987654321",  # optional
)
```

### Retrieving Messages

```python
# Get last 10 messages for a player
messages = storage.get_recent_messages("123", limit=10)

# Filter by source
game_only = storage.get_recent_messages("123", sources=["game_chat"])
```

### Cleanup

```python
# Delete old low-relevance memories (90+ days, score < 0.3)
deleted = storage.cleanup_old_memories(days=90, min_relevance=0.3)
```

## Semantic Search (ChromaDB)

ChromaDB provides similarity-based retrieval of past conversations:

```python
from amc_peripheral.memory.retrieval import MemoryRetrieval

retrieval = MemoryRetrieval()

# Add memory (embedding auto-generated)
retrieval.add_memory(
    player_id="123",
    player_name="PlayerName",
    message="I love driving buses!",
    source="game_chat",
)

# Query similar past conversations
memories = retrieval.retrieve_relevant(
    player_id="123",
    query="What vehicle should I buy?",
    n_results=5,
    max_distance=1.5,  # Lower = more similar
)
# Returns: [{"message": "I love driving buses!", "distance": 0.4, ...}]
```

## Decay and Cleanup (Phase 1c)

The memory system uses time-based relevance decay to prioritize recent memories:

```python
# Apply exponential decay (5% per day by default)
updated = storage.decay_relevance_scores(decay_rate=0.95)

# Get statistics about stored memories
stats = storage.get_memory_stats()
# Returns: {total_count, unique_players, bot_responses, avg_relevance, ...}

# Check how many memories are candidates for cleanup
low_relevance_count = storage.get_low_relevance_count(threshold=0.3)

# Delete old memories with low relevance
deleted = storage.cleanup_old_memories(days=90, min_relevance=0.3)
```

## Testing

```bash
pytest tests/test_memory_storage.py -v
```
