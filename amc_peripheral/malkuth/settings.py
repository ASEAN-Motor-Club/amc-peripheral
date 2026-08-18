"""Malkuth Ban Trap Bot — standalone env config, isolated from shared settings.py.

This bot is intentionally independent of the other amc_peripheral bots (Annie,
radio, JARVIS): it reads none of their modules, uses its own token
(DISCORD_TOKEN_MALKUTH), and runs as its own systemd unit (amc-ban-trap).

The guild/channel/exempt-role identity is REQUIRED from the environment, never
defaulted to production IDs. This bot auto-bans; if a wrong value (or none at
all) makes it through, the failure must be loud at startup, not a silent
auto-ban against live IDs.
"""

import os


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} is required (set it in the systemd env)")
    return value


BAN_TRAP_CHANNEL_ID = int(_require("BAN_TRAP_CHANNEL_ID"))
GUILD_ID = int(_require("GUILD_ID"))
BAN_TRAP_ALLOWED_ROLE_IDS = {
    int(x)
    for x in os.environ.get("BAN_TRAP_ALLOWED_ROLE_IDS", "").split(",")
    if x.strip()
}
BAN_TRAP_ANNOUNCEMENT = os.environ.get(
    "BAN_TRAP_ANNOUNCEMENT", "My apologies, but they had to go."
)
BAN_TRAP_AUTO_DELETE_ANNOUNCEMENT = (
    os.environ.get("BAN_TRAP_AUTO_DELETE_ANNOUNCEMENT", "0") == "1"
)
BAN_TRAP_CLEANUP_WINDOW_SECONDS = int(
    os.environ.get("BAN_TRAP_CLEANUP_WINDOW_SECONDS", "60")
)
BAN_TRAP_DELETE_DELAY_SECONDS = int(
    os.environ.get("BAN_TRAP_DELETE_DELAY_SECONDS", "5")
)
DISCORD_TOKEN_MALKUTH = os.environ.get("DISCORD_TOKEN_MALKUTH")
