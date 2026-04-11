import asyncio
import logging
import re
import discord
from discord import app_commands, Locale
from discord.ext import commands
from openai import AsyncOpenAI
from amc_peripheral.settings import (
    OPENAI_API_KEY_OPENROUTER,
    TRANSLATION_AI_MODEL,
    GENERAL_CHANNEL_ID,
    GAME_CHAT_CHANNEL_ID,
    LANGUAGE_CHANNELS,
    LANGUAGE_CHANNELS_GENERAL,
    ECO_GAME_CHAT_CHANNEL_ID,
    ECO_GAME_CHAT_CHINESE_CHANNEL_ID,
    RADIO_DB_PATH,
)
from amc_peripheral.bot.ai_models import (
    TranslationResponse,
    MultiTranslation,
    MultiTranslationWithEnglish,
    ThreadTranslationResponse,
)
from amc_peripheral.utils.game_utils import announce_in_game
from amc_peripheral.db import RadioDB

log = logging.getLogger(__name__)

GAME_GLOSSARY = """
Keep these gaming/technical terms unchanged: 
- Gaming terms: coil, spawn, respawn, AFK, GG, DC, lag, ping, fps, coords, waypoint, cargo, trailer, hub, zone, stash, loot, buff, debuff, meta, OP.
- Commands: /spawn, /home, /tpa, /tp, /kit, /warp.
- Game objects: truck names, vehicle names, car names.
- Roles: admin, mod, owner, VIP.
"""

CULTURAL_ADAPTATION = """
Adapt internet slang naturally between languages:
- 'lol/haha/lmao' → '555' (Thai), 'wkwk' (Indonesian), '哈哈' (Chinese), '草' or 'www' (Japanese).
- Keep English slang for Japanese/Vietnamese if no direct natural equivalent exists.
"""

# Bot ID for the MotorTown game chat relay bot
GAME_CHAT_BOT_ID = 1375420925910057041

# Prefixes for system messages that should NOT be translated
# These are forwarded by the relay bot but aren't player chat
SYSTEM_MESSAGE_PREFIXES = (
    "Player Login",
    "Player Logout",
    "Player Restocked",
)

# Regex to strip clan/faction tags like [C3G55], [P1], [MP2G29], [MC3G55] from player names
_TAG_PATTERN = re.compile(r'^\[[^\]]+\]\s*')

def strip_player_tag(name: str) -> str:
    """Strip optional clan/faction tag prefix from a player name.
    '[C3G55] fattron' -> 'fattron'
    '[MP2G29] Dingo' -> 'Dingo'
    'Yuuka' -> 'Yuuka'
    """
    return _TAG_PATTERN.sub('', name).strip()

# Patterns that indicate model self-talk leaked into translation output
_GARBAGE_PATTERNS = re.compile(
    r'(?:'
    r'This (?:output|response|is garbled|translation)'
    r'|Need to produce'
    r'|The user is asking'
    r'|Let\'s parse'
    r'|Probably an error'
    r'|correct translations'
    r'|^\s*[}\]]\s*'  # Starts with } or ] (JSON fragment leak)
    r'|\.{5,}'  # 5+ consecutive dots (degeneration)
    r')',
    re.IGNORECASE
)

def is_garbage_translation(text: str | None) -> bool:
    """Check if a translation looks like model self-talk or degenerated output."""
    if not text or not text.strip():
        return True
    return bool(_GARBAGE_PATTERNS.search(text))

# Locale to language mapping for context menu commands
LOCALE_TO_LANGUAGE = {
    Locale.thai: "Thai",
    Locale.chinese: "Chinese",
    Locale.taiwan_chinese: "Chinese",
    Locale.indonesian: "Indonesian",
    Locale.vietnamese: "Vietnamese",
    Locale.japanese: "Japanese",
}

# Supported languages for slash command choices
SUPPORTED_LANGUAGES = ["English", "Chinese", "Indonesian", "Thai", "Vietnamese", "Japanese"]


class TranslationCog(commands.Cog):
    """Handles all translation functionality for Discord channels."""

    def __init__(self, bot):
        self.bot = bot
        self.openai_client_openrouter = AsyncOpenAI(
            api_key=OPENAI_API_KEY_OPENROUTER, base_url="https://openrouter.ai/api/v1"
        )
        # Message history for context
        self.messages = []  # Game chat messages (LANGUAGE_CHANNELS)
        self.general_messages = []  # General channel messages (LANGUAGE_CHANNELS_GENERAL)
        self.eco_game_messages = []  # Eco game chat messages
        # Database for user language preferences
        self.db = RadioDB(RADIO_DB_PATH)
        
        # Register context menus on bot tree (can't be defined as class methods)
        self._register_context_menus()

    def _register_context_menus(self):
        """Register context menu commands on the bot's command tree."""
        cog = self  # Closure reference
        
        @app_commands.context_menu(name="Translate Message")
        async def translate_message_menu(interaction: discord.Interaction, message: discord.Message):
            await cog._handle_translate_message(interaction, message)
        
        @app_commands.context_menu(name="Translate Last 10")
        async def translate_batch_menu(interaction: discord.Interaction, message: discord.Message):
            await cog._handle_translate_batch(interaction, message)
        
        self.bot.tree.add_command(translate_message_menu)
        self.bot.tree.add_command(translate_batch_menu)

    # --- Parsing Helpers ---

    def _parse_completion(self, model_cls, completion):
        """Extract structured output from completion, with fallback for thinking models.
        
        If beta.parse() returned a valid parsed result, use it.
        Otherwise, fall back to manual JSON extraction from content,
        stripping <think> tags that some models (e.g., Qwen) include.
        """
        msg = completion.choices[0].message
        if hasattr(msg, 'parsed') and msg.parsed is not None:
            return msg.parsed
        
        # Fallback: extract JSON from content
        content = msg.content
        if not content:
            raise ValueError("Translation model returned empty content (parsed=None)")
        
        # Strip <think>...</think> blocks from thinking models
        cleaned = re.sub(r'<think>.*?</think>', '', content, flags=re.DOTALL).strip()
        
        # Extract JSON from markdown blocks if present
        match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', cleaned, re.DOTALL)
        if match:
            cleaned = match.group(1).strip()
            
        try:
            result = model_cls.model_validate_json(cleaned)
            log.info(f"Recovered translation via fallback parsing ({model_cls.__name__})")
            return result
        except Exception as e:
            msg_prefix = cleaned[:300].replace('\n', ' ')
            raise ValueError(f"Failed to parse as {model_cls.__name__}: {e}. Content preview: {msg_prefix}")

    async def _translate_structured(self, model_cls, messages, max_tokens=2048):
        """Call the translation model with structured output, with fallback and retry.
        
        1. Try beta.chat.completions.parse() for native structured output
        2. If SDK throws (e.g. model returns garbage), fall back to raw completion
        3. Retry once on any transient error
        """
        for attempt in range(2):  # max 2 attempts
            try:
                # We skip beta.parse() because "strict" JSON schema masking 
                # on non-OpenAI open-source models often causes catastrophic 
                # token repetition loops (the model hallucinates spaces/dots).
                schema_json = model_cls.model_json_schema()
                prompt_injection = f"\n\nYou MUST respond with perfectly formatted JSON. Use the following JSON schema:\n{schema_json}"
                
                # Clone messages and inject schema into system prompt
                run_messages = messages.copy()
                if run_messages and run_messages[0]["role"] == "system":
                    run_messages[0] = {"role": "system", "content": run_messages[0]["content"] + prompt_injection}
                
                completion = await self.openai_client_openrouter.chat.completions.create(
                    model=TRANSLATION_AI_MODEL,
                    messages=run_messages,
                    response_format={"type": "json_object"},
                    max_tokens=max_tokens,
                )
                
                result = self._parse_completion(model_cls, completion)
                if result:
                    log.info(f"Translation result via raw completion ({model_cls.__name__}): {result}")
                    return result
            except Exception as e:
                # If we hit an exception from _parse_completion (like ValueError) or network error
                if attempt == 0:
                    log.warning(f"Translation attempt failed, retrying in 1s: {e}")
                    await asyncio.sleep(1)
                else:
                    log.error(f"Translation failed after retry: {e}", exc_info=True)
                    return None

        return None

    # --- Translation Methods ---

    def extract_username_and_content(self, message: str) -> tuple[str | None, str]:
        """Extract username from message if present.
        Returns (username, content) tuple.
        Handles formats:
        - Eco game: '<t:1234567890:t> **Username**: content'
        - MotorTown game: '**Username:** content'
        - Regular: '**Username**: content' or 'Username: content'
        """
        import re
        
        # Strip Discord timestamp prefix if present (Eco format)
        # Format: <t:1234567890:t> or <t:1234567890:R> etc.
        message = re.sub(r'^<t:\d+:[tTdDfFR]>\s*', '', message)
        
        # Match **Username:** or **Username**: or Username: at start of message
        # MotorTown uses **username:** (colon inside bold)
        # Eco uses **username**: (colon outside bold)
        match = re.match(r'^(?:\*\*([^*]+?)(?::\*\*|\*\*:))\s*(.*)$', message, re.DOTALL)
        if match:
            return match.group(1).strip(), match.group(2).strip()
        
        # Fallback: simple Username: format
        match = re.match(r'^([^:]+?):\s*(.*)$', message, re.DOTALL)
        if match and len(match.group(1)) < 50:  # Reasonable username length
            return match.group(1).strip(), match.group(2).strip()
        
        return None, message
    
    def format_with_username(self, username: str | None, content: str, is_bot: bool = False) -> str:
        """Format message with username if provided and not from bot.
        """
        if username and not is_bot:
            return f"**{username}**: {content}"
        return content

    # --- Translation Methods ---

    async def translate(self, message, language, prev_messages=[], sender=None):
        """Translate a message between a language and English."""
        sender_info = f" (from {sender})" if sender else ""
        return await self._translate_structured(
            TranslationResponse,
            [
                {
                    "role": "system",
                    "content": (
                        f"Translate message from {language} to English (or vice versa). "
                        "Auto-detect the source language. If the message is already in the target language, return it unchanged. "
                        "If the message starts with a username like '**Username**: ' or 'Username: ', ignore the username and translate only the message content after it. "
                        f"\n\nGLOSSARY:\n{GAME_GLOSSARY}\n\nCULTURAL ADAPTATION:\n{CULTURAL_ADAPTATION}"
                    ),
                },
                {
                    "role": "user",
                    "content": "### PREVIOUS MESSAGES:\n" + "\n".join(prev_messages),
                },
                {"role": "user", "content": f"### MESSAGE TO TRANSLATE{sender_info}:\n{message}"},
            ],
        )

    async def translate_multi_with_english(self, player_name, message, messages=[]):
        """Translate message into English, Chinese, Indonesian, Thai, Vietnamese, and Japanese."""
        sender = f" (from {player_name})" if player_name else ""
        return await self._translate_structured(
            MultiTranslationWithEnglish,
            [
                {
                    "role": "system",
                    "content": (
                        "You are a game chat translator. Translate the message into all 6 languages: English, Chinese, Indonesian, Thai, Vietnamese, and Japanese.\n\n"
                        "CRITICAL RULES:\n"
                        "- NEVER return '...' or ellipsis or empty strings. Every language field MUST contain a real translation or the original text.\n"
                        "- If the message is in English: set the 'english' field to the EXACT original text, then translate into the other 5 languages.\n"
                        "- If the message is in a non-English language (e.g. Chinese): translate it into English and the other languages, and set that source language field to the original text.\n"
                        "- Even short, informal, or slang messages (e.g. 'lol', 'ok', 'nice one') MUST be translated — use equivalent casual expressions in each language.\n"
                        "- If the message starts with a username prefix, translate only the content after it.\n"
                        "- Casual tone, no rude words. Handle slash commands by only translating params.\n"
                        f"\n\nGLOSSARY:\n{GAME_GLOSSARY}\n\nCULTURAL ADAPTATION:\n{CULTURAL_ADAPTATION}"
                    ),
                },
                {
                    "role": "user",
                    "content": "### PREVIOUS MESSAGES:\n" + "\n".join(messages),
                },
                {
                    "role": "user",
                    "content": f"### MESSAGE TO TRANSLATE{sender}:\n\n{message}",
                },
            ],
        )

    async def translate_multi(self, message, messages=[], sender=None):
        """Translate message into multiple languages (without English)."""
        sender_info = f" (from {sender})" if sender else ""
        return await self._translate_structured(
            MultiTranslation,
            [
                {
                    "role": "system",
                    "content": (
                        "Translate message into Chinese, Indonesian, Thai, Vietnamese and Japanese. "
                        "Casual tone. Auto-detect source language. If already in target language, keep as is. "
                        f"\n\nGLOSSARY:\n{GAME_GLOSSARY}\n\nCULTURAL ADAPTATION:\n{CULTURAL_ADAPTATION}"
                    ),
                },
                {
                    "role": "user",
                    "content": "### PREVIOUS MESSAGES:\n" + "\n".join(messages),
                },
                {"role": "user", "content": f"### MESSAGE TO TRANSLATE{sender_info}:\n{message}"},
            ],
        )

    async def translate_to_language(self, message: str, target_language: str, messages: list = [], sender=None):
        """Translate a message to a specific target language."""
        sender_info = f" (from {sender})" if sender else ""
        return await self._translate_structured(
            TranslationResponse,
            [
                {
                    "role": "system",
                    "content": (
                        f"Translate the following message to {target_language}. "
                        "Auto-detect source language. If already in target language, return unchanged. "
                        "If the message starts with a username like '**Username**: ' or 'Username: ', ignore the username and translate only the message content after it. "
                        f"Output only the translated content without the username prefix.\n\nGLOSSARY:\n{GAME_GLOSSARY}\n\nCULTURAL ADAPTATION:\n{CULTURAL_ADAPTATION}"
                    ),
                },
                {
                    "role": "user",
                    "content": "### PREVIOUS MESSAGES:\n" + "\n".join(messages),
                },
                {"role": "user", "content": f"### MESSAGE TO TRANSLATE{sender_info}:\n{message}"},
            ],
        )

    # --- Message Handlers ---

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author == self.bot.user:
            return

        message_channel = message.channel
        message_channel_id = message_channel.id

        # 1. Game Chat Translation (bot messages from in-game via relay bot)
        if message.author.bot and message_channel_id == GAME_CHAT_CHANNEL_ID:
            # Extract player name and content first
            player_name, message_content = self.extract_username_and_content(message.content)

            # Skip system messages (login/logout/announcements)
            if player_name and any(prefix in player_name for prefix in SYSTEM_MESSAGE_PREFIXES):
                return

            # Skip announcement-style messages (emoji prefix like 📢, 📦)
            raw_content = message.content.strip()
            if raw_content and raw_content[0] in '\U0001f4e2\U0001f4e6\U0001f7e2\U0001f534':
                return

            # Skip slash commands — no translatable content
            stripped_content = message_content.strip()
            if stripped_content.startswith('/'):
                return

            # Skip empty or trivially short messages (e.g. "XD", "ok", "lol")
            if len(stripped_content) < 3:
                return

            # Maintain message history for context
            if not self.messages:
                async for msg in message_channel.history(limit=15):
                    username, content = self.extract_username_and_content(msg.content)
                    clean_name = strip_player_tag(username) if username else None
                    self.messages.append(f"{clean_name}: {content}" if clean_name else content)

            # Strip tag for AI context (keep original for display)
            clean_player_name = strip_player_tag(player_name) if player_name else None

            async def translate_game():
                try:
                    log.info(
                        f"[TRANSLATE_IN] player={clean_player_name!r} "
                        f"content={message_content!r} "
                        f"context_len={len(self.messages)}"
                    )
                    # Translate to all languages
                    result = await self.translate_multi_with_english(
                        clean_player_name, message_content, self.messages[-10:]
                    )
                    
                    if not result:
                        log.warning(f"[TRANSLATE_OUT] player={clean_player_name!r} result=None")
                        return
                    
                    log.info(
                        f"[TRANSLATE_OUT] player={clean_player_name!r} "
                        f"en={result.english!r} "
                        f"zh={result.chinese!r} "
                        f"id={result.indonesian!r} "
                        f"th={result.thai!r} "
                        f"vi={result.vietnamese!r} "
                        f"ja={result.japanese!r}"
                    )
                    
                    # Send to each language channel, skipping garbage translations
                    lang_fields = [
                        ("english", result.english),
                        ("chinese", result.chinese),
                        ("indonesian", result.indonesian),
                        ("thai", result.thai),
                        ("vietnamese", result.vietnamese),
                        ("japanese", result.japanese),
                    ]
                    for lang_key, translated_text in lang_fields:
                        if is_garbage_translation(translated_text):
                            if translated_text:
                                log.warning(
                                    f"[TRANSLATE_GARBAGE] lang={lang_key} "
                                    f"text={translated_text!r} "
                                    f"original={message_content!r}"
                                )
                            continue
                        channel = self.bot.get_channel(LANGUAGE_CHANNELS.get(lang_key))
                        if channel:
                            # pyrefly: ignore [missing-attribute]
                            formatted = self.format_with_username(player_name, str(translated_text))
                            await channel.send(formatted, allowed_mentions=discord.AllowedMentions.none())
                    
                except Exception as e:
                    log.error(f"Error translating game message: {e}", exc_info=True)

            self.bot.loop.create_task(translate_game())

            clean_name = strip_player_tag(player_name) if player_name else None
            self.messages.append(f"{clean_name}: {message_content}" if clean_name else message_content)
            if len(self.messages) > 15:
                self.messages.pop(0)

        # 2. Bidirectional Language Channel Translation (user messages only)
        if not message.author.bot:
            # Discord language channels -> In-game (all languages)
            for lang, channel_id in LANGUAGE_CHANNELS.items():
                if lang in ["malay", "tagalog"]: # Skip removed languages
                    continue
                
                if message_channel_id == channel_id:
                    # Single multi-language translation call for fan-out
                    multi_result = await self.translate_multi_with_english(
                        message.author.display_name, message.content, self.messages[-5:]
                    )
                    
                    if not multi_result:
                        log.warning(f"Multi-translation failed for language channel message from {message.author.display_name}")
                        break
                    
                    # Get English translation for in-game announce
                    # pyrefly: ignore [missing-attribute]
                    english_text = multi_result.english or message.content
                    
                    await announce_in_game(
                        self.bot.http_session,
                        f"{message.author.display_name}: {english_text}",
                        color="FFFFFF",
                    )
                    
                    # BIDIRECTIONAL: Send to all other language channels from single result
                    lang_to_field = {
                        "english": "english",
                        "chinese": "chinese",
                        "indonesian": "indonesian",
                        "thai": "thai",
                        "vietnamese": "vietnamese",
                        "japanese": "japanese",
                    }
                    for target_lang, target_channel_id in LANGUAGE_CHANNELS.items():
                        if target_lang == lang or target_channel_id == channel_id:
                            continue
                        if target_lang in ["malay", "tagalog"]:
                            continue
                        try:
                            target_channel = self.bot.get_channel(target_channel_id)
                            field_name = lang_to_field.get(target_lang)
                            translated_text = getattr(multi_result, field_name, None) if field_name else None
                            if target_channel and translated_text:
                                username, _ = self.extract_username_and_content(message.content)
                                formatted = self.format_with_username(
                                    username or message.author.display_name,
                                    translated_text,
                                    is_bot=(message.author == self.bot.user)
                                )
                                await target_channel.send(formatted, allowed_mentions=discord.AllowedMentions.none())
                        except Exception as e:
                            log.error(f"Error sending translation to {target_lang}: {e}", exc_info=True)
                    
                    # Track context for future translations
                    username, content = self.extract_username_and_content(message.content)
                    self.messages.append(f"{username or message.author.display_name}: {content}")
                    if len(self.messages) > 15:
                        self.messages.pop(0)

            # Language channels -> General channel (non-English to English)
            for lang, channel_id in LANGUAGE_CHANNELS_GENERAL.items():
                if lang in ["malay", "tagalog"]: # Skip removed languages
                    continue
                
                if message_channel_id == channel_id:
                    res = await self.translate(
                        message.content, lang, self.general_messages[-5:], sender=message.author.display_name
                    )
                    # pyrefly: ignore [missing-attribute]
                    translation = res.translation
                    gen_chan = self.bot.get_channel(GENERAL_CHANNEL_ID)
                    if gen_chan:
                        # Extract username and re-add to translation
                        username, _ = self.extract_username_and_content(message.content)
                        formatted = self.format_with_username(
                            username or message.author.display_name,
                            translation,
                            is_bot=(message.author == self.bot.user)
                        )
                        await gen_chan.send(formatted, allowed_mentions=discord.AllowedMentions.none())
                    # Track context for future translations
                    username, content = self.extract_username_and_content(message.content)
                    self.general_messages.append(f"{username or message.author.display_name}: {content}")
                    if len(self.general_messages) > 15:
                        self.general_messages.pop(0)
            
            # BIDIRECTIONAL: General channel -> Language channels (English to all)
            if message_channel_id == GENERAL_CHANNEL_ID:
                # Single multi-language call instead of N sequential calls
                multi_result = await self.translate_multi(
                    message.content, self.general_messages[-5:], sender=message.author.display_name
                )
                
                if multi_result:
                    lang_to_field = {
                        "chinese": "chinese",
                        "indonesian": "indonesian",
                        "thai": "thai",
                        "vietnamese": "vietnamese",
                        "japanese": "japanese",
                    }
                    for lang, channel_id in LANGUAGE_CHANNELS_GENERAL.items():
                        if lang in ["malay", "tagalog"]:
                            continue
                        try:
                            target_channel = self.bot.get_channel(channel_id)
                            field_name = lang_to_field.get(lang)
                            translated_text = getattr(multi_result, field_name, None) if field_name else None
                            if target_channel and translated_text:
                                username, _ = self.extract_username_and_content(message.content)
                                formatted = self.format_with_username(
                                    username or message.author.display_name,
                                    translated_text,
                                    is_bot=(message.author == self.bot.user)
                                )
                                await target_channel.send(formatted, allowed_mentions=discord.AllowedMentions.none())
                        except Exception as e:
                            log.error(f"Error sending translation to {lang}: {e}", exc_info=True)
                
                # Track context for future translations
                username, content = self.extract_username_and_content(message.content)
                self.general_messages.append(f"{username or message.author.display_name}: {content}")
                if len(self.general_messages) > 15:
                    self.general_messages.pop(0)

        # 3. BIDIRECTIONAL Eco Game Chat Translation (both users and bots)
        # English/Mixed -> Chinese
        if message_channel_id == ECO_GAME_CHAT_CHANNEL_ID and message.content:
            async def translate_eco_game_to_chinese():
                try:
                    # Extract username from message (handles bot messages with embedded usernames)
                    username, content = self.extract_username_and_content(message.content)
                    
                    # For non-bot Discord users, use their display name
                    if not message.author.bot and not username:
                        username = message.author.display_name
                    
                    result = await self.translate_to_language(
                        content, "Chinese", self.eco_game_messages[-10:], sender=username or message.author.display_name
                    )

                    chinese_channel = self.bot.get_channel(ECO_GAME_CHAT_CHINESE_CHANNEL_ID)
                    if chinese_channel and result and result.translation:
                        formatted = self.format_with_username(
                            username, result.translation, is_bot=(message.author == self.bot.user and not username)
                        )
                        await chinese_channel.send(formatted, allowed_mentions=discord.AllowedMentions.none())

                    # Track context for future translations
                    context_msg = f"{username}: {content}" if username else content
                    self.eco_game_messages.append(context_msg)
                    if len(self.eco_game_messages) > 15:
                        self.eco_game_messages.pop(0)
                except Exception as e:
                    log.error(f"Error translating Eco game chat message to Chinese: {e}", exc_info=True)

            self.bot.loop.create_task(translate_eco_game_to_chinese())
        
        # Chinese -> English/Mixed
        if message_channel_id == ECO_GAME_CHAT_CHINESE_CHANNEL_ID and message.content:
            async def translate_chinese_to_eco_game():
                try:
                    # Extract username from message (handles bot messages with embedded usernames)
                    username, content = self.extract_username_and_content(message.content)
                    
                    # For non-bot Discord users, use their display name
                    if not message.author.bot and not username:
                        username = message.author.display_name

                    result = await self.translate_to_language(
                        content, "English", self.eco_game_messages[-10:], sender=username or message.author.display_name
                    )

                    eco_channel = self.bot.get_channel(ECO_GAME_CHAT_CHANNEL_ID)
                    if eco_channel and result and result.translation:
                        formatted = self.format_with_username(
                            username, result.translation, is_bot=(message.author == self.bot.user and not username)
                        )
                        await eco_channel.send(formatted, allowed_mentions=discord.AllowedMentions.none())
                    
                    # Track context for future translations
                    context_msg = f"{username}: {content}" if username else content
                    self.eco_game_messages.append(context_msg)
                    if len(self.eco_game_messages) > 15:
                        self.eco_game_messages.pop(0)
                except Exception as e:
                    log.error(f"Error translating Chinese message to Eco game chat: {e}", exc_info=True)

            self.bot.loop.create_task(translate_chinese_to_eco_game())

    # --- Slash Commands ---

    async def get_user_language(self, user_id: int) -> str:
        """Get user's preferred language with fallback chain: DB -> Discord locale -> English."""
        # Check database first
        lang = self.db.get_user_language(str(user_id))
        if lang:
            return lang
        return "English"  # Default fallback

    @app_commands.command(name="set-language", description="Set your preferred language for translations")
    @app_commands.describe(language="Your preferred language")
    @app_commands.choices(language=[
        app_commands.Choice(name=lang, value=lang) for lang in SUPPORTED_LANGUAGES
    ])
    async def set_language(self, interaction: discord.Interaction, language: str):
        """Set user's preferred language."""
        success = self.db.set_user_language(str(interaction.user.id), language)
        if success:
            await interaction.response.send_message(
                f"✅ Your preferred language has been set to **{language}**.",
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                "❌ Failed to save language preference. Please try again.",
                ephemeral=True
            )

    @app_commands.command(name="translate", description="Translate text to a language")
    @app_commands.describe(
        text="The text to translate",
        to_language="Target language (defaults to your saved language)"
    )
    @app_commands.choices(to_language=[
        app_commands.Choice(name=lang, value=lang) for lang in SUPPORTED_LANGUAGES
    ])
    async def translate_text(self, interaction: discord.Interaction, text: str, to_language: str | None = None):
        """Translate text to specified language."""
        await interaction.response.defer(ephemeral=True)
        
        # Use provided language or user's saved preference
        target_lang = to_language or await self.get_user_language(interaction.user.id)
        
        result = await self.translate_to_language(text, target_lang)
        
        # pyrefly: ignore [missing-attribute]
        if result and result.translation:
            embed = discord.Embed(
                title=f"Translation → {target_lang}",
                description=result.translation,
                color=discord.Color.blurple()
            )
            embed.add_field(name="Original", value=text[:1024], inline=False)
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            await interaction.followup.send("Translation failed.", ephemeral=True)

    @app_commands.command(name="translate_thread", description="Translate recent messages in this channel")
    @app_commands.describe(
        count="Number of messages to translate (default: 10)",
        to_language="Target language (defaults to your saved language)"
    )
    @app_commands.choices(to_language=[
        app_commands.Choice(name=lang, value=lang) for lang in SUPPORTED_LANGUAGES
    ])
    async def translate_thread(self, interaction: discord.Interaction, count: app_commands.Range[int, 1, 25] = 10, to_language: str | None = None):
        """Translate last N messages in current channel."""
        await interaction.response.defer(ephemeral=True)
        target_lang = to_language or await self.get_user_language(interaction.user.id)
        
        # Ensure channel supports history
        if not isinstance(interaction.channel, (discord.TextChannel, discord.Thread, discord.VoiceChannel)):
            await interaction.followup.send("This command only works in text channels.", ephemeral=True)
            return
        
        try:
            # Fetch messages and build thread
            messages = [msg async for msg in interaction.channel.history(limit=count)]
            thread_lines = []
            
            for msg in reversed(messages):
                _, content = self.extract_username_and_content(msg.content)
                if content.strip():
                    thread_lines.append(f"{msg.author.display_name}: {content}")
            
            if not thread_lines:
                await interaction.followup.send("No messages to translate.", ephemeral=True)
                return
            
            # Translate entire thread in one API call
            thread_text = "\n".join(thread_lines)
            result = await self._translate_structured(
                ThreadTranslationResponse,
                [
                    {
                        "role": "system",
                        "content": (
                            f"Translate the following conversation thread to {target_lang}. "
                            "Preserve the format 'Username: message' exactly. "
                            "Only translate the message content, keep usernames unchanged. "
                            "Auto-detect source languages. "
                            f"\n\nGLOSSARY:\n{GAME_GLOSSARY}\n\nCULTURAL ADAPTATION:\n{CULTURAL_ADAPTATION}"
                        ),
                    },
                    {
                        "role": "user",
                        "content": f"### THREAD TO TRANSLATE:\n{thread_text}",
                    },
                ],
                max_tokens=4096,
            )
            # pyrefly: ignore [missing-attribute]
            if result and result.translated_thread:
                output = result.translated_thread
                
                # Split into chunks if too long (Discord limit: 2000 chars)
                if len(output) > 2000:
                    await interaction.followup.send(output[:2000], ephemeral=True)
                    remaining = output[2000:]
                    while remaining:
                        await interaction.followup.send(remaining[:2000], ephemeral=True)
                        remaining = remaining[2000:]
                else:
                    await interaction.followup.send(output, ephemeral=True)
            else:
                await interaction.followup.send("❌ Translation failed: No result returned", ephemeral=True)
                
        except Exception as e:
            log.error(f"Error in translate_thread: {e}", exc_info=True)
            await interaction.followup.send(f"❌ Translation failed: {str(e)}", ephemeral=True)

    async def _handle_translate_message(self, interaction: discord.Interaction, message: discord.Message):
        """Translate a single message to your language."""
        await interaction.response.defer(ephemeral=True)
        
        # Get user's preferred language with locale fallback
        target_lang = await self.get_user_language(interaction.user.id)
        if target_lang == "English" and interaction.locale in LOCALE_TO_LANGUAGE:
            target_lang = LOCALE_TO_LANGUAGE[interaction.locale]
        
        _, content = self.extract_username_and_content(message.content)
        
        if not content.strip():
            await interaction.followup.send("No text to translate.", ephemeral=True)
            return
        
        result = await self.translate_to_language(content, target_lang)
        
        # pyrefly: ignore [missing-attribute]
        if result and result.translation:
            embed = discord.Embed(
                title=f"Translation → {target_lang}",
                description=result.translation,
                color=discord.Color.blurple()
            )
            embed.add_field(name="Original", value=content[:1024], inline=False)
            embed.set_footer(text=f"From: {message.author.display_name}")
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            await interaction.followup.send("Translation failed.", ephemeral=True)

    async def _handle_translate_batch(self, interaction: discord.Interaction, message: discord.Message):
        """Translate from clicked message and 9 messages before it."""
        await interaction.response.defer(ephemeral=True)
        
        # Get user's preferred language with locale fallback
        target_lang = await self.get_user_language(interaction.user.id)
        if target_lang == "English" and interaction.locale in LOCALE_TO_LANGUAGE:
            target_lang = LOCALE_TO_LANGUAGE[interaction.locale]
        
        # Ensure channel supports history
        if not isinstance(interaction.channel, (discord.TextChannel, discord.Thread, discord.VoiceChannel)):
            await interaction.followup.send("This command only works in text channels.", ephemeral=True)
            return
        
        # Fetch 9 messages before the clicked message
        messages = [msg async for msg in interaction.channel.history(limit=9, before=message.created_at)]
        messages.insert(0, message)  # Include clicked message at start
        
        lines = []
        for msg in reversed(messages):
            _, content = self.extract_username_and_content(msg.content)
            if content.strip():
                result = await self.translate_to_language(content, target_lang)
                # pyrefly: ignore [missing-attribute]
                if result and result.translation:
                    lines.append(f"**{msg.author.display_name}**: {result.translation}")
        
        if lines:
            output = "\n".join(lines)
            if len(output) > 2000:
                await interaction.followup.send(output[:2000], ephemeral=True)
                remaining = output[2000:]
                while remaining:
                    await interaction.followup.send(remaining[:2000], ephemeral=True)
                    remaining = remaining[2000:]
            else:
                await interaction.followup.send(output, ephemeral=True)
        else:
            await interaction.followup.send("No messages to translate.", ephemeral=True)
