import logging
import discord
from discord import app_commands, Locale
from discord.ext import commands
from openai import AsyncOpenAI
from amc_peripheral.settings import (
    OPENAI_API_KEY_OPENROUTER,
    TRANSLATION_AI_MODEL,
    DEFAULT_AI_MODEL,
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
        completion = await self.openai_client_openrouter.beta.chat.completions.parse(
            model=TRANSLATION_AI_MODEL,
            messages=[
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
            response_format=TranslationResponse,
        )
        return completion.choices[0].message.parsed

    async def translate_multi_with_english(self, player_name, message, messages=[]):
        """Translate message into English, Chinese, Indonesian, Thai, Vietnamese, and Japanese."""
        sender = f" (from {player_name})" if player_name else ""
        completion = await self.openai_client_openrouter.beta.chat.completions.parse(
            model=DEFAULT_AI_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Translate message into English, Chinese, Indonesian, Thai, Vietnamese and Japanese. "
                        "Casual tone, no rude words. Handle slash commands by only translating params. "
                        "Auto-detect source language. If message is already in a target language, return it as is for that language. "
                        "If the message starts with a username, translate only the message content. "
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
            response_format=MultiTranslationWithEnglish,
        )
        return completion.choices[0].message.parsed

    async def translate_multi(self, message, messages=[], sender=None):
        """Translate message into multiple languages (without English)."""
        sender_info = f" (from {sender})" if sender else ""
        completion = await self.openai_client_openrouter.beta.chat.completions.parse(
            model=TRANSLATION_AI_MODEL,
            messages=[
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
            response_format=MultiTranslation,
        )
        return completion.choices[0].message.parsed

    async def translate_to_language(self, message: str, target_language: str, messages: list = [], sender=None):
        """Translate a message to a specific target language."""
        sender_info = f" (from {sender})" if sender else ""
        completion = await self.openai_client_openrouter.beta.chat.completions.parse(
            model=TRANSLATION_AI_MODEL,
            messages=[
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
            response_format=TranslationResponse,
        )
        return completion.choices[0].message.parsed

    # --- Message Handlers ---

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author == self.bot.user:
            return

        message_channel = message.channel
        message_channel_id = message_channel.id

        # 1. Game Chat Translation (bot messages from in-game via relay bot)
        if message.author.bot and message_channel_id == GAME_CHAT_CHANNEL_ID:
            # Maintain message history for context
            if not self.messages:
                async for msg in message_channel.history(limit=15):
                    username, content = self.extract_username_and_content(msg.content)
                    self.messages.append(f"{username}: {content}" if username else content)

            # Extract player name from the message content (sent by relay bot)
            player_name, message_content = self.extract_username_and_content(message.content)

            async def translate_game():
                try:
                    # Translate to all languages
                    result = await self.translate_multi_with_english(
                        player_name, message_content, self.messages[-10:]
                    )
                    
                    # Send to each language channel with player name
                    # pyrefly: ignore [missing-attribute]
                    if result.english:
                        english_channel = self.bot.get_channel(LANGUAGE_CHANNELS.get("english"))
                        if english_channel:
                            formatted = self.format_with_username(player_name, str(result.english))
                            await english_channel.send(formatted)
                    
                    # pyrefly: ignore [missing-attribute]
                    if result.chinese:
                        chinese_channel = self.bot.get_channel(LANGUAGE_CHANNELS.get("chinese"))
                        if chinese_channel:
                            formatted = self.format_with_username(player_name, str(result.chinese))
                            await chinese_channel.send(formatted)
                    
                    # pyrefly: ignore [missing-attribute]
                    if result.indonesian:
                        indonesian_channel = self.bot.get_channel(LANGUAGE_CHANNELS.get("indonesian"))
                        if indonesian_channel:
                            formatted = self.format_with_username(player_name, str(result.indonesian))
                            await indonesian_channel.send(formatted)
                    
                    # pyrefly: ignore [missing-attribute]
                    if result.thai:
                        thai_channel = self.bot.get_channel(LANGUAGE_CHANNELS.get("thai"))
                        if thai_channel:
                            formatted = self.format_with_username(player_name, str(result.thai))
                            await thai_channel.send(formatted)
                    
                    # pyrefly: ignore [missing-attribute]
                    if result.vietnamese:
                        vietnamese_channel = self.bot.get_channel(LANGUAGE_CHANNELS.get("vietnamese"))
                        if vietnamese_channel:
                            formatted = self.format_with_username(player_name, str(result.vietnamese))
                            await vietnamese_channel.send(formatted)
                    
                    # pyrefly: ignore [missing-attribute]
                    if result.japanese:
                        japanese_channel = self.bot.get_channel(LANGUAGE_CHANNELS.get("japanese"))
                        if japanese_channel:
                            formatted = self.format_with_username(player_name, str(result.japanese))
                            await japanese_channel.send(formatted)
                    
                except Exception as e:
                    log.error(f"Error translating game message: {e}")

            self.bot.loop.create_task(translate_game())

            username, content = self.extract_username_and_content(message.content)
            self.messages.append(f"{username}: {content}" if username else content)
            if len(self.messages) > 15:
                self.messages.pop(0)

        # 2. Bidirectional Language Channel Translation (user messages only)
        if not message.author.bot:
            # Discord language channels -> In-game (all languages)
            for lang, channel_id in LANGUAGE_CHANNELS.items():
                if lang in ["malay", "tagalog"]: # Skip removed languages
                    continue
                
                if message_channel_id == channel_id:
                    if lang != "english":
                        res = await self.translate(
                            message.content, lang, self.messages[-5:], sender=message.author.display_name
                        )
                        # pyrefly: ignore [missing-attribute]
                        translation = res.translation
                    else:
                        # For English, no translation needed
                        translation = message.content
                        # Create dummy response for consistency in bidirectional logic
                        res = type('obj', (object,), {'translation': message.content})()
                    
                    await announce_in_game(
                        self.bot.http_session,
                        f"{message.author.display_name}: {translation}",
                        color="FFFFFF",
                    )
                    
                    # BIDIRECTIONAL: Translate to all other language channels
                    for target_lang, target_channel_id in LANGUAGE_CHANNELS.items():
                        if target_lang != lang and target_channel_id != channel_id:
                            try:
                                target_channel = self.bot.get_channel(target_channel_id)
                                if target_channel:
                                    # Translate from source language to target language
                                    if lang == "english":
                                        # English -> Target language
                                        res_target = await self.translate_to_language(
                                            message.content, target_lang, self.messages[-5:], sender=message.author.display_name
                                        )
                                    elif target_lang == "english":
                                        # Source language -> English (already have this)
                                        res_target = res
                                    else:
                                        # Source language -> English -> Target language
                                        res_target = await self.translate_to_language(
                                            translation, target_lang, self.messages[-5:], sender=message.author.display_name
                                        )
                                    
                                    if res_target and res_target.translation:
                                        # Extract username from original and re-add to translation
                                        username, _ = self.extract_username_and_content(message.content)
                                        formatted = self.format_with_username(
                                            username or message.author.display_name,
                                            res_target.translation,
                                            is_bot=(message.author == self.bot.user)
                                        )
                                        await target_channel.send(formatted)
                            except Exception as e:
                                log.error(f"Error translating from {lang} to {target_lang}: {e}")
                    
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
                        await gen_chan.send(formatted)
                    # Track context for future translations
                    username, content = self.extract_username_and_content(message.content)
                    self.general_messages.append(f"{username or message.author.display_name}: {content}")
                    if len(self.general_messages) > 15:
                        self.general_messages.pop(0)
            
            # BIDIRECTIONAL: General channel -> Language channels (English to all)
            if message_channel_id == GENERAL_CHANNEL_ID:
                for lang, channel_id in LANGUAGE_CHANNELS_GENERAL.items():
                    if lang in ["malay", "tagalog"]: # Skip removed languages
                        continue
                        
                    try:
                        target_channel = self.bot.get_channel(channel_id)
                        if target_channel:
                            res = await self.translate_to_language(
                                message.content, lang, self.general_messages[-5:], sender=message.author.display_name
                            )
                            if res and res.translation:
                                # Extract username and re-add to translation
                                username, _ = self.extract_username_and_content(message.content)
                                formatted = self.format_with_username(
                                    username or message.author.display_name,
                                    res.translation,
                                    is_bot=(message.author == self.bot.user)
                                )
                                await target_channel.send(formatted)
                    except Exception as e:
                        log.error(f"Error translating from general to {lang}: {e}")
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
                        await chinese_channel.send(formatted)

                    # Track context for future translations
                    context_msg = f"{username}: {content}" if username else content
                    self.eco_game_messages.append(context_msg)
                    if len(self.eco_game_messages) > 15:
                        self.eco_game_messages.pop(0)
                except Exception as e:
                    log.error(f"Error translating Eco game chat message to Chinese: {e}")

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
                        await eco_channel.send(formatted)
                    
                    # Track context for future translations
                    context_msg = f"{username}: {content}" if username else content
                    self.eco_game_messages.append(context_msg)
                    if len(self.eco_game_messages) > 15:
                        self.eco_game_messages.pop(0)
                except Exception as e:
                    log.error(f"Error translating Chinese message to Eco game chat: {e}")

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
            completion = await self.openai_client_openrouter.beta.chat.completions.parse(
                model=TRANSLATION_AI_MODEL,
                messages=[
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
                response_format=ThreadTranslationResponse,
            )
            
            result = completion.choices[0].message.parsed
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
            log.error(f"Error in translate_thread: {e}")
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
