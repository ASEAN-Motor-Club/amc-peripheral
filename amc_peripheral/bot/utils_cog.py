import os
import json
import random
import logging
import discord
import urllib.parse
from datetime import datetime, timedelta, timezone, time as dt_time
from zoneinfo import ZoneInfo
from discord import app_commands
from discord.ext import commands, tasks
from amc_peripheral.settings import (
    LOCAL_TIMEZONE,
    STATIC_PATH,
    GENERAL_CHANNEL_ID,
    TIMEZONES_CHANNEL_ID,
)
from amc_peripheral.utils.game_utils import announce_in_game

log = logging.getLogger(__name__)


class UtilsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.local_tz = ZoneInfo(LOCAL_TIMEZONE)

        # State for announcements
        self.announcement_index = random.randint(0, 100)
        self.announcements = [
            "Please despawn unused vehicles! Ask /bot if you do not know how.",
            "Did you know? The parking lots opposite the ASEAN HQ is the Showcase Spot, where you can showcase your liveries and car customisation",
            "Tune into Radio ASEAN! You can listen to music and news surrounding the community, and even submit song requests.",
            "Please despawn unused vehicles! Ask /bot if you do not know how.",
            "Participate in the AMC Championship Cup! Each event pays up to 3 million in prizes. Check /events for more.",
            "Plan your next haul with the website (aseanmotorclub.com), where you can check live storage information.",
            "The AMC Championship season has begun! Find a team or compete solo, each race comes with prize money.",
            "Want to know where to buy a vehicle and how much it costs? Use the /bot followed by your question.",
            "Did you know? Autopilot gives you 50% of the exp you would get by driving manually.",
            "Remember to renew your land plot rent! You will receive a reminder on discord if you're verified.",
            "Regular server restarts improve FPS! Next one: Mon 8:30 AM GMT+7.",
            "Tune in to Radio ASEAN at aseanmotorclub.com/radio for pro tips!",
            "Check out Meehoi's house in the sky at Gapa, try entering the small room in the depot underneath.",
            "Our server runs a subsidy scheme. Find out jobs with bonus pay using the /jobs command!",
            "Game chat is synced with Discord. Keep in touch with the community!",
            "Depots auto-repair company vehicles. Help the community by delivering supplies to restock them! 10,000 coins subsidy.",
            "/rp_mode gives a 50% boost to all your payments and subsidies!",
            "Did you know Alt+Z hides your HUD for cinematic views? Try it!",
            "Please despawn your unused vehicles to help keep our server running smooth!",
            "Need a cheaper rental? Borrow from other players! Check Discord's rental channel.",
            "Admins can despawn stuck tow requests. Ping them on Discord!",
            "Use the website (aseanmotorclub.com) to see the live map, live storage amounts, jobs, and more!",
            "Help new players! Encourage them to join Discord (aseanmotorclub.com) & ask questions.",
            "The new Championship season is starting on Saturday 25 October. Register your team now!",
            "Corporation owners: No AI drivers! They block roads when you are offline.",
            "DJ Annie says: Turn on Radio ASEAN! Your long haul routes will thank you (and so will she!).",
            "Did you know trailers have their own Control Panel, usually on its left side. Use it to respawn the trailer if stuck.",
            "ARWRS and DOT is here to help! Use /rescue to alert them if you need a rescue operation.",
            "Find out the jobs in demand on the server with /jobs. Do them solo or together and share the rewards.",
            "Check out the Cat Altar at Ryumi's house near Pyosun Fishing Village",
        ]

        # Timezone state
        self.last_timezone_embed_message = None
        self.timezones_dict = {
            "🇨🇦 Vancouver": "America/Vancouver",
            "🇦🇷 Argentina": "America/Argentina/Buenos_Aires",
            "🇬🇧 London": "Europe/London",
            "🇮🇹 Rome": "Europe/Rome",
            "🇮🇳 Delhi": "Asia/Kolkata",
            "Bangkok 🇹🇭 / Jakarta 🇮🇩": "Asia/Bangkok",
            "Singapore 🇸🇬 / Malaysia 🇲🇾": "Asia/Singapore",
            "🇦🇺 Sydney": "Australia/Sydney",
        }

    async def cog_load(self):
        self.regular_announcement.start()
        self.rent_reminders.start()
        self.update_time_embed.start()

        # Context Menus
        self.ctx_menus = [
            app_commands.ContextMenu(
                name="Record Race Attempt", callback=self.record_race_attempt_context
            ),
            app_commands.ContextMenu(
                name="Open on Track Editor", callback=self.open_track_context
            ),
        ]
        for menu in self.ctx_menus:
            self.bot.tree.add_command(menu)

    async def cog_unload(self):
        self.regular_announcement.cancel()
        self.rent_reminders.cancel()
        self.update_time_embed.cancel()
        for menu in getattr(self, "ctx_menus", []):
            try:
                self.bot.tree.remove_command(menu.name, type=menu.type)
            except Exception:
                pass

    # --- Background Tasks ---

    @tasks.loop(seconds=60)
    async def update_time_embed(self):
        channel = self.bot.get_channel(TIMEZONES_CHANNEL_ID)
        if not channel:
            return

        def get_time_embed():
            embed = discord.Embed(title="🕒 World Clock", color=0x00AAFF)
            for city, tz in self.timezones_dict.items():
                # pyrefly: ignore [untyped-import]
                import pytz

                now = datetime.now(pytz.timezone(tz))
                time_str = now.strftime("%Y-%m-%d %H:%M")
                embed.add_field(name=city, value=f"`{time_str}`", inline=False)
            embed.set_footer(text="Updated every minute")
            return embed

        if self.last_timezone_embed_message is None:
            async for message in channel.history(limit=5):
                if (
                    message.author == self.bot.user
                    and message.embeds
                    and message.embeds[0].title == "🕒 World Clock"
                ):
                    self.last_timezone_embed_message = message
                    break

            if self.last_timezone_embed_message:
                await self.last_timezone_embed_message.edit(embed=get_time_embed())
            else:
                self.last_timezone_embed_message = await channel.send(
                    embed=get_time_embed()
                )
        else:
            try:
                await self.last_timezone_embed_message.edit(embed=get_time_embed())
            except discord.NotFound:
                self.last_timezone_embed_message = None

    @tasks.loop(minutes=15)
    async def regular_announcement(self):
        now = datetime.now(self.local_tz)
        if not self.bot.guilds:
            return
        events = self.bot.guilds[0].scheduled_events
        events = [
            f"The {event.name} is happening on {event.start_time.replace(tzinfo=ZoneInfo('UTC')).astimezone(self.local_tz).strftime('%A at %H:%M')} GMT+7, check /events for more info!"
            for event in events
            if event.start_time > now
        ]
        _announcements = [*self.announcements, *events]
        if not _announcements:
            return
        announcement = _announcements[self.announcement_index % len(_announcements)]
        self.announcement_index += 1
        await announce_in_game(self.bot.http_session, announcement, color="53EAFD")

    @tasks.loop(minutes=2)
    async def race_announcement(self):
        await announce_in_game(
            self.bot.http_session, "A race is taking place. Please mind the racers."
        )

    @tasks.loop(time=dt_time(hour=1, minute=0, tzinfo=timezone.utc))
    async def rent_reminders(self):
        if not self.bot.guilds:
            return
        guild = self.bot.guilds[0]
        general_channel = guild.get_channel(GENERAL_CHANNEL_ID)

        try:
            async with self.bot.http_session.get(
                "https://server.aseanmotorclub.com/api/housing/"
            ) as resp:
                housings = await resp.json()
        except Exception as e:
            log.error(f"Failed to fetch housing data: {e}")
            return

        for name, housing in housings.items():
            rent_left_seconds = housing.get("rentLeftTimeSeconds")
            if rent_left_seconds is not None and rent_left_seconds < 259200:
                nickname = housing.get("ownerName", "")
                member = discord.utils.get(guild.members, display_name=nickname)

                td = timedelta(seconds=rent_left_seconds)
                days = td.days
                hours = td.seconds // 3600
                rent_left = f"{days} days, {hours} hours"

                display_name = member.mention if member else nickname
                if general_channel:
                    await general_channel.send(
                        f"Rent reminder: {display_name}, your plot is expiring in {rent_left}"
                    )
                if member:
                    try:
                        await member.send(
                            f"Hi {nickname}! Just letting you know that your plot is expiring in {rent_left}"
                        )
                    except Exception:
                        pass

    # --- Thread Select View (Used by Record Race Attempt) ---
    class ThreadSelectView(discord.ui.View):
        def __init__(self, bot, threads, original_message, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.bot = bot
            self.original_message = original_message
            options = [
                discord.SelectOption(label=t.name, value=str(t.id)) for t in threads
            ]
            self.select_menu = discord.ui.Select(
                placeholder="Select a race thread...", options=options
            )
            self.select_menu.callback = self.select_callback
            self.add_item(self.select_menu)

        async def select_callback(self, interaction: discord.Interaction):
            thread = self.bot.get_channel(int(self.select_menu.values[0]))
            if not thread:
                await interaction.response.send_message(
                    "Thread not found.", ephemeral=True
                )
                return
            await thread.send(f"<@{interaction.user.id}>'s attempt:")
            await self.original_message.forward(thread)
            await interaction.response.send_message(
                f"Forwarded to '{thread.name}'.", ephemeral=True
            )
            # pyrefly: ignore [missing-attribute]
            await interaction.message.delete()

    # --- Commands ---

    @app_commands.command(name="toggle_announcement", description="Toggle announcement")
    async def toggle_announcement_cmd(
        self, interaction: discord.Interaction, state: str
    ):
        if interaction.user.id != 1155069673512120341:
            return await interaction.response.send_message("Only admins can")
        if state == "on":
            self.race_announcement.start()
            await interaction.response.send_message("Started")
        elif state == "off":
            self.race_announcement.stop()
            await interaction.response.send_message("Stopped")

    @app_commands.command(name="remind_rent", description="Trigger rent reminders")
    async def remind_rent_cmd(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await self.rent_reminders()
        await interaction.followup.send("Done", ephemeral=True)

    # --- Context Menus ---

    async def record_race_attempt_context(
        self, interaction: discord.Interaction, message: discord.Message
    ):
        forum = self.bot.get_channel(1353679733358858321)
        if not isinstance(forum, discord.ForumChannel):
            return await interaction.response.send_message(
                "Not a forum.", ephemeral=True
            )
        if "Event JSON" in message.content:
            return await interaction.response.send_message(
                "You must do this before starting.", ephemeral=True
            )
        if not forum.threads:
            return await interaction.response.send_message(
                "No threads.", ephemeral=True
            )
        await interaction.response.send_message(
            "Select thread:",
            view=self.ThreadSelectView(self.bot, reversed(forum.threads), message),
            ephemeral=True,
        )

    async def open_track_context(
        self, interaction: discord.Interaction, message: discord.Message
    ):
        await interaction.response.defer()
        for a in message.attachments:
            try:
                data = json.loads((await a.read()).decode("utf-8"))
                route_name = data.get("routeName")
                now = datetime.now()
                ts = now.timestamp()
                path = os.path.join(STATIC_PATH, "routes", f"{ts}.json")
                # pyrefly: ignore [bad-argument-type]
                await a.save(path)
                url = f"https://www.aseanmotorclub.com/routes/{ts}.json"
                return await interaction.followup.send(
                    f"**{route_name}**: https://www.aseanmotorclub.com/track?uri={urllib.parse.quote(url, safe='')}"
                )
            except Exception:
                continue
        await interaction.followup.send("Unable to parse track")
