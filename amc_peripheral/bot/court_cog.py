"""Court cog — Admin private channel manager via #court."""

import logging
import re

import discord
from discord.ext import commands

from amc_peripheral.settings import (
    ADMIN_ROLE_ID,
    COURT_CATEGORY_ID,
    COURT_CHANNEL_ID,
)

log = logging.getLogger(__name__)


def _is_admin(member: discord.Member) -> bool:
    if member.guild_permissions.administrator:
        return True
    return any(r.id == ADMIN_ROLE_ID for r in member.roles)


def _sanitize_channel_name(name: str) -> str:
    name = name.lower().replace(" ", "-")
    name = re.sub(r"[^a-z0-9\-]", "", name)
    return name[:100] or "private-channel"


def _allow_overwrite() -> discord.PermissionOverwrite:
    return discord.PermissionOverwrite(
        view_channel=True,
        send_messages=True,
        read_message_history=True,
    )


# --- Persistent Views ---


class CreateChannelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(
            discord.ui.Button(
                label="Create Private Channel",
                style=discord.ButtonStyle.primary,
                custom_id="court_create_channel",
            )
        )


class ManageChannelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(
            discord.ui.Button(
                label="Add Member",
                style=discord.ButtonStyle.success,
                custom_id="court_add_member",
            )
        )
        self.add_item(
            discord.ui.Button(
                label="Remove Member",
                style=discord.ButtonStyle.secondary,
                custom_id="court_remove_member",
            )
        )
        self.add_item(
            discord.ui.Button(
                label="Close Channel",
                style=discord.ButtonStyle.danger,
                custom_id="court_close_channel",
            )
        )


# --- Modals ---


class CreateChannelModal(discord.ui.Modal, title="Create Private Channel"):
    channel_name = discord.ui.TextInput(
        label="Channel Name",
        placeholder="e.g. case-1234",
        required=True,
        max_length=100,
    )

    def __init__(self, creator: discord.Member):
        super().__init__()
        self.creator = creator

    async def on_submit(self, interaction: discord.Interaction):
        name = _sanitize_channel_name(self.channel_name.value)
        await interaction.response.send_message(
            "Select members to add to the private channel:",
            view=SelectMembersView(channel_name=name, creator=self.creator),
            ephemeral=True,
        )


class SelectMembersView(discord.ui.View):
    def __init__(self, channel_name: str, creator: discord.Member):
        super().__init__(timeout=120)
        self.channel_name = channel_name
        self.creator = creator
        self.user_select = discord.ui.UserSelect(
            placeholder="Select members to add...",
            min_values=1,
            max_values=25,
        )
        self.user_select.callback = self.on_user_select
        self.add_item(self.user_select)

    async def on_user_select(self, interaction: discord.Interaction):
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("Guild not found.", ephemeral=True)
            return

        category = guild.get_channel(COURT_CATEGORY_ID)
        if not isinstance(category, discord.CategoryChannel):
            await interaction.response.send_message(
                "Court category not found.", ephemeral=True
            )
            return

        admin_role = guild.get_role(ADMIN_ROLE_ID)

        overwrites: dict[discord.abc.Snowflake, discord.PermissionOverwrite] = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            guild.me: _allow_overwrite(),
        }
        if admin_role:
            overwrites[admin_role] = _allow_overwrite()
        overwrites[self.creator] = _allow_overwrite()

        selected: list[discord.Member] = []
        for user in self.user_select.values:
            if isinstance(user, discord.Member) and user.id != self.creator.id:
                overwrites[user] = _allow_overwrite()
                selected.append(user)

        channel = await guild.create_text_channel(
            self.channel_name,
            category=category,
            overwrites=overwrites,  # pyrefly: ignore [bad-argument-type]
            reason=f"Court channel created by {self.creator}",
        )

        await channel.send(
            f"🔒 Private channel created by {self.creator.mention}. "
            "Use the buttons below to manage members or close this channel.",
            view=ManageChannelView(),
        )

        mentions = ", ".join(m.mention for m in selected)
        suffix = f" with {mentions}" if selected else ""
        await interaction.response.send_message(
            f"✅ Created private channel: {channel.mention}{suffix}",
            ephemeral=True,
        )
        log.info(
            "Court channel %s (%d) created by %s (%d)",
            channel.name,
            channel.id,
            self.creator,
            self.creator.id,
        )


class AddMembersView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)
        self.user_select = discord.ui.UserSelect(
            placeholder="Select members to add...",
            min_values=1,
            max_values=25,
        )
        self.user_select.callback = self.on_user_select
        self.add_item(self.user_select)

    async def on_user_select(self, interaction: discord.Interaction):
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("Guild not found.", ephemeral=True)
            return
        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message(
                "Channel not found.", ephemeral=True
            )
            return

        added = []
        for user in self.user_select.values:
            if isinstance(user, discord.Member):
                await channel.set_permissions(user, overwrite=_allow_overwrite())
                added.append(user.mention)

        if added:
            await interaction.response.send_message(
                f"✅ Added: {', '.join(added)}", ephemeral=True
            )
            await channel.send(
                f"👥 {interaction.user.mention} added: {', '.join(added)}"
            )
        else:
            await interaction.response.send_message(
                "No members selected.", ephemeral=True
            )


class RemoveMembersView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)
        self.user_select = discord.ui.UserSelect(
            placeholder="Select members to remove...",
            min_values=1,
            max_values=25,
        )
        self.user_select.callback = self.on_user_select
        self.add_item(self.user_select)

    async def on_user_select(self, interaction: discord.Interaction):
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("Guild not found.", ephemeral=True)
            return
        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message(
                "Channel not found.", ephemeral=True
            )
            return

        removed = []
        for user in self.user_select.values:
            if isinstance(user, discord.Member):
                await channel.set_permissions(user, overwrite=None)
                removed.append(user.mention)

        if removed:
            await interaction.response.send_message(
                f"✅ Removed: {', '.join(removed)}", ephemeral=True
            )
            await channel.send(
                f"👥 {interaction.user.mention} removed: {', '.join(removed)}"
            )
        else:
            await interaction.response.send_message(
                "No members selected.", ephemeral=True
            )


class CloseConfirmView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)

    @discord.ui.button(label="Yes, close", style=discord.ButtonStyle.danger)
    async def confirm_close(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message(
                "Channel not found.", ephemeral=True
            )
            return
        await interaction.response.send_message("🔒 Closing channel...")
        log.info(
            "Court channel %s (%d) closed by %s",
            channel.name,
            channel.id,
            interaction.user,
        )
        await channel.delete(reason=f"Court channel closed by {interaction.user}")

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel_close(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await interaction.response.edit_message(
            content="Channel close cancelled.", view=None
        )


# --- Cog ---


class CourtCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.add_view(CreateChannelView())
        self.bot.add_view(ManageChannelView())

    @commands.Cog.listener()
    async def on_ready(self):
        """Post the court button after the guild cache is populated."""
        if COURT_CHANNEL_ID == 0:
            return

        channel = self.bot.get_channel(COURT_CHANNEL_ID)
        if not isinstance(channel, discord.TextChannel):
            log.warning("Court channel %d not found", COURT_CHANNEL_ID)
            return

        async for message in channel.history(limit=10):
            if message.author == self.bot.user:
                for row in message.components:
                    for (
                        component
                    ) in row.children:  # pyrefly: ignore [missing-attribute]
                        if (
                            hasattr(component, "custom_id")
                            and component.custom_id == "court_create_channel"
                        ):
                            log.info("Court button message already exists")
                            return

        await channel.send(
            "🏛️ **Court** — Click below to create a private channel for admin-managed discussions.",
            view=CreateChannelView(),
        )
        log.info("Posted court button message in #%s", channel.name)

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        if interaction.type != discord.InteractionType.component:
            return

        custom_id = (interaction.data or {}).get("custom_id", "")

        if custom_id == "court_create_channel":
            if not isinstance(interaction.user, discord.Member) or not _is_admin(
                interaction.user
            ):
                await interaction.response.send_message(
                    "Only admins can create court channels.", ephemeral=True
                )
                return
            await interaction.response.send_modal(CreateChannelModal(interaction.user))

        elif custom_id == "court_add_member":
            if not isinstance(interaction.user, discord.Member) or not _is_admin(
                interaction.user
            ):
                await interaction.response.send_message(
                    "Only admins can manage court channels.", ephemeral=True
                )
                return
            await interaction.response.send_message(
                "Select members to add to this channel:",
                view=AddMembersView(),
                ephemeral=True,
            )

        elif custom_id == "court_remove_member":
            if not isinstance(interaction.user, discord.Member) or not _is_admin(
                interaction.user
            ):
                await interaction.response.send_message(
                    "Only admins can manage court channels.", ephemeral=True
                )
                return
            await interaction.response.send_message(
                "Select members to remove from this channel:",
                view=RemoveMembersView(),
                ephemeral=True,
            )

        elif custom_id == "court_close_channel":
            if not isinstance(interaction.user, discord.Member) or not _is_admin(
                interaction.user
            ):
                await interaction.response.send_message(
                    "Only admins can close court channels.", ephemeral=True
                )
                return
            await interaction.response.send_message(
                "Are you sure you want to close this channel? This cannot be undone.",
                view=CloseConfirmView(),
                ephemeral=True,
            )
