import discord
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


async def actual_discord_poll_creator(
    bot, question: str, options: list[str], channel_id=None
):
    try:
        # pyrefly: ignore [no-matching-overload]
        channel = bot.get_channel(int(channel_id))
        if not channel:
            return f"Error: Channel {channel_id} not found"
        if len(options) < 2:
            return "Error: Min 2 options"

        content = f"**Poll:** {question}\n\n" + "\n".join(
            [f"{i + 1}. {opt}" for i, opt in enumerate(options)]
        )
        content += "\n\nReact with the corresponding emoji to vote!"
        msg = await channel.send(content)
        for i in range(len(options)):
            await msg.add_reaction(f"{i + 1}\u20e3")
        return f"Poll '{question}' created!"
    except Exception as e:
        return f"Error: {e}"


async def actual_discord_event_creator(guild, name, desc, loc, start, end, tz_name):
    try:
        tz = ZoneInfo(tz_name)
        start_dt = datetime.fromisoformat(start).replace(tzinfo=tz)
        end_dt = (
            datetime.fromisoformat(end).replace(tzinfo=tz)
            if end
            else start_dt + timedelta(hours=1)
        )
        event = await guild.create_scheduled_event(
            name=name,
            description=desc,
            location=loc,
            start_time=start_dt,
            end_time=end_dt,
            entity_type=discord.EntityType.external,
            privacy_level=discord.PrivacyLevel.guild_only,
        )
        return f"Event '{name}' created: {event.url}"
    except Exception as e:
        return f"Error: {e}"
