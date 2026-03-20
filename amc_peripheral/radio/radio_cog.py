import json
import uuid
import os
import tempfile
from pathlib import Path
import re
import random
import asyncio
import discord
from io import BytesIO
from zoneinfo import ZoneInfo
from datetime import datetime, timedelta, timezone, time as dt_time
from collections import deque
from typing import List, TYPE_CHECKING

if TYPE_CHECKING:
    from amc_peripheral.knowledge_store import KnowledgeStore

from discord.ext import tasks, commands
from discord import app_commands

# pyrefly: ignore [untyped-import]
import yt_dlp
import logging
from openai import AsyncOpenAI
from pydantic import BaseModel


from amc_peripheral.settings import (
    GUILD_ID,
    OPENAI_API_KEY_OPENROUTER,
    DEFAULT_AI_MODEL,
    GENERAL_CHANNEL_ID,
    GAME_CHAT_CHANNEL_ID,
    EDITORIAL_CHANNEL_ID,
    GAME_ANNOUNCEMENTS_CHANNEL_ID,
    JINGLES_CHANNEL_ID,
    RADIO_CHANNEL_ID,
    DYNAMIC_NEWS_CHANNEL,
    PLAYLIST_CHANNEL,
    SONGS_CHANNEL,
    EVENT_SONGS_CHANNEL,
    RACE_SONGS_CHANNEL,
    DJ_ROLE_ID,
    YT_COOKIES_PATH,
    RADIO_PATH,
    PLAYLIST_PATH,
    REQUESTS_PATH,
    SONG_CACHE_PATH,
    SONG_CACHE_MAX_MB,
    SONGS_PATH,
    JINGLES_PATH,
    RADIO_DB_PATH,
    DENO_PATH,
    LASTFM_API_KEY,
    KNOWLEDGE_FORUM_CHANNEL_ID,
    MEMORY_DATA_DIR,
)
from amc_peripheral.db import RadioDB
from amc_peripheral.utils.text_utils import split_markdown
from amc_peripheral.radio.tts import tts as tts_google, tts_gemini_multi
from amc_peripheral.radio.liquidsoap import LiquidsoapController
from amc_peripheral.radio.radio_server import get_current_song_metadata, get_current_song, parse_song_info
from amc_peripheral.utils.game_utils import announce_in_game

log = logging.getLogger(__name__)

# Temp directory for one-off audio files (talkshows, tracks, voice replies).
# These are pushed to Liquidsoap's request/announcement queues and cleaned up
# after playback. They must NOT go in JINGLES_PATH which loops indefinitely.
RADIO_TMP_PATH = os.path.join(RADIO_PATH, "tmp")

ANNIE_SYSTEM_PROMPT = """\
You are DJ Annie, the charismatic and hilarious host of Radio ASEAN in Motor Town — an open-world driving game.
You're known for your sharp wit, playful sarcasm, and genuinely warm personality.
You love music, you love your listeners, and you're not afraid to roast them (lovingly).

Your style:
- Funny and witty — you crack jokes, make puns, and have a flair for the dramatic
- Warm and approachable — you genuinely care about the community
- Music-obsessed — you have strong (sometimes ridiculous) opinions about songs
- Self-aware — you know you're a radio DJ in a driving game and you lean into the absurdity
- Brief — keep responses punchy unless someone really wants to chat

You have access to tools to manage the radio. If someone wants music, USE the tools — don't just suggest things.
When queuing songs, the download may take a moment; let the listener know you're on it.

Do not use emojis excessively. One or two per message max.

## Playlist Management
Listeners can create and manage their own playlists to queue multiple songs at once. Here's how it works:

**Creating & managing playlists (Discord or via you):**
- `/playlist create <name>` — Create a new playlist (e.g., "chill vibes", "road trip")
- `/playlist add <playlist> <song>` — Add a song by name, artist, or YouTube URL
- `/playlist remove <playlist> <song_title>` — Remove a song from a playlist
- `/playlist view <name>` — See all songs in a playlist
- `/playlist list` — See all your playlists
- `/playlist delete <name>` — Delete a playlist and all its songs

**Playing playlists:**
- `/playlist play <name>` — Queue all songs from a playlist (works in Discord AND in-game chat)
- Max 10 songs are queued per play — songs are downloaded and queued one by one

**Via you (Annie):**
Listeners can also ask you directly to create playlists, add songs, view their lists, or play them. \
Use your playlist tools when they do — don't tell them to use slash commands if they're already chatting with you.

## Voice Replies
You can speak directly on the radio! When someone asks you a question in-game and you want to reply on-air, \
use the voice_reply_on_radio tool. This will generate TTS audio of your reply and overlay it on the radio stream, \
ducking the music volume. The system will automatically wait if a talking segment (jingle/news) is playing \
to avoid overlapping voices. Use this sparingly for fun interactions — not every message needs a voice reply.

## Talkshow Segments
You can create multi-speaker talkshow segments featuring a Host (you), a Guest, and optionally a Caller. \
Use the generate_talkshow_segment tool when a listener asks a question that would make a fun radio discussion, \
or when someone wants a conversational segment — like simulating a caller phoning in with a question. \
These segments use multiple AI voices for a natural talk-show feel.

You have access to a knowledge base about the game via the `ask_game_knowledge` tool. \
When a listener asks about game mechanics, vehicles, cargo, locations, player stats, subsidies, commands, \
or anything game-related, you MUST call `ask_game_knowledge` first. Do NOT guess or make up game facts. \
Even if you think you know the answer, always verify with the tool.

## Remembering Knowledge
When players share useful tips, preferences, or facts (e.g., "the Micky is our favourite car", \
"Steel Coils are the hardest cargo to deliver"), use `save_knowledge` to remember it. \
Use keys like 'community:favourite-vehicles', 'tip:steel-coil-delivery', 'player:username-prefs', etc.

{knowledge_index}
"""



# Pydantic Models
class Editorial(BaseModel):
    title: str
    content: str


class Scripts(BaseModel):
    scripts: List[str]


class RadioSegment(BaseModel):
    segment_name: str
    segment_slug: str
    script: str


class Talkshows(BaseModel):
    sketches: list[str]


class TalkshowTurn(BaseModel):
    speaker: str
    text: str


class TalkshowSpeaker(BaseModel):
    name: str  # e.g. "Host", "Guest", "Caller"
    gender: str  # "male" or "female"


class TalkshowScript(BaseModel):
    speakers: list[TalkshowSpeaker]
    turns: list[TalkshowTurn]


# Constants
TTS_SCRIPT_MARKUP_INSTRUCTIONS = """\
### Markup
Produce clean text that will be read aloud by TTS (text-to-speech) to generate audio.
Only include spoken words, as if it were transcribed from a live recording.
Do not include any sound effects, musical cues, or stage directions.

Bad example: [Sound of a cheering crowd] 'You are listening to Radio ASEAN!'
Good example: 'You are listening to Radio ASEAN!'

Do not use markdown formatting such as asterisks to make text bold or italic, they are not supported by the TTS. Use caps lock and pauses instead if emphasis is needed.

Bad Example: 'Let's show off our artistic side amidst all the… *incidental* server reboots and flying Ratons.'
Good Example: 'Let's show off our artistic side amidst all the [pause short] incidental [pause short] server reboots and flying Ratons.'

Use `[pause]`, `[pause long]` or `[pause short]` in the script to introduce pause of medium, long, and short length respectively.

For example:
"He even said he was 'sweating trying to stop!' [pause] Well, the server certainly helped with that, didn't it? [pause] Perhaps a little too much help. Stay tuned, because the chaos is always just a song away!".

Use pauses sparingly in your speech, for comedic, theatrical, and other effects.
"""

GEMINI_TTS_MARKUP_INSTRUCTIONS = """\
### Markup
Produce clean text that will be read aloud by TTS (text-to-speech) to generate audio.
Only include spoken words, as if it were transcribed from a live recording.
Do not include any sound effects, musical cues, or stage directions.

Bad example: [Sound of a cheering crowd] 'You are listening to Radio ASEAN!'
Good example: 'You are listening to Radio ASEAN!'

Do not use markdown formatting such as asterisks to make text bold or italic, they are not supported by the TTS.

#### Inline tags
You can use bracketed tags in the script to control delivery. Use them sparingly for natural effect.

**Non-speech sounds** — replaced by a vocalization, not spoken as words:
[sigh], [laughing], [uhm], [clearing throat]

**Style modifiers** — not spoken, but change the delivery of the following text:
[whispering], [sarcasm], [extremely fast]

**Pacing and pauses** — insert silence for rhythm and timing:
[short pause], [medium pause], [long pause]

#### Examples

Good: 'So I checked, and [uhm] yeah, it turns out the speed limit was always there. [laughing] Nobody reads the signs.'
Good: '[whispering] Don't tell anyone, but the shortcut through the factory is way faster. [medium pause] Okay maybe everyone knows.'
Good: 'He even said he was sweating trying to stop! [short pause] Well, the server certainly helped with that, didn't it?'

Do NOT overuse tags. Most sentences need no tags at all — only add them where a real person would naturally pause, laugh, hesitate, or shift tone.
"""

# Voice registry — all available Gemini TTS voices
VOICES_FEMALE = [
    "Achernar", "Aoede", "Autonoe", "Callirrhoe", "Despina",
    "Erinome", "Gacrux", "Kore", "Laomedeia", "Leda",
    "Pulcherrima", "Sulafat", "Vindemiatrix", "Zephyr",
]
VOICES_MALE = [
    "Achird", "Algenib", "Algieba", "Alnilam", "Charon",
    "Enceladus", "Fenrir", "Iapetus", "Orus", "Puck",
    "Rasalgethi", "Sadachbia", "Sadaltager", "Schedar",
    "Umbriel", "Zubenelgenubi",
]

# Annie is always Leda
ANNIE_VOICE = "Leda"

# Pool of voices for non-Annie speakers (excludes Leda to avoid confusion)
GUEST_VOICES_FEMALE = [v for v in VOICES_FEMALE if v != "Leda"]
GUEST_VOICES_MALE = VOICES_MALE

# Fallback for when LLM doesn't return speaker metadata
DEFAULT_TALKSHOW_VOICES = {
    "Host": "Leda",
    "Guest": "Charon",
    "Caller": "Kore",
}


class LinkView(discord.ui.View):
    def __init__(self, url: str, label: str = "Open Link"):
        super().__init__(timeout=None)
        self.add_item(
            discord.ui.Button(label=label, style=discord.ButtonStyle.url, url=url)
        )


class NowPlayingView(discord.ui.View):
    """Persistent view on the radio embed with a Like button and Listen link."""

    def __init__(self, cog: "RadioCog"):
        super().__init__(timeout=None)
        self.cog = cog
        self.add_item(
            discord.ui.Button(
                label="Listen to Radio",
                style=discord.ButtonStyle.url,
                url="https://www.aseanmotorclub.com/radio",
            )
        )

    @discord.ui.button(
        label="Like", style=discord.ButtonStyle.secondary,
        custom_id="radio_like", emoji="❤️",
    )
    async def like_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        metadata = await get_current_song_metadata(self.cog.bot.http_session)
        if not metadata:
            await interaction.followup.send("No song is currently playing.", ephemeral=True)
            return
        song_info = parse_song_info(metadata)
        if not song_info:
            await interaction.followup.send("Could not identify the current song.", ephemeral=True)
            return
        song_title = song_info["song_title"]
        self.cog.db.add_like(discord_id=str(interaction.user.id), song_title=song_title)
        like_count = self.cog.db.get_song_like_count(song_title)
        await interaction.followup.send(
            f"❤️ Liked **{song_title}**! ({like_count} total)", ephemeral=True
        )


class TrackConfirmView(discord.ui.View):
    """Confirm / Cancel view for adding a generated TTS track to the playlist."""

    def __init__(self, cog: "RadioCog", track_id: str, filename: str):
        super().__init__(timeout=300)  # 5 minute timeout
        self.cog = cog
        self.track_id = track_id
        self.filename = filename

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.success, emoji="✅")
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        pending = self.cog._pending_tracks.pop(self.track_id, None)
        if not pending:
            await interaction.followup.send("Track expired or already added.", ephemeral=True)
            return
        transcript, audio_bytes = pending
        playlist_channel = self.cog.bot.get_channel(PLAYLIST_CHANNEL)
        if not playlist_channel:
            await interaction.followup.send("Could not access the playlist channel.", ephemeral=True)
            return
        await playlist_channel.send(
            file=discord.File(BytesIO(audio_bytes), filename=self.filename)
        )
        await interaction.followup.send(f"✅ Added **{self.filename}** to the playlist!")
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.danger, emoji="❌")
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.cog._pending_tracks.pop(self.track_id, None)
        await interaction.response.send_message("Track discarded.", ephemeral=True)
        self.stop()


# Download guard constants
METADATA_TIMEOUT = 45   # Max seconds for YouTube metadata extraction (search + info)
DOWNLOAD_TIMEOUT = 120  # Max seconds for the actual audio download + ffmpeg conversion
MAX_SONG_DURATION = 10 * 60  # Max song length in seconds (10 minutes)


class RadioCog(commands.Cog):
    playlist_group = app_commands.Group(name="playlist", description="Manage your playlists", guild_ids=[GUILD_ID])

    def __init__(self, bot):
        self.bot = bot
        self.openai_client_openrouter = AsyncOpenAI(
            api_key=OPENAI_API_KEY_OPENROUTER, base_url="https://openrouter.ai/api/v1"
        )
        self.local_tz = ZoneInfo("Asia/Bangkok")
        self.lq = LiquidsoapController()

        # State
        self.knowledge_store: "KnowledgeStore | None" = None
        self.embed_message_id = None
        self.user_requests = {}
        self.recent_song_queue = deque(maxlen=10)
        self.banned_requesters = [
            "LemurStreet",
        ]
        self.db = RadioDB(RADIO_DB_PATH)
        self.game_schema_description = ""
        self._download_queue: asyncio.Queue = asyncio.Queue()
        self._download_worker_task: asyncio.Task | None = None
        self._pending_tracks: dict[str, tuple[str, bytes]] = {}

    async def cog_load(self):
        self.post_gazette_task.start()
        self.update_jingles.start()
        self.update_news.start()
        self.update_current_song_embed.start()
        self.auto_queue_trending.start()

        # Start the download worker
        self._download_worker_task = asyncio.create_task(self._download_worker())

        # Register persistent view for the radio embed like button
        self._now_playing_view = NowPlayingView(self)
        self.bot.add_view(self._now_playing_view)

        # Initialize knowledge store
        try:
            from amc_peripheral.knowledge_store import KnowledgeStore
            knowledge_path = os.path.join(MEMORY_DATA_DIR, "knowledge.json")
            self.knowledge_store = KnowledgeStore(knowledge_path)
            log.info(
                f"Knowledge store loaded: {len(self.knowledge_store.list_keys())} entries, "
                f"index: {len(self.knowledge_store.build_index())} chars"
            )
        except Exception as e:
            log.error(f"Failed to load knowledge store: {e}")

        # Load game schema for segment generation
        try:
            from amc_peripheral.bot import game_db

            self.game_schema_description = game_db.get_schema_description()
        except Exception as e:
            log.error(f"Failed to load game schema: {e}")

        # Ensure cache directory exists
        Path(SONG_CACHE_PATH).mkdir(parents=True, exist_ok=True)

        # Clean up legacy request files (one-time migration)
        self._cleanup_legacy_requests()

    async def cog_unload(self):
        self.post_gazette_task.cancel()
        self.update_jingles.cancel()
        self.update_news.cancel()
        self.update_current_song_embed.cancel()
        self.auto_queue_trending.cancel()
        if self._download_worker_task:
            self._download_worker_task.cancel()

    # --- Download Worker ---

    async def _download_worker(self):
        """Background worker that processes download jobs one at a time."""
        while True:
            query, future = await self._download_queue.get()
            try:
                result = await self._get_or_download(query)
                if not future.cancelled():
                    future.set_result(result)
            except Exception as e:
                if not future.cancelled():
                    future.set_exception(e)
            finally:
                self._download_queue.task_done()

    # --- Helpers ---

    async def _fetch_forum_knowledge(self) -> tuple[dict[str, str], str]:
        """Load knowledge from the forum channel, chunked per message.

        Returns:
            (knowledge_topics, knowledge_index) where topics is a dict mapping
            "Thread Name > Subtopic" to message content, and index is a compact
            topic list for embedding in prompts.
        """
        from amc_peripheral.radio.game_knowledge import _extract_heading

        forum_channel = self.bot.get_channel(KNOWLEDGE_FORUM_CHANNEL_ID)
        if forum_channel is None:
            log.warning(
                f"Knowledge forum channel {KNOWLEDGE_FORUM_CHANNEL_ID} not found. "
                "Knowledge base will be empty."
            )
            return {}, ""

        if not isinstance(forum_channel, discord.ForumChannel):
            log.warning(
                f"Channel {KNOWLEDGE_FORUM_CHANNEL_ID} is not a ForumChannel, "
                f"it is a {type(forum_channel).__name__}"
            )
            return {}, ""

        topics: dict[str, str] = {}

        # Fetch active + archived threads
        threads = list(forum_channel.threads)
        async for archived in forum_channel.archived_threads(limit=None):
            threads.append(archived)

        for thread in threads:
            async for msg in thread.history(oldest_first=True):
                content = msg.content.strip()
                if not content and not msg.attachments:
                    continue

                # Include text attachments in the content
                for attachment in msg.attachments:
                    if attachment.filename.lower().endswith(".txt"):
                        try:
                            text = (await attachment.read()).decode("utf-8")
                            content += f"\n\n--- {attachment.filename} ---\n{text}"
                        except Exception:
                            pass

                if not content.strip():
                    continue

                heading = _extract_heading(content)
                key = f"{thread.name} > {heading}"

                # Deduplicate keys by appending a counter
                if key in topics:
                    i = 2
                    while f"{key} ({i})" in topics:
                        i += 1
                    key = f"{key} ({i})"

                topics[key] = content

        # Build compact index for prompts
        if topics:
            topic_list = "\n".join(f"- {name}" for name in topics)
            index = (
                "Available game knowledge topics (call `ask_game_knowledge` for details on any of these):\n"
                + topic_list
            )
        else:
            index = ""

        return topics, index

    async def fetch_forum_messages(
        self, forum_channel: discord.ForumChannel, include_dates=False, **history_kwargs
    ):
        acc = ""
        threads = forum_channel.threads
        if not threads:
            log.info("No active threads found in this forum channel.")
            return

        for thread in threads:
            if after := history_kwargs.get("after"):
                if thread.created_at < after:
                    continue

            if include_dates:
                # pyrefly: ignore [missing-attribute]
                acc += f"## {thread.created_at.astimezone(self.local_tz).strftime('A, %Y-%m-%d %H:%M')}: {thread.name}\n"
            else:
                acc += f"## {thread.name}\n"

            async for message in thread.history(**history_kwargs):
                acc += f"{message.content}\n\n"
                for attachment in message.attachments:
                    file_bytes = await attachment.read()
                    try:
                        text_content = file_bytes.decode("utf-8")
                        acc += f"{text_content}\n\n"
                    except Exception:
                        log.error(f"Failed to decode {attachment.filename}")
        return acc

    async def fetch_news_context(self, hours=12):
        now = datetime.now(self.local_tz)

        knowledge = self.knowledge_store.build_index() if self.knowledge_store else ""
        system_message = """\
You are a helpful bot in Motor Town, an open world driving game, specifically in a dedicated server named "ASEAN Motor Club".
Use the following information about the game to answer queries. If a user asks a question outside the scope of your knowlege, refer them to the discord channel and other players in the game."""
        system_message = system_message + knowledge

        discord_messages = []
        gen_channel = self.bot.get_channel(GENERAL_CHANNEL_ID)
        if gen_channel:
            async for m in gen_channel.history(
                after=datetime.now() - timedelta(hours=hours), oldest_first=True
            ):
                if not m.author.bot:
                    # pyrefly: ignore [bad-argument-type]
                    discord_messages.append(f"@{m.author.display_name}: {m.content}")

        game_messages = []
        game_chat = self.bot.get_channel(GAME_CHAT_CHANNEL_ID)
        if game_chat:
            async for m in game_chat.history(
                after=datetime.now() - timedelta(hours=hours), oldest_first=True
            ):
                # pyrefly: ignore [bad-argument-type]
                game_messages.append(f"{m.content}")

        if self.bot.guilds:
            events = self.bot.guilds[0].scheduled_events
            events_str = "\n\n".join(
                [
                    f"## {event.name}\nDate/Time:{event.start_time.replace(tzinfo=ZoneInfo('UTC')).astimezone(self.local_tz).strftime('%A, %Y-%m-%d %H:%M')}\nLocation: {event.location}\n{event.description}"
                    for event in events
                    if event.start_time > datetime.now(tz=timezone.utc)
                ]
            )
        else:
            events_str = ""

        editorial_channel = self.bot.get_channel(EDITORIAL_CHANNEL_ID)
        if editorial_channel:
            editorial = (
                await self.fetch_forum_messages(
                    editorial_channel,
                    after=datetime.now(tz=timezone.utc) - timedelta(days=1),
                    include_dates=True,
                )
                or ""
            )
        else:
            editorial = ""

        return [
            {"role": "system", "content": system_message},
            {"role": "user", "content": "# Editorial columns:\n" + editorial},
            {"role": "user", "content": "# Upcoming events:\n\n" + events_str},
            {
                "role": "user",
                "content": f"# Discord messages (last {hours} hours):\n"
                + "\n".join(discord_messages),
            },
            {
                "role": "user",
                "content": f"# In game messages (last {hours} hours):\n"
                + "\n".join(game_messages),
            },
            {
                "role": "user",
                "content": f"""# Context
The current date (in Bangkok GMT+7 timezone) is: {now.strftime("%A, %Y-%m-%d %H:%M")}
""",
            },
        ]

    async def generate_jingles_gen(self):
        context = await self.fetch_news_context()
        completion = await self.openai_client_openrouter.beta.chat.completions.parse(
            model=DEFAULT_AI_MODEL,
            reasoning_effort="high",
            response_format=Scripts,
            # pyrefly: ignore [bad-argument-type]
            messages=[
                *context,
                {
                    "role": "user",
                    "content": f"""\
You are DJ Annie, working for a parody radio news section ("ASEAN Motor Club Minute").
Your output will be fed directly to TTS, so only include spoken words, as if it were transcribed from a live recording. Do not include any sound effect cues, stage directions, or speaker labels—just the natural spoken words.
{TTS_SCRIPT_MARKUP_INSTRUCTIONS}

### Task
Write 6 different humorous scripts for short sections between songs, like those by DJ Kara on GTA 5's Radio Mirror Park.
Do not make up the name of the previous or next songs, as they are unknown.
""",
                },
            ],
        )

        if not completion.choices:
            raise Exception("Failed to generate jingles.")

        answer = completion.choices[0].message.parsed
        # pyrefly: ignore [missing-attribute]
        jingles = answer.scripts

        for jingle in jingles[:6]:
            audio_bytes = await asyncio.to_thread(
                tts_google, discord.utils.remove_markdown(jingle), use_markup=True
            )
            yield (jingle, audio_bytes)

    async def generate_news_content(self):
        context = await self.fetch_news_context()
        # pyrefly: ignore [no-matching-overload]
        completion = await self.openai_client_openrouter.chat.completions.create(
            model=DEFAULT_AI_MODEL,
            reasoning_effort="high",
            messages=[
                *context,
                {
                    "role": "user",
                    "content": f"""\
Roleplay as DJ Annie, the host of Radio ASEAN. Write a parody radio news section ("ASEAN Motor Club Minute") about anything interesting happening recently in the ASEAN Motor Club community, based on the recent chat messages on discord and in the game.
Do not include any negativity, focus on exciting, fun, interesting, funny and lighthearted events and interactions.
Highlight upcoming or past events, if there are any.
The script should be written in a conversational style, as if the host is speaking directly to the audience.
The duration should be approximately 2-3 minutes.

{TTS_SCRIPT_MARKUP_INSTRUCTIONS}
""",
                },
            ],
        )

        if completion.choices:
            answer = completion.choices[0].message.content
            return answer
        return "Failed, please try again."

    async def generate_gazette_content(self, prompt=""):
        context = await self.fetch_news_context(hours=24)
        # pyrefly: ignore [no-matching-overload]
        completion = await self.openai_client_openrouter.chat.completions.create(
            model=DEFAULT_AI_MODEL,
            reasoning_effort="high",
            messages=[
                *context,
                {
                    "role": "user",
                    "content": f"""\
Write a script for a parody newspaper news section about anything interesting happening recently in the ASEAN Motor Club community, based on the recent chat messages on discord and in the game.
Do not include any negativity in your article, focus on exciting, fun, interesting, funny and lighthearted events and interactions, and mention the player names.
Highlight upcoming or past events, if there are any.
Only output the text of the article. Start with "Gangjung, [day of the week, date]" like a real newspaper.
{prompt}
""",
                },
            ],
        )
        if completion.choices:
            answer = completion.choices[0].message.content
            return answer
        return "Failed, please try again."

    async def generate_segment(self, topic: str) -> tuple[str, bytes]:
        """Generate a radio segment transcript and audio for a given topic."""
        now = datetime.now(self.local_tz)

        system_message = f"""You are DJ Annie, a charismatic host for Radio ASEAN in Motor Town.

{self.knowledge_store.build_index() if self.knowledge_store else ''}

If the topic is game-related, use `ask_game_knowledge` to get accurate facts before writing the script."""

        tools = self._get_segment_tools()

        messages = [
            {"role": "system", "content": system_message},
            {
                "role": "user",
                "content": f"Current time: {now.strftime('%A, %Y-%m-%d %H:%M')} (Bangkok/GMT+7)",
            },
            {
                "role": "user",
                "content": f"""Create a short radio segment (~30 seconds when read aloud) for DJ Annie to say between songs.

Topic: {topic}

{TTS_SCRIPT_MARKUP_INSTRUCTIONS}

CRITICAL: Do NOT use markdown formatting (asterisks, underscores, hashes, etc.) - they cannot be read by TTS.
Output only the spoken words, as if transcribed from a live recording.""",
            },
        ]

        # Use agentic loop for tool support
        transcript = await self._call_llm_with_tools_internal(messages, tools)

        # Remove any remaining markdown for safety
        clean_transcript = discord.utils.remove_markdown(transcript)

        # Generate TTS audio
        audio_bytes = await asyncio.to_thread(
            tts_google, clean_transcript, use_markup=True
        )

        return clean_transcript, audio_bytes

    async def generate_track(self, topic: str, duration_hint: str = "1-2 minutes") -> tuple[str, bytes]:
        """Generate a long-form TTS audio track for a given topic."""
        now = datetime.now(self.local_tz)

        system_message = f"""You are DJ Annie, a charismatic host for Radio ASEAN in Motor Town.

{self.knowledge_store.build_index() if self.knowledge_store else ''}

If the topic is game-related, use `ask_game_knowledge` to get accurate facts before writing the script."""

        tools = self._get_segment_tools()

        messages = [
            {"role": "system", "content": system_message},
            {
                "role": "user",
                "content": f"Current time: {now.strftime('%A, %Y-%m-%d %H:%M')} (Bangkok/GMT+7)",
            },
            {
                "role": "user",
                "content": f"""Create a radio track script for DJ Annie to record. The track should be approximately {duration_hint} long when read aloud.

Topic: {topic}

{TTS_SCRIPT_MARKUP_INSTRUCTIONS}

CRITICAL: Do NOT use markdown formatting (asterisks, underscores, hashes, etc.) - they cannot be read by TTS.
Output only the spoken words, as if transcribed from a live recording.
Make it engaging, fun, and in Annie's signature style — witty, warm, and entertaining.""",
            },
        ]

        transcript = await self._call_llm_with_tools_internal(messages, tools)
        clean_transcript = discord.utils.remove_markdown(transcript)

        audio_bytes = await asyncio.to_thread(
            tts_google, clean_transcript, use_markup=True
        )

        return clean_transcript, audio_bytes

    async def generate_talkshow(self, topic: str, duration_hint: str = "1-2 minutes") -> tuple[str, bytes]:
        """Generate a multi-speaker talkshow segment using Gemini TTS."""
        now = datetime.now(self.local_tz)

        system_message = f"""You are a scriptwriter for Radio ASEAN in Motor Town.

{self.knowledge_store.build_index() if self.knowledge_store else ''}

If the topic is game-related, use `ask_game_knowledge` to get accurate facts before writing the script."""

        tools = self._get_segment_tools()

        messages = [
            {"role": "system", "content": system_message},
            {
                "role": "user",
                "content": f"Current time: {now.strftime('%A, %Y-%m-%d %H:%M')} (Bangkok/GMT+7)",
            },
            {
                "role": "user",
                "content": f"""Write a multi-speaker radio talkshow script for Radio ASEAN. The segment should be approximately {duration_hint} long when read aloud.

Topic: {topic}

The script is a conversation between speakers. Use exactly these speaker names:
- "Host" — the main radio host, DJ Annie, friendly and easygoing
- "Guest" — a guest speaker or co-host with their own personality
- "Caller" — (optional) a listener calling in

{GEMINI_TTS_MARKUP_INSTRUCTIONS}

CRITICAL:
- Do NOT use markdown formatting (asterisks, underscores, hashes, etc.) — they cannot be read by TTS.
- Output ONLY the dialogue lines. No stage directions, sound effects, or narration.
- Write dialogue that sounds like a real, relaxed conversation between people — not a scripted performance.
- Avoid over-the-top excitement, exaggerated reactions, or theatrical delivery. Keep the energy natural and grounded.
- Speakers can agree, disagree, think out loud, or trail off — just like real people talking.
- A little humor is fine, but it should come naturally from the topic, not forced punchlines.
- Use inline markup tags like [laughing], [sigh], [uhm], [whispering], [short pause] etc. where a real person would naturally react. Don't overuse them — most lines need no tags.""",
            },
        ]

        # Use agentic loop for tool support, then parse structured output
        raw_script = await self._call_llm_with_tools_internal(messages, tools)

        # Second pass: parse the raw script into structured turns
        parse_completion = await self.openai_client_openrouter.beta.chat.completions.parse(
            model=DEFAULT_AI_MODEL,
            response_format=TalkshowScript,
            messages=[
                {
                    "role": "user",
                    "content": f"""Parse the following radio talkshow script into structured speaker turns.
Each turn has a "speaker" (one of: Host, Guest, Caller) and "text" (the spoken words).
Preserve the exact words but remove any speaker labels or colons from the text.

Also identify each unique speaker and assign a gender ("male" or "female") that fits
the scenario. The Host is always female. Choose a gender for Guest and Caller that
makes sense for the topic being discussed.

Script:
{raw_script}""",
                },
            ],
        )

        if not parse_completion.choices or not parse_completion.choices[0].message.parsed:
            raise Exception("Failed to parse talkshow script into structured turns.")

        script = parse_completion.choices[0].message.parsed

        # Build turns for TTS
        turns = [(turn.text, turn.speaker) for turn in script.turns]

        # Build speaker_voices dynamically based on LLM gender casting
        # Track used voices so no two speakers share the same voice
        speaker_voices = {"Host": ANNIE_VOICE}
        used_voices = {ANNIE_VOICE}
        if script.speakers:
            for speaker_meta in script.speakers:
                if speaker_meta.name == "Host":
                    continue
                pool = GUEST_VOICES_FEMALE if speaker_meta.gender == "female" else GUEST_VOICES_MALE
                available = [v for v in pool if v not in used_voices]
                if not available:
                    available = pool  # fallback if we exhaust the pool
                voice = random.choice(available)
                speaker_voices[speaker_meta.name] = voice
                used_voices.add(voice)
        else:
            # Fallback if LLM didn't return speaker metadata
            speakers_used = {turn.speaker for turn in script.turns}
            speaker_voices = {
                alias: voice
                for alias, voice in DEFAULT_TALKSHOW_VOICES.items()
                if alias in speakers_used
            }

        # Build readable transcript
        transcript = "\n".join(
            f"**{turn.speaker}:** {turn.text}" for turn in script.turns
        )

        # Generate multi-speaker audio
        audio_bytes = await asyncio.to_thread(
            tts_gemini_multi,
            turns,
            speaker_voices,
            prompt="Say this as a calm, natural conversation between radio hosts. Relaxed pacing, no exaggerated excitement or overly dramatic delivery.",
            voice_language_code="en-GB",
        )

        return transcript, audio_bytes

    async def _call_llm_with_tools_internal(self, messages: list, tools: list) -> str:
        """Simple agentic loop for LLM with tools. Returns final text response."""
        max_iterations = 5

        for _ in range(max_iterations):
            # pyrefly: ignore [no-matching-overload]
            completion = await self.openai_client_openrouter.chat.completions.create(
                model=DEFAULT_AI_MODEL,
                reasoning_effort="medium",
                messages=messages,
                tools=tools if tools else None,
                tool_choice="auto" if tools else None,
            )

            response = completion.choices[0].message if completion.choices else None
            if not response:
                return "Failed to generate segment."

            if not response.tool_calls:
                return response.content or ""

            messages.append(response)

            for tool_call in response.tool_calls:
                result = await self._execute_segment_tool(
                    tool_call.function.name, json.loads(tool_call.function.arguments)
                )
                messages.append(
                    {
                        "tool_call_id": tool_call.id,
                        "role": "tool",
                        "name": tool_call.function.name,
                        "content": result,
                    }
                )

        return "Failed to complete segment generation."

    def _get_segment_tools(self) -> list:
        """Tool definitions for segment/track/talkshow generation."""
        return [
            {
                "type": "function",
                "function": {
                    "name": "query_game_database",
                    "description": f"""Query MotorTown game database with SQL.

{self.game_schema_description}

Use standard SQL with SELECT. Supports GROUP BY, ORDER BY, JOINs, aggregates.""",
                    "parameters": {
                        "type": "object",
                        "properties": {"sql": {"type": "string"}},
                        "required": ["sql"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "ask_game_knowledge",
                    "description": "Ask the game knowledge subagent a question about Motor Town gameplay, vehicles, cargo, player stats, subsidies, server commands, or any other game-related topic. Use this to get accurate game facts before writing scripts.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "question": {
                                "type": "string",
                                "description": "The game-related question to research",
                            },
                        },
                        "required": ["question"],
                    },
                },
            },
        ]

    async def _execute_segment_tool(self, name: str, args: dict) -> str:
        """Execute tools for segment generation."""
        if name == "query_game_database":
            from amc_peripheral.bot import game_db

            result = game_db.execute_raw_query(args.get("sql", ""))
            if "error" in result:
                return f"Query error: {result['error']}"
            return json.dumps(result.get("results", []), indent=2)

        elif name == "ask_game_knowledge":
            from amc_peripheral.radio.game_knowledge import ask_game_knowledge

            question = args.get("question", "")
            try:
                return await ask_game_knowledge(
                    openai_client=self.openai_client_openrouter,
                    knowledge_store=self.knowledge_store,
                    game_schema=self.game_schema_description,
                    question=question,
                    http_session=self.bot.http_session,
                )
            except Exception as e:
                return f"Knowledge lookup failed: {e}"

        return f"Unknown tool: {name}"

    # --- Annie Agentic Chat ---

    def _get_annie_tools(self):
        """Tool definitions for Annie's agentic chat."""
        return [
            {
                "type": "function",
                "function": {
                    "name": "search_and_queue_song",
                    "description": "Search for a song on YouTube and queue it on the radio. The download happens in the background and may take a moment. Accepts a song name, artist, or YouTube URL.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Song name, artist, or YouTube URL",
                            },
                        },
                        "required": ["query"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_currently_playing",
                    "description": "Get the song currently playing on the radio.",
                    "parameters": {"type": "object", "properties": {}, "required": []},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_recent_requests",
                    "description": "Get recently requested songs.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "limit": {"type": "integer", "description": "Number of requests to fetch (default 10)"},
                        },
                        "required": [],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_song_stats",
                    "description": "Get like/dislike stats for songs on the radio.",
                    "parameters": {"type": "object", "properties": {}, "required": []},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_recent_news",
                    "description": "Get recent news segments that Annie has generated for the radio.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "limit": {"type": "integer", "description": "Number of news items (default 5)"},
                        },
                        "required": [],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_recent_jingles",
                    "description": "Get recent jingles/radio segments that Annie has generated.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "limit": {"type": "integer", "description": "Number of jingles (default 10)"},
                        },
                        "required": [],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "skip_current_track",
                    "description": "Skip the currently playing track on the radio.",
                    "parameters": {"type": "object", "properties": {}, "required": []},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "queue_trending_song",
                    "description": "Pick and queue a trending song from the charts.",
                    "parameters": {"type": "object", "properties": {}, "required": []},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "search_playlist",
                    "description": "Search the base radio playlist for songs by keyword. Returns matching filenames from the permanent playlist library.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Search term to match against song filenames. Leave empty to list all songs.",
                            },
                        },
                        "required": [],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "add_to_playlist",
                    "description": "Download a song and add it permanently to the base radio playlist. This adds it to the rotation library, not the request queue.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Song name, artist, or YouTube URL",
                            },
                        },
                        "required": ["query"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "remove_from_playlist",
                    "description": "Remove a song from the base radio playlist by filename. Use search_playlist first to find the exact filename.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "filename": {
                                "type": "string",
                                "description": "Exact filename of the song to remove (e.g. 'Cool_Song.mp3')",
                            },
                        },
                        "required": ["filename"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "create_user_playlist",
                    "description": "Create a new empty playlist for the user.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                "description": "Name for the new playlist (e.g. 'chill vibes', 'road trip')",
                            },
                        },
                        "required": ["name"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "add_to_user_playlist",
                    "description": "Add a song to one of the user's playlists. The song is stored as a search query/URL for later playback.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "playlist_name": {
                                "type": "string",
                                "description": "Name of the playlist to add to",
                            },
                            "song_query": {
                                "type": "string",
                                "description": "Song name, artist, or YouTube URL",
                            },
                        },
                        "required": ["playlist_name", "song_query"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "view_user_playlist",
                    "description": "View all songs in one of the user's playlists.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "playlist_name": {
                                "type": "string",
                                "description": "Name of the playlist to view",
                            },
                        },
                        "required": ["playlist_name"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "list_user_playlists",
                    "description": "List all playlists belonging to the user.",
                    "parameters": {"type": "object", "properties": {}, "required": []},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "play_user_playlist",
                    "description": "Queue all songs from one of the user's playlists on the radio. Songs are downloaded and queued one by one. Max 10 songs per play.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "playlist_name": {
                                "type": "string",
                                "description": "Name of the playlist to play",
                            },
                        },
                        "required": ["playlist_name"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "elevate_to_playlist",
                    "description": "Promote a song to the permanent base radio playlist. The song will be downloaded (or fetched from cache) and added to the main rotation. DJ use only.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "song_query": {
                                "type": "string",
                                "description": "Song name, artist, or YouTube URL to add to the base playlist",
                            },
                        },
                        "required": ["song_query"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "like_song",
                    "description": "Like the currently playing song on the radio on behalf of the listener.",
                    "parameters": {"type": "object", "properties": {}, "required": []},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_top_liked_songs",
                    "description": "Get the most liked songs on the radio, ranked by number of likes.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "limit": {"type": "integer", "description": "Number of songs to return (default 10)"},
                        },
                        "required": [],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "generate_radio_track",
                    "description": "Generate a custom TTS audio track on a given topic. The track is generated by DJ Annie and automatically added to the playlist queue. Use this when a user asks to create a new audio segment or talk track.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "topic": {
                                "type": "string",
                                "description": "The topic or prompt for the audio track",
                            },
                            "duration": {
                                "type": "string",
                                "description": "Approximate spoken duration (e.g. '1-2 minutes', '30 seconds'). Default: '1-2 minutes'",
                            },
                        },
                        "required": ["topic"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "generate_talkshow_segment",
                    "description": "Generate a multi-speaker radio talkshow segment on a given topic, featuring a Host (DJ Annie), a Guest, and optionally a Caller. Uses multiple AI voices for a natural conversation feel. Great for answering listener questions as a fun talk-show discussion, simulating a caller phoning in, or creating a banter segment between hosts. The segment is automatically added to the playlist after generation.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "topic": {
                                "type": "string",
                                "description": "The topic or question for the talkshow segment",
                            },
                            "duration": {
                                "type": "string",
                                "description": "Approximate spoken duration (e.g. '1-2 minutes', '30 seconds'). Default: '1-2 minutes'",
                            },
                        },
                        "required": ["topic"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "ask_game_knowledge",
                    "description": "Ask the game knowledge subagent a question about Motor Town gameplay, vehicles, cargo, player stats, subsidies, server commands, or any other game-related topic. Always use this instead of guessing game facts.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "question": {
                                "type": "string",
                                "description": "The game-related question to research",
                            },
                        },
                        "required": ["question"],
                    },
                },
            },

            {
                "type": "function",
                "function": {
                    "name": "voice_reply_on_radio",
                    "description": "Speak a message on the radio via TTS. The audio will be overlaid on top of the current music, ducking its volume. Use this to reply to listeners on-air. The system will wait if a talking segment is playing to avoid overlap. Use sparingly for fun interactions.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "message": {
                                "type": "string",
                                "description": "The message to speak on the radio. Should be conversational and in Annie's voice.",
                            },
                        },
                        "required": ["message"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "save_knowledge",
                    "description": "Save useful information to the knowledge base. Use this when players share tips, preferences, community facts, or anything worth remembering. Key format: '{type}:{id}' e.g., 'community:favourite-vehicles', 'tip:delivery-tips', 'player:username-prefs'.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "key": {
                                "type": "string",
                                "description": "Knowledge key in '{type}:{id}' format",
                            },
                            "content": {
                                "type": "string",
                                "description": "The knowledge content to save",
                            },
                        },
                        "required": ["key", "content"],
                    },
                },
            },
        ]

    # --- TTS Voice-Over Insertion ---

    async def _insert_tts_on_radio(self, text: str) -> bool:
        """Generate TTS audio and insert it on the radio via the announcements queue.

        Returns True on success, False on failure.
        """
        # Generate TTS audio
        try:
            audio_bytes = await asyncio.to_thread(
                tts_google, discord.utils.remove_markdown(text), use_markup=True
            )
        except Exception as e:
            log.error(f"TTS generation failed: {e}")
            return False

        # Write to a temp file in the radio tmp dir so Liquidsoap can access it
        try:
            os.makedirs(RADIO_TMP_PATH, exist_ok=True)
            fd, tmp_path = tempfile.mkstemp(suffix=".mp3", prefix="voice_", dir=RADIO_TMP_PATH)
            with os.fdopen(fd, "wb") as f:
                f.write(audio_bytes)
            os.chmod(tmp_path, 0o644)  # Liquidsoap runs as a different user
        except Exception as e:
            log.error(f"Failed to write TTS temp file: {e}")
            return False

        # Push to announcements queue (smooth_add overlay ducks the music)
        success = await self.lq.push_announcement(self.bot.http_session, tmp_path)
        if success:
            # Wait for the audio to actually reach listeners (streaming buffer delay)
            await asyncio.sleep(10)
        # Clean up temp file (deferred on success, immediate on failure)
        self.bot.loop.create_task(self._deferred_cleanup(tmp_path, delay=60 if success else 0))
        return success

    async def _deferred_cleanup(self, path: str, delay: int = 1800):
        """Delete a temp audio file after a delay, giving Liquidsoap time to consume it."""
        try:
            await asyncio.sleep(delay)
            os.unlink(path)
            log.debug(f"Cleaned up temp audio file: {path}")
        except OSError:
            pass

    async def _execute_annie_tool(self, name: str, args: dict, requester: str, notify_fn) -> str:
        """Execute a tool call from Annie's agentic loop."""
        try:
            if name == "search_and_queue_song":
                query = args.get("query", "")
                # Fire-and-forget: launch download in background
                self.bot.loop.create_task(
                    self._fire_and_forget_queue(query, requester, notify_fn)
                )
                return f"Download started for '{query}'. I'll notify the listener when it's ready."

            elif name == "get_currently_playing":
                current = await get_current_song(self.bot.http_session)
                return current or "Nothing is playing right now, or I can't reach the radio server."

            elif name == "get_recent_requests":
                limit = args.get("limit", 10)
                requests = self.db.get_top_requested_songs(limit=limit)
                if not requests:
                    return "No song requests recorded yet."
                lines = [f"- {r['song_title']} (requested {r['request_count']}x)" for r in requests]
                return "Recent popular requests:\n" + "\n".join(lines)

            elif name == "get_song_stats":
                stats = self.db.get_all_song_stats()
                if not stats:
                    return "No song stats yet."
                lines = [f"- {s['song_title']}: ❤️ {s['like_count']} | 👎 {s['dislike_count']}" for s in stats[:15]]
                return "Song stats:\n" + "\n".join(lines)

            elif name == "get_recent_news":
                limit = args.get("limit", 5)
                news = self.db.get_recent_news(limit=limit)
                if not news:
                    return "No news segments generated yet."
                lines = [f"### {n['generated_at'][:10]}\n{n['content'][:300]}..." for n in news]
                return "\n\n".join(lines)

            elif name == "get_recent_jingles":
                limit = args.get("limit", 10)
                jingles = self.db.get_recent_jingles(limit=limit)
                if not jingles:
                    return "No jingles generated yet."
                lines = [f"- [{j['generated_at'][:10]}] {j['script'][:100]}..." for j in jingles]
                return "Recent jingles:\n" + "\n".join(lines)

            elif name == "skip_current_track":
                await self.lq.skip_current_track(self.bot.http_session, "song_requests")
                return "Skipped the current track."

            elif name == "queue_trending_song":
                song_query = await self._pick_trending_song()
                self.bot.loop.create_task(
                    self._fire_and_forget_queue(song_query, "DJ Annie", notify_fn, bypass_throttling=True)
                )
                return "Queueing a trending song for you..."

            elif name == "search_playlist":
                return await self._tool_search_playlist(args.get("query", ""))

            elif name == "add_to_playlist":
                query = args.get("query", "")
                self.bot.loop.create_task(
                    self._fire_and_forget_playlist_add(query, notify_fn)
                )
                return f"Download started for '{query}'. I'll add it to the playlist once it's ready."

            elif name == "remove_from_playlist":
                filename = args.get("filename", "")
                return await self._tool_remove_from_playlist(filename)

            elif name == "create_user_playlist":
                playlist_name = args.get("name", "")
                try:
                    self.db.create_playlist(discord_id=requester, name=playlist_name)
                    return f"Created playlist '{playlist_name.strip().lower()}'!"
                except Exception as e:
                    return str(e)

            elif name == "add_to_user_playlist":
                playlist_name = args.get("playlist_name", "")
                song_query = args.get("song_query", "")
                playlist = self.db.get_playlist_by_name(discord_id=requester, name=playlist_name)
                if not playlist:
                    return f"Playlist '{playlist_name}' not found. Create it first!"
                self.db.add_song_to_playlist(playlist["id"], song_query=song_query, song_title=song_query)
                return f"Added '{song_query}' to playlist '{playlist['name']}'."

            elif name == "view_user_playlist":
                playlist_name = args.get("playlist_name", "")
                playlist = self.db.get_playlist_by_name(discord_id=requester, name=playlist_name)
                if not playlist:
                    return f"Playlist '{playlist_name}' not found."
                songs = self.db.get_playlist_songs(playlist["id"])
                if not songs:
                    return f"Playlist '{playlist['name']}' is empty."
                lines = [f"{s['position']}. {s['song_title']}" for s in songs]
                return f"Playlist '{playlist['name']}' ({len(songs)} songs):\n" + "\n".join(lines)

            elif name == "list_user_playlists":
                playlists = self.db.get_playlists(discord_id=requester)
                if not playlists:
                    return "You don't have any playlists yet. Create one!"
                lines = [f"- {p['name']} ({p['song_count']} songs)" for p in playlists]
                return "Your playlists:\n" + "\n".join(lines)

            elif name == "play_user_playlist":
                playlist_name = args.get("playlist_name", "")
                playlist = self.db.get_playlist_by_name(discord_id=requester, name=playlist_name)
                if not playlist:
                    return f"Playlist '{playlist_name}' not found."
                songs = self.db.get_playlist_songs(playlist["id"])
                if not songs:
                    return f"Playlist '{playlist['name']}' is empty."
                self.bot.loop.create_task(
                    self._play_user_playlist(songs, requester, notify_fn)
                )
                capped = min(len(songs), 10)
                return f"Queueing {capped} song(s) from '{playlist['name']}'. Each song takes about 30-60 seconds to download, so sit tight — I'll update you as each one lands!"

            elif name == "elevate_to_playlist":
                song_query = args.get("song_query", "")
                self.bot.loop.create_task(
                    self._fire_and_forget_playlist_add(song_query, notify_fn)
                )
                return f"Elevating '{song_query}' to the base playlist. I'll let you know when it's done!"

            elif name == "like_song":
                metadata = await get_current_song_metadata(self.bot.http_session)
                if not metadata:
                    return "No song is currently playing."
                song_info = parse_song_info(metadata)
                if not song_info:
                    return "Could not identify the current song."
                song_title = song_info["song_title"]
                self.db.add_like(discord_id=requester, song_title=song_title)
                like_count = self.db.get_song_like_count(song_title)
                return f"Liked '{song_title}'! It now has {like_count} like(s)."

            elif name == "get_top_liked_songs":
                limit = args.get("limit", 10)
                top = self.db.get_top_liked_songs(limit=limit)
                if not top:
                    return "No songs have been liked yet."
                lines = [f"- {s['song_title']}: ❤️ {s['like_count']}" for s in top]
                return "Top liked songs:\n" + "\n".join(lines)

            elif name == "generate_radio_track":
                topic = args.get("topic", "")
                duration = args.get("duration", "1-2 minutes")
                try:
                    transcript, audio_bytes = await self.generate_track(topic, duration)
                    # Write to temp dir and push to request queue for immediate playback
                    safe_title = re.sub(r"[^a-zA-Z0-9]", "_", transcript[:40])
                    filename = f"track_{safe_title}.mp3"
                    os.makedirs(RADIO_TMP_PATH, exist_ok=True)
                    tmp_path = os.path.join(RADIO_TMP_PATH, filename)
                    with open(tmp_path, "wb") as f:
                        f.write(audio_bytes)
                    os.chmod(tmp_path, 0o644)
                    await self.lq.push_segment(
                        self.bot.http_session, tmp_path,
                    )
                    self.bot.loop.create_task(self._deferred_cleanup(tmp_path, delay=1800))
                    return "Track generated and queued for playback. It will play after the current track."
                except Exception as e:
                    return f"Failed to generate track: {e}"

            elif name == "generate_talkshow_segment":
                topic = args.get("topic", "")
                duration = args.get("duration", "1-2 minutes")
                try:
                    transcript, audio_bytes = await self.generate_talkshow(topic, duration)
                    # Write to temp dir and push to request queue for immediate playback
                    safe_title = re.sub(r"[^a-zA-Z0-9]", "_", transcript[:40])
                    filename = f"talkshow_{safe_title}.mp3"
                    os.makedirs(RADIO_TMP_PATH, exist_ok=True)
                    tmp_path = os.path.join(RADIO_TMP_PATH, filename)
                    with open(tmp_path, "wb") as f:
                        f.write(audio_bytes)
                    os.chmod(tmp_path, 0o644)
                    await self.lq.push_segment(
                        self.bot.http_session, tmp_path,
                    )
                    self.bot.loop.create_task(self._deferred_cleanup(tmp_path, delay=1800))
                    return "Talkshow segment generated and queued for playback. It will play after the current track."
                except Exception as e:
                    return f"Failed to generate talkshow segment: {e}"

            elif name == "voice_reply_on_radio":
                message_text = args.get("message", "")
                if not message_text:
                    return "No message provided."
                self.bot.loop.create_task(
                    self._voice_reply_background(message_text, notify_fn)
                )
                return "Voice reply is being generated and will play on the radio shortly."

            elif name == "ask_game_knowledge":
                from amc_peripheral.radio.game_knowledge import ask_game_knowledge

                question = args.get("question", "")
                try:
                    answer = await ask_game_knowledge(
                        openai_client=self.openai_client_openrouter,
                        knowledge_store=self.knowledge_store,
                        game_schema=self.game_schema_description,
                        question=question,
                        http_session=self.bot.http_session,
                    )
                    return answer
                except Exception as e:
                    return f"Failed to get game knowledge: {e}"

            elif name == "save_knowledge":
                key = args.get("key", "")
                content = args.get("content", "")
                if not key or not content:
                    return "Error: both 'key' and 'content' are required."
                if ":" not in key:
                    return "Error: key must be in '{type}:{id}' format."
                if self.knowledge_store:
                    self.knowledge_store.save(key, content, source="agent")
                    log.info(f"Knowledge saved by Annie: {key} ({len(content)} chars)")
                    return f"Saved knowledge entry '{key}'."
                return "Knowledge store not available."

            return f"Unknown tool: {name}"
        except Exception as e:
            return f"Tool error ({name}): {e}"

    PLAYLIST_PLAY_CAP = 10

    async def _voice_reply_background(self, text: str, notify_fn):
        """Generate and insert TTS voice reply in the background."""
        try:
            success = await self._insert_tts_on_radio(text)
            if not success:
                await notify_fn("Failed to play voice reply on the radio.")
        except Exception as e:
            await notify_fn(f"Voice reply failed: {e}")

    async def _play_user_playlist(self, songs: list[dict], requester: str, notify_fn):
        """Queue songs from a user playlist one by one (fire-and-forget)."""
        capped = songs[:self.PLAYLIST_PLAY_CAP]
        for i, song in enumerate(capped, 1):
            try:
                title, _ = await self.request_song(
                    song["song_query"], requester, bypass_throttling=True
                )
                await notify_fn(f"🎵 [{i}/{len(capped)}] Queued **{title}**")
            except Exception as e:
                await notify_fn(f"⚠️ [{i}/{len(capped)}] Failed to queue '{song['song_title']}': {e}")
        if len(songs) > self.PLAYLIST_PLAY_CAP:
            await notify_fn(f"ℹ️ Only the first {self.PLAYLIST_PLAY_CAP} songs were queued (playlist has {len(songs)}).")

    async def _fire_and_forget_queue(self, query: str, requester: str, notify_fn, bypass_throttling=False):
        """Download and queue a song in the background, then notify."""
        try:
            title, _ = await self.request_song(
                query, requester, bypass_throttling=bypass_throttling
            )
            if bypass_throttling:
                self.db.add_auto_queue(song_title=str(title))
            await notify_fn(f'🎵 Queued **{title}** — coming up next!')
        except Exception as e:
            await notify_fn(f"Couldn't queue that song: {e}")

    async def _handle_annie_chat_discord(self, message: discord.Message, question: str):
        """Handle an @mention of Annie on Discord."""
        now = datetime.now(self.local_tz)

        # Gather channel history for context
        prev = ""
        async for m in message.channel.history(limit=20):
            if m.id == message.id:
                continue
            prev = f"{m.author.display_name}: {m.content}\n" + prev

        messages = [
            {"role": "system", "content": ANNIE_SYSTEM_PROMPT.format(knowledge_index=self.knowledge_store.build_index() if self.knowledge_store else "")},
            {"role": "user", "content": f"Current time: {now.strftime('%A, %Y-%m-%d %H:%M')} (Bangkok/GMT+7)"},
        ]
        if prev:
            messages.append({"role": "user", "content": f"Recent chat history:\n{prev}"})
        messages.append({"role": "user", "content": f"{message.author.display_name}: {question}"})

        tools = self._get_annie_tools()

        # Notify callback for fire-and-forget downloads on Discord
        async def discord_notify(msg: str):
            await message.channel.send(msg)

        async with message.channel.typing():
            response = await self._call_annie_llm(messages, tools, message.author.display_name, discord_notify)

        for chunk in split_markdown(response):
            await message.reply(chunk, mention_author=False)

    async def _handle_annie_chat_ingame(self, player_name: str, question: str):
        """Handle @annie mention from in-game chat."""
        now = datetime.now(self.local_tz)

        # Gather recent game chat from Discord channel
        prev = ""
        game_chat = self.bot.get_channel(GAME_CHAT_CHANNEL_ID)
        if game_chat:
            async for m in game_chat.history(limit=20):
                prev = f"{m.content}\n" + prev

        messages = [
            {"role": "system", "content": ANNIE_SYSTEM_PROMPT.format(knowledge_index=self.knowledge_store.build_index() if self.knowledge_store else "") + "\nRespond briefly — game chat has a character limit. Keep it under 500 chars.\nDo NOT use any emojis — the game client cannot render them."},
            {"role": "user", "content": f"Current time: {now.strftime('%A, %Y-%m-%d %H:%M')} (Bangkok/GMT+7)"},
        ]
        if prev:
            messages.append({"role": "user", "content": f"Recent in-game chat:\n{prev}"})
        messages.append({"role": "user", "content": f"{player_name}: {question}"})

        tools = self._get_annie_tools()
        channel = self.bot.get_channel(GAME_ANNOUNCEMENTS_CHANNEL_ID)

        async def ingame_notify(msg: str):
            if channel:
                await channel.send(msg)
            await announce_in_game(self.bot.http_session, msg[:520])

        response = await self._call_annie_llm(messages, tools, player_name, ingame_notify)
        await announce_in_game(self.bot.http_session, response[:520])

    async def _call_annie_llm(self, messages: list, tools: list, requester: str, notify_fn) -> str:
        """Agentic loop for Annie — calls LLM with tools until a final response."""
        max_iterations = 20

        for _ in range(max_iterations):
            # pyrefly: ignore [no-matching-overload]
            completion = await self.openai_client_openrouter.chat.completions.create(
                model=DEFAULT_AI_MODEL,
                reasoning_effort="medium",
                messages=messages,
                tools=tools if tools else None,
                tool_choice="auto" if tools else None,
            )

            response = completion.choices[0].message if completion.choices else None
            if not response:
                return "My brain just short-circuited. Try again?"

            if not response.tool_calls:
                return response.content or "..."

            messages.append(response)

            for tool_call in response.tool_calls:
                result = await self._execute_annie_tool(
                    tool_call.function.name,
                    json.loads(tool_call.function.arguments),
                    requester,
                    notify_fn,
                )
                messages.append({
                    "tool_call_id": tool_call.id,
                    "role": "tool",
                    "name": tool_call.function.name,
                    "content": result,
                })

        return "Okay I got a bit carried away there. What were we talking about?"

    async def _do_download(self, youtube_link: str, requester: str):
        """Extract metadata and download a song. Returns (title, duration, base_filename)."""
        search_query = youtube_link
        if "youtube.com" not in search_query and "youtu.be" not in search_query:
            search_query = f"ytsearch:{search_query}"

        ydl_info_opts = {
            "noplaylist": True,
            "quiet": True,
            "default_search": "ytsearch",
            "cookiefile": YT_COOKIES_PATH,
            "js_runtimes": {"deno": {"path": DENO_PATH}},
        }

        try:
            # pyrefly: ignore [bad-argument-type]
            with yt_dlp.YoutubeDL(ydl_info_opts) as ydl:
                info_dict = await asyncio.to_thread(
                    ydl.extract_info, search_query, download=False
                )
            # pyrefly: ignore [bad-typed-dict-key]
            if "entries" in info_dict and info_dict["entries"]:
                # pyrefly: ignore [bad-typed-dict-key]
                info_dict = info_dict["entries"][0]
        except Exception as e:
            raise Exception(
                "Could not find that song. Please try a different name or link."
            ) from e

        title = info_dict.get("title", "Unknown")
        duration = info_dict.get("duration", 0)
        webpage_url = info_dict.get("webpage_url")

        # --- Checks ---
        # pyrefly: ignore [missing-attribute]
        normalized_title = title.lower().strip()
        normalized_queue = [t.lower().strip() for t in self.recent_song_queue]
        if normalized_title in normalized_queue:
            raise Exception(
                f'"{title}" has been queued recently. Please choose a different song.'
            )

        # pyrefly: ignore [unsupported-operation]
        if duration > MAX_SONG_DURATION:
            # pyrefly: ignore [unsupported-operation]
            raise Exception(
                # pyrefly: ignore [unsupported-operation]
                f'"{title}" is too long ({duration // 60}m). Max duration is {MAX_SONG_DURATION // 60} minutes.'
            )

        # --- Download ---
        safe_requester = re.sub(r"[^a-zA-Z0-9]", "_", requester)
        # pyrefly: ignore [no-matching-overload]
        safe_title = re.sub(r"[^a-zA-Z0-9]", "_", title)
        base_filename = f"{safe_requester}-{safe_title}"

        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": f"{REQUESTS_PATH}/{base_filename}.%(ext)s",
            "cookiefile": YT_COOKIES_PATH,
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                },
                {
                    "key": "FFmpegMetadata",
                    "add_metadata": True,
                },
            ],
            "ffmpeg_location": os.environ.get("FFMPEG_PATH"),
            "prefer_ffmpeg": True,
            "retries": 5,
            "js_runtimes": {"deno": {"path": DENO_PATH}},
        }

        try:
            # pyrefly: ignore [bad-argument-type]
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                # pyrefly: ignore [bad-argument-type]
                await asyncio.to_thread(ydl.download, [webpage_url])
        except Exception as e:
            raise Exception(f"Failed to download audio: {e}")

        return title, duration, base_filename, webpage_url

    async def _download_to_path(self, query: str, output_dir: str) -> tuple[str, str]:
        """Download a song to a specific directory. Returns (title, filepath).

        Unlike _do_download, this has no dedup or duration checks — intended
        for playlist curation rather than user requests.
        """
        search_query = query
        if "youtube.com" not in search_query and "youtu.be" not in search_query:
            search_query = f"ytsearch:{search_query}"

        ydl_info_opts = {
            "noplaylist": True,
            "quiet": True,
            "default_search": "ytsearch",
            "cookiefile": YT_COOKIES_PATH,
            "js_runtimes": {"deno": {"path": DENO_PATH}},
        }

        try:
            # pyrefly: ignore [bad-argument-type]
            with yt_dlp.YoutubeDL(ydl_info_opts) as ydl:
                info_dict = await asyncio.to_thread(
                    ydl.extract_info, search_query, download=False
                )
            # pyrefly: ignore [bad-typed-dict-key]
            if "entries" in info_dict and info_dict["entries"]:
                # pyrefly: ignore [bad-typed-dict-key]
                info_dict = info_dict["entries"][0]
        except Exception as e:
            raise Exception(
                "Could not find that song. Please try a different name or link."
            ) from e

        title = info_dict.get("title", "Unknown")
        webpage_url = info_dict.get("webpage_url")
        # pyrefly: ignore [no-matching-overload]
        safe_title = re.sub(r"[^a-zA-Z0-9]", "_", title)
        base_filename = safe_title

        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": f"{output_dir}/{base_filename}.%(ext)s",
            "cookiefile": YT_COOKIES_PATH,
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                },
                {
                    "key": "FFmpegMetadata",
                    "add_metadata": True,
                },
            ],
            "ffmpeg_location": os.environ.get("FFMPEG_PATH"),
            "prefer_ffmpeg": True,
            "retries": 5,
            "js_runtimes": {"deno": {"path": DENO_PATH}},
        }

        try:
            # pyrefly: ignore [bad-argument-type]
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                # pyrefly: ignore [bad-argument-type]
                await asyncio.to_thread(ydl.download, [webpage_url])
        except Exception as e:
            raise Exception(f"Failed to download audio: {e}")

        filepath = f"{output_dir}/{base_filename}.mp3"
        return title, filepath

    async def _tool_search_playlist(self, query: str) -> str:
        """Search the base playlist channel for songs matching a query."""
        playlist_channel = self.bot.get_channel(PLAYLIST_CHANNEL)
        if not playlist_channel:
            return "Could not access the playlist channel."

        matches = []
        async for message in playlist_channel.history(limit=None):
            for attachment in message.attachments:
                if not query or query.lower() in attachment.filename.lower():
                    matches.append(attachment.filename)

        if not matches:
            return f"No songs found matching '{query}'." if query else "The playlist is empty."

        matches.sort()
        lines = [f"- {name}" for name in matches[:50]]
        header = f"Found {len(matches)} song(s)" + (f" matching '{query}'" if query else "") + ":\n"
        return header + "\n".join(lines)

    async def _tool_remove_from_playlist(self, filename: str) -> str:
        """Remove a song from the playlist channel by filename."""
        if not filename:
            return "Please provide a filename to remove. Use search_playlist to find the exact name."

        playlist_channel = self.bot.get_channel(PLAYLIST_CHANNEL)
        if not playlist_channel:
            return "Could not access the playlist channel."

        async for message in playlist_channel.history(limit=None):
            for attachment in message.attachments:
                if attachment.filename.lower() == filename.lower():
                    await message.delete()
                    return f"Removed '{attachment.filename}' from the playlist."

        return f"Could not find '{filename}' in the playlist. Use search_playlist to check the exact filename."

    async def _fire_and_forget_playlist_add(self, query: str, notify_fn):
        """Download a song (cache-aware) and add it to the playlist channel in the background."""
        try:
            # Use cache-aware download
            title, duration, local_path, webpage_url = await asyncio.wait_for(
                self._get_or_download(query),
                timeout=DOWNLOAD_TIMEOUT,
            )

            playlist_channel = self.bot.get_channel(PLAYLIST_CHANNEL)
            if not playlist_channel:
                await notify_fn("Could not access the playlist channel.")
                return

            await playlist_channel.send(
                file=discord.File(local_path)
            )
            await notify_fn(f'🎵 Added **{title}** to the playlist!')
        except Exception as e:
            await notify_fn(f"Couldn't add that song to the playlist: {e}")

    async def request_song(
        self,
        youtube_link: str,
        requester: str,
        discord_id: str | None = None,
        bypass_throttling=False,
    ):
        now = datetime.now(self.local_tz)

        # --- Throttling Logic ---
        ten_minutes_ago = now - timedelta(minutes=10)
        self.user_requests.setdefault(requester, [])
        self.user_requests[requester] = [
            t for t in self.user_requests[requester] if t > ten_minutes_ago
        ]

        five_minutes_ago = now - timedelta(minutes=5)
        requests_last_5_min = sum(
            1 for t in self.user_requests[requester] if t > five_minutes_ago
        )
        requests_last_10_min = len(self.user_requests[requester])

        if not bypass_throttling:
            if requests_last_5_min >= 3:
                raise Exception(
                    "You have queued too many songs. Please wait a moment. (Limit: 3 songs per 5 minutes)"
                )
            if requests_last_10_min >= 5:
                raise Exception(
                    "You have queued too many songs. Please wait a moment. (Limit: 5 songs per 10 minutes)"
                )

        if "chips" in requester.lower().strip():
            raise Exception("User not allowed to request songs.")
        if "give you up" in youtube_link.lower().strip():
            raise Exception("No, just no")

        # --- Queued download (processed by background worker) ---
        future: asyncio.Future = asyncio.get_event_loop().create_future()
        await self._download_queue.put((youtube_link, future))
        queue_pos = self._download_queue.qsize()
        if queue_pos > 0:
            log.info(f"Song '{youtube_link}' queued at position {queue_pos}")

        # Worker applies DOWNLOAD_TIMEOUT when it picks up the job,
        # so we just await the future here — no caller-side timeout.
        title, duration, local_path, webpage_url = await future

        # --- Checks that need resolved metadata ---
        normalized_title = title.lower().strip()
        normalized_queue = [t.lower().strip() for t in self.recent_song_queue]
        if normalized_title in normalized_queue:
            raise Exception(
                f'"{ title}" has been queued recently. Please choose a different song.'
            )

        # pyrefly: ignore [unsupported-operation]
        if duration > MAX_SONG_DURATION:
            # pyrefly: ignore [unsupported-operation]
            raise Exception(
                # pyrefly: ignore [unsupported-operation]
                f'"{ title}" is too long ({duration // 60}m). Max duration is {MAX_SONG_DURATION // 60} minutes.'
            )

        # --- Push to Queue ---
        try:
            await self.lq.push_to_queue(
                self.bot.http_session, "song_requests", local_path,
                title=str(title), requester=requester,
            )
        except Exception as e:
            log.error(f"Failed to push song to queue: {e}")

        # Update throttling
        self.user_requests[requester].append(now)
        self.recent_song_queue.append(title)

        # Persist request
        try:
            self.db.add_request(
                discord_id=discord_id,
                song_title=str(title),
                song_url=str(webpage_url) if webpage_url else None,
                requester_name=requester,
            )
        except Exception as e:
            log.error(f"Failed to persist song request: {e}")

        return title, duration

    async def _get_or_download(self, query: str) -> tuple:
        """Resolve metadata and return cached file or download fresh. Returns (title, duration, local_path, webpage_url)."""
        search_query = query
        if "youtube.com" not in search_query and "youtu.be" not in search_query:
            search_query = f"ytsearch:{search_query}"

        ydl_info_opts = {
            "noplaylist": True,
            "quiet": True,
            "default_search": "ytsearch",
            "cookiefile": YT_COOKIES_PATH,
            "js_runtimes": {"deno": {"path": DENO_PATH}},
        }

        try:
            # pyrefly: ignore [bad-argument-type]
            with yt_dlp.YoutubeDL(ydl_info_opts) as ydl:
                info_dict = await asyncio.wait_for(
                    asyncio.to_thread(
                        ydl.extract_info, search_query, download=False
                    ),
                    timeout=METADATA_TIMEOUT,
                )
            # pyrefly: ignore [bad-typed-dict-key]
            if "entries" in info_dict and info_dict["entries"]:
                # pyrefly: ignore [bad-typed-dict-key]
                info_dict = info_dict["entries"][0]
        except asyncio.TimeoutError:
            raise Exception(
                "Song search timed out. YouTube may be slow — please try again."
            )
        except Exception as e:
            raise Exception(
                "Could not find that song. Please try a different name or link."
            ) from e

        title = info_dict.get("title", "Unknown")
        duration = info_dict.get("duration", 0)
        webpage_url = info_dict.get("webpage_url")
        video_id = info_dict.get("id", "")

        if not video_id:
            raise Exception("Could not resolve video ID for this song.")

        # Check cache
        cached = self.db.get_cached_song(video_id)
        cache_path = f"{SONG_CACHE_PATH}/{video_id}.mp3"

        if cached and os.path.exists(cached["local_path"]):
            log.info(f"Cache hit for '{title}' (video_id={video_id})")
            return title, duration, cached["local_path"], webpage_url

        # Cache miss — evict if needed, then download
        log.info(f"Cache miss for '{title}' (video_id={video_id}), downloading...")
        self._evict_cache()

        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": f"{SONG_CACHE_PATH}/{video_id}.%(ext)s",
            "cookiefile": YT_COOKIES_PATH,
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                },
                {
                    "key": "FFmpegMetadata",
                    "add_metadata": True,
                },
            ],
            "ffmpeg_location": os.environ.get("FFMPEG_PATH"),
            "prefer_ffmpeg": True,
            "retries": 5,
            "js_runtimes": {"deno": {"path": DENO_PATH}},
        }

        try:
            # pyrefly: ignore [bad-argument-type]
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                # pyrefly: ignore [bad-argument-type]
                await asyncio.wait_for(
                    asyncio.to_thread(ydl.download, [webpage_url]),
                    timeout=DOWNLOAD_TIMEOUT,
                )
        except asyncio.TimeoutError:
            raise Exception(
                "Download timed out. The song may be too large or the server is under load. Please try again."
            )
        except Exception as e:
            raise Exception(f"Failed to download audio: {e}")

        # Record in cache
        file_size = os.path.getsize(cache_path) if os.path.exists(cache_path) else 0
        self.db.cache_song(
            video_id=video_id,
            title=title,
            duration=duration,
            local_path=cache_path,
            webpage_url=webpage_url or "",
            file_size=file_size,
        )

        return title, duration, cache_path, webpage_url

    def _evict_cache(self):
        """Evict least-recently-used cache entries to stay under the size cap."""
        max_bytes = SONG_CACHE_MAX_MB * 1024 * 1024
        stats = self.db.get_cache_stats()

        while stats["total_bytes"] > max_bytes or stats["total_files"] > 500:
            oldest = self.db.get_oldest_cached_songs(limit=5)
            if not oldest:
                break
            for entry in oldest:
                try:
                    p = Path(entry["local_path"])
                    if p.exists():
                        p.unlink()
                    self.db.delete_cached_song(entry["video_id"])
                    log.info(f"Evicted cached song: {entry['title']} ({entry['video_id']})")
                except Exception as e:
                    log.error(f"Failed to evict cache entry {entry['video_id']}: {e}")
            stats = self.db.get_cache_stats()

    def _cleanup_legacy_requests(self):
        """Remove old per-requester mp3 files from REQUESTS_PATH (one-time migration)."""
        requests_dir = Path(REQUESTS_PATH)
        if not requests_dir.exists():
            return
        count = 0
        for f in requests_dir.glob("*.mp3"):
            f.unlink(missing_ok=True)
            count += 1
        if count:
            log.info(f"Cleaned up {count} legacy request files from {REQUESTS_PATH}")

    async def compile_playlist(self):
        os.makedirs(PLAYLIST_PATH, exist_ok=True)
        os.makedirs(REQUESTS_PATH, exist_ok=True)
        os.makedirs(os.path.join(RADIO_PATH, "event_songs"), exist_ok=True)
        os.makedirs(os.path.join(RADIO_PATH, "race_songs"), exist_ok=True)
        os.makedirs(JINGLES_PATH, exist_ok=True)

        playlist_list = ""

        files_channel = self.bot.get_channel(PLAYLIST_CHANNEL)
        messages = [m async for m in files_channel.history(limit=None) if m.attachments]
        messages = sorted(messages, key=lambda m: m.content)

        for message in messages:
            for attachment in message.attachments:
                local_path = os.path.join(PLAYLIST_PATH, attachment.filename)
                await attachment.save(local_path)
                playlist_list += f"\n{local_path}"

        with open(os.path.join(PLAYLIST_PATH, "playlist.txt"), "w") as f:
            f.write(playlist_list)

        # Event songs
        event_songs_channel = self.bot.get_channel(EVENT_SONGS_CHANNEL)
        if event_songs_channel:
            event_songs_messages = [
                m
                async for m in event_songs_channel.history(limit=None)
                if m.attachments
            ]
            for message in event_songs_messages:
                for attachment in message.attachments:
                    local_path = os.path.join(
                        RADIO_PATH, "event_songs", attachment.filename
                    )
                    await attachment.save(local_path)

        # Race songs
        race_songs_channel = self.bot.get_channel(RACE_SONGS_CHANNEL)
        if race_songs_channel:
            race_songs_messages = [
                m async for m in race_songs_channel.history(limit=None) if m.attachments
            ]
            for message in race_songs_messages:
                for attachment in message.attachments:
                    local_path = os.path.join(
                        RADIO_PATH, "race_songs", attachment.filename
                    )
                    await attachment.save(local_path)

    async def game_request_song(self, song_name, requester):
        channel = self.bot.get_channel(GAME_ANNOUNCEMENTS_CHANNEL_ID)
        try:
            title, _ = await self.request_song(song_name, requester)
            await channel.send(f"Queued {title} for you, {requester}!")
            await announce_in_game(
                self.bot.http_session,
                f'Queued "{title}" for you, {requester}!',
                color="FEE75C",
            )
        except Exception as e:
            await channel.send(f"Failed to queue {song_name} for {requester}: {e}")

    async def game_queue_trending(self, requester):
        channel = self.bot.get_channel(GAME_ANNOUNCEMENTS_CHANNEL_ID)
        try:
            song_query = await self._pick_trending_song()
            title, _ = await self.request_song(
                song_query,
                requester="DJ Annie",
                discord_id=None,
                bypass_throttling=True,
            )
            self.db.add_auto_queue(song_title=str(title))
            await channel.send(f'🎵 {requester} triggered a trending song: "{title}"!')
            await announce_in_game(
                self.bot.http_session,
                f'Queued trending song "{title}" for you, {requester}!',
                color="FEE75C",
            )
        except Exception as e:
            await channel.send(f"Failed to queue trending song for {requester}: {e}")

    async def game_like_song(self, requester):
        metadata = await get_current_song_metadata(self.bot.http_session)
        if not metadata:
            return

        song_info = parse_song_info(metadata)
        if not song_info:
            return

        song_title = song_info["song_title"]
        original_requester = song_info.get("requester", "Unknown")
        self.db.add_like(discord_id=requester, song_title=song_title)

        await announce_in_game(
            self.bot.http_session,
            f'{requester} liked "{song_title}" (requested by {original_requester})!',
            color="FEE75C",
        )

    async def game_dislike_song(self, requester):
        metadata = await get_current_song_metadata(self.bot.http_session)
        if not metadata:
            return

        song_info = parse_song_info(metadata)
        if not song_info:
            return

        song_title = song_info["song_title"]
        original_requester = song_info.get("requester", "Unknown")
        self.db.add_dislike(discord_id=requester, song_title=song_title)

        await announce_in_game(
            self.bot.http_session,
            f'{requester} disliked "{song_title}" (requested by {original_requester}).',
            color="FEE75C",
        )

    async def game_current_song(self, requester):
        metadata = await get_current_song_metadata(self.bot.http_session)
        if not metadata:
            await announce_in_game(
                self.bot.http_session,
                "No song info available right now.",
                color="FEE75C",
            )
            return

        song_info = parse_song_info(metadata)
        if not song_info:
            await announce_in_game(
                self.bot.http_session,
                "No song info available right now.",
                color="FEE75C",
            )
            return

        song_title = song_info["song_title"]
        original_requester = song_info.get("requester", "Unknown")
        await announce_in_game(
            self.bot.http_session,
            f'Now playing: "{song_title}" (requested by {original_requester})',
            color="FEE75C",
        )

    async def game_playlist_play(self, requester: str, playlist_name: str):
        """Handle /playlist_play from in-game chat."""
        channel = self.bot.get_channel(GAME_ANNOUNCEMENTS_CHANNEL_ID)
        # In-game users are identified by player name (same as game_like_song)
        playlist = self.db.get_playlist_by_name(discord_id=requester, name=playlist_name)
        if not playlist:
            msg = f"Playlist '{playlist_name}' not found, {requester}."
            if channel:
                await channel.send(msg)
            await announce_in_game(self.bot.http_session, msg, color="FEE75C")
            return

        songs = self.db.get_playlist_songs(playlist["id"])
        if not songs:
            msg = f"Playlist '{playlist['name']}' is empty, {requester}."
            if channel:
                await channel.send(msg)
            await announce_in_game(self.bot.http_session, msg, color="FEE75C")
            return

        capped = min(len(songs), self.PLAYLIST_PLAY_CAP)
        msg = f"Queueing {capped} song(s) from '{playlist['name']}' for {requester}. Each download takes ~30-60s, hang tight!"
        if channel:
            await channel.send(msg)
        await announce_in_game(self.bot.http_session, msg, color="FEE75C")

        async def ingame_notify(msg: str):
            if channel:
                await channel.send(msg)
            await announce_in_game(self.bot.http_session, msg[:520])

        await self._play_user_playlist(songs, requester, ingame_notify)

    # --- Commands ---


    @app_commands.command(name="update_jingles", description="Update jingles")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    @app_commands.checks.has_permissions(administrator=True)
    async def update_jingles_discord(self, interaction: discord.Interaction):
        await interaction.response.defer()
        # This calls the task method directly? Wait, task is a loop object.
        # The original code called `client.update_jingles()` but `update_jingles` was decorated with @tasks.loop.
        # Calling a loop object calls its `__call__` which runs it immediately once? No, tasks.loop is not callable like that.
        # Actually in discord.py tasks, `update_jingles.coro(self)` might work or `await update_jingles()` if it wasn't started?
        # Re-reading original radio.py logic: `@tasks.loop` `async def update_jingles(self):`.
        # `await client.update_jingles()`... wait, if `client.update_jingles` is the loop object, awaiting it is valid?
        # No, you usually can't await a Loop object.
        # However, we can extract the function and run it manually.
        # Let's extract the core logic to a helper if we want to trigger it manually.
        # For now, I'll extract logic from the loop body to `_update_jingles_logic` and call that.
        await self._update_jingles_logic()
        await interaction.followup.send("Updated")

    @app_commands.command(name="post_gazette", description="Generate a gazette")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    @app_commands.checks.has_permissions(administrator=True)
    async def gazette_cmd(self, interaction: discord.Interaction, prompt: str = ""):
        await interaction.response.defer()
        try:
            gazette = await self.generate_gazette_content(prompt=prompt)
        except Exception as e:
            await interaction.followup.send(f"Failed: {e}")
            return

        for chunk in split_markdown(gazette):
            await interaction.followup.send(chunk)

    @app_commands.command(
        name="create_segment", description="Create a custom DJ Annie radio segment"
    )
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    @app_commands.checks.has_permissions(administrator=True)
    async def create_segment_cmd(self, interaction: discord.Interaction, topic: str):
        await interaction.response.defer()

        try:
            transcript, audio_bytes = await self.generate_segment(topic)
        except Exception as e:
            await interaction.followup.send(f"Failed to generate segment: {e}")
            return

        # Save to jingles directory
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"segment_{timestamp}.mp3"
        local_path = os.path.join(JINGLES_PATH, filename)
        with open(local_path, "wb") as f:
            f.write(audio_bytes)

        # Upload to Discord and reply with both transcript and audio
        await interaction.followup.send(
            content=f"**Segment created!**\n\n{transcript[:1900]}",
            file=discord.File(BytesIO(audio_bytes), filename=filename),
        )

    @app_commands.command(
        name="create_track", description="Generate a custom TTS audio track for the radio playlist"
    )
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    @app_commands.checks.has_permissions(administrator=True)
    async def create_track_cmd(
        self, interaction: discord.Interaction, topic: str, duration: str = "1-2 minutes"
    ):
        await interaction.response.defer()

        try:
            transcript, audio_bytes = await self.generate_track(topic, duration)
        except Exception as e:
            await interaction.followup.send(f"Failed to generate track: {e}")
            return

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"track_{timestamp}.mp3"

        # Store pending for confirmation
        track_id = str(uuid.uuid4())
        self._pending_tracks[track_id] = (transcript, audio_bytes)

        view = TrackConfirmView(self, track_id, filename)
        await interaction.followup.send(
            content=f"**Track preview:**\n\n{transcript[:1800]}\n\n*Click Confirm to add to the playlist, or Cancel to discard.*",
            file=discord.File(BytesIO(audio_bytes), filename=filename),
            view=view,
        )

    @app_commands.command(
        name="create_talkshow", description="Generate a multi-speaker radio talkshow segment"
    )
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def create_talkshow_cmd(
        self, interaction: discord.Interaction, topic: str, duration: str = "1-2 minutes"
    ):
        # Allow admins or DJ role
        member = interaction.user
        is_admin = member.guild_permissions.administrator if hasattr(member, "guild_permissions") else False
        is_dj = any(r.id == DJ_ROLE_ID for r in member.roles) if hasattr(member, "roles") else False
        if not is_admin and not is_dj:
            await interaction.response.send_message(
                "Only admins and DJs can create talkshow segments.", ephemeral=True
            )
            return

        await interaction.response.defer()

        try:
            transcript, audio_bytes = await self.generate_talkshow(topic, duration)
        except Exception as e:
            await interaction.followup.send(f"Failed to generate talkshow: {e}")
            return

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"talkshow_{timestamp}.mp3"

        # Store pending for confirmation (reuse track confirm flow)
        track_id = str(uuid.uuid4())
        self._pending_tracks[track_id] = (transcript, audio_bytes)

        view = TrackConfirmView(self, track_id, filename)
        await interaction.followup.send(
            content=f"**Talkshow preview:**\n\n{transcript[:1800]}\n\n*Click Confirm to add to the playlist, or Cancel to discard.*",
            file=discord.File(BytesIO(audio_bytes), filename=filename),
            view=view,
        )

    @app_commands.command(
        name="voice_announce", description="Speak a message over the radio via TTS (Admin only)"
    )
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    @app_commands.checks.has_permissions(administrator=True)
    async def voice_announce_cmd(self, interaction: discord.Interaction, message: str):
        await interaction.response.defer()
        try:
            success = await self._insert_tts_on_radio(message)
            if success:
                await interaction.followup.send(
                    f"🎙️ Voice announcement queued! It will play on the radio shortly.\n\n> {message[:500]}"
                )
            else:
                await interaction.followup.send("Failed to insert voice announcement.")
        except Exception as e:
            await interaction.followup.send(f"Failed: {e}")

    @app_commands.command(name="song_request", description="Submit a song request")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def song_request_cmd(
        self, interaction: discord.Interaction, song_or_youtube_link: str
    ):
        await interaction.response.defer(ephemeral=True)
        member = interaction.user
        bypass_throttling = False
        # pyrefly: ignore [missing-attribute]
        if any(r.id == DJ_ROLE_ID for r in member.roles):
            bypass_throttling = True

        try:
            title, _ = await self.request_song(
                song_or_youtube_link,
                interaction.user.display_name,
                str(interaction.user.id),
                bypass_throttling,
            )
            await interaction.followup.send(
                f'Downloaded, your song "{title}" will be played soon!', ephemeral=True
            )
        except Exception as e:
            await interaction.followup.send(f"Failed: {e}", ephemeral=True)

    @app_commands.command(name="like", description="Like the currently playing song")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def like_cmd(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        metadata = await get_current_song_metadata(self.bot.http_session)
        if not metadata:
            await interaction.followup.send(
                "No song is currently playing.", ephemeral=True
            )
            return

        song_info = parse_song_info(metadata)
        if not song_info:
            await interaction.followup.send(
                "Could not identify the current song.", ephemeral=True
            )
            return

        song_title = song_info["song_title"]
        # Unfortunately liquidsoap doesn't always give us the URL,
        # but we have the title which is our primary key for likes

        self.db.add_like(discord_id=str(interaction.user.id), song_title=song_title)

        await interaction.followup.send(f"❤️ Liked **{song_title}**!", ephemeral=True)

    @app_commands.command(
        name="dislike", description="Dislike the currently playing song"
    )
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def dislike_cmd(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        metadata = await get_current_song_metadata(self.bot.http_session)
        if not metadata:
            await interaction.followup.send(
                "No song is currently playing.", ephemeral=True
            )
            return

        song_info = parse_song_info(metadata)
        if not song_info:
            await interaction.followup.send(
                "Could not identify the current song.", ephemeral=True
            )
            return

        song_title = song_info["song_title"]

        self.db.add_dislike(discord_id=str(interaction.user.id), song_title=song_title)

        await interaction.followup.send(
            f"👎 Disliked **{song_title}**.", ephemeral=True
        )

    @app_commands.command(
        name="list_likes", description="List song likes and unlikes (Admin only)"
    )
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    @app_commands.checks.has_permissions(administrator=True)
    async def list_likes_cmd(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        stats = self.db.get_all_song_stats()
        if not stats:
            await interaction.followup.send(
                "No likes or unlikes recorded yet.", ephemeral=True
            )
            return

        lines = ["# 📻 Song Popularity Stats\n"]
        for s in stats:
            title = s["song_title"]
            likes = s["like_count"]
            dislikes = s["dislike_count"]
            if likes > 0 or dislikes > 0:
                lines.append(f"- **{title}**: ❤️ {likes} | 👎 {dislikes}")

        content = "\n".join(lines)
        for chunk in split_markdown(content):
            await interaction.followup.send(chunk, ephemeral=True)

    @app_commands.command(name="top_likes", description="See the most liked songs on the radio")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def top_likes_cmd(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        top = self.db.get_top_liked_songs(limit=10)
        if not top:
            await interaction.followup.send("No songs have been liked yet.", ephemeral=True)
            return
        lines = ["**❤️ Most Liked Songs**\n"]
        for i, s in enumerate(top, 1):
            lines.append(f"{i}. **{s['song_title']}** — ❤️ {s['like_count']}")
        await interaction.followup.send("\n".join(lines), ephemeral=True)

    @app_commands.command(
        name="recompile_playlist", description="Recompile radio playlist"
    )
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    @app_commands.checks.has_permissions(administrator=True)
    async def recompile_playlist_cmd(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        self.bot.loop.create_task(self.compile_playlist())
        await interaction.followup.send("Update queued", ephemeral=True)

    @app_commands.command(name="regenerate_news", description="Regenerate news")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    @app_commands.checks.has_permissions(administrator=True)
    async def regenerate_news_cmd(self, interaction: discord.Interaction):
        await interaction.response.defer()
        await self._update_news_logic()
        await interaction.followup.send("Updated")

    @app_commands.command(name="queue_trending", description="Queue a trending song from the charts")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    @app_commands.checks.has_permissions(administrator=True)
    async def queue_trending_cmd(self, interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            song_query = await self._pick_trending_song()
            title, _ = await self.request_song(
                song_query,
                requester="DJ Annie",
                discord_id=None,
                bypass_throttling=True,
            )
            self.db.add_auto_queue(song_title=str(title))
            await interaction.followup.send(f"🎵 Auto-queued **{title}**!")
        except Exception as e:
            await interaction.followup.send(f"Failed: {e}")

    @app_commands.command(name="skip_radio_track", description="Skip a radio track")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def skip_radio_track(self, interaction: discord.Interaction):
        await interaction.response.send_message("Skipping", ephemeral=True)
        self.bot.loop.create_task(
            self.lq.skip_current_track(self.bot.http_session, "song_requests")
        )

    # --- Playlist Commands (group: /playlist <subcommand>) ---

    @playlist_group.command(name="create", description="Create a new playlist")
    async def playlist_create_cmd(self, interaction: discord.Interaction, name: str):
        await interaction.response.defer(ephemeral=True)
        try:
            self.db.create_playlist(discord_id=str(interaction.user.id), name=name)
            await interaction.followup.send(f"✅ Created playlist **{name.strip().lower()}**!", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"Failed: {e}", ephemeral=True)

    @playlist_group.command(name="delete", description="Delete one of your playlists")
    async def playlist_delete_cmd(self, interaction: discord.Interaction, name: str):
        await interaction.response.defer(ephemeral=True)
        deleted = self.db.delete_playlist(discord_id=str(interaction.user.id), name=name)
        if deleted:
            await interaction.followup.send(f"🗑️ Deleted playlist **{name.strip().lower()}** and all its songs.", ephemeral=True)
        else:
            await interaction.followup.send(f"Playlist '{name}' not found.", ephemeral=True)

    @playlist_group.command(name="add", description="Add a song to one of your playlists")
    async def playlist_add_cmd(self, interaction: discord.Interaction, playlist: str, song: str):
        await interaction.response.defer(ephemeral=True)
        pl = self.db.get_playlist_by_name(discord_id=str(interaction.user.id), name=playlist)
        if not pl:
            await interaction.followup.send(f"Playlist '{playlist}' not found. Create it first with `/playlist create`.", ephemeral=True)
            return
        self.db.add_song_to_playlist(pl["id"], song_query=song, song_title=song)
        await interaction.followup.send(f"🎵 Added **{song}** to playlist **{pl['name']}**!", ephemeral=True)

    @playlist_group.command(name="remove", description="Remove a song from one of your playlists")
    async def playlist_remove_cmd(self, interaction: discord.Interaction, playlist: str, song_title: str):
        await interaction.response.defer(ephemeral=True)
        pl = self.db.get_playlist_by_name(discord_id=str(interaction.user.id), name=playlist)
        if not pl:
            await interaction.followup.send(f"Playlist '{playlist}' not found.", ephemeral=True)
            return
        removed = self.db.remove_song_from_playlist(pl["id"], song_title=song_title)
        if removed:
            await interaction.followup.send(f"Removed **{song_title}** from **{pl['name']}**.", ephemeral=True)
        else:
            await interaction.followup.send(f"Song '{song_title}' not found in playlist '{pl['name']}'.", ephemeral=True)

    @playlist_group.command(name="view", description="View songs in one of your playlists")
    async def playlist_view_cmd(self, interaction: discord.Interaction, name: str):
        await interaction.response.defer(ephemeral=True)
        pl = self.db.get_playlist_by_name(discord_id=str(interaction.user.id), name=name)
        if not pl:
            await interaction.followup.send(f"Playlist '{name}' not found.", ephemeral=True)
            return
        songs = self.db.get_playlist_songs(pl["id"])
        if not songs:
            await interaction.followup.send(f"Playlist **{pl['name']}** is empty.", ephemeral=True)
            return
        lines = [f"{s['position']}. {s['song_title']}" for s in songs]
        await interaction.followup.send(f"📋 **{pl['name']}** ({len(songs)} songs):\n" + "\n".join(lines), ephemeral=True)

    @playlist_group.command(name="list", description="List all your playlists")
    async def playlist_list_cmd(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        playlists = self.db.get_playlists(discord_id=str(interaction.user.id))
        if not playlists:
            await interaction.followup.send("You don't have any playlists yet. Use `/playlist create` to make one!", ephemeral=True)
            return
        lines = [f"- **{p['name']}** ({p['song_count']} songs)" for p in playlists]
        await interaction.followup.send("📻 **Your Playlists:**\n" + "\n".join(lines), ephemeral=True)

    @playlist_group.command(name="play", description="Queue all songs from one of your playlists")
    async def playlist_play_cmd(self, interaction: discord.Interaction, name: str):
        await interaction.response.defer(ephemeral=True)
        pl = self.db.get_playlist_by_name(discord_id=str(interaction.user.id), name=name)
        if not pl:
            await interaction.followup.send(f"Playlist '{name}' not found.", ephemeral=True)
            return
        songs = self.db.get_playlist_songs(pl["id"])
        if not songs:
            await interaction.followup.send(f"Playlist **{pl['name']}** is empty.", ephemeral=True)
            return
        capped = min(len(songs), self.PLAYLIST_PLAY_CAP)
        await interaction.followup.send(f"🎶 Queueing {capped} song(s) from **{pl['name']}**. Each download takes ~30-60s — I'll notify you as each one is ready!", ephemeral=True)

        async def discord_notify(msg: str):
            await interaction.followup.send(msg, ephemeral=True)

        self.bot.loop.create_task(
            self._play_user_playlist(songs, interaction.user.display_name, discord_notify)
        )

    @playlist_group.command(name="elevate", description="Promote a song to the permanent base radio playlist")
    async def playlist_elevate_cmd(self, interaction: discord.Interaction, song: str):
        # Check DJ role
        if not any(r.id == DJ_ROLE_ID for r in interaction.user.roles):
            await interaction.response.send_message("Only DJs can elevate songs to the base playlist.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)

        async def discord_notify(msg: str):
            await interaction.followup.send(msg, ephemeral=True)

        self.bot.loop.create_task(
            self._fire_and_forget_playlist_add(song, discord_notify)
        )
        await interaction.followup.send(f"Elevating **{song}** to the base playlist...", ephemeral=True)

    @app_commands.command(name="set_event_mode", description="Set event mode")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    @app_commands.checks.has_any_role("DJ", "Event Organiser", 1346047801473105950)
    async def set_event_mode(self, interaction: discord.Interaction, state: bool):
        await interaction.response.send_message("Setting event mode")
        state_str = "true" if state else "false"
        self.bot.loop.create_task(
            self.lq.set_var(self.bot.http_session, "event_mode", state_str)
        )
        self.bot.loop.create_task(
            self.lq.set_var(self.bot.http_session, "race_mode", "false")
        )

    @app_commands.command(name="set_race_mode", description="Set race mode")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    @app_commands.checks.has_any_role("DJ", "Event Organiser", 1346047801473105950)
    async def set_race_mode(self, interaction: discord.Interaction, state: bool):
        await interaction.response.send_message("Setting race mode")
        state_str = "true" if state else "false"
        self.bot.loop.create_task(
            self.lq.set_var(self.bot.http_session, "race_mode", state_str)
        )

    # --- Tasks ---

    async def _update_jingles_logic(self):
        channel = self.bot.get_channel(JINGLES_CHANNEL_ID)
        i = 0
        async for jingle, jingle_audio in self.generate_jingles_gen():
            filename = f"jingle{i}.mp3"
            with open(os.path.join(JINGLES_PATH, filename), "wb") as f:
                f.write(jingle_audio)

            # Persist to DB
            self.db.add_jingle(script=jingle, audio_filename=filename)

            if channel:
                self.bot.loop.create_task(
                    channel.send(
                        jingle[:2000],
                        file=discord.File(
                            BytesIO(jingle_audio), filename=filename
                        ),
                    )
                )
            i += 1

    @tasks.loop(
        time=[
            dt_time(hour=0, minute=30, tzinfo=timezone.utc),
            dt_time(hour=5, minute=00, tzinfo=timezone.utc),
            dt_time(hour=8, minute=00, tzinfo=timezone.utc),
            dt_time(hour=11, minute=00, tzinfo=timezone.utc),
            dt_time(hour=15, minute=00, tzinfo=timezone.utc),
            dt_time(hour=19, minute=00, tzinfo=timezone.utc),
        ]
    )
    async def update_jingles(self):
        await self._update_jingles_logic()

    @update_jingles.before_loop
    async def before_update_jingles(self):
        await self.bot.wait_until_ready()

    @update_jingles.error
    async def update_jingles_error(self, error):
        log.error(f"update_jingles task error: {error}", exc_info=error)

    @tasks.loop(time=dt_time(hour=0, minute=30, tzinfo=timezone.utc))
    async def post_gazette_task(self):
        gazette = await self.generate_gazette_content()
        chan = self.bot.get_channel(GENERAL_CHANNEL_ID)
        if chan:
            for chunk in split_markdown(gazette):
                await chan.send(chunk)

    @post_gazette_task.before_loop
    async def before_post_gazette_task(self):
        await self.bot.wait_until_ready()

    # --- Auto-Queue Trending Songs ---

    FALLBACK_QUERIES = [
        "top driving songs", "best road trip songs",
        "popular chill songs", "indie rock hits",
        "classic rock driving", "summer hits playlist",
        "feel good songs", "upbeat pop songs",
    ]

    # Tags for tag.gettoptracks — driving/radio-friendly genres
    LASTFM_TAGS = [
        "rock", "pop", "indie", "electronic", "hip-hop", "r&b",
        "alternative", "classic rock", "soul", "funk", "dance",
        "80s", "90s", "chill", "driving", "summer",
    ]

    # Countries for geo.gettoptracks — ASEAN + popular music markets
    LASTFM_COUNTRIES = [
        "Thailand", "Indonesia", "Malaysia", "Philippines", "Vietnam",
        "Singapore", "Japan", "South Korea", "United States",
        "United Kingdom", "Australia",
    ]

    async def _pick_trending_song(self) -> str:
        """Pick a random song from Last.fm using varied API methods for diversity.

        Randomly selects between three Last.fm sources to avoid repeating
        the same small pool of global chart tracks:
          - 60% tag.gettoptracks (genre-based discovery)
          - 25% chart.gettoptracks with random page 1-5
          - 15% geo.gettoptracks (regional discovery)
        """
        try:
            url = "https://ws.audioscrobbler.com/2.0/"
            roll = random.random()

            if roll < 0.60:
                # Genre-based discovery
                tag = random.choice(self.LASTFM_TAGS)
                params = {
                    "method": "tag.gettoptracks",
                    "tag": tag,
                    "api_key": LASTFM_API_KEY,
                    "format": "json",
                    "limit": 50,
                }
                log.debug(f"Last.fm source: tag.gettoptracks (tag={tag})")
            elif roll < 0.85:
                # Global chart with random page for deeper discovery
                page = random.randint(1, 5)
                params = {
                    "method": "chart.gettoptracks",
                    "page": page,
                    "api_key": LASTFM_API_KEY,
                    "format": "json",
                    "limit": 50,
                }
                log.debug(f"Last.fm source: chart.gettoptracks (page={page})")
            else:
                # Regional discovery
                country = random.choice(self.LASTFM_COUNTRIES)
                params = {
                    "method": "geo.gettoptracks",
                    "country": country,
                    "api_key": LASTFM_API_KEY,
                    "format": "json",
                    "limit": 50,
                }
                log.debug(f"Last.fm source: geo.gettoptracks (country={country})")

            async with self.bot.http_session.get(url, params=params) as resp:
                data = await resp.json()

            tracks = data["tracks"]["track"]

            # Filter out songs auto-queued in the last 24 hours
            recent_auto = self.db.get_recent_auto_queued(hours=24)
            recent_titles = {r["song_title"].lower() for r in recent_auto}
            candidates = [
                t for t in tracks
                if f"{t['artist']['name']} - {t['name']}".lower() not in recent_titles
            ]
            if not candidates:
                candidates = tracks  # fallback to full list if all filtered

            track = random.choice(candidates)
            return f"{track['artist']['name']} - {track['name']}"
        except Exception as e:
            log.warning(f"Last.fm fetch failed, using fallback: {e}")
            return f"ytsearch:{random.choice(self.FALLBACK_QUERIES)}"

    @tasks.loop(minutes=20)
    async def auto_queue_trending(self):
        """Queue a trending song only if the request queue is empty."""
        try:
            queue_len = await self.lq.get_queue_length(
                self.bot.http_session, "song_requests"
            )
            if queue_len is not None and queue_len > 0:
                log.info(
                    f"Skipping auto-queue: {queue_len} song(s) already in queue"
                )
                return

            song_query = await self._pick_trending_song()
            title, _ = await self.request_song(
                song_query,
                requester="DJ Annie",
                discord_id=None,
                bypass_throttling=True,
            )
            self.db.add_auto_queue(song_title=str(title))
            log.info(f"Auto-queued trending song: {title}")
        except Exception as e:
            log.error(f"Failed to auto-queue trending song: {e}")

    @auto_queue_trending.before_loop
    async def before_auto_queue_trending(self):
        await self.bot.wait_until_ready()

    async def _update_news_logic(self):
        channel = self.bot.get_channel(DYNAMIC_NEWS_CHANNEL)
        if not channel:
            return
        news = await self.generate_news_content()
        news_audio = await asyncio.to_thread(
            tts_google, discord.utils.remove_markdown(news), use_markup=True
        )
        message = await channel.send(
            news[:2000], file=discord.File(BytesIO(news_audio), filename="news.mp3")
        )

        # Persist to DB
        audio_filename = None
        if message.attachments:
            attachment = message.attachments[0]
            audio_filename = attachment.filename
            local_path = os.path.join(JINGLES_PATH, attachment.filename)
            await attachment.save(local_path)

        self.db.add_news(content=news, audio_filename=audio_filename)

    @tasks.loop(
        time=[
            dt_time(hour=0, minute=45, tzinfo=timezone.utc),
            dt_time(hour=8, minute=30, tzinfo=timezone.utc),
            dt_time(hour=10, minute=0, tzinfo=timezone.utc),
            dt_time(hour=12, minute=30, tzinfo=timezone.utc),
            dt_time(hour=15, minute=0, tzinfo=timezone.utc),
        ]
    )
    async def update_news(self):
        await self._update_news_logic()

    @update_news.before_loop
    async def before_update_news(self):
        await self.bot.wait_until_ready()

    @update_news.error
    async def update_news_error(self, error):
        log.error(f"update_news task error: {error}", exc_info=error)

    @tasks.loop(seconds=10)
    async def update_current_song_embed(self):
        # Send systemd watchdog heartbeat (proves the event loop is alive)
        try:
            import systemd.daemon  # type: ignore[import-untyped]
            systemd.daemon.notify("WATCHDOG=1")
        except ImportError:
            pass

        radio_channel = self.bot.get_channel(RADIO_CHANNEL_ID)
        if not radio_channel:
            # log.warning(f'Radio channel cannot be found from channel id: {RADIO_CHANNEL_ID}')
            return

        metadata = await get_current_song_metadata(self.bot.http_session)
        if not metadata:
            return

        song_info = parse_song_info(metadata)
        if not song_info:
            return

        folder = song_info["folder"]
        requester = song_info["requester"]
        song_title = song_info["song_title"]

        embed = discord.Embed(
            title="📻 AMC Radio",
            color=discord.Color.yellow(),
        )
        embed.add_field(name="Currently Playing", value=f"*{song_title}*", inline=False)
        verb = (
            "Previously requested by" if folder == "prev_requests" else "Requested by"
        )
        embed.add_field(name=verb, value=requester, inline=False)
        embed.add_field(
            name="How to tune in",
            value="Find **ASEAN Motor Club** in the game's radio channel list, or\n**[Listen on the Website](https://www.aseanmotorclub.com/radio)**",
            inline=False,
        )
        embed.add_field(
            name="How to request songs",
            value="Use the `/song_request` command in this channel or in the game chat, followed by the name of the song/artist, or a youtube link",
            inline=False,
        )

        # Show like count if any
        like_count = self.db.get_song_like_count(song_title)
        if like_count > 0:
            embed.add_field(
                name="❤️ Likes", value=str(like_count), inline=True,
            )

        view = self._now_playing_view

        if self.embed_message_id:
            try:
                message = await radio_channel.fetch_message(self.embed_message_id)
                await message.edit(embed=embed, view=view)
            except discord.NotFound:
                self.embed_message_id = None
            except Exception as e:
                log.error(f"Error updating message: {e}")

        if not self.embed_message_id:
            try:
                new_message = await radio_channel.send(embed=embed, view=view)
                self.embed_message_id = new_message.id
            except Exception as e:
                log.error(f"Error sending new message: {e}")

    @update_current_song_embed.before_loop
    async def before_update_current_song_embed(self):
        await self.bot.wait_until_ready()
        radio_channel = self.bot.get_channel(RADIO_CHANNEL_ID)
        if radio_channel:
            async for m in radio_channel.history(limit=1, oldest_first=True):
                if m.author.bot:
                    self.embed_message_id = m.id

    # --- Listeners ---

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if message.channel.id == PLAYLIST_CHANNEL:
            if message.attachments:
                self.bot.loop.create_task(self.compile_playlist())

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author == self.bot.user:
            return

        channel_id = message.channel.id

        # Discord @mention → Annie agentic chat
        if self.bot.user in message.mentions and message.content:
            question = message.content.replace(f"<@{self.bot.user.id}>", "").replace(f"<@!{self.bot.user.id}>", "").strip()
            if question:
                self.bot.loop.create_task(self._handle_annie_chat_discord(message, question))
                return

        if channel_id == RADIO_CHANNEL_ID:
            if message.type != discord.MessageType.chat_input_command:
                await message.delete()

        elif channel_id == SONGS_CHANNEL:
            attachment = None
            if message.attachments:
                attachment = message.attachments[0]
            elif message.reference and message.reference.resolved:
                # pyrefly: ignore [missing-attribute]
                attachment = message.reference.resolved.attachments[0]

            if attachment:
                local_path = os.path.join(SONGS_PATH, attachment.filename)
                # pyrefly: ignore [bad-argument-type]
                await attachment.save(local_path)

        elif channel_id in [PLAYLIST_CHANNEL, RACE_SONGS_CHANNEL, EVENT_SONGS_CHANNEL]:
            if message.attachments:
                self.bot.loop.create_task(self.compile_playlist())

        elif channel_id == EDITORIAL_CHANNEL_ID:
            # Using unawaited invocation or loop task?
            # Original code: await client.update_news(). But update_news is a task loop.
            # It probably meant running the logic once.
            await self._update_news_logic()

        elif channel_id == GAME_CHAT_CHANNEL_ID:
            if command_match := re.match(
                r"\*\*(?P<name>.+):\*\* /(?P<command>\w+)(?: (?P<args>.+))?",
                message.content,
            ):
                name = command_match.group("name")
                command = command_match.group("command")
                args = command_match.group("args")
                log.info(f"Received command {name} {command} {args}")

                if command == "song_request" and args:
                    song_name = args
                    if name in self.banned_requesters:
                        return
                    self.bot.loop.create_task(self.game_request_song(song_name, name))
                elif command == "like":
                    self.bot.loop.create_task(self.game_like_song(name))
                elif command == "dislike":
                    self.bot.loop.create_task(self.game_dislike_song(name))
                elif command == "event_mode" and args:
                    self.bot.loop.create_task(
                        self.lq.set_var(self.bot.http_session, "event_mode", args)
                    )
                elif command == "skip":
                    self.bot.loop.create_task(
                        self.lq.skip_current_track(self.bot.http_session, "song_requests")
                    )
                elif command == "current_song":
                    self.bot.loop.create_task(self.game_current_song(name))
                elif command == "queue_trending":
                    self.bot.loop.create_task(self.game_queue_trending(name))
                elif command == "playlist_play" and args:
                    self.bot.loop.create_task(self.game_playlist_play(name, args))

            # In-game @annie mention → Annie agentic chat
            elif annie_match := re.match(
                r"\*\*(?P<name>.+):\*\* @annie\s+(?P<question>.+)",
                message.content,
                re.IGNORECASE,
            ):
                name = annie_match.group("name")
                question = annie_match.group("question")
                if name not in self.banned_requesters:
                    self.bot.loop.create_task(self._handle_annie_chat_ingame(name, question))

    @commands.Cog.listener()
    async def on_message_edit(
        self, message_before: discord.Message, message: discord.Message
    ):
        if message.channel.id == PLAYLIST_CHANNEL and message.attachments:
            self.bot.loop.create_task(self.compile_playlist())
