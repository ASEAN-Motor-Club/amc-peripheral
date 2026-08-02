import os

# Malkuth Ban Trap Bot — standalone env config, isolated from shared settings.py

BAN_TRAP_CHANNEL_ID = int(os.environ.get("BAN_TRAP_CHANNEL_ID", "1529987241278177352"))
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
GUILD_ID = int(os.environ.get("GUILD_ID", "1341775494026231859"))
DISCORD_TOKEN_MALKUTH = os.environ.get("DISCORD_TOKEN_MALKUTH")