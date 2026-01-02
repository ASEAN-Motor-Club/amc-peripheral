"""
JARVIS Dev Bot Cog - LLM-powered codebase assistant.

Handles @mentions, tool calling, and guide generation.
"""

import json
import logging
from typing import Any, Optional
import discord
from discord.ext import commands
from openai import AsyncOpenAI
from amc_peripheral.settings import (
    OPENAI_API_KEY_OPENROUTER,
    JARVIS_REPO_PATH,
    JARVIS_AI_MODEL,
    JARVIS_ALLOWED_CHANNELS,
)
from amc_peripheral.utils.text_utils import split_markdown
from .codebase_tools import CodebaseTools

log = logging.getLogger(__name__)


class DevBotCog(commands.Cog):
    """JARVIS cog providing codebase assistance via LLM with tool calling."""

    def __init__(self, bot):
        self.bot = bot
        self.repo_path = JARVIS_REPO_PATH
        self.ai_model = JARVIS_AI_MODEL
        self.allowed_channels = JARVIS_ALLOWED_CHANNELS

        # Initialize OpenAI client
        self.openai_client = AsyncOpenAI(
            api_key=OPENAI_API_KEY_OPENROUTER,
            base_url="https://openrouter.ai/api/v1",
        )

        # Initialize codebase tools
        self.tools: Optional[CodebaseTools] = None
        try:
            self.tools = CodebaseTools(self.repo_path)  # type: ignore[arg-type]
            log.info(f"JARVIS initialized with repo path: {self.repo_path}")
        except Exception as e:
            log.error(f"Failed to initialize codebase tools: {e}")
            self.tools = None

        # Tool definitions for LLM
        self.tool_definitions: list[dict[str, Any]] = [
            {
                "type": "function",
                "function": {
                    "name": "search_files",
                    "description": "Search for files in the monorepo by name or glob pattern. Use this to find files when you know part of the filename.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "pattern": {
                                "type": "string",
                                "description": "Glob pattern or filename to search for (e.g., 'flake.nix', '*.py', '**/mods.nix')",
                            },
                            "max_results": {
                                "type": "integer",
                                "description": "Maximum number of results (default 20)",
                                "default": 20,
                            },
                        },
                        "required": ["pattern"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": "Read contents of a specific file from the monorepo. You can optionally specify line ranges to read only part of the file.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "description": "Relative path to file from repo root",
                            },
                            "start_line": {
                                "type": "integer",
                                "description": "Start line number (1-indexed, inclusive)",
                            },
                            "end_line": {
                                "type": "integer",
                                "description": "End line number (1-indexed, inclusive)",
                            },
                        },
                        "required": ["path"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "grep_search",
                    "description": "Search for text patterns or code snippets in files. Use this to find where specific functions, variables, or configuration values are defined or used.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Text or code pattern to search for",
                            },
                            "path": {
                                "type": "string",
                                "description": "Directory or file path to search in (default: '.' for entire repo)",
                                "default": ".",
                            },
                            "max_results": {
                                "type": "integer",
                                "description": "Maximum number of results (default 30)",
                                "default": 30,
                            },
                        },
                        "required": ["query"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "list_directory",
                    "description": "List files and subdirectories in a directory. Useful for exploring the structure of the codebase.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "description": "Relative path to directory (default: '.' for root)",
                                "default": ".",
                            },
                            "recursive": {
                                "type": "boolean",
                                "description": "Whether to list recursively (default: False)",
                                "default": False,
                            },
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "nix_hash_url",
                    "description": "Calculate the Nix hash for a URL. Returns an SRI hash suitable for use in fetchzip, fetchurl, or other Nix fetchers. Use this when you need to add a mod or package that downloads from a URL.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "url": {
                                "type": "string",
                                "description": "The URL to fetch and calculate the hash for (e.g., 'https://mod.io/download/...')",
                            },
                            "unpack": {
                                "type": "boolean",
                                "description": "Whether to unpack the archive before hashing (use True for fetchzip, False for fetchurl). Default: True",
                                "default": True,
                            },
                        },
                        "required": ["url"],
                    },
                },
            },
        ]

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Handle messages that mention JARVIS."""
        # Ignore own messages
        if message.author == self.bot.user:
            return

        # Check if bot was mentioned
        if self.bot.user not in message.mentions:
            return

        # Check channel restrictions
        if self.allowed_channels and message.channel.id not in self.allowed_channels:
            await message.channel.send(
                "I can only respond in specific channels. Please @mention me in an allowed channel."
            )
            return

        # Check if tools are available
        if self.tools is None:
            await message.channel.send(
                "❌ I'm having trouble accessing the codebase right now. Please check my configuration."
            )
            return

        # Process the query
        await self._handle_query(message)

    async def _handle_query(self, message: discord.Message):
        """Process a user query with LLM and tools."""
        try:
            # Show typing indicator
            async with message.channel.typing():
                # Extract query (remove bot mention)
                query = message.content
                for mention in message.mentions:
                    query = query.replace(f"<@{mention.id}>", "").strip()
                    query = query.replace(f"<@!{mention.id}>", "").strip()

                if not query:
                    await message.reply(
                        "How can I help you with the codebase? Ask me anything about the AMC server project!"
                    )
                    return

                # Build system message
                system_message = """You are JARVIS (Just A Rather Very Intelligent System), a helpful AI assistant for the ASEAN Motor Club server project.

Your role is to help developers understand and work with the monorepo codebase. You have access to tools that let you:
- Search for files by name or pattern
- Read file contents
- Search for text patterns in code
- List directory structures

When asked a question:
1. Use your tools to explore the codebase and find relevant information
2. Provide clear, actionable guidance with code examples
3. Reference specific files and line numbers when relevant
4. Format your responses in markdown for readability

The monorepo contains:
- motortown-server-flake: Game server configurations and Lua mods
- amc-peripheral: Discord bots (this is me!) and radio service
- amc-backend: Backend API services
- eco-server, necesse-server: Other game servers
- flake.nix: NixOS configuration for all services

Be concise but thorough. Format code blocks with appropriate language tags."""

                # Build messages for LLM
                messages = [
                    {"role": "system", "content": system_message},
                    {
                        "role": "user",
                        "content": f"User {message.author.display_name} asks: {query}",
                    },
                ]

                # Call LLM with tools
                response = await self._call_llm_with_tools(messages)

                # Send response (split if too long)
                for chunk in split_markdown(response):
                    await message.reply(chunk)

        except Exception as e:
            log.error(f"Error handling JARVIS query: {e}", exc_info=True)
            await message.reply(
                f"❌ Sorry, I encountered an error processing your request: {str(e)}"
            )

    async def _call_llm_with_tools(self, messages: list[dict]) -> str:
        """
        Call LLM with tool support and handle tool calls iteratively.

        Args:
            messages: Conversation messages

        Returns:
            Final response text
        """
        max_iterations = 20  # Prevent infinite loops
        iteration = 0

        while iteration < max_iterations:
            iteration += 1

            # Call LLM
            # pyrefly: ignore [no-matching-overload]
            completion = await self.openai_client.chat.completions.create(
                model=self.ai_model,
                messages=messages,
                tools=self.tool_definitions,
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
                    f"JARVIS calling tool: {function_name} with args: {function_args}"
                )

                # Call the appropriate tool
                tool_result = await self._execute_tool(function_name, function_args)

                # Add tool result to messages
                messages.append(
                    {
                        "tool_call_id": tool_call.id,
                        "role": "tool",
                        "name": function_name,
                        "content": json.dumps(tool_result),
                    }
                )

            # Continue loop to get final response with tool results

        return "I'm sorry, I couldn't complete your request due to complexity. Please try simplifying your question."

    async def _execute_tool(self, function_name: str, arguments: dict) -> Any:
        """
        Execute a codebase tool.

        Args:
            function_name: Name of the tool
            arguments: Tool arguments

        Returns:
            Tool result (serializable)
        """
        if self.tools is None:
            return {"error": "Codebase tools not initialized"}
        
        try:
            if function_name == "search_files":
                return self.tools.search_files(
                    pattern=arguments["pattern"],
                    max_results=arguments.get("max_results", 20),
                )
            elif function_name == "read_file":
                return self.tools.read_file(
                    path=arguments["path"],
                    start_line=arguments.get("start_line"),
                    end_line=arguments.get("end_line"),
                )
            elif function_name == "grep_search":
                return self.tools.grep_search(
                    query=arguments["query"],
                    path=arguments.get("path", "."),
                    max_results=arguments.get("max_results", 30),
                )
            elif function_name == "list_directory":
                return self.tools.list_directory(
                    path=arguments.get("path", "."),
                    recursive=arguments.get("recursive", False),
                )
            elif function_name == "nix_hash_url":
                return self.tools.nix_hash_url(
                    url=arguments["url"],
                    unpack=arguments.get("unpack", True),
                )
            else:
                return {"error": f"Unknown tool: {function_name}"}

        except Exception as e:
            log.error(f"Tool execution error ({function_name}): {e}", exc_info=True)
            return {"error": f"Tool execution failed: {str(e)}"}
