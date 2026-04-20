import logging
import discord
from discord import app_commands
from discord.ext import commands
from ..settings import ADMIN_ROLE_ID

log = logging.getLogger(__name__)


def is_admin():
    async def predicate(interaction: discord.Interaction) -> bool:
        if not isinstance(interaction.user, discord.Member):
            return False
        if any(r.id == ADMIN_ROLE_ID for r in interaction.user.roles):
            return True
        await interaction.response.send_message(
            "Only admins can set up self-assignable roles.", ephemeral=True
        )
        return False
    return app_commands.check(predicate)


class RoleButtonView(discord.ui.View):
    def __init__(self, role_id: int, role_name: str):
        super().__init__(timeout=None)
        self.role_id = role_id
        self.add_item(
            discord.ui.Button(
                label=f"✅ Get {role_name}",
                style=discord.ButtonStyle.success,
                custom_id=f"role_add_{role_id}",
            )
        )
        self.add_item(
            discord.ui.Button(
                label=f"❌ Remove {role_name}",
                style=discord.ButtonStyle.danger,
                custom_id=f"role_remove_{role_id}",
            )
        )


class RoleCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(
        name="role-setup",
        description="Create a self-assignable role message (Admin only)",
    )
    @app_commands.describe(
        role="The role users can self-assign",
        description="A short description shown in the embed",
        emoji="Optional emoji to display in the embed title",
    )
    @is_admin()
    async def role_setup(
        self,
        interaction: discord.Interaction,
        role: discord.Role,
        description: str = "",
        emoji: str = "",
    ):
        if role.position >= interaction.guild.me.top_role.position:
            await interaction.response.send_message(
                f"I can't assign **{role.name}** — it's above my highest role. "
                "Move my role above it in Server Settings.",
                ephemeral=True,
            )
            return

        if role.managed:
            await interaction.response.send_message(
                f"**{role.name}** is a managed/integration role and can't be self-assigned.",
                ephemeral=True,
            )
            return

        title = f"{emoji} {role.name}" if emoji else role.name
        embed = discord.Embed(
            title=title,
            description=description or f"Click a button below to add or remove the **{role.name}** role.",
            color=role.color if role.color != discord.Color.default() else discord.Color.blurple(),
        )
        embed.set_footer(text=f"Role ID: {role.id}")

        view = RoleButtonView(role.id, role.name)
        await interaction.response.send_message(embed=embed, view=view)

    @app_commands.command(
        name="role-list",
        description="List self-assignable role messages in this channel",
    )
    async def role_list(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        found = []
        async for message in interaction.channel.history(limit=100):
            if message.author != self.bot.user:
                continue
            if not message.components:
                continue
            for row in message.components:
                for component in row.children:
                    if hasattr(component, "custom_id") and (
                        component.custom_id or ""
                    ).startswith("role_add_"):
                        found.append(message.jump_url)
                        break

        if found:
            lines = "\n".join(f"• {url}" for url in found)
            await interaction.followup.send(
                f"Self-assignable role messages in this channel:\n{lines}",
                ephemeral=True,
            )
        else:
            await interaction.followup.send(
                "No self-assignable role messages found in this channel.",
                ephemeral=True,
            )

    async def _handle_role_button(self, interaction: discord.Interaction, add: bool):
        custom_id = interaction.data.get("custom_id", "")
        try:
            role_id = int(custom_id.split("_")[-1])
        except (ValueError, IndexError):
            await interaction.response.send_message(
                "Could not determine the role.", ephemeral=True
            )
            return

        role = interaction.guild.get_role(role_id)
        if not role:
            await interaction.response.send_message(
                "That role no longer exists.", ephemeral=True
            )
            return

        member = interaction.user

        if add:
            if role in member.roles:
                await interaction.response.send_message(
                    f"You already have the **{role.name}** role.", ephemeral=True
                )
                return
            try:
                await member.add_roles(role, reason="Self-assigned via role button")
                await interaction.response.send_message(
                    f"Added **{role.name}** role! ✅", ephemeral=True
                )
            except discord.Forbidden:
                await interaction.response.send_message(
                    "I don't have permission to assign that role.", ephemeral=True
                )
        else:
            if role not in member.roles:
                await interaction.response.send_message(
                    f"You don't have the **{role.name}** role.", ephemeral=True
                )
                return
            try:
                await member.remove_roles(role, reason="Self-removed via role button")
                await interaction.response.send_message(
                    f"Removed **{role.name}** role. ❌", ephemeral=True
                )
            except discord.Forbidden:
                await interaction.response.send_message(
                    "I don't have permission to remove that role.", ephemeral=True
                )

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        if interaction.type != discord.InteractionType.component:
            return
        custom_id = interaction.data.get("custom_id", "")
        if custom_id.startswith("role_add_"):
            await self._handle_role_button(interaction, add=True)
        elif custom_id.startswith("role_remove_"):
            await self._handle_role_button(interaction, add=False)


async def setup(bot):
    await bot.add_cog(RoleCog(bot))