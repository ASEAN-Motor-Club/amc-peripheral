import json
import logging
import asyncio
import discord
from datetime import datetime, timedelta, time as dt_time
from zoneinfo import ZoneInfo
from io import BytesIO
from discord import app_commands
from discord.ext import commands, tasks
from openai import AsyncOpenAI
from typing import Optional, Callable, Awaitable
from amc_peripheral.settings import (
    OPENAI_API_KEY_OPENROUTER,
    KNOWLEDGE_LOG_CHANNEL_ID,
    LOCAL_TIMEZONE,
    DEFAULT_AI_MODEL,
    KNOWLEDGE_FORUM_CHANNEL_ID,
    NEWS_CHANNEL_ID,
    BACKEND_API_URL,
    BOT_MAX_ITERATIONS,
    BOT_FEEDBACK_DELAY_SECONDS,
    BOT_TOOL_STATUS_DELAY_SECONDS,
    ASK_BOT_CHANNEL_ID,
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
from amc_peripheral.utils.rate_limiter import RateLimiter
from amc_peripheral.bot import game_db
from amc_peripheral.bot import backend_db
from amc_peripheral.memory.storage import MemoryStorage
from amc_peripheral.memory.retrieval import MemoryRetrieval
from amc_peripheral.wiki import (
    WikiStorage,
    WikiRetrieval,
    WikiIndex,
    WikiIngest,
    WikiLint,
    WikiExporter,
    WikiSynthesizer,
)

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
        self.backend_schema_description = ""
        self._ingame_bot_limiter = RateLimiter(max_calls=100, period_minutes=10)

        # Debounced knowledge reload
        self._knowledge_reload_task: Optional[asyncio.Task] = None
        self._knowledge_reload_debounce_seconds = 30

        # SSE connection to backend
        self._sse_task: Optional[asyncio.Task] = None

        # Per-player message history for semantic search personalization
        self._player_message_history: dict[str, list[str]] = {}
        self._max_history_per_player = 10

        # Global chat history for cross-player context (all players' messages)
        self._global_chat_history: list[
            tuple[str, str, str]
        ] = []  # (player_id, player_name, message)
        self._max_global_history = 30

        # Long-term memory storage
        self._memory_storage: Optional[MemoryStorage] = None
        self._memory_retrieval: Optional[MemoryRetrieval] = None

        # Wiki subsystem
        self._wiki_storage: Optional[WikiStorage] = None
        self._wiki_retrieval: Optional[WikiRetrieval] = None
        self._wiki_index: Optional[WikiIndex] = None
        self._wiki_ingest: Optional[WikiIngest] = None
        self._wiki_lint: Optional[WikiLint] = None
        self._wiki_exporter: Optional[WikiExporter] = None
        self._wiki_synthesizer: Optional[WikiSynthesizer] = None
        self._wiki_pending_conversations: list[dict] = []

        self._active_tasks = set()

    async def cog_load(self):
        # Initialize long-term memory storage
        try:
            self._memory_storage = MemoryStorage()
            log.info(f"Memory storage initialized at {self._memory_storage.db_path}")
        except Exception as e:
            log.error(f"Failed to initialize memory storage: {e}")
            self._memory_storage = None

        # Initialize semantic retrieval (ChromaDB)
        try:
            self._memory_retrieval = MemoryRetrieval()
            log.info("ChromaDB memory retrieval initialized")
        except Exception as e:
            log.warning(f"ChromaDB not available, semantic search disabled: {e}")
            self._memory_retrieval = None

        # Initialize wiki storage and retrieval
        try:
            self._wiki_storage = WikiStorage()
            log.info(f"Wiki storage initialized at {self._wiki_storage.db_path}")
        except Exception as e:
            log.error(f"Failed to initialize wiki storage: {e}")
            self._wiki_storage = None

        try:
            self._wiki_retrieval = WikiRetrieval()
            log.info("Wiki ChromaDB retrieval initialized")
        except Exception as e:
            log.warning(
                f"Wiki ChromaDB not available, semantic wiki search disabled: {e}"
            )
            self._wiki_retrieval = None

        if self._wiki_storage:
            try:
                self._wiki_index = WikiIndex(self._wiki_storage)
                log.info("Wiki index initialized")
            except Exception as e:
                log.warning(f"Wiki index initialization failed: {e}")
                self._wiki_index = None

        if self._wiki_storage and self._wiki_retrieval:
            try:
                self._wiki_ingest = WikiIngest(self._wiki_storage, self._wiki_retrieval)
                log.info("Wiki ingest initialized")
            except Exception as e:
                log.warning(f"Wiki ingest initialization failed: {e}")
                self._wiki_ingest = None

            try:
                self._wiki_lint = WikiLint(self._wiki_storage, self._wiki_retrieval)
                log.info("Wiki lint initialized")
            except Exception as e:
                log.warning(f"Wiki lint initialization failed: {e}")
                self._wiki_lint = None

        if self._wiki_storage:
            try:
                self._wiki_exporter = WikiExporter(self._wiki_storage, self._wiki_index)
                log.info("Wiki exporter initialized")
            except Exception as e:
                log.warning(f"Wiki exporter initialization failed: {e}")
                self._wiki_exporter = None

        if self._wiki_storage and self._wiki_retrieval:
            try:
                self._wiki_synthesizer = WikiSynthesizer(
                    storage=self._wiki_storage,
                    retrieval=self._wiki_retrieval,
                    llm_client=self.openai_client_openrouter,
                    model=DEFAULT_AI_MODEL,
                )
                log.info("Wiki synthesizer initialized")
            except Exception as e:
                log.warning(f"Wiki synthesizer initialization failed: {e}")
                self._wiki_synthesizer = None

        # Context Menus
        self.ctx_menus = [
            app_commands.ContextMenu(
                name="Process Image with Prompt", callback=self.process_image_context
            ),
        ]
        for menu in self.ctx_menus:
            self.bot.tree.add_command(menu)

        # Start SSE listener for backend events
        self._sse_task = asyncio.create_task(self._listen_backend_events())

        # Start wiki background tasks
        self.wiki_background_ingest.start()
        self.wiki_daily_lint.start()
        self.wiki_daily_export.start()
        self.wiki_weekly_synthesis.start()

    async def cog_unload(self):
        # Cancel SSE listener
        if self._sse_task:
            self._sse_task.cancel()

        # Cancel wiki background tasks
        self.wiki_background_ingest.cancel()
        self.wiki_daily_lint.cancel()
        self.wiki_daily_export.cancel()
        self.wiki_weekly_synthesis.cancel()

        # Close memory storage
        if self._memory_storage:
            self._memory_storage.close()
            log.info("Memory storage closed")

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

        # Load backend schema description for LLM tool
        self.backend_schema_description = backend_db.get_schema_description()
        log.info(
            f"Backend schema loaded: {len(self.backend_schema_description)} characters"
        )

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
        player_id=None,
    ):
        now = datetime.now(self.local_tz)

        wiki_index_str = ""
        if self._wiki_index:
            try:
                wiki_index_str = self._wiki_index.get_index() or ""
            except Exception:
                pass

        if generic:
            system_message = "You are a helpful assistant for the ASEAN MotorTown Club discord server. Do not use markdown tables or emojis in your responses."
        else:
            system_message = (
                "You are a helpful bot in Motor Town, an open world driving game, specifically in a dedicated server named 'ASEAN Motor Club'.\n"
                "Only use the following information about the game to answer queries. If a user asks a question outside the scope of your knowledge, refer them to the discord channel and other players in the game.\n"
                "Do not use markdown tables or emojis in your responses.\n\n"
                "## Your Wiki\n"
                "You maintain a personal wiki of knowledge about the community, players, and game world. "
                "Before answering questions about people, community dynamics, or long-running topics, search your wiki for relevant pages. "
                "When you learn something new and notable from a conversation, update your wiki using write_wiki_page. "
                "If the current speaker asks what you know about them, call get_my_wiki_profile (no arguments). "
                "For game-related questions, use the ask_game_knowledge tool instead of guessing.\n\n"
                f"{self.knowledge_system_message}"
            )

        if wiki_index_str:
            system_message += f"\n\n## Wiki Knowledge Index\n{wiki_index_str}"

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
                                "description": "SQL SELECT query to execute",
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

        # Inject economy tools if user has Financial Minister role
        from amc_peripheral.settings import FINANCIAL_MINISTER_ROLE_ID

        if interaction and isinstance(interaction.user, discord.Member):
            economy_cog = self.bot.get_cog("EconomyCog")
            if economy_cog and (
                interaction.user.guild_permissions.administrator
                or any(
                    r.id == FINANCIAL_MINISTER_ROLE_ID for r in interaction.user.roles
                )
            ):
                tools.extend(economy_cog.get_tool_definitions())

        # Inject wiki tools
        tools.extend(self._get_wiki_tool_definitions())

        # Retrieve relevant wiki context
        wiki_context = await self._get_wiki_context(question)

        messages = [
            {"role": "system", "content": system_message},
            {
                "role": "user",
                "content": f"## Context\nThe current date and time (in Bangkok GMT+7 timezone) is: {now.strftime('%A, %Y-%m-%d %H:%M')}",
            },
        ]
        if wiki_context:
            messages.append({"role": "user", "content": wiki_context})
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
        return await self._call_llm_with_tools(
            messages, tools, model, interaction=interaction, player_id=player_id
        )

    async def ai_helper(
        self,
        player_name,
        question,
        prev_messages,
        ingame_feedback_fn: Optional[Callable[[str], Awaitable[None]]] = None,
        player_id: Optional[str] = None,
    ):
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
            "You are a helpful bot in Motor Town, an open world driving game, specifically in 'ASEAN Motor Club'.\n"
            "Answer in a short sentence or paragraph since the game only allows short messages, and avoid using newlines.\n"
            "Only use the following knowledge. Do not use markdown, tables, or emojis.\n"
            "For game-related questions, use the ask_game_knowledge tool instead of guessing.\n\n"
            + self.knowledge_system_message
        )

        wiki_index_str = ""
        if self._wiki_index:
            try:
                wiki_index_str = self._wiki_index.get_index() or ""
            except Exception:
                pass
        if wiki_index_str:
            system_message += f"\n\n## Wiki Knowledge Index\n{wiki_index_str}"

        # Retrieve relevant wiki context for the question
        wiki_context = await self._get_wiki_context(question)

        messages = [
            {"role": "system", "content": system_message},
        ]
        if events_str:
            messages.append(
                {"role": "user", "content": "# Upcoming events:\n\n" + events_str}
            )
        if wiki_context:
            messages.append({"role": "user", "content": wiki_context})

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
                                "description": "SQL SELECT query to execute",
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
            {
                "type": "function",
                "function": {
                    "name": "query_backend_database",
                    "description": f"""Query the AMC backend PostgreSQL database with SQL.

{self.backend_schema_description}

Use standard PostgreSQL SQL with SELECT. Supports JOINs, GROUP BY, aggregates, CTEs, window functions.
Results limited to 100 rows. Read-only access. Finance tables (balances, transactions) are restricted.
Use this for player stats, deliveries, race results, teams, jobs, ministry data, and game analytics.""",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "sql": {
                                "type": "string",
                                "description": "PostgreSQL SELECT query to execute",
                            }
                        },
                        "required": ["sql"],
                    },
                },
            },
        ]

        # Inject wiki tools
        tools.extend(self._get_wiki_tool_definitions())

        return await self._call_llm_with_tools(
            messages,
            tools,
            DEFAULT_AI_MODEL,
            ingame_feedback_fn=ingame_feedback_fn,
            player_id=player_id,
        )

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

    def _get_wiki_tool_definitions(self) -> list[dict]:
        """Return wiki + ask_game_knowledge tool definitions for the LLM."""
        tools = [
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
                    "name": "read_wiki_page",
                    "description": "Read a wiki page by title or slug. Use this to recall detailed information about a player, vehicle, location, concept, or event from the wiki.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "title_or_slug": {
                                "type": "string",
                                "description": "The page title or slug to read (e.g. 'player:freemanlatif', 'vehicle:Gosan_G7', 'concept:steel-coil-curse')",
                            },
                        },
                        "required": ["title_or_slug"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "search_wiki",
                    "description": "Search the wiki for pages semantically related to a query. Returns the most relevant pages with summaries.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "The search query",
                            },
                            "n_results": {
                                "type": "integer",
                                "description": "Number of results to return (default 3, max 5)",
                            },
                        },
                        "required": ["query"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "list_wiki_pages",
                    "description": "List wiki pages by category or with a keyword filter. Use this to browse what the wiki knows about.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "category": {
                                "type": "string",
                                "description": "Optional category filter (e.g. 'player', 'vehicle', 'concept', 'event')",
                            },
                            "keyword": {
                                "type": "string",
                                "description": "Optional keyword to filter titles/content",
                            },
                            "limit": {
                                "type": "integer",
                                "description": "Max pages to return (default 10)",
                            },
                        },
                        "required": [],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "write_wiki_page",
                    "description": "Create or update a wiki page. Use this when the bot learns something new and notable that should be remembered long-term. The page will be indexed for future retrieval.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "title": {
                                "type": "string",
                                "description": "Page title (e.g. 'player:freemanlatif', 'concept:steel-coil-curse')",
                            },
                            "category": {
                                "type": "string",
                                "description": "Page category (e.g. 'player', 'vehicle', 'location', 'concept', 'event', 'relationship', 'song')",
                            },
                            "content": {
                                "type": "string",
                                "description": "The page content",
                            },
                            "summary": {
                                "type": "string",
                                "description": "A brief summary of the page",
                            },
                        },
                        "required": ["title", "category", "content"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "add_wiki_link",
                    "description": "Create a cross-reference link between two wiki pages. This helps navigate the knowledge graph.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "from_page": {
                                "type": "string",
                                "description": "Title or slug of the source page",
                            },
                            "to_page": {
                                "type": "string",
                                "description": "Title or slug of the target page",
                            },
                            "link_type": {
                                "type": "string",
                                "description": "Type of link (default: 'mentions')",
                            },
                        },
                        "required": ["from_page", "to_page"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_wiki_summary",
                    "description": "Get a brief summary of the wiki contents — total pages, categories, and recent updates.",
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
                    "name": "get_my_wiki_profile",
                    "description": "Get the wiki profile page for the current speaker. Use this when someone asks 'what do you know about me?', 'show me my profile', or 'do you remember me?'. Takes no arguments — the correct player_id is injected automatically.",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "required": [],
                    },
                },
            },
        ]
        return tools

    async def _call_llm_with_tools(
        self,
        messages: list[dict],
        tools: list[dict],
        model: str,
        interaction: Optional[discord.Interaction] = None,
        ingame_feedback_fn: Optional[Callable[[str], Awaitable[None]]] = None,
        player_id: Optional[str] = None,
    ) -> str:
        """
        Call LLM with tool support and handle tool calls iteratively.
        Provides user feedback for long-running operations.

        Args:
            messages: Conversation messages
            tools: Tool definitions
            model: AI model to use
            interaction: Discord interaction for sending feedback (optional)
            ingame_feedback_fn: Callback for sending in-game feedback (optional)
            player_id: Current speaker's player ID (for wiki profile lookups)

        Returns:
            Final response text
        """
        max_iterations = BOT_MAX_ITERATIONS
        iteration = 0
        start_time = asyncio.get_event_loop().time()

        # Feedback state
        initial_feedback_sent = False
        tool_feedback_sent = False
        last_tool_name: Optional[str] = None

        while iteration < max_iterations:
            iteration += 1
            elapsed = asyncio.get_event_loop().time() - start_time

            # --- Progress Feedback Logic ---
            if not initial_feedback_sent and elapsed >= BOT_FEEDBACK_DELAY_SECONDS:
                await self._send_progress_feedback(
                    message="Working on it...",
                    interaction=interaction,
                    ingame_feedback_fn=ingame_feedback_fn,
                )
                initial_feedback_sent = True

            if (
                not tool_feedback_sent
                and elapsed >= BOT_TOOL_STATUS_DELAY_SECONDS
                and last_tool_name
            ):
                tool_msg = self._get_tool_status_message(last_tool_name)
                await self._send_progress_feedback(
                    message=tool_msg,
                    interaction=interaction,
                    ingame_feedback_fn=ingame_feedback_fn,
                )
                tool_feedback_sent = True

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

            # Track last tool called for status messages
            last_tool_name = response_message.tool_calls[-1].function.name

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
                tool_result = await self._execute_tool(
                    function_name, function_args, interaction, player_id=player_id
                )

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

    async def _send_progress_feedback(
        self,
        message: str,
        interaction: Optional[discord.Interaction] = None,
        ingame_feedback_fn: Optional[Callable[[str], Awaitable[None]]] = None,
    ) -> None:
        """Send progress feedback to user via appropriate channel."""
        try:
            if interaction:
                # Discord: edit the deferred response
                await interaction.edit_original_response(content=message)
            elif ingame_feedback_fn:
                # In-game: use the provided callback
                await ingame_feedback_fn(message)
        except Exception as e:
            log.warning(f"Failed to send progress feedback: {e}")

    def _get_tool_status_message(self, tool_name: str) -> str:
        """Return user-friendly status message for a tool."""
        tool_messages = {
            "query_game_database": "Crunching the numbers...",
            "query_backend_database": "Querying the backend database...",
            "get_current_subsidies": "Checking subsidy rates...",
            "get_server_commands": "Looking up commands...",
            "get_currently_playing_song": "Checking the radio...",
            "create_poll": "Creating your poll...",
            "create_scheduled_event": "Setting up the event...",
            "manage_subsidy_rules_list": "Fetching subsidy rules...",
            "manage_subsidy_rule_create": "Creating subsidy rule...",
            "manage_subsidy_rule_update": "Updating subsidy rule...",
            "manage_subsidy_rule_deactivate": "Deactivating subsidy rule...",
            "manage_subsidy_rule_reorder": "Reordering subsidy rules...",
            "manage_job_config_get": "Fetching job configuration...",
            "manage_job_config_update": "Updating job configuration...",
            "ask_game_knowledge": "Researching game knowledge...",
            "read_wiki_page": "Reading wiki page...",
            "search_wiki": "Searching the wiki...",
            "list_wiki_pages": "Browsing wiki pages...",
            "write_wiki_page": "Updating wiki...",
            "add_wiki_link": "Linking wiki pages...",
            "get_wiki_summary": "Checking wiki stats...",
            "get_my_wiki_profile": "Looking up your profile...",
        }
        return tool_messages.get(tool_name, f"Processing ({tool_name})...")

    async def _get_wiki_context(self, query: str = "") -> str:
        """Retrieve relevant wiki pages for bot chats.

        Searches ChromaDB for semantically relevant pages and returns a
        formatted context string. If no query is provided, returns the wiki index.
        """
        if not self._wiki_storage or not self._wiki_retrieval:
            return ""

        try:
            if query:
                results = self._wiki_retrieval.search(query, n_results=3)
                if results:
                    page_ids = [r["page_id"] for r in results if r.get("page_id")]
                    if self._wiki_index and page_ids:
                        context = self._wiki_index.get_multi_page_context(page_ids)
                        if context:
                            return f"Relevant wiki pages:\n{context}"

            if self._wiki_index:
                index = self._wiki_index.get_index()
                if index:
                    return f"Wiki index:\n{index}"

            return ""
        except Exception as e:
            log.warning(f"Failed to retrieve wiki context: {e}")
            return ""

    def _get_player_wiki_summary(self, player_id: str) -> str:
        """Return a formatted summary of the player's wiki page."""
        if not player_id:
            return (
                "I don't have a player ID to look up right now. Try chatting "
                "with me a bit more and I'll build your page."
            )
        if not self._wiki_storage:
            return "My wiki isn't available right now."

        try:
            slug = f"player:{player_id}"
            page = self._wiki_storage.get_page_by_slug(slug)
            if not page:
                page = self._wiki_storage.get_page_by_title(slug)
            if not page:
                return (
                    f"I don't have a wiki page for you yet (player_id={player_id}). "
                    "Let's chat more and I'll get to know you!"
                )

            lines: list[str] = [
                f"--- {page.get('title', '(untitled)')} ---",
                f"Category: {page.get('category', 'player')}",
            ]
            summary = (page.get("summary") or "").strip()
            if summary:
                lines.append(f"Summary: {summary}")
            content = (page.get("content") or "").strip()
            if content:
                excerpt = content if len(content) <= 2000 else content[:2000] + "..."
                lines.append("Content:")
                lines.append(excerpt)

            try:
                outbound = self._wiki_storage.get_links_from(page["id"])
                inbound = self._wiki_storage.get_links_to(page["id"])
            except Exception:
                outbound = []
                inbound = []
            if outbound:
                titles = ", ".join(link.get("to_title", "") for link in outbound[:10])
                lines.append(f"Links to: {titles}")
            if inbound:
                titles = ", ".join(link.get("from_title", "") for link in inbound[:10])
                lines.append(f"Linked from: {titles}")

            return "\n".join(lines)
        except Exception as e:
            log.warning(f"_get_player_wiki_summary failed: {e}")
            return (
                "I had trouble reading your wiki page just now — "
                "but you're still on my mind."
            )

    async def _execute_tool(
        self,
        function_name: str,
        arguments: dict,
        interaction: Optional[discord.Interaction] = None,
        player_id: Optional[str] = None,
    ) -> str:
        """
        Execute a knowledge bot tool.

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
                if (
                    not interaction
                    or not isinstance(interaction.user, discord.Member)
                    or not interaction.user.guild_permissions.administrator
                ):
                    return (
                        "Error: You do not have permission to create scheduled events."
                    )

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
                    formatted_output += (
                        f"\n\nNote: Results were limited to {count} rows."
                    )

                return formatted_output

            elif function_name == "get_currently_playing_song":
                from amc_peripheral.radio.radio_server import get_current_song

                current_song = await get_current_song(self.bot.http_session)
                return (
                    current_song
                    or "No song is currently playing or unable to fetch song info."
                )

            elif function_name == "get_current_subsidies":
                async with self.bot.http_session.get(
                    f"{BACKEND_API_URL}/api/subsidies/"
                ) as resp:
                    data = await resp.json()
                    return data.get(
                        "subsidies_text", "No subsidy information available."
                    )

            elif function_name == "get_server_commands":
                async with self.bot.http_session.get(
                    f"{BACKEND_API_URL}/api/commands/"
                ) as resp:
                    if resp.status != 200:
                        return "Failed to fetch server commands."
                    commands_data = await resp.json()

                    # Format commands by category for better readability
                    formatted = "Available server commands:\n\n"

                    # Group by category
                    from itertools import groupby

                    for category, cmds in groupby(
                        commands_data, key=lambda x: x.get("category", "General")
                    ):
                        formatted += f"## {category}\n"
                        for cmd in cmds:
                            cmd_name = cmd["command"]
                            shorthand = cmd.get("shorthand")
                            description = cmd.get("description", "")

                            if shorthand:
                                formatted += f"- **{cmd_name}** (or **{shorthand}**): {description}\n"
                            else:
                                formatted += f"- **{cmd_name}**: {description}\n"
                        formatted += "\n"

                    return formatted

            elif function_name == "query_backend_database":
                sql = arguments.get("sql")
                if not sql:
                    return "Backend database query failed: sql parameter required"

                result = await asyncio.to_thread(backend_db.execute_query, sql)

                if "error" in result:
                    return f"Backend database query failed: {result['error']}"

                return backend_db.format_results(result)

            elif function_name.startswith("manage_subsidy") or function_name.startswith(
                "manage_job_config"
            ):
                economy_cog = self.bot.get_cog("EconomyCog")
                if economy_cog:
                    return await economy_cog.execute_tool(
                        function_name, arguments, interaction
                    )
                return "Error: Economy management is not available."

            # --- Wiki tools ---
            elif function_name == "ask_game_knowledge":
                from amc_peripheral.radio.game_knowledge import ask_game_knowledge

                question = arguments.get("question", "")
                if not self._wiki_storage:
                    return "Wiki storage not available."
                try:
                    answer = await ask_game_knowledge(
                        openai_client=self.openai_client_openrouter,
                        wiki_storage=self._wiki_storage,
                        wiki_retrieval=self._wiki_retrieval,
                        wiki_index=self._wiki_index,
                        game_schema=self.game_schema_description,
                        question=question,
                        http_session=self.bot.http_session,
                    )
                    return answer
                except Exception as e:
                    return f"Failed to get game knowledge: {e}"

            elif function_name == "read_wiki_page":
                title_or_slug = arguments.get("title_or_slug", "")
                if not title_or_slug:
                    return "Error: 'title_or_slug' is required."
                if not self._wiki_storage:
                    return "Wiki storage not available."
                page = self._wiki_storage.get_page_by_slug(title_or_slug)
                if not page:
                    page = self._wiki_storage.get_page_by_title(title_or_slug)
                if not page:
                    return f"No wiki page found for '{title_or_slug}'."
                return (
                    f"--- {page['title']} ---\n"
                    f"Category: {page['category']}\n"
                    f"Summary: {page.get('summary', '')}\n"
                    f"Content:\n{page['content']}"
                )

            elif function_name == "search_wiki":
                query = arguments.get("query", "")
                n_results = arguments.get("n_results", 3)
                if not query:
                    return "Error: 'query' is required."
                if not self._wiki_retrieval:
                    return "Wiki retrieval not available."
                results = self._wiki_retrieval.search(query, n_results=n_results)
                if not results:
                    return f"No wiki pages found for '{query}'."
                lines = []
                for r in results:
                    lines.append(  # pyrefly: ignore [bad-argument-type]
                        f"- {r.get('title', 'Unknown')} ({r.get('category', 'unknown')}): "
                        f"{r.get('content', '')[:200]}..."
                    )
                return "Wiki search results:\n" + "\n".join(lines)

            elif function_name == "list_wiki_pages":
                category = arguments.get("category") or None
                keyword = arguments.get("keyword") or None
                limit = arguments.get("limit", 10)
                if not self._wiki_storage:
                    return "Wiki storage not available."
                pages = self._wiki_storage.list_pages(
                    category=category, keyword=keyword, limit=limit
                )
                if not pages:
                    return "No wiki pages found."
                lines = []
                for p in pages:
                    lines.append(  # pyrefly: ignore [bad-argument-type]
                        f"- {p['title']} ({p['category']}): {p.get('summary', '')[:100]}"
                    )
                return "Wiki pages:\n" + "\n".join(lines)

            elif function_name == "write_wiki_page":
                title = arguments.get("title", "")
                category = arguments.get("category", "concept")
                content = arguments.get("content", "")
                summary = arguments.get("summary", "")
                if not title or not content:
                    return "Error: 'title' and 'content' are required."
                if not self._wiki_storage or not self._wiki_retrieval:
                    return "Wiki storage not available."
                slug = self._wiki_storage._make_slug(title)
                existing = self._wiki_storage.get_page_by_slug(slug)
                if existing:
                    self._wiki_storage.update_page(
                        existing["id"],
                        content=content,
                        summary=summary or existing.get("summary", ""),
                    )
                    refreshed = self._wiki_storage.get_page_by_id(existing["id"])
                    if refreshed:
                        self._wiki_retrieval.index_page(
                            page_id=existing["id"],
                            title=refreshed["title"],
                            content=refreshed["content"],
                            category=refreshed["category"],
                            updated_at=refreshed["updated_at"],
                        )
                    return f"Updated wiki page '{title}'."
                else:
                    page_id = self._wiki_storage.create_page(
                        title=title, category=category, content=content, summary=summary
                    )
                    refreshed = self._wiki_storage.get_page_by_id(page_id)
                    if refreshed:
                        self._wiki_retrieval.index_page(
                            page_id=page_id,
                            title=refreshed["title"],
                            content=refreshed["content"],
                            category=refreshed["category"],
                            updated_at=refreshed["updated_at"],
                        )
                    return f"Created wiki page '{title}'."

            elif function_name == "add_wiki_link":
                from_page = arguments.get("from_page", "")
                to_page = arguments.get("to_page", "")
                link_type = arguments.get("link_type", "mentions")
                if not from_page or not to_page:
                    return "Error: 'from_page' and 'to_page' are required."
                if not self._wiki_storage:
                    return "Wiki storage not available."
                from_p = self._wiki_storage.get_page_by_slug(
                    from_page
                ) or self._wiki_storage.get_page_by_title(from_page)
                to_p = self._wiki_storage.get_page_by_slug(
                    to_page
                ) or self._wiki_storage.get_page_by_title(to_page)
                if not from_p:
                    return f"From page '{from_page}' not found."
                if not to_p:
                    return f"To page '{to_page}' not found."
                self._wiki_storage.add_link(from_p["id"], to_p["id"], link_type)
                return f"Linked '{from_p['title']}' -> '{to_p['title']}' ({link_type})."

            elif function_name == "get_wiki_summary":
                if not self._wiki_storage:
                    return "Wiki storage not available."
                stats = self._wiki_storage.get_stats()
                lines = [
                    "Wiki summary:",
                    f"- Total pages: {stats.get('total_pages', 0)}",
                    f"- Categories: {stats.get('total_categories', 0)}",
                    f"- Total sources: {stats.get('total_sources', 0)}",
                    f"- Total links: {stats.get('total_links', 0)}",
                    f"- Log entries: {stats.get('total_log_entries', 0)}",
                ]
                if stats.get("latest_update"):
                    lines.append(f"- Latest update: {stats['latest_update']}")
                return "\n".join(lines)

            elif function_name == "get_my_wiki_profile":
                return self._get_player_wiki_summary(player_id or "")

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
            player_id=str(interaction.user.id),
        )
        for line in split_markdown(ans):
            await interaction.followup.send(line)

        await self._store_bot_interaction(
            player_id=str(interaction.user.id),
            player_name=interaction.user.display_name,
            question=question,
            response=ans,
            source="discord_slash",
        )

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
            # Fetch active threads first
            threads = list(channel.threads)
            active_count = len(threads)
            # Then add archived threads
            async for archived in channel.archived_threads(limit=None):
                threads.append(archived)
            log.info(
                f"Fetched {len(threads)} threads ({active_count} active, {len(threads) - active_count} archived)"
            )
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

        # Validate knowledge base content
        if not acc.strip():
            log.error("CRITICAL: Knowledge base is EMPTY after fetching forum!")
        elif len(acc) < 500:
            log.warning(f"Knowledge base unusually short: {len(acc)} chars")

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

    async def _debounced_knowledge_reload(self, forum_channel: discord.ForumChannel):
        """Wait for debounce period then reload knowledge."""
        try:
            await asyncio.sleep(self._knowledge_reload_debounce_seconds)
            await self.fetch_forum_messages(forum_channel)
            log.info("Knowledge base reloaded after debounce")
        except asyncio.CancelledError:
            log.debug("Knowledge reload cancelled (new update pending)")
        finally:
            self._knowledge_reload_task = None

    def trigger_knowledge_reload(self, forum_channel: discord.ForumChannel):
        """Trigger a debounced knowledge reload."""
        if self._knowledge_reload_task is not None:
            self._knowledge_reload_task.cancel()
        self._knowledge_reload_task = asyncio.create_task(
            self._debounced_knowledge_reload(forum_channel)
        )

    # --- Wiki Background Tasks ---

    @tasks.loop(minutes=5)
    async def wiki_background_ingest(self):
        """Drain the pending ingest queue and process conversations."""
        if not self._wiki_pending_conversations:
            return
        if not self._wiki_ingest or not self._wiki_storage:
            log.warning("Wiki ingest not available, skipping background ingest")
            self._wiki_pending_conversations.clear()
            return

        batch = self._wiki_pending_conversations[:]
        self._wiki_pending_conversations.clear()
        log.info(f"Wiki background ingest: processing {len(batch)} conversation(s)")

        for item in batch:
            try:
                await self._ingest_to_wiki(
                    item["player_id"],
                    item["player_name"],
                    item["question"],
                    item["response"],
                )
            except Exception as e:
                log.warning(
                    f"Wiki background ingest failed for {item.get('player_name')}: {e}"
                )

    @wiki_background_ingest.before_loop
    async def before_wiki_background_ingest(self):
        await self.bot.wait_until_ready()

    @wiki_background_ingest.error
    async def wiki_background_ingest_error(self, error):
        log.error(f"wiki_background_ingest task error: {error}", exc_info=error)

    @tasks.loop(time=dt_time(hour=4, minute=0, tzinfo=ZoneInfo("Asia/Bangkok")))
    async def wiki_daily_lint(self):
        """Run daily wiki lint: scan for orphans, stale pages, missing links."""
        if not self._wiki_lint or not self._wiki_storage:
            log.warning("Wiki lint not available, skipping daily lint")
            return

        try:
            report = self._wiki_lint.run_lint(auto_fix=True)
            total_issues = (
                len(report.get("orphans", []))
                + len(report.get("stale", []))
                + len(report.get("missing_links", []))
                + len(report.get("inactive_players", []))
            )
            fixes = len(report.get("fixes_applied", []))
            log.info(
                f"Wiki daily lint: {total_issues} issues found, {fixes} auto-fixed"
            )
        except Exception as e:
            log.error(f"Wiki daily lint failed: {e}", exc_info=e)

    @wiki_daily_lint.before_loop
    async def before_wiki_daily_lint(self):
        await self.bot.wait_until_ready()

    @wiki_daily_lint.error
    async def wiki_daily_lint_error(self, error):
        log.error(f"wiki_daily_lint task error: {error}", exc_info=error)

    @tasks.loop(time=dt_time(hour=4, minute=30, tzinfo=ZoneInfo("Asia/Bangkok")))
    async def wiki_daily_export(self):
        """Export the wiki to markdown every morning at 4:30 Bangkok time."""
        if not self._wiki_exporter:
            log.warning("Wiki exporter not available, skipping daily export")
            return
        try:
            summary = await asyncio.to_thread(self._wiki_exporter.export_all)
            log.info(
                f"Wiki daily export complete: "
                f"{summary.get('pages_exported', 0)} pages -> "
                f"{summary.get('output_dir', '')}"
            )
        except Exception as e:
            log.error(f"Wiki daily export failed: {e}", exc_info=e)

    @wiki_daily_export.before_loop
    async def before_wiki_daily_export(self):
        await self.bot.wait_until_ready()

    @wiki_daily_export.error
    async def wiki_daily_export_error(self, error):
        log.error(f"wiki_daily_export task error: {error}", exc_info=error)

    @tasks.loop(time=dt_time(hour=9, minute=0, tzinfo=ZoneInfo("Asia/Bangkok")))
    async def wiki_weekly_synthesis(self):
        """Run weekly synthesis on Monday mornings (Bangkok time)."""
        now = datetime.now(self.local_tz)
        if now.weekday() != 0:  # 0 = Monday
            return
        if not self._wiki_synthesizer:
            log.warning("Wiki synthesizer not available, skipping weekly synthesis")
            return
        try:
            page = await self._wiki_synthesizer.generate_weekly_synthesis(now=now)
            if page is None:
                log.info("Weekly synthesis produced no page (no recent activity)")
            else:
                log.info(
                    f"Weekly synthesis page written: {page.get('title', 'synthesis')}"
                )
        except Exception as e:
            log.error(f"Weekly synthesis failed: {e}", exc_info=e)

    @wiki_weekly_synthesis.before_loop
    async def before_wiki_weekly_synthesis(self):
        await self.bot.wait_until_ready()

    @wiki_weekly_synthesis.error
    async def wiki_weekly_synthesis_error(self, error):
        log.error(f"wiki_weekly_synthesis task error: {error}", exc_info=error)

    # --- SSE Backend Connection ---

    @staticmethod
    def _notify_watchdog():
        """Send systemd watchdog heartbeat via NOTIFY_SOCKET (no python-systemd needed)."""
        import os
        import socket

        addr = os.environ.get("NOTIFY_SOCKET")
        if not addr:
            return
        if addr[0] == "@":
            addr = "\0" + addr[1:]
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
            sock.connect(addr)
            sock.sendall(b"WATCHDOG=1")
            sock.close()
        except Exception:
            pass

    async def _listen_backend_events(self):
        """Listen to backend SSE for game events with rich context."""
        import aiohttp
        import random

        retry_delay = 5
        max_retry_delay = 60

        while True:
            try:
                log.info(f"Connecting to SSE at {BACKEND_API_URL}/api/bot_events/...")
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        f"{BACKEND_API_URL}/api/bot_events/",
                        timeout=aiohttp.ClientTimeout(total=None, sock_connect=10),
                    ) as resp:
                        log.info(f"SSE connected, status: {resp.status}")
                        retry_delay = 5  # Reset backoff on successful connection
                        async for line in resp.content:
                            line_str = line.decode("utf-8").strip()
                            if line_str.startswith("data: "):
                                try:
                                    event = json.loads(line_str[6:])
                                    event_type = event.get("type", "unknown")
                                    if event_type == "heartbeat":
                                        log.debug("SSE heartbeat received")
                                    else:
                                        log.info(
                                            f"SSE event received: type={event_type}, is_bot_command={event.get('is_bot_command')}"
                                        )
                                    self._notify_watchdog()

                                    task = asyncio.create_task(
                                        self._handle_backend_event(event)
                                    )
                                    self._active_tasks.add(task)
                                    task.add_done_callback(self._active_tasks.discard)
                                except json.JSONDecodeError as e:
                                    log.warning(f"Failed to parse SSE event: {e}")
            except asyncio.CancelledError:
                log.info("SSE listener cancelled")
                break
            except Exception as e:
                log.error(f"SSE connection error: {e}")
                jitter = random.uniform(0, retry_delay * 0.1)
                log.info(f"SSE reconnecting in {retry_delay:.0f}s...")
                await asyncio.sleep(retry_delay + jitter)
                retry_delay = min(retry_delay * 2, max_retry_delay)

    # --- Event-driven wiki ingest ---

    async def ingest_game_event(
        self,
        event_type: str,
        event_id: str,
        title: str,
        description: str,
        participants: list[str] | None = None,
    ) -> list[int]:
        """Ingest a backend/game event into the wiki.

        Returns affected page IDs.
        """
        if not self._wiki_ingest:
            log.warning("Wiki ingest not available, cannot ingest game event")
            return []
        try:
            return self._wiki_ingest.ingest_event(
                event_type=event_type,
                event_id=event_id,
                title=title,
                description=description,
                participants=participants,
            )
        except Exception as e:
            log.warning(f"Game event ingest failed ({event_type}:{event_id}): {e}")
            return []

    @staticmethod
    def map_event_to_wiki(event: dict) -> tuple[str, str, str, str, list[str] | None]:
        """Shape a raw backend event dict into ingest_game_event arguments.

        Returns (event_type, event_id, title, description, participants).
        """
        event_type = event.get("type", "unknown")
        timestamp = event.get("timestamp") or "unknown"
        event_id = event.get("event_id") or f"{event_type}-{timestamp}"
        title = event.get("title") or f"{event_type} @ {timestamp}"
        description = event.get("description") or ""
        if not description:
            try:
                description = json.dumps(
                    {k: v for k, v in event.items() if k != "type"},
                    default=str,
                )
            except Exception:
                description = str(event)
        participants = event.get("participants")
        if participants is not None and not isinstance(participants, list):
            participants = None
        return event_type, event_id, title, description, participants

    async def _handle_backend_event(self, event: dict):
        """Handle events from backend SSE stream.

        - `chat_message` → memory + chat history + /bot command handling
        - `heartbeat` → no-op
        - Anything else → routed through wiki ingest
        """
        event_type = event.get("type")

        if event_type == "heartbeat":
            return

        if event_type == "chat_message":
            player_id = event["player_id"]
            player_name = event["player_name"]
            message = event["message"]
            timestamp = datetime.fromisoformat(event["timestamp"])
            discord_id = event.get("discord_id")

            # Store in long-term memory (SQLite)
            if self._memory_storage:
                try:
                    self._memory_storage.store_message(
                        player_id=player_id,
                        player_name=player_name,
                        message=message,
                        source="game_chat",
                        timestamp=timestamp,
                        discord_user_id=str(discord_id) if discord_id else None,
                    )
                except Exception as e:
                    log.warning(f"Failed to store message in memory: {e}")

            # Add to semantic search (ChromaDB)
            if self._memory_retrieval:
                try:
                    self._memory_retrieval.add_memory(
                        player_id=player_id,
                        player_name=player_name,
                        message=message,
                        source="game_chat",
                        timestamp=timestamp,
                        discord_user_id=str(discord_id) if discord_id else None,
                    )
                except Exception as e:
                    log.warning(f"Failed to add memory to ChromaDB: {e}")

            # Track message history per player
            if player_id not in self._player_message_history:
                self._player_message_history[player_id] = []

            player_history = self._player_message_history[player_id]
            player_history.append(f"{player_name}: {message}")

            if len(player_history) > self._max_history_per_player:
                self._player_message_history[player_id] = player_history[
                    -self._max_history_per_player :
                ]

            # Track global chat history
            self._global_chat_history.append((player_id, player_name, message))
            if len(self._global_chat_history) > self._max_global_history:
                self._global_chat_history = self._global_chat_history[
                    -self._max_global_history :
                ]

            # Handle /bot command if this is one
            if event.get("is_bot_command"):
                log.info(f"Bot command detected from {player_name}: {message}")
                prev_messages = (
                    "\n".join(
                        f"{name}: {msg}"
                        for _, name, msg in self._global_chat_history[:-1]
                    )
                    if len(self._global_chat_history) > 1
                    else ""
                )

                semantic_context = ""
                if self._memory_retrieval:
                    try:
                        memories = self._memory_retrieval.retrieve_relevant(
                            player_id=player_id,
                            query=message,
                            n_results=3,
                        )
                        if memories:
                            semantic_context = "\n".join(
                                [
                                    f"[{m['timestamp'][:10]}] {m['player_name']}: {m['message']}"
                                    for m in memories
                                ]
                            )
                    except Exception as e:
                        log.warning(f"Failed to retrieve semantic memories: {e}")

                await self._handle_ingame_bot_command(
                    player_name=player_name,
                    player_id=player_id,
                    discord_id=discord_id,
                    message=message,
                    prev_messages=prev_messages,
                    semantic_context=semantic_context,
                )
            return

        # Non-chat events → wiki ingest
        if not event_type:
            log.warning(f"SSE event missing type: {event!r}")
            return

        try:
            mapped_type, event_id, title, description, participants = (
                self.map_event_to_wiki(event)
            )
        except Exception as e:
            log.warning(f"SSE event shape invalid ({event!r}): {e}")
            return

        try:
            await self.ingest_game_event(
                event_type=mapped_type,
                event_id=event_id,
                title=title,
                description=description,
                participants=participants,
            )
        except Exception as e:
            log.warning(f"SSE ingest failed ({event_type}): {e}")

    # --- Conversation → Wiki Pipeline ---

    async def _store_bot_interaction(
        self,
        player_id: str,
        player_name: str,
        question: str,
        response: str,
        source: str = "discord_dm",
    ) -> None:
        """Store both the player's question and bot response in long-term memory."""
        if not self._memory_storage:
            return

        try:
            self._memory_storage.store_message(
                player_id=player_id,
                player_name=player_name,
                message=question,
                source=source,
                is_bot_response=False,
            )
        except Exception as e:
            log.warning(f"Failed to store player question: {e}")

        try:
            self._memory_storage.store_message(
                player_id=player_id,
                player_name="Bot",
                message=response,
                source=source,
                is_bot_response=True,
            )
        except Exception as e:
            log.warning(f"Failed to store bot response: {e}")

        if self._memory_retrieval:
            try:
                self._memory_retrieval.add_memory(
                    player_id=player_id,
                    player_name=player_name,
                    message=question,
                    source=source,
                    is_bot_response=False,
                )
                self._memory_retrieval.add_memory(
                    player_id=player_id,
                    player_name="Bot",
                    message=response,
                    source=source,
                    is_bot_response=True,
                )
            except Exception as e:
                log.warning(f"Failed to add bot interaction to ChromaDB: {e}")

        self._schedule_wiki_ingest(player_id, player_name, question, response)

    def _schedule_wiki_ingest(
        self,
        player_id: str,
        player_name: str,
        question: str,
        response: str,
    ) -> None:
        """Queue a conversation for background wiki ingest."""
        self._wiki_pending_conversations.append(
            {
                "player_id": player_id,
                "player_name": player_name,
                "question": question,
                "response": response,
                "timestamp": datetime.now(self.local_tz).isoformat(),
            }
        )

    async def _ingest_to_wiki(
        self,
        player_id: str,
        player_name: str,
        question: str,
        response: str,
    ) -> None:
        """LLM-based fact extraction from a conversation → wiki pages.

        Fire-and-forget — errors are logged but not raised.
        """
        if not self._wiki_ingest or not self._wiki_storage:
            return

        try:
            messages = [
                {
                    "role": "system",
                    "content": (
                        "You are a fact extraction assistant. Given a conversation between a player and a bot, "
                        "extract any notable facts worth saving to a wiki. Return a JSON list of fact objects. "
                        "Each fact should have: title, category (one of: player, vehicle, location, concept, event, relationship, song), "
                        "content, summary. Only include genuinely new or notable information. "
                        "If nothing notable was learned, return an empty list."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Player: {player_name}\nPlayer question: {question}\nBot response: {response}",
                },
            ]

            # pyrefly: ignore [no-matching-overload]
            completion = await self.openai_client_openrouter.chat.completions.create(
                model=DEFAULT_AI_MODEL,
                reasoning_effort="low",
                messages=messages,
            )

            if not completion.choices:
                return

            content = completion.choices[0].message.content or ""
            content = content.strip()
            if content.startswith("```json"):
                content = content.split("```json")[-1].split("```")[0].strip()
            elif content.startswith("```"):
                content = content.split("```")[-1].split("```")[0].strip()

            facts = json.loads(content) if content else []
            if not isinstance(facts, list):
                facts = []

            if facts:
                conversation_messages = [
                    {
                        "message": question,
                        "is_bot_response": False,
                        "timestamp": datetime.now().isoformat(),
                    },
                    {
                        "message": response,
                        "is_bot_response": True,
                        "timestamp": datetime.now().isoformat(),
                    },
                ]
                self._wiki_ingest.ingest_conversation(
                    player_id=player_id,
                    player_name=player_name,
                    messages=conversation_messages,
                    extracted_facts=facts,
                )
                log.info(
                    f"Wiki ingest completed for {player_name}: {len(facts)} fact(s)"
                )
        except Exception as e:
            log.warning(f"Wiki ingest failed for {player_name}: {e}")

    async def _handle_ingame_bot_command(
        self,
        player_name: str,
        player_id: str,
        discord_id: int | None,
        message: str,
        prev_messages: str = "",
        semantic_context: str = "",
    ):
        """Handle /bot command from in-game with full player context."""
        allowed, wait_time = self._ingame_bot_limiter.check()
        if not allowed:
            assert wait_time is not None
            await announce_in_game(
                self.bot.http_session,
                f"I need some rest, please wait {wait_time.seconds} seconds, or #ask-bot on discord instead!",
            )
            return

        # Build full context with semantic memories
        full_context = prev_messages
        if semantic_context:
            full_context = f"Relevant past conversations:\n{semantic_context}\n\nRecent messages:\n{prev_messages}"

        # Define feedback callback for in-game status updates
        async def ingame_status_fn(status_msg: str) -> None:
            await announce_in_game(self.bot.http_session, status_msg)

        try:
            # Now we have player_id, discord_id, message history, AND semantic context!
            answer = await self.ai_helper(
                player_name,
                message,
                full_context,
                ingame_feedback_fn=ingame_status_fn,
                player_id=player_id,
            )
            await announce_in_game(self.bot.http_session, answer[:520])

            # Store interaction in long-term memory + schedule wiki ingest
            await self._store_bot_interaction(
                player_id=player_id,
                player_name=player_name,
                question=message,
                response=answer,
                source="game_chat",
            )
        except Exception as e:
            log.error(f"Bot command error for {player_name}: {e}")
            await announce_in_game(self.bot.http_session, f"{e}")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author == self.bot.user:
            return

        message_channel = message.channel

        # 1. Auto-respond in #ask-bot channel or when @mentioned
        is_ask_bot_channel = message_channel.id == ASK_BOT_CHANNEL_ID
        is_mentioned = self.bot.user in message.mentions

        if (is_ask_bot_channel or is_mentioned) and message.content:
            # Strip the mention from the message content if present
            question = message.content
            if is_mentioned:
                question = (
                    question.replace(f"<@{self.bot.user.id}>", "")
                    .replace(f"<@!{self.bot.user.id}>", "")
                    .strip()
                )
            if not question:
                return

            # Gather channel history (same pattern as /bot slash command)
            prev = ""
            async for m in message_channel.history(limit=20):
                if m.id == message.id:
                    continue
                ms = f"### {m.author.display_name}:\n{m.content}\n"
                if m.reactions:
                    ms += "**Reactions**\n" + "\n".join(
                        [
                            f"{r.emoji}: {', '.join([u.display_name async for u in r.users()])}"
                            for r in m.reactions
                        ]
                    )
                prev = ms + "\n" + prev

            async with message_channel.typing():
                ans = await self.ai_helper_discord(
                    message.author.display_name,
                    question,
                    prev,
                    generic=is_mentioned,  # Use generic mode outside #ask-bot
                    player_id=str(message.author.id),
                )
            for line in split_markdown(ans):
                await message.reply(line, mention_author=False)

            await self._store_bot_interaction(
                player_id=str(message.author.id),
                player_name=message.author.display_name,
                question=question,
                response=ans,
                source="discord_mention",
            )
            return

        # Note: In-game /bot commands are now handled via SSE backend connection
        # which provides richer player context (player_id, discord_id, character_guid)

        # 2. Knowledge Update (Forum/News)
        # Forum channel knowledge update
        if isinstance(message_channel, discord.Thread) and message_channel.parent:
            if message_channel.parent.id == KNOWLEDGE_FORUM_CHANNEL_ID:
                # pyrefly: ignore [bad-argument-type]
                self.trigger_knowledge_reload(message_channel.parent)
            elif message_channel.parent.id == NEWS_CHANNEL_ID:
                await self.fetch_messages(
                    message_channel.parent,
                    "Latest News",
                    "news",
                    limit=None,
                    after=datetime.now() - timedelta(days=7),
                )
