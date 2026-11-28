"""Keep Discord scheduled events in sync with Django ScheduledEvent rows.

The in-game announcement rotation in ``UtilsCog`` already announces Discord
scheduled events that start in the future. This cog is the missing link: it
creates one Discord event per Django ScheduledEvent, so no manual Discord setup
is needed, and removes it 15 minutes after the event ends.

Source of truth is the Django row. Events we manage are tagged with an
``AMC-SE-<id>`` marker in their description; unmanaged events are never touched.
"""

import asyncio
import logging
import re
from datetime import UTC, datetime, timedelta

import discord
from discord.ext import commands, tasks

from ..settings import GUILD_ID
from .backend_db import fetch_scheduled_events

log = logging.getLogger(__name__)

MARKER_RE = re.compile(r"AMC-SE-(\d+)")
DELETE_GRACE = timedelta(minutes=15)


def marker_for(se_id: int) -> str:
    return f"AMC-SE-{se_id}"


def managed_se_id(description: str | None) -> int | None:
    match = MARKER_RE.search(description or "")
    return int(match.group(1)) if match else None


def as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def description_for(row: dict) -> str:
    """Use the Django SE description, capped to Discord's 1000-char limit."""
    marker = marker_for(row["id"])
    base = (row.get("description") or "").strip()
    if not base:
        base = f"{row['name']} - community event."
    max_base = 1000 - len(marker) - 2
    if len(base) > max_base:
        base = base[:max_base].rstrip()
    return f"{base}\n\n{marker}"


def event_drifted(event: discord.ScheduledEvent, row: dict) -> bool:
    start = as_utc(row["start_time"])
    end = as_utc(row["end_time"])
    return (
        event.name != row["name"]
        or (event.description or "") != description_for(row)
        or as_utc(event.start_time) != start
        or as_utc(event.end_time) != end
    )


class EventSyncCog(commands.Cog):
    """Sync Django ScheduledEvent rows into managed Discord scheduled events."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.sync_events.start()

    async def cog_unload(self) -> None:
        self.sync_events.cancel()

    @tasks.loop(minutes=5)
    async def sync_events(self) -> None:
        guild = self.bot.get_guild(GUILD_ID)
        if guild is None:
            log.warning("EventSyncCog: guild %s not cached, skipping", GUILD_ID)
            return

        rows = await asyncio.to_thread(fetch_scheduled_events)
        now = datetime.now(UTC)
        wanted: dict[int, dict] = {}
        for row in rows:
            end = as_utc(row["end_time"])
            if end is None or end > now - DELETE_GRACE:
                wanted[row["id"]] = row

        managed: dict[int, discord.ScheduledEvent] = {}
        for event in list(guild.scheduled_events):
            se_id = managed_se_id(event.description)
            if se_id is not None:
                managed[se_id] = event

        for se_id, event in managed.items():
            if se_id in wanted:
                continue
            try:
                await event.delete()
                log.info("EventSyncCog: deleted Discord event for SE %s", se_id)
            except discord.HTTPException as exc:
                log.warning("EventSyncCog: delete failed for SE %s: %s", se_id, exc)

        for se_id, row in wanted.items():
            event = managed.get(se_id)
            if event is None:
                await self._create(guild, row)
            elif event_drifted(event, row):
                await self._update(event, row)

    @sync_events.before_loop
    async def before_sync(self) -> None:
        await self.bot.wait_until_ready()

    async def _create(self, guild: discord.Guild, row: dict) -> None:
        try:
            await guild.create_scheduled_event(
                name=row["name"],
                scheduled_start_time=as_utc(row["start_time"]),
                scheduled_end_time=as_utc(row["end_time"]) or discord.utils.MISSING,
                entity_type=discord.EntityType.external,
                privacy_level=discord.PrivacyLevel.guild_only,
                description=description_for(row),
                entity_metadata=discord.ScheduledEventEntityMetadata(location="Motor Town"),
            )
            log.info("EventSyncCog: created Discord event for SE %s", row["id"])
        except discord.HTTPException as exc:
            log.warning("EventSyncCog: create failed for SE %s: %s", row["id"], exc)

    async def _update(self, event: discord.ScheduledEvent, row: dict) -> None:
        try:
            await event.edit(
                name=row["name"],
                scheduled_start_time=as_utc(row["start_time"]),
                scheduled_end_time=as_utc(row["end_time"]) or discord.utils.MISSING,
                description=description_for(row),
                entity_metadata=discord.ScheduledEventEntityMetadata(location="Motor Town"),
            )
            log.info("EventSyncCog: updated Discord event for SE %s", row["id"])
        except discord.HTTPException as exc:
            log.warning("EventSyncCog: update failed for SE %s: %s", row["id"], exc)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(EventSyncCog(bot))
