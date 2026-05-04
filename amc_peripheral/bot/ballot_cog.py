"""Secret ballot cog — anonymous voting via slash commands and persistent button views."""

import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands, tasks
from sqlite_utils import Database

from amc_peripheral.settings import ADMIN_ROLE_ID

log = logging.getLogger(__name__)

MAX_OPTIONS = 10
MIN_OPTIONS = 2


def _is_admin(member: discord.Member) -> bool:
    if member.guild_permissions.administrator:
        return True
    return any(r.id == ADMIN_ROLE_ID for r in member.roles)


def _parse_duration(s: str) -> int | None:
    s = s.strip().lower()
    total = 0
    for value, unit in re.findall(r"(\d+)\s*([hms])", s):
        v = int(value)
        if unit == "h":
            total += v * 3600
        elif unit == "m":
            total += v * 60
        elif unit == "s":
            total += v
    return total if total > 0 else None


# ── SQLite persistence ──────────────────────────────────────────────


class BallotDB:
    def __init__(self, db_path: str):
        self.db = Database(db_path)
        self.db.conn.execute("PRAGMA busy_timeout = 5000")
        self._ensure_tables()

    def _ensure_tables(self):
        if "ballots" not in self.db.table_names():
            # pyrefly: ignore [missing-attribute]
            self.db["ballots"].create(
                {
                    "id": int,
                    "question": str,
                    "options": str,
                    "channel_id": str,
                    "message_id": str,
                    "creator_id": str,
                    "creator_name": str,
                    "status": str,
                    "closes_at": str,
                    "created_at": str,
                    "closed_at": str,
                },
                pk="id",
            )
            # pyrefly: ignore [missing-attribute]
            self.db["ballots"].create_index(["status"])

        if "ballot_votes" not in self.db.table_names():
            # pyrefly: ignore [missing-attribute]
            self.db["ballot_votes"].create(
                {
                    "id": int,
                    "ballot_id": int,
                    "voter_id": str,
                    "voter_name": str,
                    "option_index": int,
                    "voted_at": str,
                },
                pk="id",
            )
            # pyrefly: ignore [missing-attribute]
            self.db["ballot_votes"].create_index(
                ["ballot_id", "voter_id"], unique=True
            )
            # pyrefly: ignore [missing-attribute]
            self.db["ballot_votes"].create_index(["ballot_id"])

    def create_ballot(
        self,
        *,
        question: str,
        options: list[str],
        channel_id: str,
        creator_id: str,
        creator_name: str,
        closes_at: str | None,
    ) -> int:
        now = datetime.now(timezone.utc).isoformat()
        row = {
            "question": question,
            "options": json.dumps(options),
            "channel_id": channel_id,
            "message_id": "",
            "creator_id": creator_id,
            "creator_name": creator_name,
            "status": "open",
            "closes_at": closes_at or "",
            "created_at": now,
            "closed_at": "",
        }
        # pyrefly: ignore [missing-attribute]
        return self.db["ballots"].insert(row).last_pk

    def get_ballot(self, ballot_id: int) -> dict | None:
        rows = list(self.db["ballots"].rows_where("id = ?", [ballot_id]))
        return rows[0] if rows else None

    def get_open_ballots(self) -> list[dict]:
        return list(
            self.db["ballots"].rows_where(
                "status = 'open'", order_by="created_at asc"
            )
        )

    def update_ballot(self, ballot_id: int, **kwargs) -> None:
        # pyrefly: ignore [missing-attribute]
        self.db["ballots"].update(ballot_id, kwargs)

    def set_message_id(self, ballot_id: int, message_id: str) -> None:
        self.update_ballot(ballot_id, message_id=message_id)

    def cast_vote(
        self,
        *,
        ballot_id: int,
        voter_id: str,
        voter_name: str,
        option_index: int,
    ) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        existing = list(
            self.db["ballot_votes"].rows_where(
                "ballot_id = ? AND voter_id = ?", [ballot_id, voter_id]
            )
        )
        if existing:
            # pyrefly: ignore [missing-attribute]
            self.db["ballot_votes"].update(
                existing[0]["id"],
                {"option_index": option_index, "voted_at": now, "voter_name": voter_name},
            )
            return False  # Not a new vote, it's an update
        row = {
            "ballot_id": ballot_id,
            "voter_id": voter_id,
            "voter_name": voter_name,
            "option_index": option_index,
            "voted_at": now,
        }
        # pyrefly: ignore [missing-attribute]
        self.db["ballot_votes"].insert(row)
        return True  # New vote

    def get_vote(self, ballot_id: int, voter_id: str) -> dict | None:
        rows = list(
            self.db["ballot_votes"].rows_where(
                "ballot_id = ? AND voter_id = ?", [ballot_id, voter_id]
            )
        )
        return rows[0] if rows else None

    def get_vote_counts(self, ballot_id: int) -> dict[int, int]:
        rows = list(
            self.db.query(
                "SELECT option_index, COUNT(*) as cnt "
                "FROM ballot_votes WHERE ballot_id = ? "
                "GROUP BY option_index",
                [ballot_id],
            )
        )
        return {row["option_index"]: row["cnt"] for row in rows}

    def get_total_votes(self, ballot_id: int) -> int:
        rows = list(
            self.db.query(
                "SELECT COUNT(*) as cnt FROM ballot_votes WHERE ballot_id = ?",
                [ballot_id],
            )
        )
        return rows[0]["cnt"] if rows else 0


# ── Embed builders ──────────────────────────────────────────────────


def _bar_chart(count: int, total: int, width: int = 20) -> str:
    if total == 0:
        return "░" * width
    filled = round(count / total * width)
    return "█" * filled + "░" * (width - filled)


def build_open_embed(ballot: dict) -> discord.Embed:
    options: list[str] = json.loads(ballot["options"])
    embed = discord.Embed(
        title=f"🗳️ Secret Ballot #{ballot['id']}",
        description=f"**{ballot['question']}**",
        color=discord.Color.blurple(),
    )
    options_text = "\n".join(f"**{i + 1}.** {opt}" for i, opt in enumerate(options))
    embed.add_field(name="Options", value=options_text, inline=False)

    if ballot.get("closes_at"):
        try:
            closes_at = datetime.fromisoformat(ballot["closes_at"])
            embed.add_field(
                name="Closes",
                value=f"<t:{int(closes_at.timestamp())}:R>",
                inline=True,
            )
        except Exception:
            pass

    embed.add_field(name="Status", value="OPEN — Cast Your Vote", inline=True)
    embed.set_footer(text=f"Created by {ballot['creator_name']} • Your vote is secret")
    return embed


def build_closed_embed(ballot: dict) -> discord.Embed:
    options: list[str] = json.loads(ballot["options"])
    counts = ballot.get("_counts", {})
    total = ballot.get("_total", 0)

    embed = discord.Embed(
        title=f"🗳️ Secret Ballot #{ballot['id']} — CLOSED",
        description=f"**{ballot['question']}**",
        color=discord.Color.gold(),
    )

    if total == 0:
        embed.add_field(name="Result", value="No votes were cast.", inline=False)
    else:
        max_count = max(counts.values()) if counts else 0
        lines = []
        for i, opt in enumerate(options):
            count = counts.get(i, 0)
            pct = (count / total * 100) if total else 0
            bar = _bar_chart(count, total)
            winner_marker = " 🏆" if count == max_count and count > 0 else ""
            lines.append(f"**{i + 1}.** {opt}\n{bar} {count} vote{'s' if count != 1 else ''} ({pct:.0f}%){winner_marker}")
        embed.add_field(name="Results", value="\n\n".join(lines), inline=False)

    embed.add_field(name="Total Votes", value=str(total), inline=True)
    embed.set_footer(text=f"Created by {ballot['creator_name']}")
    return embed


# ── Persistent vote view ────────────────────────────────────────────


class BallotVoteView(discord.ui.View):
    def __init__(self, ballot_id: int, options: list[str]):
        super().__init__(timeout=None)
        self.ballot_id = ballot_id
        for i, opt in enumerate(options):
            label = opt[:80]  # Discord button label limit
            self.add_item(
                discord.ui.Button(
                    label=label,
                    style=discord.ButtonStyle.secondary,
                    custom_id=f"ballot_vote_{ballot_id}_{i}",
                )
            )


# ── Cog ─────────────────────────────────────────────────────────────


class BallotCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        data_dir = os.environ.get("AUCTION_DATA_DIR", "/var/lib/amc-peripheral")
        os.makedirs(data_dir, exist_ok=True)
        self.db = BallotDB(os.path.join(data_dir, "ballots.db"))

    async def cog_load(self):
        self.check_ballot_timers.start()
        self._restore_persistent_views()

    async def cog_unload(self):
        self.check_ballot_timers.cancel()

    def _restore_persistent_views(self):
        """Re-register persistent button views for all open ballots."""
        for ballot in self.db.get_open_ballots():
            options: list[str] = json.loads(ballot["options"])
            view = BallotVoteView(ballot["id"], options)
            self.bot.add_view(view)
        log.info("Restored persistent ballot views")

    @tasks.loop(seconds=30)
    async def check_ballot_timers(self):
        now = datetime.now(timezone.utc)
        for ballot in self.db.get_open_ballots():
            closes_at_str = ballot.get("closes_at", "")
            if not closes_at_str:
                continue
            try:
                closes_at = datetime.fromisoformat(closes_at_str)
            except Exception:
                continue
            if now >= closes_at:
                await self._close_ballot(ballot)

    @check_ballot_timers.before_loop
    async def before_check_ballot_timers(self):
        await self.bot.wait_until_ready()

    async def _close_ballot(self, ballot: dict):
        ballot_id = ballot["id"]
        counts = self.db.get_vote_counts(ballot_id)
        total = self.db.get_total_votes(ballot_id)

        self.db.update_ballot(
            ballot_id,
            status="closed",
            closed_at=datetime.now(timezone.utc).isoformat(),
        )

        # Edit original message to show results
        channel_id = int(ballot["channel_id"])
        message_id = ballot.get("message_id")
        channel = self.bot.get_channel(channel_id)

        closed_ballot = dict(ballot)
        closed_ballot["status"] = "closed"
        closed_ballot["_counts"] = counts
        closed_ballot["_total"] = total
        embed = build_closed_embed(closed_ballot)

        if channel and message_id:
            try:
                msg = await channel.fetch_message(int(message_id))
                # Disable all buttons
                for action_row in msg.components:
                    for component in action_row.children:
                        component.disabled = True  # type: ignore[union-attr]
                await msg.edit(embed=embed, view=None)
            except discord.NotFound:
                log.warning("Ballot embed message %s not found", message_id)
            except Exception as e:
                log.error("Failed to close ballot embed: %s", e)

        log.info("Ballot #%d closed: %d votes cast", ballot_id, total)

    # ── Commands ─────────────────────────────────────────────────────

    ballot_group = app_commands.Group(
        name="ballot",
        description="Manage secret ballots",
    )

    @ballot_group.command(
        name="create", description="Create a new secret ballot (Admin only)"
    )
    @app_commands.describe(
        question="The ballot question",
        options="Options separated by | (pipe), e.g. 'Yes|No|Abstain'",
        duration="Optional auto-close duration (e.g. 2h, 30m). Leave empty for manual close.",
    )
    async def ballot_create(
        self,
        interaction: discord.Interaction,
        question: str,
        options: str,
        duration: str | None = None,
    ):
        if not isinstance(interaction.user, discord.Member) or not _is_admin(
            interaction.user
        ):
            return await interaction.response.send_message(
                "Only admins can create ballots.", ephemeral=True
            )

        option_list = [opt.strip() for opt in options.split("|") if opt.strip()]
        if len(option_list) < MIN_OPTIONS:
            return await interaction.response.send_message(
                f"At least {MIN_OPTIONS} options are required.", ephemeral=True
            )
        if len(option_list) > MAX_OPTIONS:
            return await interaction.response.send_message(
                f"At most {MAX_OPTIONS} options are allowed.", ephemeral=True
            )

        closes_at: str | None = None
        if duration:
            seconds = _parse_duration(duration)
            if not seconds or seconds < 30:
                return await interaction.response.send_message(
                    "Invalid duration. Use format like `2h`, `30m`, `1h30m`. Minimum 30 seconds.",
                    ephemeral=True,
                )
            if seconds > 604800:
                return await interaction.response.send_message(
                    "Duration too long. Maximum 7 days.", ephemeral=True
                )
            closes_at = (
                datetime.now(timezone.utc) + timedelta(seconds=seconds)
            ).isoformat()

        ballot_id = self.db.create_ballot(
            question=question,
            options=option_list,
            channel_id=str(interaction.channel_id),
            creator_id=str(interaction.user.id),
            creator_name=interaction.user.display_name,
            closes_at=closes_at,
        )

        ballot = self.db.get_ballot(ballot_id)
        assert ballot is not None
        embed = build_open_embed(ballot)
        view = BallotVoteView(ballot_id, option_list)

        await interaction.response.send_message(embed=embed, view=view)
        msg = await interaction.original_response()
        self.db.set_message_id(ballot_id, str(msg.id))

        # Register persistent view
        self.bot.add_view(view)

        log.info(
            "Ballot #%d created by %s: %s (%d options)",
            ballot_id,
            interaction.user.display_name,
            question,
            len(option_list),
        )

    @ballot_group.command(
        name="close", description="Close a ballot and reveal results (Admin only)"
    )
    @app_commands.describe(id="The ballot ID to close")
    async def ballot_close(self, interaction: discord.Interaction, id: int):
        if not isinstance(interaction.user, discord.Member) or not _is_admin(
            interaction.user
        ):
            return await interaction.response.send_message(
                "Only admins can close ballots.", ephemeral=True
            )

        ballot = self.db.get_ballot(id)
        if not ballot:
            return await interaction.response.send_message(
                "Ballot not found.", ephemeral=True
            )
        if ballot["status"] != "open":
            return await interaction.response.send_message(
                "This ballot is already closed.", ephemeral=True
            )

        await interaction.response.send_message(
            f"Closing ballot #{id}...", ephemeral=True
        )
        await self._close_ballot(ballot)

    @ballot_group.command(name="list", description="List active ballots")
    async def ballot_list(self, interaction: discord.Interaction):
        ballots = self.db.get_open_ballots()
        if not ballots:
            return await interaction.response.send_message(
                "No active ballots.", ephemeral=True
            )

        embed = discord.Embed(
            title="🗳️ Active Ballots",
            color=discord.Color.blurple(),
        )
        for b in ballots[:25]:
            options: list[str] = json.loads(b["options"])
            total = self.db.get_total_votes(b["id"])
            value_parts = [
                f"Options: {', '.join(options)}",
                f"Votes: {total}",
            ]
            if b.get("closes_at"):
                try:
                    closes_at = datetime.fromisoformat(b["closes_at"])
                    value_parts.append(f"Closes: <t:{int(closes_at.timestamp())}:R>")
                except Exception:
                    pass
            embed.add_field(
                name=f"#{b['id']}: {b['question'][:100]}",
                value="\n".join(value_parts),
                inline=False,
            )

        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── Button interaction handler ───────────────────────────────────

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        if interaction.type != discord.InteractionType.component:
            return

        custom_id = (interaction.data or {}).get("custom_id", "")
        if not custom_id.startswith("ballot_vote_"):
            return

        parts = custom_id.split("_")
        # ballot_vote_{ballot_id}_{option_index}
        if len(parts) < 4:
            return

        try:
            ballot_id = int(parts[2])
            option_index = int(parts[3])
        except (ValueError, IndexError):
            return

        ballot = self.db.get_ballot(ballot_id)
        if not ballot or ballot["status"] != "open":
            await interaction.response.send_message(
                "This ballot is no longer open.", ephemeral=True
            )
            return

        options: list[str] = json.loads(ballot["options"])
        if option_index < 0 or option_index >= len(options):
            await interaction.response.send_message("Invalid option.", ephemeral=True)
            return

        voter_id = str(interaction.user.id)
        voter_name = interaction.user.display_name
        is_new = self.db.cast_vote(
            ballot_id=ballot_id,
            voter_id=voter_id,
            voter_name=voter_name,
            option_index=option_index,
        )

        chosen = options[option_index]
        if is_new:
            await interaction.response.send_message(
                f"✅ Your vote for **{chosen}** has been recorded. Your vote is secret — no one can see your choice.",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                f"🔄 Your vote has been changed to **{chosen}**. Your vote is secret — no one can see your choice.",
                ephemeral=True,
            )
