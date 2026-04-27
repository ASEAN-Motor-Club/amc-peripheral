# amc_peripheral — Agent Guide

Core Python package for all ASEAN Motor Club peripheral services. Contains three independent Discord bots, a radio REST API, and shared data/utility layers.

## Package Layout

```
amc_peripheral/
├── settings.py          # All config — env vars, channel IDs, paths, AI models
├── bot/                 # Annie (main community bot)
│   ├── bot.py           # AMCBot entry point (amc_bot)
│   ├── knowledge_cog.py # Agentic AI cog — game knowledge, tool use, chat
│   ├── translation_cog.py  # Auto-translation across language channels
│   ├── utils_cog.py     # /timezone, /save, /playerinfo, announcements
│   ├── share_cog.py     # Sharry file-sharing integration
│   ├── youtube_cog.py   # YouTube transcript & search
│   ├── backend_db.py    # Read-only PostgreSQL access to amc-backend (via Tailscale)
│   ├── game_db.py       # Read-only SQLite access to gamedata.db
│   └── ai_models.py     # OpenRouter LLM helpers
├── radio/               # Radio bot + web API
│   ├── radio.py         # AMCBot entry point for radio (amc_radio)
│   ├── radio_cog.py     # Full radio logic — song requests, downloads, queue, TTS
│   ├── api.py           # aiohttp REST API for Discord Activity (radio-web)
│   ├── radio_server.py  # Icecast metadata helpers
│   ├── liquidsoap.py    # Liquidsoap telnet control
│   ├── game_knowledge.py  # Game knowledge for radio DJ context
│   └── tts.py           # Text-to-speech (ElevenLabs, Google Cloud TTS)
├── devbot/              # JARVIS (dev bot)
│   ├── devbot.py        # AMCDevBot entry point (amc_jarvis)
│   ├── devbot_cog.py    # Codebase chat, search, and dev tooling
│   └── codebase_tools.py  # File search, grep, git tools for LLM agents
├── db.py                # RadioDB — SQLite (sqlite-utils) for radio state
├── announcements.py     # AnnouncementsDB — configurable in-game announcements
├── memory/              # Long-term player memory
│   ├── storage.py       # MemoryStorage — SQLite for conversation history
│   └── retrieval.py     # ChromaDB semantic retrieval
├── wiki/                # Annie's self-maintained wiki (replaces KnowledgeStore)
│   ├── storage.py       # WikiStorage — SQLite pages, links, sources, log
│   ├── retrieval.py     # WikiRetrieval — ChromaDB semantic search
│   ├── index.py         # WikiIndex — compact prompt-context index
│   ├── ingest.py        # WikiIngest — raw source → wiki updates
│   ├── lint.py          # WikiLint — orphan/stale/contradiction scans
│   ├── export.py        # WikiExporter — markdown export for humans
│   └── synthesis.py     # WikiSynthesizer — weekly State of the Community
└── utils/               # Shared helpers
    ├── discord_utils.py
    ├── game_utils.py
    ├── json_utils.py
    ├── rate_limiter.py
    ├── save.py
    └── text_utils.py
```

## Entry Points

Defined in `pyproject.toml` → `[project.scripts]`:

| Command      | Module                          | Service           |
|--------------|---------------------------------|-------------------|
| `amc_bot`    | `amc_peripheral.bot.bot:main`   | Annie (community) |
| `amc_radio`  | `amc_peripheral.radio.radio:main` | Radio bot + API |
| `amc_jarvis` | `amc_peripheral.devbot.devbot:main` | JARVIS (dev)   |

All three are independent `discord.py` bots running as separate systemd services on the `amc-peripheral` server.

## Key Concepts

### Data Layer

- **`RadioDB`** (`db.py`) — SQLite via `sqlite-utils`. Tables: `song_requests`, `song_likes`, `user_language_preferences`, `auto_queued_songs`, `generated_news`, `generated_jingles`, `user_playlists`, `playlist_songs`, `downloaded_songs`. Used by `radio_cog.py`.
- **Annie's Wiki** (`wiki/`) — SQLite (`annie_wiki.db`) + ChromaDB (`annie_wiki_chromadb/`). Replaces the legacy `KnowledgeStore` JSON. Pages use `{type}:{id}` slugs (e.g. `vehicle:Gosan_G7`). Accessed through `WikiStorage`/`WikiRetrieval`/`WikiIndex`/`WikiIngest`.
- **`AnnouncementsDB`** (`announcements.py`) — SQLite for configurable in-game announcement rotation.
- **`MemoryStorage`** (`memory/storage.py`) — SQLite for player conversation history with relevance scoring and time-based decay.
- **`backend_db.py`** — Read-only PostgreSQL connector to the `amc-backend` database over Tailscale. Multi-layered safety: keyword blocking, SELECT-only enforcement, connection-level `read_only`, and DB-level RLS.

### Radio API

`radio/api.py` runs an **aiohttp** server (`127.0.0.1:7001`) in the same event loop as the radio Discord bot. Exposes REST endpoints for the SvelteKit Discord Activity (`radio-web/`). Auth via Discord OAuth2 token exchange + `access_token` validation.

### Configuration

All config lives in `settings.py`, loaded from environment variables with sensible defaults. On the NixOS server, env vars are injected via the systemd service unit. For local dev, use a `.env` file.

## Development

> [!IMPORTANT]
> This is a NixOS-managed project. **Do not use `uv sync`** to create a venv. Use the Nix dev shell instead — it provides the correct Python, all dependencies, and tooling.

```bash
# Enter dev shell (auto via direnv, or manually)
nix develop

# Run tests
pytest

# Lint + format
ruff check . && ruff format --check .

# Type check
pyrefly check .
```

Python dependencies are managed via **uv2nix** — see `flake.nix` for the packaging. Add deps to `pyproject.toml`, run `uv lock`, then the Nix shell picks them up.

## Testing

Tests live in `tests/` at the repo root. Uses `pytest` + `pytest-asyncio` + `dpytest`.

```bash
# All tests
pytest

# Specific test
pytest tests/test_knowledge_cog.py
```

## Operations

- **Secrets** are managed with `ragenix` (encrypted, committed to the repo). Editing secrets requires the user.
- **Deployments** use `nixos-rebuild` via the monorepo `deploy` script. Ask the user to deploy.
- **Service restarts** — NixOS services use `restartIfChanged`. Changes to service-linked Nix files (e.g. `radio/liquidsoap.nix`, service module configs) will **restart that service** on deploy.

## Patterns & Conventions

- **Cogs** are the primary unit of bot functionality. Each cog is self-contained with its own slash commands and background tasks.
- **AI tools** in `knowledge_cog.py` follow an agentic loop pattern: the LLM calls tools iteratively until it produces a final response (`BOT_MAX_ITERATIONS` cap).
- **`# pyrefly: ignore`** comments are used where `pyrefly` cannot resolve dynamic `sqlite-utils` attribute access.
- **systemd notify** — bots send `READY=1` to systemd on `on_ready()` for `Type=notify` service health.
