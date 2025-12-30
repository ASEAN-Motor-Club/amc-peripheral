import os
import json

OPENAI_API_KEY_OPENROUTER = os.environ.get("OPENAI_API_KEY_OPENROUTER")

DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN")
DISCORD_TOKEN_RADIO = os.environ.get("DISCORD_TOKEN_RADIO")
DISCORD_GATEWAY = os.environ.get(
    "DISCORD_GATEWAY", "wss://gateway.discord.gg/?v=10&encoding=json"
)
API_BASE_URL = os.environ.get("API_BASE_URL", "https://discord.com/api/v10")
APPLICATION_ID = os.environ.get("APPLICATION_ID")
GUILD_ID = int(os.environ.get("GUILD_ID", "1341775494026231859"))

GAME_API_PASSWORD = os.environ.get("GAME_API_PASSWORD", "")

# Liquidsoap
LIQUIDSOAP_TELNET_HOST = os.environ.get("LIQUIDSOAP_TELNET_HOST", "localhost")
LIQUIDSOAP_TELNET_PORT = int(os.environ.get("LIQUIDSOAP_TELNET_PORT", "1234"))

# Paths
STATIC_PATH = os.environ.get("STATIC_PATH", "/srv/www")

# AI Config
DEFAULT_AI_MODEL = os.environ.get("DEFAULT_AI_MODEL", "google/gemini-3-flash-preview")
LOCAL_TIMEZONE = os.environ.get("LOCAL_TIMEZONE", "Asia/Bangkok")

# Channels
TEAMS_CHANNEL = int(os.environ.get("TEAMS_CHANNEL", "1373884428493000714"))
STATUS_CHANNEL_ID = int(os.environ.get("STATUS_CHANNEL_ID", "1347246236234678423"))
GENERAL_CHANNEL_ID = int(os.environ.get("GENERAL_CHANNEL_ID", "1341775494496129116"))
GAME_ANNOUNCEMENTS_CHANNEL_ID = int(
    os.environ.get("GAME_ANNOUNCEMENTS_CHANNEL_ID", "1373149137897263124")
)
GAME_SERVER_API_URL = os.environ.get(
    "GAME_SERVER_API_URL", "http://asean-mt-server:8080"
)
GAME_CHAT_CHANNEL_ID = int(
    os.environ.get("GAME_CHAT_CHANNEL_ID", "1344219722886938626")
)
KNOWLEDGE_FORUM_CHANNEL_ID = int(
    os.environ.get("KNOWLEDGE_FORUM_CHANNEL_ID", "1348530437768745020")
)
NEWS_CHANNEL_ID = int(os.environ.get("NEWS_CHANNEL_ID", "1359088371514867746"))
KNOWLEDGE_LOG_CHANNEL_ID = int(
    os.environ.get("KNOWLEDGE_LOG_CHANNEL_ID", "1359033463864299594")
)
TIMEZONES_CHANNEL_ID = int(
    os.environ.get("TIMEZONES_CHANNEL_ID", "1355738561865056346")
)

# Radio Channels
RADIO_CHANNEL_ID = int(os.environ.get("RADIO_CHANNEL_ID", "1422525934103171125"))
JINGLES_CHANNEL_ID = int(os.environ.get("JINGLES_CHANNEL_ID", "1392041491471274056"))
FILES_CHANNEL_ID = int(os.environ.get("FILES_CHANNEL_ID", "1359033463864299594"))
EDITORIAL_CHANNEL_ID = int(
    os.environ.get("EDITORIAL_CHANNEL_ID", "1359088371514867746")
)
DYNAMIC_NEWS_CHANNEL = int(
    os.environ.get("DYNAMIC_NEWS_CHANNEL", "1360265161536962580")
)
PLAYLIST_CHANNEL = int(os.environ.get("PLAYLIST_CHANNEL", "1359058724710256640"))
SONGS_CHANNEL = int(os.environ.get("SONGS_CHANNEL", "1360679318438547753"))
EVENT_SONGS_CHANNEL = int(os.environ.get("EVENT_SONGS_CHANNEL", "1364828221425713152"))
RACE_SONGS_CHANNEL = int(os.environ.get("RACE_SONGS_CHANNEL", "1365619448056385617"))

# Roles
DJ_ROLE_ID = int(os.environ.get("DJ_ROLE_ID", "1364484047447003248"))

# Radio Paths
YT_COOKIES_PATH = os.environ.get("YT_COOKIES_PATH", "/var/lib/radio/cookies.txt")
RADIO_PATH = os.environ.get("RADIO_PATH", "/var/lib/radio")
PLAYLIST_PATH = os.environ.get("PLAYLIST_PATH", "/var/lib/radio/playlists")
REQUESTS_PATH = os.environ.get("REQUESTS_PATH", "/var/lib/radio/requests")
SONGS_PATH = os.environ.get("SONGS_PATH", "/var/lib/radio/songs")
JINGLES_PATH = os.environ.get("JINGLES_PATH", "/var/lib/radio/jingles")
RADIO_DB_PATH = os.environ.get("RADIO_DB_PATH", os.path.join(RADIO_PATH, "radio.db"))
DENO_PATH = os.environ.get(
    "DENO_PATH", "/nix/store/vqh16h1p153k533b66i9h1i91b0k816v-deno-1.46.3/bin/deno"
)


# Mapping Helpers
def get_env_dict(var_name, default):
    val = os.environ.get(var_name)
    if val:
        try:
            return json.loads(val)
        except json.JSONDecodeError:
            pass
    return default


LANGUAGE_CHANNELS = get_env_dict(
    "LANGUAGE_CHANNELS",
    {
        "english": 1346733584169435136,
        "indonesian": 1346744118130245682,
        "malay": 1346744692137791509,
        "thai": 1346744784185983008,
        "vietnamese": 1377566939811024896,
        "tagalog": 1346744822660206623,
        "chinese": 1348247390099996763,
        "japanese": 1364643230443900928,
    },
)

TRANSLATION_CHANNELS_GAME = get_env_dict(
    "TRANSLATION_CHANNELS_GAME",
    {
        "english": 1346733584169435136,
        "vietnamese": 1377566939811024896,
        "thai": 1346744784185983008,
        "indonesian": 1346744118130245682,
        "chinese": 1348247390099996763,
        "japanese": 1364643230443900928,
    },
)

TRANSLATION_CHANNELS_GENERAL = get_env_dict(
    "TRANSLATION_CHANNELS_GENERAL",
    {
        "vietnamese": 1386266972303392798,
        "thai": 1358687778572865646,
        "indonesian": 1358687629503365280,
        "chinese": 1358687813394108577,
        "japanese": 1364643176085848074,
    },
)

LANGUAGE_CHANNELS_GENERAL = get_env_dict(
    "LANGUAGE_CHANNELS_GENERAL",
    {
        "indonesian": 1358687629503365280,
        "malay": 1358687751930646741,
        "thai": 1358687778572865646,
        "tagalog": 1358687811414392942,
        "chinese": 1358687813394108577,
        "japanese": 1364643176085848074,
    },
)
