import logging
import discord
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
)
from amc_peripheral.bot.ai_models import (
    TranslationResponse,
    MultiTranslation,
    MultiTranslationWithEnglish,
)
from amc_peripheral.utils.game_utils import announce_in_game

log = logging.getLogger(__name__)


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

    # --- Translation Methods ---

    async def translate(self, message, language, prev_messages=[]):
        """Translate a message between a language and English."""
        completion = await self.openai_client_openrouter.beta.chat.completions.parse(
            model=TRANSLATION_AI_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": f"Translate message from {language} to English (or vice versa). IMPORTANT: If the message contains a username format like '**Username**: message' or 'Username: message', preserve the username exactly and only translate the message content.",
                },
                {
                    "role": "user",
                    "content": "### PREVIOUS MESSAGES:\n" + "\n".join(prev_messages),
                },
                {"role": "user", "content": f"### MESSAGE TO TRANSLATE:\n{message}"},
            ],
            response_format=TranslationResponse,
        )
        return completion.choices[0].message.parsed

    async def translate_multi_with_english(self, player_name, message, messages=[]):
        """Translate message to multiple languages including English."""
        sender = f" (from {player_name})" if player_name else ""
        completion = await self.openai_client_openrouter.beta.chat.completions.parse(
            model=DEFAULT_AI_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": "Translate message into English, Chinese, Indonesian, Malay, Thai and Tagalog. Casual tone, no rude words. Handle slash commands by only translating params. IMPORTANT: If the message contains a username format like '**Username**: message' or 'Username: message', preserve the username exactly and only translate the message content.",
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

    async def translate_multi(self, message, messages=[]):
        """Translate message to multiple languages (without English)."""
        completion = await self.openai_client_openrouter.beta.chat.completions.parse(
            model=TRANSLATION_AI_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": "Translate message into Chinese, Indonesian, Malay, Thai and Tagalog. Casual tone. Preserve sender [username].",
                },
                {
                    "role": "user",
                    "content": "### PREVIOUS MESSAGES:\n" + "\n".join(messages),
                },
                {"role": "user", "content": f"### MESSAGE TO TRANSLATE:\n{message}"},
            ],
            response_format=MultiTranslation,
        )
        return completion.choices[0].message.parsed

    async def translate_to_language(self, message: str, target_language: str, messages: list = []):
        """Translate a message to a specific target language."""
        completion = await self.openai_client_openrouter.beta.chat.completions.parse(
            model=TRANSLATION_AI_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": f"Translate the following message to {target_language}. IMPORTANT: Preserve the username format exactly (e.g., '**Username**: message' should become '**Username**: translated_message'). Only translate the message content, not the username. Preserve the original meaning and tone. If the message is already in {target_language}, return it unchanged.",
                },
                {
                    "role": "user",
                    "content": "### PREVIOUS MESSAGES:\n" + "\n".join(messages),
                },
                {"role": "user", "content": f"### MESSAGE TO TRANSLATE:\n{message}"},
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

        # 1. Game Chat Translation (bot messages from in-game)
        if message.author.bot and message_channel_id == GAME_CHAT_CHANNEL_ID:
            # Maintain message history for context
            if not self.messages:
                async for msg in message_channel.history(limit=15):
                    self.messages.append(msg.content)

            async def translate_game():
                try:
                    await self.translate_multi_with_english(
                        None, message.content, self.messages[-10:]
                    )
                except Exception as e:
                    log.error(f"Error translating game message: {e}")

            self.bot.loop.create_task(translate_game())

            self.messages.append(message.content)
            if len(self.messages) > 15:
                self.messages.pop(0)

        # 2. Bidirectional Language Channel Translation (user messages only)
        if not message.author.bot:
            # Discord language channels -> In-game (all languages)
            for lang, channel_id in LANGUAGE_CHANNELS.items():
                if message_channel_id == channel_id:
                    if lang != "english":
                        res = await self.translate(
                            message.content, lang, self.messages[-5:]
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
                                            message.content, target_lang, self.messages[-5:]
                                        )
                                    elif target_lang == "english":
                                        # Source language -> English (already have this)
                                        res_target = res
                                    else:
                                        # Source language -> English -> Target language
                                        res_target = await self.translate_to_language(
                                            translation, target_lang, self.messages[-5:]
                                        )
                                    
                                    if res_target and res_target.translation:
                                        # Don't prepend bot's own name
                                        if message.author == self.bot.user:
                                            await target_channel.send(res_target.translation)
                                        else:
                                            await target_channel.send(
                                                f"**{message.author.display_name}**: {res_target.translation}"
                                            )
                            except Exception as e:
                                log.error(f"Error translating from {lang} to {target_lang}: {e}")
                    
                    # Track context for future translations
                    self.messages.append(f"{message.author.display_name}: {message.content}")
                    if len(self.messages) > 15:
                        self.messages.pop(0)

            # Language channels -> General channel (non-English to English)
            for lang, channel_id in LANGUAGE_CHANNELS_GENERAL.items():
                if message_channel_id == channel_id:
                    res = await self.translate(
                        message.content, lang, self.general_messages[-5:]
                    )
                    # pyrefly: ignore [missing-attribute]
                    translation = res.translation
                    gen_chan = self.bot.get_channel(GENERAL_CHANNEL_ID)
                    if gen_chan:
                        # Don't prepend bot's own name
                        if message.author == self.bot.user:
                            await gen_chan.send(translation)
                        else:
                            await gen_chan.send(
                                f"**{message.author.display_name}**: {translation}"
                            )
                    # Track context for future translations
                    self.general_messages.append(f"{message.author.display_name}: {message.content}")
                    if len(self.general_messages) > 15:
                        self.general_messages.pop(0)
            
            # BIDIRECTIONAL: General channel -> Language channels (English to all)
            if message_channel_id == GENERAL_CHANNEL_ID:
                for lang, channel_id in LANGUAGE_CHANNELS_GENERAL.items():
                    try:
                        target_channel = self.bot.get_channel(channel_id)
                        if target_channel:
                            res = await self.translate_to_language(
                                message.content, lang, self.general_messages[-5:]
                            )
                            if res and res.translation:
                                # Don't prepend bot's own name
                                if message.author == self.bot.user:
                                    await target_channel.send(res.translation)
                                else:
                                    await target_channel.send(
                                        f"**{message.author.display_name}**: {res.translation}"
                                    )
                    except Exception as e:
                        log.error(f"Error translating from general to {lang}: {e}")
                # Track context for future translations
                self.general_messages.append(f"{message.author.display_name}: {message.content}")
                if len(self.general_messages) > 15:
                    self.general_messages.pop(0)

        # 3. BIDIRECTIONAL Eco Game Chat Translation (both users and bots)
        # English/Mixed -> Chinese
        if message_channel_id == ECO_GAME_CHAT_CHANNEL_ID and message.content:
            async def translate_eco_game_to_chinese():
                try:
                    author_name = message.author.display_name
                    # Don't include bot's own name in the content
                    if message.author == self.bot.user:
                        content = message.content
                    else:
                        content = f"**{author_name}**: {message.content}"

                    result = await self.translate_to_language(
                        content, "Chinese", self.eco_game_messages[-10:]
                    )

                    chinese_channel = self.bot.get_channel(ECO_GAME_CHAT_CHINESE_CHANNEL_ID)
                    if chinese_channel and result and result.translation:
                        await chinese_channel.send(result.translation)

                    self.eco_game_messages.append(content)
                    if len(self.eco_game_messages) > 15:
                        self.eco_game_messages.pop(0)
                except Exception as e:
                    log.error(f"Error translating Eco game chat message to Chinese: {e}")

            self.bot.loop.create_task(translate_eco_game_to_chinese())
        
        # Chinese -> English/Mixed
        if message_channel_id == ECO_GAME_CHAT_CHINESE_CHANNEL_ID and message.content:
            async def translate_chinese_to_eco_game():
                try:
                    author_name = message.author.display_name
                    # Don't include bot's own name in the content
                    if message.author == self.bot.user:
                        content = message.content
                    else:
                        content = f"**{author_name}**: {message.content}"

                    result = await self.translate_to_language(
                        content, "English", self.eco_game_messages[-10:]
                    )

                    eco_channel = self.bot.get_channel(ECO_GAME_CHAT_CHANNEL_ID)
                    if eco_channel and result and result.translation:
                        await eco_channel.send(result.translation)
                    
                    # Track context for future translations
                    self.eco_game_messages.append(content)
                    if len(self.eco_game_messages) > 15:
                        self.eco_game_messages.pop(0)
                except Exception as e:
                    log.error(f"Error translating Chinese message to Eco game chat: {e}")

            self.bot.loop.create_task(translate_chinese_to_eco_game())
