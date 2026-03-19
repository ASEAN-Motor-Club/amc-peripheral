"""
Game Knowledge Subagent for DJ Annie.

A lightweight agentic module that answers game-related questions using:
- KnowledgeStore (agent-managed JSON knowledge base)
- Game database queries (SQLite)
- Backend API calls (subsidies, server commands)

This runs as an internal LLM call ("subagent") within the radio process,
so Annie's main prompt stays lean and radio-focused.
"""

import json
import logging
import re
from typing import Optional

import aiohttp
from openai import AsyncOpenAI

from amc_peripheral.knowledge_store import KnowledgeStore
from amc_peripheral.settings import BACKEND_API_URL, DEFAULT_AI_MODEL

log = logging.getLogger(__name__)

# Max iterations for the agentic tool loop
MAX_ITERATIONS = 5


def _build_tools(game_schema: str) -> list[dict]:
    """Build tool definitions for the game knowledge subagent."""
    tools = [
        {
            "type": "function",
            "function": {
                "name": "lookup_knowledge",
                "description": (
                    "Search the knowledge base for information about a topic. "
                    "Pass a keyword or topic name. "
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
                    "List all knowledge entries, optionally filtered by type. "
                    "Types include: vehicle, cargo, part, guide, location, mechanic, etc."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "type_filter": {
                            "type": "string",
                            "description": "Optional type prefix to filter by (e.g., 'vehicle', 'guide')",
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
                    "Save or update a knowledge entry. Use this to record useful "
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
                    "Remove a knowledge entry by key. "
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
                "name": "query_game_database",
                "description": f"""Query MotorTown game database with SQL.

{game_schema}

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
    return tools


def _lookup_knowledge(topic: str, store: KnowledgeStore) -> str:
    """Search knowledge store for entries matching a topic query."""
    if not topic:
        return "No knowledge available."

    results = store.search(topic)
    if not results:
        # Show available types to guide the model
        keys = store.list_keys()
        if not keys:
            return "Knowledge store is empty."
        available = ", ".join(keys[:20])
        if len(keys) > 20:
            available += f", ... (+{len(keys) - 20} more)"
        return f"No knowledge found for '{topic}'. Available keys: {available}"

    parts = []
    for key, content in results:
        parts.append(f"### {key}\n{content}")
    return "\n\n".join(parts)


async def _execute_tool(
    name: str,
    args: dict,
    http_session: aiohttp.ClientSession,
    store: KnowledgeStore | None = None,
) -> str:
    """Execute a game knowledge tool call."""
    try:
        if name == "lookup_knowledge":
            if not store:
                return "Knowledge store not available."
            return _lookup_knowledge(args.get("topic", ""), store)

        elif name == "list_knowledge":
            if not store:
                return "Knowledge store not available."
            type_filter = args.get("type_filter")
            keys = store.list_keys(type_filter)
            if not keys:
                return f"No entries found{f' for type {type_filter!r}' if type_filter else ''}."
            return f"Knowledge entries ({len(keys)}):\n" + "\n".join(f"- {k}" for k in sorted(keys))

        elif name == "save_knowledge":
            if not store:
                return "Knowledge store not available."
            key = args.get("key", "")
            content = args.get("content", "")
            if not key or not content:
                return "Error: both 'key' and 'content' are required."
            if ":" not in key:
                return "Error: key must be in '{type}:{id}' format, e.g., 'vehicle:Gosan_G7'."
            store.save(key, content, source="agent")
            log.info(f"Knowledge saved: {key} ({len(content)} chars)")
            return f"Saved knowledge entry '{key}'."

        elif name == "remove_knowledge":
            if not store:
                return "Knowledge store not available."
            key = args.get("key", "")
            if not key:
                return "Error: 'key' is required."
            if store.remove(key):
                log.info(f"Knowledge removed: {key}")
                return f"Removed knowledge entry '{key}'."
            return f"No entry found for key '{key}'."

        elif name == "query_game_database":
            from amc_peripheral.bot import game_db

            sql = args.get("sql", "")
            result = game_db.execute_raw_query(sql)

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

        elif name == "get_current_subsidies":
            async with http_session.get(
                f"{BACKEND_API_URL}/api/subsidies/"
            ) as resp:
                data = await resp.json()
                return data.get(
                    "subsidies_text", "No subsidy information available."
                )

        elif name == "get_server_commands":
            async with http_session.get(
                f"{BACKEND_API_URL}/api/commands/"
            ) as resp:
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
    knowledge_store: KnowledgeStore,
    game_schema: str,
    question: str,
    http_session: aiohttp.ClientSession,
    model: Optional[str] = None,
) -> str:
    """
    Subagent: answer a game question using knowledge store + tools.

    Uses a compact knowledge index in the system prompt and tools
    for targeted retrieval, database queries, and knowledge management.

    Args:
        openai_client: OpenAI-compatible async client (e.g. OpenRouter)
        knowledge_store: Agent-managed knowledge store
        game_schema: Game database schema description for SQL tool
        question: The game-related question to answer
        http_session: aiohttp session for API calls
        model: LLM model to use (defaults to DEFAULT_AI_MODEL)

    Returns:
        Answer text from the subagent
    """
    model = model or DEFAULT_AI_MODEL

    knowledge_index = knowledge_store.build_index()
    system_message = (
        "You are a game knowledge assistant for Motor Town, an open world driving game, "
        "specifically in a dedicated server named 'ASEAN Motor Club'.\n"
        "Answer questions accurately and concisely using the tools provided.\n"
        "ALWAYS use lookup_knowledge first to retrieve relevant information before answering.\n"
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
            reasoning_effort="medium",
            messages=messages,
            tools=tools if tools else None,
            tool_choice="auto" if tools else None,
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
                store=knowledge_store,
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
