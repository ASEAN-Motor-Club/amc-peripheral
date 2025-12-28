# MotorTown Backend

This repository contains the backend services and Discord bot for the ASEAN Motor Club's MotorTown community.

## Dependency Management with `uv`

This project uses [uv](https://github.com/astral-sh/uv) for fast, reliable Python package management and project isolation.

### Installation

If you don't have `uv` installed, you can install it using:

```bash
curl -LsSf https://astral-sh.uv/install.sh | sh
```

### Project Setup

To install all dependencies (including development dependencies) and create a local virtual environment:

```bash
uv sync
```

### Running the Bot

To run the bot using the entry points defined in `pyproject.toml`:

```bash
uv run motortown_knowledge
```

## Testing

We use `pytest` along with `pytest-asyncio` and `dpytest` to verify the bot's functionality and Cog logic.

### Running All Tests

To execute the entire test suite:

```bash
uv run pytest
```

### Running Specific Tests

To run a specific test file (e.g., the task lifecycle tests):

```bash
uv run pytest tests/test_knowledge_cog_tasks.py
```

### Test Suite Overview

- **`tests/test_knowledge_cog.py`**: Contains tests for the core logic, AI helper functions, and message processing of the `KnowledgeCog`.
- **`tests/test_knowledge_cog_tasks.py`**: Verifies that background tasks (like `regular_announcement` and `rent_reminders`) are correctly initialized, started, and cancelled during the Cog's lifecycle.

## Configuration

Configuration is managed via `motortown_backend/settings.py` and supports environment variable overrides using a `.env` file. Refer to `settings.py` for a full list of available settings.

### Discord Bot Intents

This bot requires the following **Privileged Gateway Intents** to be enabled in the [Discord Developer Portal](https://discord.com/developers/applications):

1.  **Server Members Intent**: Required for looking up player names and plot ownership in `rent_reminders`.
2.  **Message Content Intent**: Required for reading message contents for AI help, translation, and moderation.

Ensure these are toggled **ON** under the "Bot" tab of your application settings.
