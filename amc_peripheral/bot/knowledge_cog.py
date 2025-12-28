import json
import logging
import discord
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from io import BytesIO
from discord import app_commands
from discord.ext import commands
from openai import AsyncOpenAI
from amc_peripheral.settings import (
    OPENAI_API_KEY_OPENROUTER,
    KNOWLEDGE_LOG_CHANNEL_ID,
    LOCAL_TIMEZONE,
    DEFAULT_AI_MODEL
)
from amc_peripheral.bot.ai_models import (
    TranslationResponse,
    MultiTranslation,
    MultiTranslationWithEnglish,
    ModerationResponse
)
from amc_peripheral.utils.text_utils import split_markdown
from amc_peripheral.utils.discord_utils import actual_discord_poll_creator, actual_discord_event_creator

# --- Cog Implementation ---

log = logging.getLogger(__name__)

class KnowledgeCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.local_tz = ZoneInfo(LOCAL_TIMEZONE)
        
        # clients
        self.openai_client_openrouter = AsyncOpenAI(api_key=OPENAI_API_KEY_OPENROUTER, base_url="https://openrouter.ai/api/v1")
        
        # state
        self.knowledge_system_message = ""
        self.user_requests = {}
        self.messages = []
        self.moderation_cooldown = [20]
        self.player_warnings = {}
        self.bot_calls = []
        
    async def cog_load(self):
        # Context Menus
        self.ctx_menus = [
            app_commands.ContextMenu(name="Process Image with Prompt", callback=self.process_image_context),
        ]
        for menu in self.ctx_menus:
            self.bot.tree.add_command(menu)

    async def cog_unload(self):
        for menu in getattr(self, 'ctx_menus', []):
            try:
                self.bot.tree.remove_command(menu.name, type=menu.type)
            except Exception:
                pass

    # --- AI Helpers ---

    async def ai_helper_discord(self, player_name, question, prev_messages_str, generic=False, smart=False, interaction=None):
        now = datetime.now(self.local_tz)
        if generic:
            system_message = "You are a helpful assistant for the ASEAN MotorTown Club discord server."
        else:
            system_message = f"You are a helpful bot in Motor Town, an open world driving game, specifically in a dedicated server named 'ASEAN Motor Club'.\nOnly use the following information about the game to answer queries. If a user asks a question outside the scope of your knowledge, refer them to the discord channel and other players in the game.\n\n{self.knowledge_system_message}"

        model = DEFAULT_AI_MODEL
        tools = []
        if smart:
            tools = [
                {
                    "type": "function",
                    "function": {
                        "name": "create_poll",
                        "description": "Creates a poll in the Discord channel.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "question": {"type": "string"},
                                "options": {"type": "array", "items": {"type": "string"}},
                                "channel_id": {"type": "string"}
                            },
                            "required": ["question", "options"]
                        }
                    }
                },
                {
                    "type": "function",
                    "function": {
                        "name": "create_scheduled_event",
                        "description": "Creates a scheduled event in the Discord server.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "description": {"type": "string"},
                                "location": {"type": "string"},
                                "start_time": {"type": "string", "format": "date-time"},
                                "end_time": {"type": "string", "format": "date-time"},
                                "timezone": {"type": "string"}
                            },
                            "required": ["name", "start_time", "timezone"]
                        }
                    }
                }
            ]

        messages = [
            {"role": "system", "content": system_message},
            {"role": "user", "content": f"## Context\nThe current date and time (in Bangkok GMT+7 timezone) is: {now.strftime('%A, %Y-%m-%d %H:%M')}"}
        ]
        if prev_messages_str:
            messages.append({"role": "user", "content": f'## Previous messages:\n{prev_messages_str}'})
        messages.append({"role": "user", "content": f'### Message from {player_name}\n{question}'})

        completion = await self.openai_client_openrouter.chat.completions.create(
            model=model,
            reasoning_effort="medium",
            messages=messages,
            tools=tools,
            tool_choice="auto",
        )

        response_message = completion.choices[0].message if completion.choices else None

        if response_message and response_message.tool_calls:
            messages.append(response_message)
            for tool_call in response_message.tool_calls:
                function_name = tool_call.function.name
                function_args = json.loads(tool_call.function.arguments)
                
                if function_name == "create_poll":
                    res = await actual_discord_poll_creator(
                        self.bot,
                        function_args.get("question"),
                        function_args.get("options"),
                        (function_args.get("channel_id") or interaction.channel.id) if interaction else None
                    )
                elif function_name == "create_scheduled_event":
                    res = await actual_discord_event_creator(
                        interaction.guild if interaction else None,
                        function_args.get("name"),
                        function_args.get("description"),
                        function_args.get("location"),
                        function_args.get("start_time"),
                        function_args.get("end_time"),
                        function_args.get("timezone")
                    )
                else:
                    res = f"Error: Unknown function '{function_name}'"
                
                messages.append({"tool_call_id": tool_call.id, "role": "tool", "name": function_name, "content": res})

            second_completion = await self.openai_client_openrouter.chat.completions.create(
                model=model,
                reasoning_effort="medium",
                messages=messages,
            )
            return second_completion.choices[0].message.content if second_completion.choices else "Failed to get follow-up"

        return response_message.content if response_message else "Empty response"

    async def ai_helper(self, player_name, question, prev_messages):
        now = datetime.now(self.local_tz)
        
        # Throttling
        fifteen_minutes_ago = now - timedelta(minutes=15)
        self.user_requests[player_name] = [t for t in self.user_requests.get(player_name, []) if t > fifteen_minutes_ago]
        
        five_minutes_ago = now - timedelta(minutes=5)
        last_5 = sum(1 for t in self.user_requests[player_name] if t > five_minutes_ago)
        if last_5 >= 4:
            raise Exception('Quota exceeded (3/5min)')
        if len(self.user_requests[player_name]) >= 5:
            raise Exception('Quota exceeded (4/15min)')

        # Fetch active players
        async with self.bot.http_session.get("https://server.aseanmotorclub.com/api/active_players/") as resp:
            player_data = await resp.text()

        events_str = '\n\n'.join([
            f"## {event.name}\nDate/Time:{event.start_time.replace(tzinfo=ZoneInfo('UTC')).astimezone(self.local_tz).strftime('%A, %Y-%m-%d %H:%M')}\nLocation: {event.location}\n{event.description}"
            for event in self.bot.guilds[0].scheduled_events if event.start_time > now
        ])

        system_message = "You are a helpful bot in Motor Town, an open world driving game, specifically in 'ASEAN Motor Club'.\nAnswer in a short sentence or paragraph since the game only allows short messages, and avoid using newlines.\nOnly use the following knowledge. Do not use markdown or emojis.\n\n" + self.knowledge_system_message
        
        completion = await self.openai_client_openrouter.chat.completions.create(
            model=DEFAULT_AI_MODEL,
            reasoning_effort="medium",
            messages=[
                {"role": "system", "content": system_message},
                {"role": "user", "content": '# Upcoming events:\n\n' + events_str},
                {"role": "user", "content": f"## Context\nTime: {now.strftime('%A, %Y-%m-%d %H:%M')}\n\n### Online Players:\n{player_data}\n\n### Previous messages:\n{prev_messages}"},
                {"role": "user", "content": f'### Message from {player_name}:\n{question}'},
            ],
        )
        self.user_requests[player_name].append(now)
        return completion.choices[0].message.content

    async def translate(self, message, language, prev_messages=[]):
        completion = await self.openai_client_openrouter.beta.chat.completions.parse(
            model="gpt-4.1-mini-2025-04-14",
            messages=[
                {"role": "system", "content": f"Translate message from {language} to English (or vice versa)"},
                {"role": "user", "content": '### PREVIOUS MESSAGES:\n' + '\n'.join(prev_messages)},
                {"role": "user", "content": f'### MESSAGE TO TRANSLATE:\n{message}'},
            ],
            response_format=TranslationResponse,
        )
        return completion.choices[0].message.parsed

    async def translate_multi_with_english(self, player_name, message, messages=[]):
        sender = f" (from {player_name})" if player_name else ""
        completion = await self.openai_client_openrouter.beta.chat.completions.parse(
            model=DEFAULT_AI_MODEL,
            messages=[
                {"role": "system", "content": "Translate message into English, Chinese, Indonesian, Malay, Thai and Tagalog. Casual tone, no rude words. Handle slash commands by only translating params."},
                {"role": "user", "content": '### PREVIOUS MESSAGES:\n' + '\n'.join(messages)},
                {"role": "user", "content": f'### MESSAGE TO TRANSLATE{sender}:\n\n{message}'},
            ],
            response_format=MultiTranslationWithEnglish,
        )
        return completion.choices[0].message.parsed

    async def translate_multi(self, message, messages=[]):
        completion = await self.openai_client_openrouter.beta.chat.completions.parse(
            model="gpt-4.1-mini-2025-04-14",
            messages=[
                {"role": "system", "content": "Translate message into Chinese, Indonesian, Malay, Thai and Tagalog. Casual tone. Preserve sender [username]."},
                {"role": "user", "content": '### PREVIOUS MESSAGES:\n' + '\n'.join(messages)},
                {"role": "user", "content": f'### MESSAGE TO TRANSLATE:\n{message}'},
            ],
            response_format=MultiTranslation,
        )
        return completion.choices[0].message.parsed

    async def moderation(self, prev_messages=[]):
        completion = await self.openai_client_openrouter.beta.chat.completions.parse(
            model="google/gemini-2.0-flash-lite-001",
            messages=[
                {"role": "system", "content": "You are the AI moderator for our game server. Assess tone and context for escalating conflict. Recognize playful banter vs genuine anger."},
                {"role": "user", "content": f'### MESSAGES:\n{prev_messages}'},
            ],
            response_format=ModerationResponse,
        )
        return completion.choices[0].message.parsed

    # --- Modals ---

    class PromptModal(discord.ui.Modal, title="Enter your prompt"):
        prompt = discord.ui.TextInput(
            label="Prompt",
            placeholder="Type your prompt here...",
            style=discord.TextStyle.long,
            required=True
        )

        def __init__(self, cog, message):
            super().__init__()
            self.cog = cog
            self.message = message

        async def on_submit(self, interaction: discord.Interaction):
            if not self.message or not self.message.attachments:
                await interaction.response.send_message("No image found.", ephemeral=True)
                return

            image_urls = [a.url for a in self.message.attachments if any(a.filename.lower().endswith(ext) for ext in [".png", ".jpg", ".jpeg"])]
            if not image_urls:
                await interaction.response.send_message("No valid image found.", ephemeral=True)
                return

            await interaction.response.defer()
            try:
                response = await self.cog.openai_client_openrouter.chat.completions.create(
                    model="openai/gpt-4o",
                    messages=[
                        {"role": "user", "content": [
                            {"type": "text", "text": self.prompt.value},
                        ] + [
                            {"type": "image_url", "image_url": {"url": url}}
                            for url in image_urls
                        ]},
                    ]
                )
                await interaction.followup.send(response.choices[0].message.content)
            except Exception as e:
                await interaction.followup.send(f"Error: {e}", ephemeral=True)

    # --- Commands ---

    @app_commands.command(name="bot", description="Generic bot")
    async def helper_cmd(self, interaction: discord.Interaction, question: str):
        await interaction.response.defer()
        prev = ""
        async for m in interaction.channel.history(limit=20):
            ms = f"### {m.author.display_name}:\n{m.content}\n"
            if m.reactions:
                ms += "**Reactions**\n" + "\n".join([f"{r.emoji}: {', '.join([u.display_name async for u in r.users()])}" for r in m.reactions])
            prev = ms + '\n' + prev
        ans = await self.ai_helper_discord(interaction.user.display_name, question, prev, generic=True, interaction=interaction)
        for line in split_markdown(ans):
            await interaction.followup.send(line)

    async def process_image_context(self, interaction: discord.Interaction, message: discord.Message):
        if not message.attachments:
            return await interaction.response.send_message("No attachments found.", ephemeral=True)
        await interaction.response.send_modal(self.PromptModal(self, message))

    # --- Thread Fetching ---

    async def _fetch_thread_contents(self, channel, **history_kwargs):
        acc = ""
        threads = []
        if isinstance(channel, discord.ForumChannel):
            threads = [t async for t in channel.archived_threads(limit=None)]
        elif hasattr(channel, "threads"): # TextChannel with threads
            threads = list(channel.threads)
        
        for thread in threads:
            acc += f"## {thread.name}\n"
            async for msg in thread.history(oldest_first=True, **history_kwargs):
                acc += f"{msg.content}\n\n"
                for attachment in msg.attachments:
                    if attachment.filename.lower().endswith('.txt'):
                        try:
                            content = (await attachment.read()).decode('utf-8')
                            acc += f"--- Attachment: {attachment.filename} ---\n{content}\n\n"
                        except Exception:
                            pass
        return acc

    async def fetch_forum_messages(self, forum_channel: discord.ForumChannel):
        acc = await self._fetch_thread_contents(forum_channel)
        self.knowledge_system_message = acc
        file_stream = BytesIO(acc.encode("utf-8"))
        log_channel = self.bot.get_channel(KNOWLEDGE_LOG_CHANNEL_ID)
        if log_channel:
            await log_channel.send("Knowledge Updated", file=discord.File(fp=file_stream, filename="knowledge.txt"))

    async def fetch_messages(self, channel, title, name, **kwargs):
        content = await self._fetch_thread_contents(channel, **kwargs)
        acc = f"# {title}\n{content}"
        file_stream = BytesIO(acc.encode("utf-8"))
        log_channel = self.bot.get_channel(KNOWLEDGE_LOG_CHANNEL_ID)
        if log_channel:
            await log_channel.send(f"{title} Updated", file=discord.File(fp=file_stream, filename=f"{name}.txt"))
        return acc
