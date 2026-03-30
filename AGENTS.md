# AMC Peripheral — Agent Guide

## Overview

Peripheral services for the ASEAN Motor Club: radio station, Discord bots, and the tire mod build system. Runs on the `amc-peripheral` server as a NixOS service.

## Structure

```
amc-peripheral/
├── amc_peripheral/          # Python package (installed via hatch)
│   ├── bot/                 # Discord bot (server status monitor, translation)
│   ├── radio/               # Radio station service
│   ├── devbot/              # Jarvis dev assistant bot
│   └── mods/                # Tire mod build API (aiohttp on port 7002)
├── tire-web/                # SvelteKit static frontend for tire mod creator
│   ├── src/lib/             # Svelte components, API client, types
│   ├── default.nix          # Nix build via buildNpmPackage
│   └── ...
├── flake.nix                # NixOS module: services, nginx, packages
├── pyproject.toml           # Python project config + entry points
└── .gitignore               # ⚠️ Python-oriented, see caveat below
```

## Known Issue: Mixed-Language Monorepo

This repository was originally a **pure Python project**, so the root `.gitignore` uses a standard Python template (ignoring `lib/`, `build/`, `dist/`, etc.). With the addition of `tire-web/` (a SvelteKit project), there is now a **language mismatch** in the ignore rules:

- The Python `lib/` ignore rule catches SvelteKit's `src/lib/` convention. A negation (`!tire-web/src/lib/`) has been added as a workaround.
- The `build/` ignore rule is handled by `tire-web/.gitignore` locally, but could cause confusion.

**This should be addressed eventually** by either:
1. **Separating frontend projects** into their own repositories/submodules, or
2. **Restructuring amc-peripheral as a proper monorepo** with per-project `.gitignore` files and a minimal shared root ignore.

Until then, when adding new non-Python projects, check that the root `.gitignore` isn't silently hiding files. Use `git check-ignore -v <path>` to debug.

## Entry Points

Defined in `pyproject.toml` under `[project.scripts]`:

| Command      | Module                              | Description                    |
|--------------|-------------------------------------|--------------------------------|
| `amc_bot`    | `amc_peripheral.bot.bot:main`       | Discord bot                    |
| `amc_radio`  | `amc_peripheral.radio.radio:main`   | Radio station                  |
| `amc_jarvis` | `amc_peripheral.devbot.devbot:main` | Dev assistant bot              |
| `amc_mods`   | `amc_peripheral.mods.server:main`   | Tire mod build API             |

## Building

```bash
# Python package
nix build .#default

# Tire-web static site
nix-build --expr 'let pkgs = import <nixpkgs> {}; in (import ./tire-web { inherit pkgs; }).package'
```
