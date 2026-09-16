"""
Game Knowledge Subagent for DJ Annie.

A lightweight agentic module that answers game-related questions using:
- Annie's wiki (WikiStorage + WikiRetrieval + WikiIndex)
- The game knowledge wiki (wiki_kb — public DokuWiki page store: vehicles,
  cargos, parts, delivery points, cargo spaces/types)
- Backend API calls (subsidies, server commands)
- The AMC backend database (query_amc_database) — ONLY for player/server
  operations data (players, deliveries, jobs), never game knowledge.

This runs as an internal LLM call ("subagent") within the radio process,
so Annie's main prompt stays lean and radio-focused.

Note: the tool names (`lookup_knowledge`, `list_knowledge`, `save_knowledge`,
`remove_knowledge`) are preserved from the legacy KnowledgeStore era so that
the subagent's system prompt wording stays stable. Internally, every tool
now routes through the wiki.
"""

import asyncio
import json
import logging
import re
from typing import Optional

import aiohttp
from openai import AsyncOpenAI

from amc_peripheral.settings import BACKEND_API_URL, DEFAULT_AI_MODEL
from amc_peripheral.wiki.storage import WikiStorage
from amc_peripheral.wiki.retrieval import WikiRetrieval
from amc_peripheral.wiki.index import WikiIndex

log = logging.getLogger(__name__)

# Max iterations for the agentic tool loop
MAX_ITERATIONS = 5


def _build_tools(game_knowledge_guide: str) -> list[dict]:
    """Build tool definitions for the game knowledge subagent.

    `game_knowledge_guide` is the wiki_kb page-store guide text (legacy param
    name `game_schema`). It is no longer interpolated into a SQL tool
    description — the SQL tool is a fixed player/server-ops tool.
    """
    tools = [
        {
            "type": "function",
            "function": {
                "name": "lookup_vehicle",
                "description": "Look up detailed specs for a vehicle by name. Returns type, cost, weight, engine, cargo space, drivetrain, and capabilities.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Vehicle name or partial name (e.g. 'Tronko', 'Gosan')",
                        }
                    },
                    "required": ["name"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "lookup_cargo",
                "description": "Look up detailed specs for a cargo type by name. Returns weight, payment, compatible vehicle types, and production chains.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Cargo name or partial name (e.g. 'Steel Coil', 'SmallBox')",
                        }
                    },
                    "required": ["name"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "compare_vehicles",
                "description": "Compare multiple vehicles side-by-side. Returns a table of key specs for each vehicle.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "names": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of vehicle names to compare (e.g. ['Tronko', 'Maity'])",
                        }
                    },
                    "required": ["names"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "lookup_knowledge",
                "description": (
                    "Search BOTH knowledge sources for a topic: the game wiki "
                    "(vehicles, cargo, parts, delivery points — authoritative game "
                    "facts) and the DJ wiki (community/radio knowledge). Returns "
                    "labeled results from each. For full game-wiki details follow "
                    "up with lookup_vehicle / lookup_cargo / compare_vehicles. "
                    "You can call this multiple times for different queries."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "topic": {
                            "type": "string",
                            "description": "Topic name or keyword to search for",
                        }
                    },
                    "required": ["topic"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "list_knowledge",
                "description": (
                    "List wiki pages, optionally filtered by category. "
                    "Categories include: vehicle, cargo, guide, location, concept, "
                    "event, player, relationship, song, etc."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "type_filter": {
                            "type": "string",
                            "description": "Optional category filter (e.g., 'vehicle', 'guide')",
                        }
                    },
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "save_knowledge",
                "description": (
                    "Create or update a wiki page. Use this to record useful "
                    "information learned from conversations, tips from players, "
                    "or corrections to existing knowledge. "
                    "Key format: '{type}:{id}' e.g., 'vehicle:Gosan_G7', 'guide:delivery-tips'."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "key": {
                            "type": "string",
                            "description": "Knowledge key in '{type}:{id}' format",
                        },
                        "content": {
                            "type": "string",
                            "description": "The knowledge content to store",
                        },
                    },
                    "required": ["key", "content"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "remove_knowledge",
                "description": (
                    "Remove a wiki page by key. "
                    "Only use this for incorrect or outdated information."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "key": {
                            "type": "string",
                            "description": "Knowledge key to remove",
                        }
                    },
                    "required": ["key"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "query_amc_database",
                "description": (
                    "Query the AMC backend database (PostgreSQL) with SQL. "
                    "Use this for PLAYER and SERVER OPERATIONS data only: "
                    "players, player deliveries/jobs, delivery points, "
                    "subsidies, server commands, events. "
                    "Do NOT use this for game knowledge (vehicle specs, cargo "
                    "specs, parts, game mechanics) — the backend database has "
                    "NO game data tables. For game facts use lookup_vehicle, "
                    "lookup_cargo, lookup_knowledge or search_wiki instead. "
                    "Supports SELECT with GROUP BY, ORDER BY, JOINs, "
                    "aggregates (COUNT, AVG, SUM, MIN, MAX). Results are "
                    "limited to 100 rows. Database is read-only."
                ),
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
    return tools


def _lookup_knowledge(
    topic: str,
    wiki_storage: WikiStorage,
    wiki_retrieval: Optional[WikiRetrieval] = None,
) -> str:
    """Search BOTH knowledge sources for a topic query.

    - Game wiki (public DokuWiki corpus via ``wiki_kb``): authoritative for
      game facts — vehicles, cargo, parts, delivery points. Lexical
      full-phrase search; recall gaps are closed by the caller retrying a
      different phrasing (by design — no query expansion).
    - DJ wiki (``wiki_storage`` + optional ``wiki_retrieval``): Annie's
      community/radio knowledge. Substring matches (fast, exact) plus
      semantic matches from ChromaDB (broader recall), de-duplicated by
      page id.

    Both sections are returned labeled so the model can tell curated game
    data from community memory, with the ``lookup_vehicle``/``lookup_cargo``
    verbs named for full game-wiki details.
    """
    if not topic:
        return "No knowledge available."

    found: dict[int, dict] = {}

    # Substring results first
    for page in wiki_storage.search_by_substring(topic, limit=10):
        found[page["id"]] = page

    # Semantic results enrich recall when available
    if wiki_retrieval is not None:
        try:
            for result in wiki_retrieval.search(topic, n_results=5):
                page_id = result.get("page_id")
                if page_id is None or page_id in found:
                    continue
                # ChromaDB may not have full content in sync with storage —
                # prefer the storage record if it exists, otherwise fall
                # back to the retrieval snapshot.
                page = wiki_storage.get_page_by_id(page_id)
                if page is None:
                    page = {
                        "id": page_id,
                        "title": result.get("title", "Unknown"),
                        "category": result.get("category", "concept"),
                        "content": result.get("content", ""),
                        "summary": "",
                    }
                found[page_id] = page
        except Exception as e:  # noqa: BLE001
            log.warning(f"Semantic wiki search failed for '{topic}': {e}")

    sections: list[str] = []

    # Game wiki first — it is the authoritative source for game facts.
    try:
        from amc_peripheral.bot import wiki_kb

        game_hits = wiki_kb.search_wiki(topic).get("results", [])
    except Exception as e:  # noqa: BLE001
        log.warning(f"Game wiki search failed for '{topic}': {e}")
        game_hits = []

    if game_hits:
        lines = [f"[Game wiki] pages matching '{topic}':"]
        for hit in game_hits:
            lines.append(f"- [{hit['category']}] {hit['name']} (slug: {hit['slug']})")
        lines.append(
            "Use lookup_vehicle / lookup_cargo / compare_vehicles to get full "
            "details for a game-wiki hit."
        )
        sections.append("\n".join(lines))
    else:
        sections.append(
            f"[Game wiki] no pages matched '{topic}'. If it is a vehicle or "
            "cargo name, try lookup_vehicle / lookup_cargo directly, or "
            "retry with a shorter/different phrasing."
        )

    if found:
        parts = []
        for page in found.values():
            parts.append(f"### {page['title']}\n{page.get('content', '')}")
        sections.append("[DJ wiki] (community/radio knowledge):\n" + "\n\n".join(parts))
    else:
        sections.append(f"[DJ wiki] no pages matched '{topic}'.")

    return "\n\n".join(sections)


async def _execute_tool(
    name: str,
    args: dict,
    http_session: aiohttp.ClientSession,
    wiki_storage: Optional[WikiStorage] = None,
    wiki_retrieval: Optional[WikiRetrieval] = None,
) -> str:
    """Execute a game knowledge tool call."""
    try:
        if name == "lookup_knowledge":
            if not wiki_storage:
                return "Wiki not available."
            return await asyncio.to_thread(
                _lookup_knowledge, args.get("topic", ""), wiki_storage, wiki_retrieval
            )

        elif name == "list_knowledge":
            if not wiki_storage:
                return "Wiki not available."
            type_filter = args.get("type_filter")
            pages = await asyncio.to_thread(
                wiki_storage.list_pages, category=type_filter, limit=500
            )
            if not pages:
                return f"No entries found{f' for category {type_filter!r}' if type_filter else ''}."
            titles = sorted(p["title"] for p in pages)
            return f"Wiki pages ({len(titles)}):\n" + "\n".join(
                f"- {t}" for t in titles
            )

        elif name == "save_knowledge":
            if not wiki_storage:
                return "Wiki not available."
            key = args.get("key", "")
            content = args.get("content", "")
            if not key or not content:
                return "Error: both 'key' and 'content' are required."
            if ":" not in key:
                return "Error: key must be in '{type}:{id}' format, e.g., 'vehicle:Gosan_G7'."

            category = key.split(":", 1)[0]
            title = key

            existing = wiki_storage.get_page_by_slug(title)
            if existing:
                wiki_storage.update_page(
                    existing["id"],
                    content=content,
                    summary=existing.get("summary", "") or f"Wiki entry {key}",
                )
                page_id = existing["id"]
                log.info(f"Wiki page updated by subagent: {key} ({len(content)} chars)")
                action = "Updated"
            else:
                page_id = wiki_storage.create_page(
                    title=title,
                    category=category,
                    content=content,
                    summary=f"Wiki entry {key}",
                )
                log.info(f"Wiki page created by subagent: {key} ({len(content)} chars)")
                action = "Saved"

            wiki_storage.add_source(page_id, "subagent", key)

            if wiki_retrieval is not None:
                refreshed = wiki_storage.get_page_by_id(page_id)
                if refreshed:
                    try:
                        wiki_retrieval.index_page(
                            page_id=page_id,
                            title=refreshed["title"],
                            content=refreshed["content"],
                            category=refreshed["category"],
                            updated_at=refreshed["updated_at"],
                        )
                    except Exception as e:
                        log.warning(f"Wiki re-index failed for {key}: {e}")

            return f"{action} knowledge entry '{key}'."

        elif name == "remove_knowledge":
            if not wiki_storage:
                return "Wiki not available."
            key = args.get("key", "")
            if not key:
                return "Error: 'key' is required."
            existing = wiki_storage.get_page_by_slug(key)
            if not existing:
                return f"No entry found for key '{key}'."

            if wiki_retrieval is not None:
                try:
                    wiki_retrieval.remove_page(existing["id"])
                except Exception as e:
                    log.warning(f"Wiki retrieval remove failed for {key}: {e}")

            if wiki_storage.delete_page_by_slug(key):
                log.info(f"Wiki page removed by subagent: {key}")
                return f"Removed knowledge entry '{key}'."
            return f"No entry found for key '{key}'."

        elif name == "query_amc_database":
            from amc_peripheral.bot import backend_db

            sql = args.get("sql", "")
            result = backend_db.execute_query(sql)

            if "error" in result:
                return f"Database query failed: {result['error']}"

            results = result.get("results", [])
            count = result.get("count", 0)
            truncated = result.get("truncated", False)

            if count == 0:
                return "Query executed successfully but returned no results."

            output = f"Query returned {count} result(s):\n\n"
            output += json.dumps(results, indent=2)
            if truncated:
                output += f"\n\nNote: Results were limited to {count} rows."
            return output

        elif name == "lookup_vehicle":
            from amc_peripheral.bot import wiki_kb

            vehicle_name = args.get("name", "")
            if not vehicle_name:
                return "Error: 'name' is required."
            result = await asyncio.to_thread(wiki_kb.lookup_vehicle, vehicle_name)
            if "error" in result:
                return result["error"]
            return json.dumps(result, indent=2)

        elif name == "lookup_cargo":
            from amc_peripheral.bot import wiki_kb

            cargo_name = args.get("name", "")
            if not cargo_name:
                return "Error: 'name' is required."
            result = await asyncio.to_thread(wiki_kb.lookup_cargo, cargo_name)
            if "error" in result:
                return result["error"]
            return json.dumps(result, indent=2)

        elif name == "compare_vehicles":
            from amc_peripheral.bot import wiki_kb

            names = args.get("names", [])
            if not names:
                return "Error: 'names' list is required."
            result = await asyncio.to_thread(wiki_kb.compare_vehicles, names)
            if not result:
                return "No matching vehicles found."
            return json.dumps(result, indent=2)

        elif name == "get_current_subsidies":
            async with http_session.get(f"{BACKEND_API_URL}/api/subsidies/") as resp:
                data = await resp.json()
                return data.get("subsidies_text", "No subsidy information available.")

        elif name == "get_server_commands":
            async with http_session.get(f"{BACKEND_API_URL}/api/commands/") as resp:
                if resp.status != 200:
                    return "Failed to fetch server commands."
                commands_data = await resp.json()

                from itertools import groupby

                formatted = "Available server commands:\n\n"
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

        return f"Unknown tool: {name}"

    except Exception as e:
        log.error(f"Game knowledge tool error ({name}): {e}", exc_info=True)
        return f"Tool error: {e}"


def _extract_heading(content: str) -> str:
    """Extract the first markdown heading from content, or first non-empty line."""
    for line in content.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        # Match markdown headings
        match = re.match(r"^#{1,4}\s+(.+)", line)
        if match:
            return match.group(1).strip()
        # Use first non-empty line as fallback
        return line[:80]
    return "Untitled"


async def ask_game_knowledge(
    openai_client: AsyncOpenAI,
    wiki_storage: WikiStorage,
    wiki_retrieval: Optional[WikiRetrieval],
    wiki_index: Optional[WikiIndex],
    game_schema: str,
    question: str,
    http_session: aiohttp.ClientSession,
    model: Optional[str] = None,
) -> str:
    """
    Subagent: answer a game question using the wiki + tools.

    Uses a compact wiki index in the system prompt and tools
    for targeted retrieval, database queries, and knowledge management.

    Args:
        openai_client: OpenAI-compatible async client (e.g. OpenRouter)
        wiki_storage: WikiStorage handle
        wiki_retrieval: Optional WikiRetrieval handle for semantic search
        wiki_index: Optional WikiIndex handle for compact prompt context
        game_schema: Legacy name; the game-knowledge guide for tool descriptions
            (wiki_kb page-store description, not a SQL schema)
        question: The game-related question to answer
        http_session: aiohttp session for API calls
        model: LLM model to use (defaults to DEFAULT_AI_MODEL)

    Returns:
        Answer text from the subagent
    """
    model = model or DEFAULT_AI_MODEL

    knowledge_index = wiki_index.get_index() if wiki_index is not None else ""
    system_message = (
        "You are a game knowledge assistant for Motor Town, an open world driving game, "
        "specifically in a dedicated server named 'ASEAN Motor Club'.\n"
        "Answer questions accurately and concisely using the tools provided.\n"
        "ALWAYS use lookup_knowledge first to retrieve relevant information before answering.\n"
        "Game facts (vehicles, cargo, parts, game mechanics) come ONLY from the wiki "
        "tools (lookup_vehicle, lookup_cargo, compare_vehicles, lookup_knowledge) — "
        "never from SQL. The query_amc_database tool is for PLAYER and SERVER data "
        "(players, deliveries, jobs) and contains NO game tables.\n"
        "You can save useful knowledge learned from conversations using save_knowledge.\n"
        "Do not use markdown tables or emojis.\n\n"
        f"{knowledge_index}"
    )

    messages: list[dict] = [
        {"role": "system", "content": system_message},
        {"role": "user", "content": question},
    ]

    tools = _build_tools(game_schema) if game_schema else []
    for _ in range(MAX_ITERATIONS):
        # pyrefly: ignore [no-matching-overload]
        completion = await openai_client.chat.completions.create(
            model=model,
            messages=messages,
            tools=tools if tools else None,
            tool_choice="auto" if tools else None,
            extra_body={"provider": {"order": ["parasail", "novita"]}},
        )

        response = completion.choices[0].message if completion.choices else None
        if not response:
            return "Could not get an answer about that."

        if not response.tool_calls:
            return response.content or "No answer available."

        messages.append(response)

        for tool_call in response.tool_calls:
            result = await _execute_tool(
                tool_call.function.name,
                json.loads(tool_call.function.arguments),
                http_session,
                wiki_storage=wiki_storage,
                wiki_retrieval=wiki_retrieval,
            )
            messages.append(
                {
                    "tool_call_id": tool_call.id,
                    "role": "tool",
                    "name": tool_call.function.name,
                    "content": result,
                }
            )

    return "Could not resolve the question within the allowed iterations."
