"""
Discord Cog for automatic YouTube video transcript extraction and summarization.

Listens for YouTube links in the #off-topic channel and creates a thread
with the full transcript, an AI-generated summary, and (when warranted)
a critical analysis with fact-checks and information quality rating.
"""

import asyncio
import io
import logging
import re

import discord
from discord.ext import commands
from openai import AsyncOpenAI

from ..settings import (
    DEFAULT_AI_MODEL,
    OFF_TOPIC_CHANNEL_ID,
    OPENAI_API_KEY_OPENROUTER,
)
from .ai_models import ContentTriageResult
from .youtube_transcript import get_youtube_transcript

log = logging.getLogger(__name__)

YOUTUBE_URL_PATTERN = re.compile(
    r"(https?://)?(www\.)?(youtube\.com/watch\?v=|youtu\.be/|youtube\.com/shorts/)[\w-]+"
)


def _split_message(text: str, max_length: int = 2000) -> list[str]:
    """Split a message into chunks that fit within Discord's character limit."""
    if len(text) <= max_length:
        return [text]

    chunks = []
    while text:
        if len(text) <= max_length:
            chunks.append(text)
            break
        # Find a good split point (newline or space)
        split_at = text.rfind("\n", 0, max_length)
        if split_at == -1:
            split_at = text.rfind(" ", 0, max_length)
        if split_at == -1:
            split_at = max_length
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip()
    return chunks


def _score_bar(score: int, max_score: int = 10) -> str:
    """Render a score as an emoji bar. e.g. 7/10 → '🟩🟩🟩🟩🟩🟩🟩⬜⬜⬜'."""
    filled = "🟩" if score <= 3 else ("🟨" if score <= 6 else "🟥")
    return filled * score + "⬜" * (max_score - score)


def _format_analysis_header(triage: ContentTriageResult) -> str:
    """Format the triage scores into a readable header."""
    return (
        "## 🔍 Information Quality Report\n\n"
        f"**Controversialness:** {_score_bar(triage.controversialness)} ({triage.controversialness}/10)\n"
        f"**Speaker Confidence on Dubious Claims:** {_score_bar(triage.confidence)} ({triage.confidence}/10)\n"
        f"**Information Quality:** {_score_bar(triage.info_quality)} ({triage.info_quality}/10)\n"
    )


class YouTubeCog(commands.Cog):
    """Auto-summarize YouTube videos shared in #off-topic."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.openai_client = AsyncOpenAI(
            api_key=OPENAI_API_KEY_OPENROUTER,
            base_url="https://openrouter.ai/api/v1",
        )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        # Debug: log all messages to see if the listener is firing
        log.info(
            f"YouTubeCog.on_message: channel={message.channel.id} "
            f"(expected={OFF_TOPIC_CHANNEL_ID}), content={message.content[:80]!r}"
        )

        # Only react in #off-topic
        if message.channel.id != OFF_TOPIC_CHANNEL_ID:
            return

        youtube_match = YOUTUBE_URL_PATTERN.search(message.content)
        if youtube_match:
            log.info(f"YouTube link detected: {youtube_match.group()}")
            await self.handle_youtube_link(message, youtube_match.group())

    async def handle_youtube_link(self, message: discord.Message, url: str):
        """Extract transcript, summarize, triage, and optionally critically analyze."""
        try:
            log.info(f"handle_youtube_link: fetching transcript for {url}")
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None, lambda: get_youtube_transcript(url)
            )

            log.info(f"Transcript result: success={result.success}, error={result.error}, segments={len(result.segments)}")

            if not result.success:
                log.warning(f"Transcript extraction failed for {url}: {result.error}")
                return

            transcript_text = result.get_full_text()

            # Truncate for LLM calls
            transcript_for_llm = transcript_text
            if len(transcript_for_llm) > 25000:
                transcript_for_llm = transcript_for_llm[:25000] + "... (truncated)"

            async with message.channel.typing():
                # Phase 1: Summary
                summary = await self._summarize_transcript(
                    result.title, transcript_for_llm
                )

                # Phase 2: Triage — score controversialness & info quality
                triage = await self._triage_content(
                    result.title, transcript_for_llm
                )

                # Phase 3: Critical analysis (only if triage triggers it)
                analysis = None
                if triage and triage.needs_analysis:
                    analysis = await self._critical_analysis(
                        result.title, transcript_for_llm, triage
                    )

                # Create transcript file
                safe_title = "".join(
                    c for c in result.title if c.isalnum() or c in (" ", "-", "_")
                ).strip()[:50]
                filename = f"{safe_title}_transcript.txt"
                transcript_file = discord.File(
                    io.BytesIO(transcript_text.encode("utf-8")), filename=filename
                )

                # Create thread under the message
                try:
                    thread = await message.create_thread(
                        name=f"📺 Video Summary: {result.title[:50]}",
                        auto_archive_duration=60,
                    )
                    await thread.send(
                        content="📄 **Full Transcript**", file=transcript_file
                    )
                    for chunk in _split_message(summary):
                        await thread.send(chunk)

                    # Post analysis if triggered
                    if triage and triage.needs_analysis and analysis:
                        header = _format_analysis_header(triage)
                        full_analysis = f"{header}\n{analysis}"
                        for chunk in _split_message(full_analysis):
                            await thread.send(chunk)

                except Exception:
                    # Fallback to reply if thread creation fails
                    transcript_file = discord.File(
                        io.BytesIO(transcript_text.encode("utf-8")), filename=filename
                    )
                    await message.reply(
                        content=f"📺 **Transcript: {result.title}**",
                        file=transcript_file,
                    )
                    for chunk in _split_message(
                        f"📺 **Video Summary: {result.title}**\n\n{summary}"
                    ):
                        await message.reply(chunk)

        except Exception as e:
            log.exception(f"Error in handle_youtube_link: {e}")

    async def _summarize_transcript(self, title: str, transcript: str) -> str:
        """Call LLM to summarize transcript text."""
        summary_prompt = (
            f"Please provide a comprehensive summary of this YouTube video.\n"
            f"Title: {title}\n\n"
            f"Transcript:\n{transcript}\n\n"
            f"Focus on the main ideas, key takeaways, and any specific details that seem important."
        )

        try:
            response = await self.openai_client.chat.completions.create(
                model=DEFAULT_AI_MODEL,
                messages=[{"role": "user", "content": summary_prompt}],
            )
            return response.choices[0].message.content or "Summary not available"
        except Exception as e:
            log.exception(f"Error in _summarize_transcript: {e}")
            return f"❌ Failed to summarize video: {str(e)}"

    async def _triage_content(
        self, title: str, transcript: str
    ) -> ContentTriageResult | None:
        """Score the content for controversialness and information quality."""
        triage_prompt = (
            "Analyze the following YouTube video transcript and evaluate it.\n\n"
            "Score each dimension 0-10:\n"
            "- controversialness: how controversial or polarizing the claims are\n"
            "- confidence: how confidently the speaker asserts uncertain/unverified claims\n"
            "- info_quality: overall quality as an information source (sourcing, nuance, accuracy)\n"
            "- needs_analysis: set to true if controversialness >= 5 OR info_quality <= 4\n"
            "- topics: list the key claims or topics that may need fact-checking\n\n"
            f"Title: {title}\n\n"
            f"Transcript:\n{transcript}"
        )

        try:
            response = await self.openai_client.beta.chat.completions.parse(
                model=DEFAULT_AI_MODEL,
                messages=[{"role": "user", "content": triage_prompt}],
                response_format=ContentTriageResult,
            )
            return response.choices[0].message.parsed
        except Exception as e:
            log.exception(f"Error in _triage_content: {e}")
            return None

    async def _critical_analysis(
        self, title: str, transcript: str, triage: ContentTriageResult
    ) -> str:
        """Produce a critical analysis with fact-checks and nuance."""
        topics_list = "\n".join(f"- {t}" for t in triage.topics)

        analysis_prompt = (
            "You are a critical media analyst. Analyze the following YouTube video transcript.\n\n"
            f"Title: {title}\n"
            f"Controversialness Score: {triage.controversialness}/10\n"
            f"Information Quality Score: {triage.info_quality}/10\n\n"
            f"Key claims/topics to examine:\n{topics_list}\n\n"
            f"Transcript:\n{transcript}\n\n"
            "Provide:\n"
            "1. **Fact Check** — verify or dispute the key claims. Be specific.\n"
            "2. **Missing Nuance** — what perspectives, caveats, or context is the video leaving out?\n"
            "3. **Source Quality** — how reliable is this video as a source? "
            "Does the speaker cite sources? Are they an authority on the subject?\n"
            "4. **Overall Assessment** — a brief verdict on the trustworthiness of this content.\n\n"
            "Be fair and balanced. Acknowledge what the video gets right, not just what it gets wrong."
        )

        try:
            response = await self.openai_client.chat.completions.create(
                model=DEFAULT_AI_MODEL,
                messages=[{"role": "user", "content": analysis_prompt}],
            )
            return response.choices[0].message.content or "Analysis not available"
        except Exception as e:
            log.exception(f"Error in _critical_analysis: {e}")
            return f"❌ Failed to analyze video: {str(e)}"
