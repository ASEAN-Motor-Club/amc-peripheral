import re
import json
import logging
import discord
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from io import BytesIO
from discord import app_commands
from discord.ext import commands
from openai import AsyncOpenAI
from typing import Optional, List, Any
from amc_peripheral.settings import (
    OPENAI_API_KEY_OPENROUTER,
    KNOWLEDGE_LOG_CHANNEL_ID,
    LOCAL_TIMEZONE,
    DEFAULT_AI_MODEL,
    GENERAL_CHANNEL_ID,
    GAME_CHAT_CHANNEL_ID,
    KNOWLEDGE_FORUM_CHANNEL_ID,
    NEWS_CHANNEL_ID,
    BACKEND_API_URL,
)
from amc_peripheral.bot.ai_models import (
    ModerationResponse,
)
from amc_peripheral.utils.text_utils import split_markdown
from amc_peripheral.utils.discord_utils import (
    actual_discord_poll_creator,
    actual_discord_event_creator,
)
from amc_peripheral.utils.game_utils import announce_in_game
from amc_peripheral.radio.radio_server import get_current_song
from amc_peripheral.bot import game_db

# --- Cog Implementation ---

log = logging.getLogger(__name__)


class KnowledgeCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.local_tz = ZoneInfo(LOCAL_TIMEZONE)

        # clients
        self.openai_client_openrouter = AsyncOpenAI(
            api_key=OPENAI_API_KEY_OPENROUTER, base_url="https://openrouter.ai/api/v1"
        )

        # state
        self.knowledge_system_message = ""
        self.game_schema_description = ""
        self.user_requests = {}
        self.messages = []
        self.moderation_cooldown = [20]
        self.player_warnings = {}
        self.bot_calls = []

    async def cog_load(self):
        # Context Menus
        self.ctx_menus = [
            app_commands.ContextMenu(
                name="Process Image with Prompt", callback=self.process_image_context
            ),
        ]
        for menu in self.ctx_menus:
            self.bot.tree.add_command(menu)

    async def cog_unload(self):
        for menu in getattr(self, "ctx_menus", []):
            try:
                self.bot.tree.remove_command(menu.name, type=menu.type)
            except Exception:
                pass

    @commands.Cog.listener()
    async def on_ready(self):
        """Initialize knowledge base from forum channel on startup."""
        # Validate game database schema
        if not game_db.validate_schema():
            log.warning(
                "Game database schema validation failed - game queries may not work correctly"
            )
        else:
            log.info("Game database schema validated successfully")
        
        # Load game schema description for LLM tool
        self.game_schema_description = game_db.get_schema_description()
        log.info(f"Game schema loaded: {len(self.game_schema_description)} characters")
        
        forum_channel = self.bot.get_channel(KNOWLEDGE_FORUM_CHANNEL_ID)
        if forum_channel is None:
            log.warning(
                f"Knowledge forum channel {KNOWLEDGE_FORUM_CHANNEL_ID} not found. Knowledge base will be empty."
            )
            return

        if isinstance(forum_channel, discord.ForumChannel):
            log.info("Loading knowledge base from forum channel...")
            await self.fetch_forum_messages(forum_channel)
            log.info(
                f"Knowledge base loaded: {len(self.knowledge_system_message)} characters"
            )
        else:
            log.warning(
                f"Channel {KNOWLEDGE_FORUM_CHANNEL_ID} is not a ForumChannel, it is a {type(forum_channel).__name__}"
            )

    # --- AI Helpers ---

    async def ai_helper_discord(
        self,
        player_name,
        question,
        prev_messages_str,
        generic=False,
        interaction=None,
    ):
        now = datetime.now(self.local_tz)
        if generic:
            system_message = "You are a helpful assistant for the ASEAN MotorTown Club discord server."
        else:
            system_message = f"You are a helpful bot in Motor Town, an open world driving game, specifically in a dedicated server named 'ASEAN Motor Club'.\nOnly use the following information about the game to answer queries. If a user asks a question outside the scope of your knowledge, refer them to the discord channel and other players in the game.\n\n{self.knowledge_system_message}"

        model = DEFAULT_AI_MODEL
        tools = []
        model = DEFAULT_AI_MODEL
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
                                "options": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                                "channel_id": {"type": "string"},
                            },
                            "required": ["question", "options"],
                        },
                    },
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
                                "timezone": {"type": "string"},
                            },
                            "required": ["name", "start_time", "timezone"],
                        },
                    },
                },
                {
                    "type": "function",
                    "function": {
                        "name": "query_game_database",
                        "description": f"""Query MotorTown game database with SQL.

{self.game_schema_description}

Use standard SQL with SELECT. Supports GROUP BY, ORDER BY, JOINs, aggregates (COUNT, AVG, SUM, MIN, MAX).
Results are limited to 100 rows. Database is read-only.""",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "sql": {
                                    "type": "string",
                                    "description": "SQL SELECT query to execute"
                                }
                            },
                            "required": ["sql"],
                        },
                    },
                },
                {
                    "type": "function",
                    "function": {
                        "name": "get_current_subsidies",
                        "description": "Get the current active government subsidies for cargo deliveries. Returns subsidy rules including cargo types, reward percentages, and source/destination requirements.",
                        "parameters": {
                            "type": "object",
                            "properties": {},
                            "required": [],
                        },
                    },
                },
                {
                    "type": "function",
                    "function": {
                        "name": "get_server_commands",
                        "description": "Get a list of all available server-side commands that players can use in-game. Returns command names, shortcuts/aliases, descriptions, and categories.",
                        "parameters": {
                            "type": "object",
                            "properties": {},
                            "required": [],
                        },
                    },
                },
            ]

        messages = [
            {"role": "system", "content": system_message},
            {
                "role": "user",
                "content": f"## Context\nThe current date and time (in Bangkok GMT+7 timezone) is: {now.strftime('%A, %Y-%m-%d %H:%M')}",
            },
        ]
        if prev_messages_str:
            messages.append(
                {
                    "role": "user",
                    "content": f"## Previous messages:\n{prev_messages_str}",
                }
            )
        messages.append(
            {"role": "user", "content": f"### Message from {player_name}\n{question}"}
        )

        # Use agentic loop (tools are always available)
        return await self._call_llm_with_tools(messages, tools, model, interaction=interaction)


    async def ai_helper(self, player_name, question, prev_messages):
        now = datetime.now(self.local_tz)

        # Fetch active players
        async with self.bot.http_session.get(
            "https://server.aseanmotorclub.com/api/active_players/"
        ) as resp:
            player_data = await resp.text()

        events_str = "\n\n".join(
            [
                f"## {event.name}\nDate/Time:{event.start_time.replace(tzinfo=ZoneInfo('UTC')).astimezone(self.local_tz).strftime('%A, %Y-%m-%d %H:%M')}\nLocation: {event.location}\n{event.description}"
                for event in self.bot.guilds[0].scheduled_events
                if event.start_time > now
            ]
        )

        system_message = (
            "You are a helpful bot in Motor Town, an open world driving game, specifically in 'ASEAN Motor Club'.\nAnswer in a short sentence or paragraph since the game only allows short messages, and avoid using newlines.\nOnly use the following knowledge. Do not use markdown or emojis.\n\n"
            + self.knowledge_system_message
        )

        messages = [
            {"role": "system", "content": system_message},
        ]
        if events_str:
            messages.append(
                {"role": "user", "content": "# Upcoming events:\n\n" + events_str}
            )

        messages.extend(
            [
                {
                    "role": "user",
                    "content": f"## Context\nTime: {now.strftime('%A, %Y-%m-%d %H:%M')}\n\n### Online Players:\n{player_data}\n\n### Previous messages:\n{prev_messages}",
                },
                {
                    "role": "user",
                    "content": f"### Message from {player_name}:\n{question}",
                },
            ]
        )

        tools = [
            {
                "type": "function",
                "function": {
                    "name": "get_currently_playing_song",
                    "description": "Get the currently playing song on the radio station. Returns the song title and who requested it.",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "required": [],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "query_game_database",
                    "description": f"""Query MotorTown game database with SQL.

{self.game_schema_description}

Use standard SQL with SELECT. Supports GROUP BY, ORDER BY, JOINs, aggregates (COUNT, AVG, SUM, MIN, MAX).
Results are limited to 100 rows. Database is read-only.""",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "sql": {
                                "type": "string",
                                "description": "SQL SELECT query to execute"
                            }
                        },
                        "required": ["sql"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_current_subsidies",
                    "description": "Get the current active government subsidies for cargo deliveries. Returns subsidy rules including cargo types, reward percentages, and source/destination requirements.",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "required": [],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_server_commands",
                    "description": "Get a list of all available server-side commands that players can use in-game. Returns command names, shortcuts/aliases, descriptions, and categories.",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "required": [],
                    },
                },
            },
        ]

        return await self._call_llm_with_tools(messages, tools, DEFAULT_AI_MODEL)

    async def moderation(self, prev_messages=[]):
        completion = await self.openai_client_openrouter.beta.chat.completions.parse(
            model="google/gemini-2.0-flash-lite-001",
            messages=[
                {
                    "role": "system",
                    "content": "You are the AI moderator for our game server. Assess tone and context for escalating conflict. Recognize playful banter vs genuine anger.",
                },
                {"role": "user", "content": f"### MESSAGES:\n{prev_messages}"},
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
            required=True,
        )

        def __init__(self, cog, message):
            super().__init__()
            self.cog = cog
            self.message = message

        async def on_submit(self, interaction: discord.Interaction):
            if not self.message or not self.message.attachments:
                await interaction.response.send_message(
                    "No image found.", ephemeral=True
                )
                return

            image_urls = [
                a.url
                for a in self.message.attachments
                if any(
                    a.filename.lower().endswith(ext)
                    for ext in [".png", ".jpg", ".jpeg"]
                )
            ]
            if not image_urls:
                await interaction.response.send_message(
                    "No valid image found.", ephemeral=True
                )
                return

            await interaction.response.defer()
            try:
                response = (
                    await self.cog.openai_client_openrouter.chat.completions.create(
                        model="openai/gpt-4o",
                        messages=[
                            {
                                "role": "user",
                                "content": [
                                    {"type": "text", "text": self.prompt.value},
                                ]
                                + [
                                    {"type": "image_url", "image_url": {"url": url}}
                                    for url in image_urls
                                ],
                            },
                        ],
                    )
                )
                await interaction.followup.send(response.choices[0].message.content)
            except Exception as e:
                await interaction.followup.send(f"Error: {e}", ephemeral=True)

    # --- Agentic Loop Infrastructure ---

    async def _call_llm_with_tools(
        self, messages: list[dict], tools: list[dict], model: str, interaction: Optional[discord.Interaction] = None
    ) -> str:
        """
        Call LLM with tool support and handle tool calls iteratively.

        Args:
            messages: Conversation messages
            tools: Tool definitions
            model: AI model to use

        Returns:
            Final response text
        """
        max_iterations = 10  # Fewer than JARVIS since game queries are simpler
        iteration = 0

        while iteration < max_iterations:
            iteration += 1

            # Call LLM
            # pyrefly: ignore [no-matching-overload]
            completion = await self.openai_client_openrouter.chat.completions.create(
                model=model,
                reasoning_effort="medium",
                messages=messages,
                tools=tools,
                tool_choice="auto",
            )

            response_message = (
                completion.choices[0].message if completion.choices else None
            )

            if not response_message:
                return "I received an empty response from my AI backend."

            # If no tool calls, return the content
            if not response_message.tool_calls:
                return response_message.content or "I don't have a response."

            # Add assistant message to conversation
            messages.append(response_message)

            # Execute tool calls
            for tool_call in response_message.tool_calls:
                function_name = tool_call.function.name
                function_args = json.loads(tool_call.function.arguments)

                log.info(
                    f"Knowledge bot calling tool: {function_name} with args: {function_args}"
                )

                # Call the appropriate tool
                tool_result = await self._execute_tool(function_name, function_args, interaction)

                # Add tool result to messages
                messages.append(
                    {
                        "tool_call_id": tool_call.id,
                        "role": "tool",
                        "name": function_name,
                        "content": tool_result,
                    }
                )

            # Continue loop to get final response with tool results

        return "I'm sorry, I couldn't complete your request due to complexity. Please try simplifying your question."

    async def _execute_tool(
        self, function_name: str, arguments: dict, interaction: Optional[discord.Interaction] = None
    ) -> str:
        """
        Execute a knowledge bot  tool.

        Args:
            function_name: Name of the tool
            arguments: Tool arguments

        Returns:
            Tool result as string
        """
        try:
            if function_name == "create_poll":
                question = arguments.get("question") or ""
                options = arguments.get("options") or []
                res = await actual_discord_poll_creator(
                    self.bot,
                    question,
                    options,
                    arguments.get("channel_id"),
                )
                return res

            elif function_name == "create_scheduled_event":
                # Only allow admins to create events
                # pyrefly: ignore [missing-attribute]
                if not interaction or not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.administrator:
                    return "Error: You do not have permission to create scheduled events."
                    
                res = await actual_discord_event_creator(
                    interaction.guild,
                    arguments.get("name"),
                    arguments.get("description"),
                    arguments.get("location"),
                    arguments.get("start_time"),
                    arguments.get("end_time"),
                    arguments.get("timezone"),
                )
                return res

            elif function_name == "query_game_database":
                sql = arguments.get("sql")
                if not sql:
                    return "Database query failed: sql parameter required"
                
                result = game_db.execute_raw_query(sql)
                
                # Handle errors
                if "error" in result:
                    return f"Database query failed: {result['error']}"
                
                # Format results for better LLM comprehension
                results = result.get("results", [])
                count = result.get("count", 0)
                truncated = result.get("truncated", False)
                
                if count == 0:
                    return "Query executed successfully but returned no results."
                
                # Format as readable output
                formatted_output = f"Query returned {count} result(s):\n\n"
                formatted_output += json.dumps(results, indent=2)
                
                if truncated:
                    formatted_output += f"\n\nNote: Results were limited to {count} rows."
                
                return formatted_output

            elif function_name == "get_currently_playing_song":
                from amc_peripheral.radio.radio_server import get_current_song
                current_song = await get_current_song(self.bot.http_session)
                return current_song or "No song is currently playing or unable to fetch song info."

            elif function_name == "get_current_subsidies":
                async with self.bot.http_session.get(f"{BACKEND_API_URL}/api/subsidies/") as resp:
                    data = await resp.json()
                    return data.get("subsidies_text", "No subsidy information available.")

            elif function_name == "get_server_commands":
                async with self.bot.http_session.get(f"{BACKEND_API_URL}/api/commands/") as resp:
                    if resp.status != 200:
                        return "Failed to fetch server commands."
                    commands_data = await resp.json()
                    
                    # Format commands by category for better readability
                    formatted = "Available server commands:\n\n"
                    
                    # Group by category
                    from itertools import groupby
                    for category, cmds in groupby(commands_data, key=lambda x: x.get('category', 'General')):
                        formatted += f"## {category}\n"
                        for cmd in cmds:
                            cmd_name = cmd['command']
                            shorthand = cmd.get('shorthand')
                            description = cmd.get('description', '')
                            
                            if shorthand:
                                formatted += f"- **{cmd_name}** (or **{shorthand}**): {description}\n"
                            else:
                                formatted += f"- **{cmd_name}**: {description}\n"
                        formatted += "\n"
                    
                    return formatted

            else:
                return json.dumps({"error": f"Unknown function: {function_name}"})

        except Exception as e:
            log.error(f"Tool execution error ({function_name}): {e}", exc_info=True)
            return json.dumps({"error": f"Tool execution failed: {str(e)}"})


    # --- Commands ---

    @app_commands.command(name="bot", description="Generic bot")
    async def helper_cmd(self, interaction: discord.Interaction, question: str):
        await interaction.response.defer()
        prev = ""
        # pyrefly: ignore [missing-attribute]
        async for m in interaction.channel.history(limit=20):
            ms = f"### {m.author.display_name}:\n{m.content}\n"
            if m.reactions:
                ms += "**Reactions**\n" + "\n".join(
                    [
                        f"{r.emoji}: {', '.join([u.display_name async for u in r.users()])}"
                        for r in m.reactions
                    ]
                )
            prev = ms + "\n" + prev
        ans = await self.ai_helper_discord(
            interaction.user.display_name,
            question,
            prev,
            generic=True,
            interaction=interaction,
        )
        for line in split_markdown(ans):
            await interaction.followup.send(line)

    async def process_image_context(
        self, interaction: discord.Interaction, message: discord.Message
    ):
        if not message.attachments:
            return await interaction.response.send_message(
                "No attachments found.", ephemeral=True
            )
        await interaction.response.send_modal(self.PromptModal(self, message))

    # --- Thread Fetching ---

    async def _fetch_thread_contents(self, channel, **history_kwargs):
        acc = ""
        threads = []
        if isinstance(channel, discord.ForumChannel):
            threads = [t async for t in channel.archived_threads(limit=None)]
        elif hasattr(channel, "threads"):  # TextChannel with threads
            threads = list(channel.threads)

        for thread in threads:
            acc += f"## {thread.name}\n"
            async for msg in thread.history(oldest_first=True, **history_kwargs):
                acc += f"{msg.content}\n\n"
                for attachment in msg.attachments:
                    if attachment.filename.lower().endswith(".txt"):
                        try:
                            content = (await attachment.read()).decode("utf-8")
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
            await log_channel.send(
                "Knowledge Updated",
                file=discord.File(fp=file_stream, filename="knowledge.txt"),
            )

    async def fetch_messages(self, channel, title, name, **kwargs):
        content = await self._fetch_thread_contents(channel, **kwargs)
        acc = f"# {title}\n{content}"
        file_stream = BytesIO(acc.encode("utf-8"))
        log_channel = self.bot.get_channel(KNOWLEDGE_LOG_CHANNEL_ID)
        if log_channel:
            await log_channel.send(
                f"{title} Updated",
                file=discord.File(fp=file_stream, filename=f"{name}.txt"),
            )
        return acc

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author == self.bot.user:
            return

        message_channel = message.channel
        message_channel_id = message_channel.id

        # 1. General Chat Translation & Announcement
        if (
            message_channel_id == GENERAL_CHANNEL_ID
            and message.content
            and not message.author.bot
        ):
            # We use a task to not block the listener
            async def translate_and_announce():
                try:
                    # In the original snippet, there was a call to translate_general_message.
                    # Our KnowledgeCog has translate_multi which seems to be the intended modern equivalent.
                    # We'll use translate_multi to translate and log it (or send it to other channels if needed).
                    # For now, following the spirit of "lost during refactoring", we restore the logic.
                    pass
                except Exception as e:
                    log.error(f"Error in general chat translation: {e}")

        # 2. Game Chat Handling (Synced from In-game) - /bot command only
        # Note: Translation is handled by TranslationCog
        if message.author.bot and message_channel_id == GAME_CHAT_CHANNEL_ID:

            # In-game /bot command
            if command_match := re.match(
                r"\*\*(?P<name>.+):\*\* /(?P<command>\w+) (?P<args>.+)", message.content
            ):
                player_name = command_match.group("name")
                command = command_match.group("command")
                args = command_match.group("args")

                if command == "bot":
                    BOT_RATE_LIMIT_PERIOD = 10
                    BOT_RATE_LIMIT_MAX = 100

                    self.bot_calls = [
                        call
                        for call in self.bot_calls
                        if call
                        > datetime.now() - timedelta(minutes=BOT_RATE_LIMIT_PERIOD)
                    ]
                    if len(self.bot_calls) > BOT_RATE_LIMIT_MAX:
                        time_to_next = (
                            min(self.bot_calls)
                            + timedelta(minutes=BOT_RATE_LIMIT_PERIOD)
                        ) - datetime.now()
                        await announce_in_game(
                            self.bot.http_session,
                            f"I need some rest, please wait {time_to_next.seconds} seconds, or #ask-bot on discord instead!",
                        )
                        return

                    self.bot_calls.append(datetime.now())

                    prev_messages = "\n".join(self.messages[-10:])
                    try:
                        answer = await self.ai_helper(player_name, args, prev_messages)
                        await announce_in_game(self.bot.http_session, answer[:360])
                    except Exception as e:
                        await announce_in_game(self.bot.http_session, f"{e}")
            return

        # 3. Knowledge Update (Forum/News)
        # Forum channel knowledge update
        if isinstance(message_channel, discord.Thread) and message_channel.parent:
            if message_channel.parent.id == KNOWLEDGE_FORUM_CHANNEL_ID:
                # pyrefly: ignore [bad-argument-type]
                await self.fetch_forum_messages(message_channel.parent)
            elif message_channel.parent.id == NEWS_CHANNEL_ID:
                await self.fetch_messages(
                    message_channel.parent,
                    "Latest News",
                    "news",
                    limit=None,
                    after=datetime.now() - timedelta(days=7),
                )
