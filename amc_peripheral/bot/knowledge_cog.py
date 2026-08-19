import json
import logging
import asyncio
import time
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
from amc_peripheral.bot import motorpedia
from amc_peripheral.memory.storage import MemoryStorage
from amc_peripheral.memory.retrieval import MemoryRetrieval
from amc_peripheral.memory.player_index import PlayerIndex
from amc_peripheral.wiki.memory import MemoryStore
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

        # API response cache for tool calls
        self._api_cache: dict[str, tuple[float, str]] = {}
        self._api_cache_ttl = 300  # 5 minutes

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

        # Player identity / alias index (name  -> canonical player resolution)
        try:
            self._player_index = PlayerIndex()
            log.info("Player index initialized")
        except Exception as e:
            log.warning(f"Player index unavailable: {e}")
            self._player_index = None

        # Durable agent memory (self + fact categories over the wiki)
        if self._wiki_storage and self._wiki_retrieval:
            self._memory_store = MemoryStore(
                self._wiki_storage, self._wiki_retrieval
            )
            log.info("Memory store initialized")
        else:
            self._memory_store = None
            log.warning("Memory store unavailable (no wiki storage/retrieval)")

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

        # Load game schema description for subagent (game_knowledge.py)
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
        player_id=None,
    ):
        now = datetime.now(self.local_tz)

        # Retrieve the speaker's long-term memory so the Discord /bot command,
        # #ask-bot, and @mention paths answer from the SAME ChromaDB memory that
        # the in-game /bot path uses (parity: write + recall across all entry points).
        semantic_context = ""
        if player_id:
            semantic_context = await self._retrieve_semantic_context(player_id, question)

        KNOWLEDGE_MAX_CHARS = 20000

        # Parallelize wiki index fetching
        wiki_index_str = await asyncio.to_thread(
            lambda: self._wiki_index.get_index() if self._wiki_index else ""
        )

        knowledge = self.knowledge_system_message
        if len(knowledge) > KNOWLEDGE_MAX_CHARS:
            knowledge = knowledge[:KNOWLEDGE_MAX_CHARS] + "\n\n[...continued — use wiki tools for full detail]"

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
                "When you learn something new and notable from a conversation, update your wiki using update_wiki. "
                "If the current speaker asks what you know about them, call get_my_wiki_profile (no arguments). "
                "For game-related questions, use the ask_game_knowledge tool instead of guessing.\n\n"
                "## Your Memory\n"
                "Your Standing Memory above is durable facts you chose to remember about yourself and the community — they are always in your context. "
                "Use the memory tool to persist a lasting fact (write), retrieve remembered facts (recall), browse (list), or remove one (delete). "
                "Remember facts that will still matter later; don't clutter memory with trivia.\n\n"
                f"{knowledge}"
            )

        if wiki_index_str:
            system_message += f"\n\n## Wiki Knowledge Index\n{wiki_index_str}"

        motorpedia_index = await asyncio.to_thread(motorpedia.get_index)
        if motorpedia_index:
            system_message += f"\n\n{motorpedia_index}"

        location_index = await asyncio.to_thread(backend_db.get_location_index)
        if location_index:
            system_message += f"\n\n{location_index}"

        memory_self = await asyncio.to_thread(self._get_memory_self_block)
        if memory_self:
            system_message += f"\n\n## Standing Memory\n{memory_self}"

        model = DEFAULT_AI_MODEL
        tools = self._get_shared_tool_definitions()

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

        messages = [
            {"role": "system", "content": system_message},
            {
                "role": "user",
                "content": f"## Context\nThe current date and time (in Bangkok GMT+7 timezone) is: {now.strftime('%A, %Y-%m-%d %H:%M')}",
            },
        ]
        if semantic_context:
            prev_messages_str = f"Relevant past conversations:\n{semantic_context}\n\nRecent messages:\n{prev_messages_str}" if prev_messages_str else f"Relevant past conversations:\n{semantic_context}"
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

        KNOWLEDGE_MAX_CHARS = 20000

        # Parallelize: active players, wiki index
        async def _fetch_active_players():
            async with self.bot.http_session.get(
                "https://server.aseanmotorclub.com/api/active_players/"
            ) as resp:
                return await resp.text()

        def _build_events_str():
            return "\n\n".join(
                [
                    f"## {event.name}\nDate/Time:{event.start_time.replace(tzinfo=ZoneInfo('UTC')).astimezone(self.local_tz).strftime('%A, %Y-%m-%d %H:%M')}\nLocation: {event.location}\n{event.description}"
                    for event in self.bot.guilds[0].scheduled_events
                    if event.start_time > now
                ]
            )

        players_task = asyncio.create_task(_fetch_active_players())
        wiki_index_task = asyncio.create_task(
            asyncio.to_thread(lambda: self._wiki_index.get_index() if self._wiki_index else "")
        )

        player_data, wiki_index_str = await asyncio.gather(
            players_task, wiki_index_task
        )
        events_str = _build_events_str()

        knowledge = self.knowledge_system_message
        if len(knowledge) > KNOWLEDGE_MAX_CHARS:
            knowledge = knowledge[:KNOWLEDGE_MAX_CHARS] + "\n\n[...continued — use wiki tools for full detail]"

        system_message = (
            "You are a helpful bot in Motor Town, an open world driving game, specifically in 'ASEAN Motor Club'.\n"
            "Answer in a short sentence or paragraph since the game only allows short messages, and avoid using newlines.\n"
            "Only use the following knowledge. Do not use markdown, tables, or emojis.\n"
            "For game-related questions, use the ask_game_knowledge tool instead of guessing.\n\n"
            + knowledge
        )

        if wiki_index_str:
            system_message += f"\n\n## Wiki Knowledge Index\n{wiki_index_str}"

        motorpedia_index = await asyncio.to_thread(motorpedia.get_index)
        if motorpedia_index:
            system_message += f"\n\n{motorpedia_index}"

        location_index = await asyncio.to_thread(backend_db.get_location_index)
        if location_index:
            system_message += f"\n\n{location_index}"

        memory_self = await asyncio.to_thread(self._get_memory_self_block)
        if memory_self:
            system_message += f"\n\n## Standing Memory\n{memory_self}"

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

        tools = self._get_shared_tool_definitions()

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

    def _get_shared_tool_definitions(self) -> list[dict]:
        """Return consolidated tool definitions for the LLM.

        3 tools instead of ~12: run (data queries), wiki (knowledge), discord (admin actions).
        """
        return [
            {
                "type": "function",
                "function": {
                    "name": "run",
                    "description": "Execute a data query. Verbs: vehicle <name>, cargo <name>, "
                                   "compare <v1,v2,...>, subsidies, commands, server (status/players), "
                                   "player <name or id> (who a player is, their aliases & nicknames), "
                                   "motorpedia <topic> (in-game help/encyclopedia article, e.g. 'town policy' or 'fuel management'), "
                                   "location <place> (map/delivery-point name → its 3D coordinates; answers 'where is X', e.g. 'location Oji Drilling'), "
                                   "song (currently playing), db <SQL> (SELECT only). "
                                   "Example: 'vehicle Tronko' returns specs.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "command": {
                                "type": "string",
                                "description": "The command string. First word = verb, rest = args. "
                                               "e.g. 'vehicle Tronko', 'cargo Steel Coil', 'compare Tronko, Maity', "
                                               "'subsidies', 'commands', 'server', 'song', 'db SELECT ...'",
                            }
                        },
                        "required": ["command"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "wiki",
                    "description": "Annie's personal wiki. Actions: search (semantic), read (by title), "
                                   "list (browse), write (create/update page), link (cross-reference), "
                                   "ask (game knowledge research), summary (stats), profile (your page).",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "action": {
                                "type": "string",
                                "enum": ["search", "read", "list", "write", "link", "ask", "summary", "profile"],
                                "description": "What to do with the wiki",
                            },
                            "query": {
                                "type": "string",
                                "description": "Search query or page title (for search/read/ask actions)",
                            },
                            "title": {
                                "type": "string",
                                "description": "Page title slug e.g. 'player:freeman' (for write action)",
                            },
                            "category": {
                                "type": "string",
                                "description": "Page category e.g. 'player', 'vehicle', 'concept' (for list/write)",
                            },
                            "content": {
                                "type": "string",
                                "description": "Page body content (for write action)",
                            },
                            "summary": {
                                "type": "string",
                                "description": "Brief summary (for write action)",
                            },
                            "from_page": {
                                "type": "string",
                                "description": "Source page slug (for link action)",
                            },
                            "to_page": {
                                "type": "string",
                                "description": "Target page slug (for link action)",
                            },
                            "link_type": {
                                "type": "string",
                                "description": "Link type (for link, default 'mentions')",
                            },
                            "n_results": {
                                "type": "integer",
                                "description": "Number of search results (search mode, default 3)",
                            },
                        },
                        "required": ["action"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "discord",
                    "description": "Discord server actions (only in Discord, not in-game). "
                                   "Actions: poll (create a poll), event (create a scheduled event).",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "action": {
                                "type": "string",
                                "enum": ["poll", "event"],
                                "description": "What Discord action to perform",
                            },
                            "question": {
                                "type": "string",
                                "description": "Poll question (for poll action)",
                            },
                            "options": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Poll options list (for poll action)",
                            },
                            "name": {
                                "type": "string",
                                "description": "Event name (for event action)",
                            },
                            "description": {
                                "type": "string",
                                "description": "Event description (for event action)",
                            },
                            "location": {
                                "type": "string",
                                "description": "Event location (for event action)",
                            },
                            "start_time": {
                                "type": "string",
                                "description": "Start time ISO format (for event action)",
                            },
                            "end_time": {
                                "type": "string",
                                "description": "End time ISO format (for event action)",
                            },
                            "timezone": {
                                "type": "string",
                                "description": "Timezone (for event action)",
                            },
                        },
                        "required": ["action"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "memory",
                    "description": "Annie's durable memory. Actions: write (persist a fact: title, "
                                   "content, category 'self' or 'fact', optional summary), recall "
                                   "(semantic search of remembered facts by query), list (browse "
                                   "memory, optional category), delete (forget a fact by title). "
                                   "'self' facts are always in your context; use them for standing "
                                   "facts about yourself and the community.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "action": {
                                "type": "string",
                                "enum": ["write", "recall", "list", "delete"],
                                "description": "Memory operation to perform",
                            },
                            "title": {
                                "type": "string",
                                "description": "Fact title (for write/delete)",
                            },
                            "content": {
                                "type": "string",
                                "description": "Fact content (for write)",
                            },
                            "category": {
                                "type": "string",
                                "enum": ["self", "fact"],
                                "description": "Memory category (write): 'self' (standing, always "
                                               "present) or 'fact' (recalled on demand). Default fact.",
                            },
                            "summary": {
                                "type": "string",
                                "description": "Optional short summary (for write)",
                            },
                            "query": {
                                "type": "string",
                                "description": "Search query (for recall)",
                            },
                            "n_results": {
                                "type": "integer",
                                "description": "Number of recall results (default 5)",
                            },
                        },
                        "required": ["action"],
                    },
                },
            },
        ]

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
        tool_feedback_sent = False
        last_tool_name: Optional[str] = None

        # IMMEDIATE feedback — before first LLM call.
        # Discord (interaction) already shows the "thinking" defer flag, so an
        # explicit "Working on it..." edit is redundant there. Only the in-game
        # path (no defer) gets the immediate status.
        if not interaction:
            await self._send_progress_feedback(
                message="Working on it...",
                interaction=interaction,
                ingame_feedback_fn=ingame_feedback_fn,
            )

        while iteration < max_iterations:
            iteration += 1
            elapsed = asyncio.get_event_loop().time() - start_time

            # --- Progress Feedback Logic ---
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

            # Call LLM with timeout and provider pinning
            try:
                # pyrefly: ignore [no-matching-overload]
                completion = await asyncio.wait_for(
                    self.openai_client_openrouter.chat.completions.create(
                        model=model,
                        messages=messages,
                        tools=tools,
                        tool_choice="auto",
                        extra_body={"provider": {"order": ["parasail", "novita"]}},
                    ),
                    timeout=90.0,
                )
            except asyncio.TimeoutError:
                return "I'm taking too long to think. Please try a simpler question."

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

                log.info(f"Tool call: {function_name}")

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
            "run": "Running your query...",
            "wiki": "Looking into that...",
            "discord": "Working on it...",
            "memory": "Checking my memory...",
            "manage_subsidy_rules_list": "Fetching subsidy rules...",
            "manage_subsidy_rule_create": "Creating subsidy rule...",
            "manage_subsidy_rule_update": "Updating subsidy rule...",
            "manage_subsidy_rule_deactivate": "Deactivating subsidy rule...",
            "manage_subsidy_rule_reorder": "Reordering subsidy rules...",
            "manage_job_config_get": "Fetching job configuration...",
            "manage_job_config_update": "Updating job configuration...",
            "query_game_database": "Crunching the numbers...",
        }
        return tool_messages.get(tool_name, f"Processing ({tool_name})...")

    async def _cached_api_get(self, url: str) -> str:
        now = time.monotonic()
        if url in self._api_cache:
            ts, data = self._api_cache[url]
            if now - ts < self._api_cache_ttl:
                return data
        async with self.bot.http_session.get(url) as resp:
            data = await resp.text()
            if resp.status != 200:
                return data
        self._api_cache[url] = (now, data)
        return data

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

    def _sync_player_wiki(self, profile: dict) -> int | None:
        """Ensure a canonical player profile page exists for the resolved player.

        Syncs the PlayerIndex alias/nickname facts into Annie's wiki (and indexes
        the page into ChromaDB) so later generic ``wiki`` recall agrees with the
        explicit ``player <name>`` lookup. Never raises; returns the wiki page id
        when a sync happened, else None.
        """
        if not self._wiki_storage or not self._wiki_ingest:
            return None
        return self._wiki_ingest.ingest_player_profile(profile)

    def _get_memory_self_block(self) -> str:
        """Annie's standing self-facts — always injected into her context.

        Mirrors Hermes' always-present memory: these are the durable 'who I am /
        how the community runs' facts that should be top-of-mind every turn (the
        ``self`` category in MemoryStore). Never raises.
        """
        if not self._memory_store:
            return ""
        try:
            return self._memory_store.self_block()
        except Exception as e:  # noqa: BLE001 - memory must never break a reply
            log.warning(f"Failed to build memory self block: {e}")
            return ""

    async def _execute_tool(
        self,
        function_name: str,
        arguments: dict,
        interaction: Optional[discord.Interaction] = None,
        player_id: Optional[str] = None,
    ) -> str:
        """Execute a knowledge bot tool — dispatches to run/wiki/discord/economy handlers."""
        try:
            if function_name == "run":
                return await self._execute_run(
                    arguments.get("command", ""), interaction=interaction
                )

            elif function_name == "wiki":
                return await self._execute_wiki(arguments, player_id=player_id)

            elif function_name == "discord":
                action = arguments.get("action", "")
                if action == "poll":
                    question = arguments.get("question") or ""
                    options = arguments.get("options") or []
                    return await actual_discord_poll_creator(
                        self.bot, question, options, None
                    )
                elif action == "event":
                    if (
                        not interaction
                        or not isinstance(interaction.user, discord.Member)
                        or not interaction.user.guild_permissions.administrator
                    ):
                        return "Error: You do not have permission to create scheduled events."
                    return await actual_discord_event_creator(
                        interaction.guild,
                        arguments.get("name"),
                        arguments.get("description"),
                        arguments.get("location"),
                        arguments.get("start_time"),
                        arguments.get("end_time"),
                        arguments.get("timezone"),
                    )
                else:
                    return f"Error: Unknown discord action '{action}'."

            elif function_name == "memory":
                return await self._execute_memory(arguments)

            # Economy tools still dispatched by EconomyCog
            elif function_name.startswith("manage_subsidy") or function_name.startswith(
                "manage_job_config"
            ):
                economy_cog = self.bot.get_cog("EconomyCog")
                if economy_cog:
                    return await economy_cog.execute_tool(
                        function_name, arguments, interaction
                    )
                return "Error: Economy management is not available."

            # Legacy query_game_database (kept for backward compat)
            elif function_name == "query_game_database":
                sql = arguments.get("sql")
                if not sql:
                    return "Database query failed: sql parameter required"
                result = game_db.execute_raw_query(sql)
                if "error" in result:
                    return f"Database query failed: {result['error']}"
                results = result.get("results", [])
                count = result.get("count", 0)
                truncated = result.get("truncated", False)
                if count == 0:
                    return "Query executed successfully but returned no results."
                formatted_output = f"Query returned {count} result(s):\n\n"
                formatted_output += json.dumps(results, indent=2)
                if truncated:
                    formatted_output += (
                        f"\n\nNote: Results were limited to {count} rows."
                    )
                return formatted_output

            else:
                return json.dumps({"error": f"Unknown function: {function_name}"})

        except Exception as e:
            log.error(f"Tool execution error ({function_name}): {e}", exc_info=True)
            return json.dumps({"error": f"Tool execution failed: {str(e)}"})

    async def _execute_run(self, command: str, interaction=None) -> str:
        """Execute a 'run' command by parsing the first word as verb."""
        if not command or not command.strip():
            return "Error: No command provided."

        parts = command.strip().split(maxsplit=1)
        verb = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        if verb == "vehicle":
            if not args:
                return "Error: Vehicle name required. Usage: vehicle <name>"
            result = await asyncio.to_thread(game_db.lookup_vehicle, args)
            if "error" in result:
                return result["error"]
            return json.dumps(result, indent=2)

        elif verb == "cargo":
            if not args:
                return "Error: Cargo name required. Usage: cargo <name>"
            result = await asyncio.to_thread(game_db.lookup_cargo, args)
            if "error" in result:
                return result["error"]
            return json.dumps(result, indent=2)

        elif verb == "compare":
            if not args:
                return "Error: Vehicle names required. Usage: compare <v1>, <v2>, ..."
            names = [n.strip() for n in args.split(",")]
            result = await asyncio.to_thread(game_db.compare_vehicles, names)
            if not result:
                return "No matching vehicles found."
            return json.dumps(result, indent=2)

        elif verb == "subsidies":
            raw = await self._cached_api_get(f"{BACKEND_API_URL}/api/subsidies/")
            try:
                data = json.loads(raw)
                return data.get(
                    "subsidies_text", "No subsidy information available."
                )
            except json.JSONDecodeError:
                return raw

        elif verb == "commands":
            raw = await self._cached_api_get(f"{BACKEND_API_URL}/api/commands/")
            try:
                commands_data = json.loads(raw)
            except json.JSONDecodeError:
                return "Failed to parse server commands."
            formatted = "Available server commands:\n\n"
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

        elif verb == "song":
            cache_key = "currently_playing_song"
            now = time.monotonic()
            if cache_key in self._api_cache:
                ts, data = self._api_cache[cache_key]
                if now - ts < 30:
                    return data
            from amc_peripheral.radio.radio_server import get_current_song
            current_song = await get_current_song(self.bot.http_session)
            result = (
                current_song
                or "No song is currently playing or unable to fetch song info."
            )
            self._api_cache[cache_key] = (now, result)
            return result

        elif verb == "db":
            if not args:
                return "Error: SQL query required. Usage: db <SELECT query>"
            result = await asyncio.to_thread(backend_db.execute_query, args)
            if "error" in result:
                return f"Backend database query failed: {result['error']}"
            return backend_db.format_results(result)

        elif verb == "server":
            return await self._cached_api_get(
                "https://server.aseanmotorclub.com/api/active_players/"
            )

        elif verb == "player":
            if not args:
                return "Error: Player name or ID required. Usage: player <name>"
            if not self._player_index:
                return "Player index is not available right now."
            results = await asyncio.to_thread(self._player_index.lookup, args)
            if not results:
                return f"No player found matching '{args}' in my memory."
            top = results[0]
            try:
                await asyncio.to_thread(self._sync_player_wiki, top)
            except Exception as e:  # noqa: BLE001 - best-effort sync, never block lookup
                log.warning(f"player wiki sync failed: {e}")
            return json.dumps(results, indent=2)

        elif verb == "motorpedia":
            return await asyncio.to_thread(motorpedia.lookup, args)

        elif verb == "location":
            return json.dumps(
                await asyncio.to_thread(backend_db.lookup_location, args),
                indent=2,
            )

        else:
            return (
                f"Error: Unknown command '{verb}'. "
                f"Available: vehicle, cargo, compare, subsidies, commands, song, db, server, motorpedia, player, location"
            )

    async def _execute_wiki(self, arguments: dict, player_id: Optional[str] = None) -> str:
        """Execute a wiki action (search, read, list, write, link, ask, summary, profile)."""
        action = arguments.get("action", "search")

        if action == "search":
            query = arguments.get("query", "")
            if not query:
                return "Error: 'query' is required for search."
            n_results = arguments.get("n_results", 3)
            if not self._wiki_retrieval:
                return "Wiki retrieval not available."
            results = await asyncio.to_thread(
                self._wiki_retrieval.search, query, n_results=n_results
            )
            if not results:
                return f"No wiki pages found for '{query}'."
            lines = []
            for r in results:  # pyrefly: ignore [bad-argument-type]
                lines.append(
                    f"- {r.get('title', 'Unknown')} ({r.get('category', 'unknown')}): "
                    f"{r.get('content', '')[:200]}..."
                )
            return "Wiki search results:\n" + "\n".join(lines)

        elif action == "read":
            query = arguments.get("query", "")
            if not query:
                return "Error: 'query' is required for read."
            if not self._wiki_storage:
                return "Wiki storage not available."
            page = self._wiki_storage.get_page_by_slug(query)
            if not page:
                page = self._wiki_storage.get_page_by_title(query)
            if not page:
                return f"No wiki page found for '{query}'."
            return (
                f"--- {page['title']} ---\n"
                f"Category: {page['category']}\n"
                f"Summary: {page.get('summary', '')}\n"
                f"Content:\n{page['content']}"
            )

        elif action == "list":
            category = arguments.get("category") or None
            keyword = arguments.get("query") or None
            limit = arguments.get("n_results", 10)
            if not self._wiki_storage:
                return "Wiki storage not available."
            pages = self._wiki_storage.list_pages(
                category=category, keyword=keyword, limit=limit
            )
            if not pages:
                return "No wiki pages found."
            lines = []
            for p in pages:  # pyrefly: ignore [bad-argument-type]
                lines.append(
                    f"- {p['title']} ({p['category']}): {p.get('summary', '')[:100]}"
                )
            return "Wiki pages:\n" + "\n".join(lines)

        elif action == "write":
            title = arguments.get("title", "")
            category = arguments.get("category", "concept")
            content = arguments.get("content", "")
            summary = arguments.get("summary", "")
            if not title or not content:
                return "Error: 'title' and 'content' are required for write action."
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
                    await asyncio.to_thread(
                        self._wiki_retrieval.index_page,
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
                    await asyncio.to_thread(
                        self._wiki_retrieval.index_page,
                        page_id=page_id,
                        title=refreshed["title"],
                        content=refreshed["content"],
                        category=refreshed["category"],
                        updated_at=refreshed["updated_at"],
                    )
                return f"Created wiki page '{title}'."

        elif action == "link":
            from_page = arguments.get("from_page", "")
            to_page = arguments.get("to_page", "")
            link_type = arguments.get("link_type", "mentions")
            if not from_page or not to_page:
                return "Error: 'from_page' and 'to_page' are required for link action."
            if not self._wiki_storage:
                return "Wiki storage not available."
            from_p = self._wiki_storage.get_page_by_slug(from_page) or self._wiki_storage.get_page_by_title(from_page)
            to_p = self._wiki_storage.get_page_by_slug(to_page) or self._wiki_storage.get_page_by_title(to_page)
            if not from_p:
                return f"From page '{from_page}' not found."
            if not to_p:
                return f"To page '{to_page}' not found."
            self._wiki_storage.add_link(from_p["id"], to_p["id"], link_type)
            return f"Linked '{from_p['title']}' -> '{to_p['title']}' ({link_type})."

        elif action == "ask":
            from amc_peripheral.radio.game_knowledge import ask_game_knowledge

            question = arguments.get("query", "")
            if not question:
                return "Error: 'query' is required for ask action."
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

        elif action == "summary":
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

        elif action == "profile":
            return self._get_player_wiki_summary(player_id or "")

        else:
            return f"Error: Unknown wiki action '{action}'. Available: search, read, list, write, link, ask, summary, profile"

    async def _execute_memory(self, arguments: dict) -> str:
        """Execute a memory action (write, recall, list, delete).

        Memory is Annie's durable, agent-writable fact layer over the wiki.
        'self' category facts are always injected into her context; 'fact'
        category facts are recalled on demand via semantic search.
        """
        if not self._memory_store:
            return "Memory is not available right now."

        action = arguments.get("action", "")
        try:
            if action == "write":
                title = (arguments.get("title") or "").strip()
                content = (arguments.get("content") or "").strip()
                category = arguments.get("category") or "fact"
                summary = (arguments.get("summary") or "").strip()
                if not title or not content:
                    return "Error: 'title' and 'content' are required for write."
                page_id = await asyncio.to_thread(
                    self._memory_store.write_fact, title, content, category, summary
                )
                return f"Remembered '{title}' ({category}) → page #{page_id}."

            elif action == "recall":
                query = arguments.get("query") or ""
                n = arguments.get("n_results", 5)
                if not query:
                    return "Error: 'query' is required for recall."
                results = await asyncio.to_thread(self._memory_store.recall, query, n)
                if not results:
                    return f"No memories found for '{query}'."
                lines = []
                for r in results:  # pyrefly: ignore [bad-argument-type]
                    lines.append(
                        f"- {r.get('title', 'Unknown')} ({r.get('category', 'unknown')}): "
                        f"{r.get('content', '')[:200]}..."
                    )
                return "Memory recall results:\n" + "\n".join(lines)

            elif action == "list":
                category = arguments.get("category") or None
                limit = arguments.get("n_results", 50)
                pages = await asyncio.to_thread(self._memory_store.list_facts, category, limit)
                if not pages:
                    return "No memories stored."
                lines = []
                for p in pages:  # pyrefly: ignore [bad-argument-type]
                    lines.append(
                        f"- {p['title']} ({p['category']}): {p.get('summary', '')[:100]}"
                    )
                return "Annie's memories:\n" + "\n".join(lines)

            elif action == "delete":
                title = arguments.get("title") or ""
                if not title:
                    return "Error: 'title' is required for delete."
                deleted = await asyncio.to_thread(self._memory_store.delete, title)
                if not deleted:
                    return f"No memory found for '{title}'."
                return f"Forgot '{title}'."

            else:
                return f"Error: Unknown memory action '{action}'. Available: write, recall, list, delete"

        except Exception as e:  # noqa: BLE001 - surface memory errors to the model
            log.warning(f"_execute_memory failed: {e}")
            return f"Memory operation failed: {e}"

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
                    [f"{r.emoji}: {r.count}" for r in m.reactions]
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

        task = asyncio.create_task(self._store_bot_interaction(
            player_id=str(interaction.user.id),
            player_name=interaction.user.display_name,
            question=question,
            response=ans,
            source="discord_slash",
        ))
        task.add_done_callback(
            lambda t: t.exception() and log.warning(f"_store_bot_interaction failed: {t.exception()}")
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
                    await asyncio.to_thread(
                        self._memory_retrieval.add_memory,
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

                semantic_context = await self._retrieve_semantic_context(
                    player_id, message
                )

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
                await asyncio.to_thread(
                    self._memory_retrieval.add_memory,
                    player_id=player_id,
                    player_name=player_name,
                    message=question,
                    source=source,
                    is_bot_response=False,
                )
                await asyncio.to_thread(
                    self._memory_retrieval.add_memory,
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

    async def _retrieve_semantic_context(
        self, player_id: str, query: str, n_results: int = 3
    ) -> str:
        """Retrieve a player's relevant past conversations from ChromaDB long-term memory.

        Shared by the in-game `/bot` path and the Discord `/bot`/`#ask-bot`/mention
        paths so every entry point answers from the *same* memory the bot writes to.
        Returns an empty string when retrieval is unavailable or nothing matches.
        """
        if not self._memory_retrieval or not player_id:
            return ""
        try:
            memories = await asyncio.to_thread(
                self._memory_retrieval.retrieve_relevant,
                player_id=player_id,
                query=query,
                n_results=n_results,
            )
            if not memories:
                return ""
            return "\n".join(
                f"[{m['timestamp'][:10]}] {m['player_name']}: {m['message']}"
                for m in memories
            )
        except Exception as e:
            log.warning(f"Failed to retrieve semantic memories: {e}")
            return ""

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

            # Store interaction in long-term memory + schedule wiki ingest (fire-and-forget)
            task = asyncio.create_task(self._store_bot_interaction(
                player_id=player_id,
                player_name=player_name,
                question=message,
                response=answer,
                source="game_chat",
            ))
            task.add_done_callback(
                lambda t: t.exception() and log.warning(f"_store_bot_interaction failed: {t.exception()}")
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
                        [f"{r.emoji}: {r.count}" for r in m.reactions]
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

            task = asyncio.create_task(self._store_bot_interaction(
                player_id=str(message.author.id),
                player_name=message.author.display_name,
                question=question,
                response=ans,
                source="discord_mention",
            ))
            task.add_done_callback(
                lambda t: t.exception() and log.warning(f"_store_bot_interaction failed: {t.exception()}")
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
