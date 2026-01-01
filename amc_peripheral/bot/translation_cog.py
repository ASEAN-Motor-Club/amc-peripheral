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
        self.messages = []  # Game chat messages
        self.eco_game_messages = []  # Eco game chat messages

    # --- Translation Methods ---

    async def translate(self, message, language, prev_messages=[]):
        """Translate a message between a language and English."""
        completion = await self.openai_client_openrouter.beta.chat.completions.parse(
            model=TRANSLATION_AI_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": f"Translate message from {language} to English (or vice versa)",
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
                    "content": "Translate message into English, Chinese, Indonesian, Malay, Thai and Tagalog. Casual tone, no rude words. Handle slash commands by only translating params.",
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
                    "content": f"Translate the following message to {target_language}. Preserve the original meaning and tone. If the message is already in {target_language}, return it unchanged.",
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
            # Discord language channels -> In-game
            for lang, channel_id in LANGUAGE_CHANNELS.items():
                if message_channel_id == channel_id:
                    if lang != "english":
                        res = await self.translate(
                            message.content, lang, self.messages[-5:]
                        )
                        # pyrefly: ignore [missing-attribute]
                        translation = res.translation
                    else:
                        translation = message.content
                    await announce_in_game(
                        self.bot.http_session,
                        f"{message.author.display_name}: {translation}",
                        color="FFFFFF",
                    )

            # Language channels -> General channel
            for lang, channel_id in LANGUAGE_CHANNELS_GENERAL.items():
                if message_channel_id == channel_id:
                    res = await self.translate(
                        message.content, lang, self.messages[-5:]
                    )
                    # pyrefly: ignore [missing-attribute]
                    translation = res.translation
                    gen_chan = self.bot.get_channel(GENERAL_CHANNEL_ID)
                    if gen_chan:
                        await gen_chan.send(
                            f"**{message.author.display_name}**: {translation}"
                        )

        # 3. Eco Game Chat Channel -> Chinese Translation (both users and bots)
        if message_channel_id == ECO_GAME_CHAT_CHANNEL_ID and message.content:
            async def translate_eco_game_to_chinese():
                try:
                    author_name = message.author.display_name
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
