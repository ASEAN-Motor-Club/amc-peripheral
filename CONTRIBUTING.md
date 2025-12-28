# Contributing to AMC Peripheral

Welcome to the ASEAN Motor Club's peripheral repository! This project deals with custom Discord bots, radio services, and other community-driven tools. We encourage community members to contribute their own ideas, cogs, and improvements.

## getting Started

1.  **Fork the repository** (if you don't have direct write access) or clone it.
2.  **Install dependencies** using `uv` (see `README.md`).
3.  **Create a branch** for your feature or fix.

## Adding a New Bot or Cog

If you are creating a new Cog for the main bot:
1.  Place your new Cog file in `amc_peripheral/bot/` (or a subdirectory if complex).
2.  Ensure it follows the structure of existing Cogs (e.g., `knowledge_cog.py`).
3.  Register your Cog in `amc_peripheral/bot/bot.py`.

If you are creating a completely new bot or service:
1.  Discuss it with the maintainers first!
2.  Create a new directory under `amc_peripheral/` for your service.
3.  Add entry points in `pyproject.toml` if it needs to be run as a standalone script.

## Code Style

*   We use `ruff` for linting and formatting. Please run `uv run ruff check .` and `uv run ruff format .` before submitting.
*   Type hinting is encouraged.

## Testing

*   Write tests for your new features in the `tests/` directory.
*   Run tests using `uv run pytest`.

## Submitting a Pull Request

1.  Push your branch.
2.  Open a Pull Request against the `master` branch.
3.  Describe your changes clearly.
