"""
Game Knowledge Subagent for DJ Annie.

A lightweight agentic module that answers game-related questions using:
- Knowledge text (from the Discord knowledge forum, shared via knowledge.txt)
- Game database queries (SQLite)
- Backend API calls (subsidies, server commands)

This runs as an internal LLM call ("subagent") within the radio process,
so Annie's main prompt stays lean and radio-focused.
"""

import json
import logging
from typing import Optional

import aiohttp
from openai import AsyncOpenAI

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


async def _execute_tool(
    name: str,
    args: dict,
    http_session: aiohttp.ClientSession,
) -> str:
    """Execute a game knowledge tool call."""
    try:
        if name == "query_game_database":
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


async def ask_game_knowledge(
    openai_client: AsyncOpenAI,
    knowledge_text: str,
    game_schema: str,
    question: str,
    http_session: aiohttp.ClientSession,
    model: Optional[str] = None,
) -> str:
    """
    Subagent: answer a game question using knowledge context + tools.

    Makes a separate LLM call with the full knowledge blob and database
    tools, then returns the final answer text. This is designed to be
    called from Annie's tool executor when she encounters a game question.

    Args:
        openai_client: OpenAI-compatible async client (e.g. OpenRouter)
        knowledge_text: Full game knowledge text (from knowledge.txt)
        game_schema: Game database schema description for SQL tool
        question: The game-related question to answer
        http_session: aiohttp session for API calls
        model: LLM model to use (defaults to DEFAULT_AI_MODEL)

    Returns:
        Answer text from the subagent
    """
    model = model or DEFAULT_AI_MODEL

    system_message = (
        "You are a game knowledge assistant for Motor Town, an open world driving game, "
        "specifically in a dedicated server named 'ASEAN Motor Club'.\n"
        "Answer questions accurately and concisely using the knowledge and tools provided.\n"
        "Do not use markdown tables or emojis.\n\n"
        f"{knowledge_text}"
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
