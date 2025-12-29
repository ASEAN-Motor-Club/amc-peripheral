import os
import re
import asyncio
import discord
from io import BytesIO
from zoneinfo import ZoneInfo
from datetime import datetime, timedelta, timezone, time as dt_time
from collections import deque
from typing import List

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
    NEWS_CHANNEL_ID,
    EDITORIAL_CHANNEL_ID,
    GAME_ANNOUNCEMENTS_CHANNEL_ID,
    JINGLES_CHANNEL_ID,
    FILES_CHANNEL_ID,
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
    SONGS_PATH,
    JINGLES_PATH,
    DENO_PATH,
)
from amc_peripheral.utils.text_utils import split_markdown
from amc_peripheral.radio.tts import tts as tts_google
from amc_peripheral.radio.liquidsoap import LiquidsoapController

log = logging.getLogger(__name__)


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


class LinkView(discord.ui.View):
    def __init__(self, url: str, label: str = "Open Link"):
        super().__init__(timeout=None)
        self.add_item(
            discord.ui.Button(label=label, style=discord.ButtonStyle.url, url=url)
        )


class RadioCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.openai_client_openrouter = AsyncOpenAI(
            api_key=OPENAI_API_KEY_OPENROUTER, base_url="https://openrouter.ai/api/v1"
        )
        self.local_tz = ZoneInfo("Asia/Bangkok")
        self.lq = LiquidsoapController()

        # State
        self.knowledge_system_message = None
        self.embed_message_id = None
        self.user_requests = {}
        self.recent_song_queue = deque(maxlen=10)
        self.banned_requesters = [
            "LemurStreet",
        ]

    async def cog_load(self):
        self.post_gazette_task.start()
        self.update_jingles.start()
        self.update_news.start()
        self.update_current_song_embed.start()

        # Load knowledge on start
        try:
            self.knowledge_system_message = await self.fetch_knowledge()
        except Exception as e:
            log.error(f"Failed to load initial knowledge: {e}")

    async def cog_unload(self):
        self.post_gazette_task.cancel()
        self.update_jingles.cancel()
        self.update_news.cancel()
        self.update_current_song_embed.cancel()

    # --- Helpers ---

    async def fetch_knowledge(self):
        files_channel = self.bot.get_channel(FILES_CHANNEL_ID)
        if not files_channel:
            # Fallback/Retry logic could be here, or just raise
            return ""

        files_messages = [
            m async for m in files_channel.history(limit=4) if m.attachments
        ]
        for m in files_messages:
            if m.attachments[0].filename == "knowledge.txt":
                file_bytes = await m.attachments[0].read()
                try:
                    return file_bytes.decode("utf-8")
                except UnicodeDecodeError:
                    log.error("Failed to extract knowledge")
        raise Exception("Failed to find knowledge")

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

        knowledge = self.knowledge_system_message or ""
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

    async def request_song(
        self, youtube_link: str, requester: str, bypass_throttling=False
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

        # --- Extract Metadata ---
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
        if duration > 600:
            # pyrefly: ignore [unsupported-operation]
            raise Exception(
                # pyrefly: ignore [unsupported-operation]
                f'"{title}" is too long ({duration // 60}m). Max duration is 10 minutes.'
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
            "js_runtimes": {"deno": {"path": DENO_PATH}},
        }

        # We need to find if file already exists to avoid re-downloading if we wanted,
        # but logic says "request" implies playing it now, so downloading is safer to ensure it gets to the folder.
        # But we can check if we want optim. For now, following original logic (download).

        try:
            # pyrefly: ignore [bad-argument-type]
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                # pyrefly: ignore [bad-argument-type]
                await asyncio.to_thread(ydl.download, [webpage_url])
        except Exception as e:
            raise Exception(f"Failed to download audio: {e}")

        # Update throttling
        self.user_requests[requester].append(now)
        self.recent_song_queue.append(title)
        return title, duration

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
        except Exception as e:
            await channel.send(f"Failed to queue {song_name} for {requester}: {e}")

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
                song_or_youtube_link, interaction.user.display_name, bypass_throttling
            )
            await interaction.followup.send(
                f'Downloaded, your song "{title}" will be played soon!', ephemeral=True
            )
        except Exception as e:
            await interaction.followup.send(f"Failed: {e}", ephemeral=True)

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

    @app_commands.command(name="skip_radio_track", description="Skip a radio track")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def skip_radio_track(self, interaction: discord.Interaction):
        await interaction.response.send_message("Skipping", ephemeral=True)
        self.bot.loop.create_task(
            asyncio.to_thread(self.lq.skip_current_track, "song_requests")
        )

    @app_commands.command(name="set_event_mode", description="Set event mode")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    @app_commands.checks.has_any_role("DJ", "Event Organiser", 1346047801473105950)
    async def set_event_mode(self, interaction: discord.Interaction, state: bool):
        await interaction.response.send_message("Setting event mode")
        state_str = "true" if state else "false"
        self.bot.loop.create_task(
            asyncio.to_thread(
                self.lq._send_command, f"var.set event_mode = {state_str}"
            )
        )
        self.bot.loop.create_task(
            asyncio.to_thread(self.lq._send_command, "var.set race_mode = false")
        )

    @app_commands.command(name="set_race_mode", description="Set race mode")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    @app_commands.checks.has_any_role("DJ", "Event Organiser", 1346047801473105950)
    async def set_race_mode(self, interaction: discord.Interaction, state: bool):
        await interaction.response.send_message("Setting race mode")
        state_str = "true" if state else "false"
        self.bot.loop.create_task(
            asyncio.to_thread(self.lq._send_command, f"var.set race_mode = {state_str}")
        )

    # --- Tasks ---

    async def _update_jingles_logic(self):
        channel = self.bot.get_channel(JINGLES_CHANNEL_ID)
        i = 0
        async for jingle, jingle_audio in self.generate_jingles_gen():
            with open(os.path.join(JINGLES_PATH, f"jingle{i}.mp3"), "wb") as f:
                f.write(jingle_audio)

            if channel:
                self.bot.loop.create_task(
                    channel.send(
                        jingle[:2000],
                        file=discord.File(
                            BytesIO(jingle_audio), filename=f"jingle{i}.mp3"
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

    @tasks.loop(time=dt_time(hour=0, minute=30, tzinfo=timezone.utc))
    async def post_gazette_task(self):
        gazette = await self.generate_gazette_content()
        chan = self.bot.get_channel(NEWS_CHANNEL_ID)
        if chan:
            for chunk in split_markdown(gazette):
                await chan.send(chunk)

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

        if message.attachments:
            attachment = message.attachments[0]
            local_path = os.path.join(JINGLES_PATH, attachment.filename)
            await attachment.save(local_path)

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

    @tasks.loop(seconds=10)
    async def update_current_song_embed(self):
        radio_channel = self.bot.get_channel(RADIO_CHANNEL_ID)
        if not radio_channel:
            # log.warning(f'Radio channel cannot be found from channel id: {RADIO_CHANNEL_ID}')
            return

        filename = None
        try:
            async with self.bot.http_session.get(
                "http://localhost:6001/metadata"
            ) as resp:
                metadata = await resp.json()
                filename = metadata.get("filename")
        except Exception:
            # log.error("Could not fetch metadata")
            return

        if not filename:
            return

        filename = filename.removeprefix("/var/lib/radio/")
        try:
            folder, filepath = filename.split("/")
            requester, song_path = filepath.split("-", 1)
            song_title = song_path.removesuffix(".mp3")
        except ValueError:
            # Handle unexpected filename format
            return

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

        view = LinkView("https://www.aseanmotorclub.com/radio", "Listen to Radio")

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
        if message.author.bot:
            return

        channel_id = message.channel.id

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
                r"\*\*(?P<name>.+):\*\* /(?P<command>\w+) (?P<args>.+)", message.content
            ):
                name = command_match.group("name")
                command = command_match.group("command")
                args = command_match.group("args")

                if command == "song_request":
                    song_name = args
                    if name in self.banned_requesters:
                        return
                    self.bot.loop.create_task(self.game_request_song(song_name, name))
                elif command == "event_mode":
                    self.bot.loop.create_task(
                        asyncio.to_thread(
                            self.lq._send_command, f"var.set event_mode = {args}"
                        )
                    )
                elif command == "skip":
                    self.bot.loop.create_task(
                        asyncio.to_thread(self.lq.skip_current_track, "song_requests")
                    )

    @commands.Cog.listener()
    async def on_message_edit(
        self, message_before: discord.Message, message: discord.Message
    ):
        if message.channel.id == PLAYLIST_CHANNEL and message.attachments:
            self.bot.loop.create_task(self.compile_playlist())
