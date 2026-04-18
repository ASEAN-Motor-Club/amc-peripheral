"""Auction cog — Discord slash commands, escrow, background timer."""

import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands, tasks

from amc_peripheral.settings import (
    ADMIN_ROLE_ID,
    AUCTION_CHANNEL_ID,
    BACKEND_API_URL,
)
from amc_peripheral.bot.auction_db import AuctionDB
from amc_peripheral.bot.auction_views import (
    build_cancelled_embed,
    build_closed_embed,
    build_history_embed,
    build_live_embed,
)

log = logging.getLogger(__name__)


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


def _is_admin(member: discord.Member) -> bool:
    if member.guild_permissions.administrator:
        return True
    return any(r.id == ADMIN_ROLE_ID for r in member.roles)


class AuctionCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        data_dir = os.environ.get("AUCTION_DATA_DIR", "/var/lib/amc-peripheral")
        os.makedirs(data_dir, exist_ok=True)
        self.db = AuctionDB(os.path.join(data_dir, "auctions.db"))
        self._last_embed_update: dict[int, float] = {}

    async def cog_load(self):
        self.check_auction_timers.start()

    async def cog_unload(self):
        self.check_auction_timers.cancel()

    # --- Backend API helpers ---

    async def _escrow(self, discord_id: str, amount: int, character_id: int | None = None) -> tuple[int | None, int | None, str | None]:
        """Escrow funds from a player's bank account.

        Returns (post_escrow_balance, character_id, error_message).
        On success: (balance, character_id, None).
        On failure: (None, None, error_string).
        """
        url = f"{BACKEND_API_URL}/api/auction/escrow/"
        payload: dict = {"player_discord_id": discord_id, "amount": amount}
        if character_id is not None:
            payload["character_id"] = character_id
        try:
            async with self.bot.http_session.post(url, json=payload) as resp:
                if resp.status == 409:
                    data = await resp.json()
                    return None, None, data.get("error", "Insufficient funds.")
                if resp.status == 404:
                    return None, None, "Could not find your bank account. Are you registered in-game?"
                if resp.status != 200:
                    log.warning("Auction escrow returned %d", resp.status)
                    return None, None, "Escrow service unavailable. Try again later."
                data = await resp.json()
                return data.get("balance", 0), data.get("character_id"), None
        except Exception as e:
            log.error("Auction escrow failed: %s", e)
            return None, None, "Escrow service unavailable. Try again later."

    async def _refund(self, discord_id: str, amount: int, character_id: int | None = None) -> bool:
        """Refund escrowed funds to a player. Returns True on success."""
        url = f"{BACKEND_API_URL}/api/auction/refund/"
        payload: dict = {"player_discord_id": discord_id, "amount": amount}
        if character_id is not None:
            payload["character_id"] = character_id
        try:
            async with self.bot.http_session.post(url, json=payload) as resp:
                if resp.status != 200:
                    log.warning("Auction refund returned %d for %s", resp.status, discord_id)
                    return False
                return True
        except Exception as e:
            log.error("Auction refund failed for %s: %s", discord_id, e)
            return False

    async def _settle(self, winner_discord_id: str, seller_discord_id: str, amount: int, seller_type: str = "player", winner_character_id: int | None = None, seller_character_id: int | None = None) -> bool:
        """Settle auction funds from escrow to seller. Returns True on success."""
        url = f"{BACKEND_API_URL}/api/auction/settle/"
        payload: dict = {
            "winner_discord_id": winner_discord_id,
            "seller_discord_id": seller_discord_id,
            "amount": amount,
            "seller_type": seller_type,
        }
        if winner_character_id is not None:
            payload["winner_character_id"] = winner_character_id
        if seller_character_id is not None:
            payload["seller_character_id"] = seller_character_id
        try:
            async with self.bot.http_session.post(url, json=payload) as resp:
                if resp.status != 200:
                    log.warning("Auction settle returned %d", resp.status)
                    return False
                return True
        except Exception as e:
            log.error("Auction settle failed: %s", e)
            return False

    # --- Embed helpers ---

    async def _update_embed(self, auction: dict):
        channel_id = int(auction["channel_id"])
        message_id = auction.get("message_id")
        if not message_id:
            return

        channel = self.bot.get_channel(channel_id)
        if not channel:
            return

        try:
            msg = await channel.fetch_message(int(message_id))
            embed = build_live_embed(auction)
            await msg.edit(embed=embed)
        except discord.NotFound:
            log.warning("Auction embed message %s not found", message_id)
        except Exception as e:
            log.error("Failed to update auction embed: %s", e)

    async def _close_auction(self, auction: dict):
        auction_id = auction["id"]
        creator_id = auction.get("creator_id", "")
        has_winner = auction.get("highest_bidder_id")
        seller_type = auction.get("seller_type", "player")
        seller_character_id = auction.get("seller_character_id") or None

        if has_winner:
            winning_amount = auction["highest_bid"]
            winner_id = auction["highest_bidder_id"]
            winner_bid = self.db.get_bidder_active_bid(auction_id, winner_id)
            winner_character_id = winner_bid.get("bidder_character_id") if winner_bid else None
            settled = await self._settle(
                winner_id, creator_id, winning_amount,
                seller_type=seller_type,
                winner_character_id=winner_character_id,
                seller_character_id=seller_character_id,
            )
            if not settled:
                log.error(
                    "Auction #%d: settle FAILED for $%s — funds remain in escrow, use /auction reconcile",
                    auction_id,
                    f"{winning_amount:,}",
                )
            else:
                escrowed_bids = self.db.get_escrowed_bids(auction_id)
                for bid in escrowed_bids:
                    if str(bid["bidder_id"]) == winner_id and bid["amount"] == winning_amount:
                        self.db.update_bid(bid["id"], escrowed_amount=0)
                        break

        # Safety: refund any remaining escrowed bids (shouldn't exist)
        for bid in self.db.get_escrowed_bids(auction_id):
            bid_character_id = bid.get("bidder_character_id") or None
            refunded = await self._refund(bid["bidder_id"], bid["escrowed_amount"], character_id=bid_character_id)
            if refunded:
                self.db.update_bid(bid["id"], escrowed_amount=0)
            else:
                log.error(
                    "Auction #%d: refund FAILED for bid #%d ($%s) — use /auction reconcile",
                    auction_id,
                    bid["id"],
                    f"{bid['escrowed_amount']:,}",
                )

        self.db.update_auction(auction_id, status="closed", finalised_at=datetime.now(timezone.utc).isoformat())
        self._last_embed_update.pop(auction_id, None)

        channel_id = int(auction["channel_id"])
        channel = self.bot.get_channel(channel_id)
        if not channel:
            return

        closed_auction = self.db.get_auction(auction_id)
        embed = build_closed_embed(closed_auction)

        content = None
        if closed_auction.get("highest_bidder_id"):
            content = f"<@{closed_auction['highest_bidder_id']}>"

        await channel.send(content=content, embed=embed)

        message_id = auction.get("message_id")
        if message_id:
            try:
                msg = await channel.fetch_message(int(message_id))
                await msg.delete()
            except Exception:
                pass

    # --- Background timer ---

    @tasks.loop(seconds=15)
    async def check_auction_timers(self):
        now = datetime.now(timezone.utc)

        for auction in self.db.get_open_auctions():
            status = auction["status"]
            closes_at = datetime.fromisoformat(auction["closes_at"])
            finalisation_seconds = auction["finalisation_seconds"]

            if status == "open" and now >= closes_at:
                deadline = closes_at + timedelta(seconds=finalisation_seconds)
                self.db.update_auction(
                    auction["id"],
                    status="finalising",
                    closes_at=deadline.isoformat(),
                )
                updated = self.db.get_auction(auction["id"])
                await self._update_embed(updated)
                log.info("Auction #%d entered finalising", auction["id"])

            elif status == "finalising":
                if now >= closes_at:
                    await self._close_auction(auction)
                    log.info("Auction #%d closed", auction["id"])

            else:
                last_update = self._last_embed_update.get(auction["id"], 0)
                remaining = (closes_at - now).total_seconds()
                should_update = (
                    remaining < 300
                    or (time.monotonic() - last_update) >= 60
                )
                if should_update:
                    await self._update_embed(auction)
                    self._last_embed_update[auction["id"]] = time.monotonic()

    @check_auction_timers.before_loop
    async def before_check_timers(self):
        await self.bot.wait_until_ready()

    # --- Commands ---

    auction_group = app_commands.Group(
        name="auction",
        description="Manage auctions",
    )

    @auction_group.command(name="create", description="Create and start a new auction")
    @app_commands.describe(
        name="Auction title",
        description="Item description",
        starting_price="Starting bid amount",
        min_increment="Minimum bid increase",
        duration="How long bidding lasts (e.g. 2h, 30m, 1h30m)",
        finalisation_window="Time after last bid before closing (default: 5m)",
        image_url="Optional image URL",
        seller_type="Who receives the payment: player or treasury (default: player)",
    )
    async def auction_create(
        self,
        interaction: discord.Interaction,
        name: str,
        starting_price: int,
        min_increment: int,
        duration: str,
        description: str = "",
        finalisation_window: str = "5m",
        image_url: str = "",
        seller_type: str = "player",
    ):
        if not _is_admin(interaction.user):
            return await interaction.response.send_message(
                "Only admins can create auctions.", ephemeral=True
            )

        if seller_type not in ("player", "treasury"):
            return await interaction.response.send_message(
                "Seller type must be 'player' or 'treasury'.", ephemeral=True
            )

        duration_seconds = _parse_duration(duration)
        if not duration_seconds or duration_seconds < 60:
            return await interaction.response.send_message(
                "Invalid duration. Use format like `2h`, `30m`, `1h30m`. Minimum 1 minute.",
                ephemeral=True,
            )

        if duration_seconds > 604800:
            return await interaction.response.send_message(
                "Duration too long. Maximum 7 days.",
                ephemeral=True,
            )

        finalisation_seconds = _parse_duration(finalisation_window)
        if not finalisation_seconds or finalisation_seconds < 30:
            return await interaction.response.send_message(
                "Invalid finalisation window. Use format like `5m`, `2m30s`. Minimum 30 seconds.",
                ephemeral=True,
            )

        if starting_price < 1:
            return await interaction.response.send_message(
                "Starting price must be at least 1.", ephemeral=True
            )

        if min_increment < 1:
            return await interaction.response.send_message(
                "Minimum increment must be at least 1.", ephemeral=True
            )

        channel_id = str(AUCTION_CHANNEL_ID) if AUCTION_CHANNEL_ID else str(interaction.channel_id)

        existing = self.db.get_active_auction(channel_id)
        if existing:
            return await interaction.response.send_message(
                f"An auction is already active in this channel (#{existing['id']} — {existing['name']}). "
                "Cancel it first with `/auction cancel`.",
                ephemeral=True,
            )

        # Resolve seller character for player-type auctions
        seller_character_id = 0
        if seller_type == "player":
            balance_url = f"{BACKEND_API_URL}/api/auction/balance/?player_id={interaction.user.id}"
            try:
                async with self.bot.http_session.get(balance_url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        seller_character_id = data.get("character_id", 0)
            except Exception:
                pass

        closes_at = (datetime.now(timezone.utc) + timedelta(seconds=duration_seconds)).isoformat()

        auction_id = self.db.create_auction(
            name=name,
            description=description,
            starting_price=starting_price,
            min_increment=min_increment,
            duration_seconds=duration_seconds,
            finalisation_seconds=finalisation_seconds,
            image_url=image_url or None,
            channel_id=channel_id,
            creator_id=str(interaction.user.id),
            creator_name=interaction.user.display_name,
            seller_type=seller_type,
            seller_character_id=seller_character_id,
            closes_at=closes_at,
        )

        auction = self.db.get_auction(auction_id)
        embed = build_live_embed(auction)

        await interaction.response.send_message(embed=embed)
        msg = await interaction.original_response()
        self.db.set_message_id(auction_id, str(msg.id))

        log.info("Auction #%d created by %s: %s", auction_id, interaction.user.display_name, name)

    @auction_group.command(name="bid", description="Place a bid on the active auction")
    @app_commands.describe(amount="Your bid amount (must exceed current highest bid + min increment)")
    async def auction_bid(self, interaction: discord.Interaction, amount: int):
        channel_id = str(interaction.channel_id)
        auction = self.db.get_active_auction(channel_id)

        if not auction:
            return await interaction.response.send_message(
                "No active auction in this channel.", ephemeral=True
            )

        auction_id = auction["id"]
        bidder_id = str(interaction.user.id)

        if amount < 1:
            return await interaction.response.send_message(
                "Bid amount must be at least 1.", ephemeral=True
            )

        if bidder_id == auction["creator_id"]:
            return await interaction.response.send_message(
                "You can't bid on your own auction.", ephemeral=True
            )

        if bidder_id == auction.get("highest_bidder_id"):
            return await interaction.response.send_message(
                "You're already the highest bidder. No need to outbid yourself!",
                ephemeral=True,
            )

        min_required = auction["highest_bid"] + auction["min_increment"]

        if amount < min_required:
            return await interaction.response.send_message(
                f"Bid too low. Minimum bid is ${min_required:,} "
                f"(current ${auction['highest_bid']:,} + ${auction['min_increment']:,} increment).",
                ephemeral=True,
            )

        # Step 1: If this bidder has a previous bid on this auction, refund it first
        previous_bid = self.db.get_bidder_active_bid(auction_id, bidder_id)
        if previous_bid and previous_bid.get("escrowed_amount", 0) > 0:
            prev_char_id = previous_bid.get("bidder_character_id") or None
            refunded = await self._refund(bidder_id, previous_bid["escrowed_amount"], character_id=prev_char_id)
            if refunded:
                self.db.update_bid(previous_bid["id"], escrowed_amount=0)
            else:
                log.warning(
                    "Auction #%d: failed to refund previous bid #%d for %s — continuing",
                    auction_id,
                    previous_bid["id"],
                    bidder_id,
                )

        # Step 2: Escrow the new bid amount
        balance, character_id, escrow_error = await self._escrow(bidder_id, amount)
        if escrow_error:
            return await interaction.response.send_message(escrow_error, ephemeral=True)

        # Re-check auction is still active (could have closed during the await above)
        auction = self.db.get_active_auction(channel_id)
        if not auction or auction["id"] != auction_id:
            await self._refund(bidder_id, amount, character_id=character_id)
            return await interaction.response.send_message(
                "This auction is no longer active.", ephemeral=True
            )

        # Step 3: Refund the previous highest bidder (if different person)
        old_winner_id = auction.get("highest_bidder_id")
        if old_winner_id and old_winner_id != bidder_id:
            old_winner_bid = self.db.get_bidder_active_bid(auction_id, old_winner_id)
            if old_winner_bid and old_winner_bid.get("escrowed_amount", 0) > 0:
                old_char_id = old_winner_bid.get("bidder_character_id") or None
                refunded = await self._refund(old_winner_id, old_winner_bid["escrowed_amount"], character_id=old_char_id)
                if refunded:
                    self.db.update_bid(old_winner_bid["id"], escrowed_amount=0)
                else:
                    log.error(
                        "Auction #%d: failed to refund outbid player %s ($%s) — use /auction reconcile",
                        auction_id,
                        old_winner_id,
                        f"{old_winner_bid['escrowed_amount']:,}",
                    )

        # Step 4: Record the bid
        self.db.place_bid(
            auction_id=auction_id,
            bidder_id=bidder_id,
            bidder_name=interaction.user.display_name,
            bidder_character_id=character_id or 0,
            amount=amount,
            escrowed_amount=amount,
        )

        # If auction is in finalising, extend the deadline (anti-snipe)
        updated_auction = self.db.get_auction(auction_id)
        if updated_auction["status"] == "finalising":
            new_deadline = (
                datetime.now(timezone.utc) + timedelta(seconds=auction["finalisation_seconds"])
            ).isoformat()
            self.db.update_auction(auction_id, closes_at=new_deadline)
            updated_auction = self.db.get_auction(auction_id)

        # Immediately update embed (bypass throttle)
        self._last_embed_update[auction_id] = time.monotonic()
        await self._update_embed(updated_auction)

        await interaction.response.send_message(
            f"Bid of **${amount:,}** accepted! Funds escrowed. "
            f"(Remaining balance: ${balance:,})",
            ephemeral=True,
        )

        log.info(
            "Auction #%d: %s bid $%s",
            auction_id,
            interaction.user.display_name,
            f"{amount:,}",
        )

    @auction_group.command(name="cancel", description="Cancel the active auction")
    async def auction_cancel(self, interaction: discord.Interaction):
        if not _is_admin(interaction.user):
            return await interaction.response.send_message(
                "Only admins can cancel auctions.", ephemeral=True
            )

        channel_id = str(interaction.channel_id)
        auction = self.db.get_active_auction(channel_id)

        if not auction:
            return await interaction.response.send_message(
                "No active auction in this channel.", ephemeral=True
            )

        auction_id = auction["id"]

        # Refund all escrowed bids
        for bid in self.db.get_escrowed_bids(auction_id):
            bid_char_id = bid.get("bidder_character_id") or None
            refunded = await self._refund(bid["bidder_id"], bid["escrowed_amount"], character_id=bid_char_id)
            if refunded:
                self.db.update_bid(bid["id"], escrowed_amount=0)
            else:
                log.error(
                    "Auction #%d cancel: refund FAILED for bid #%d ($%s) — use /auction reconcile",
                    auction_id,
                    bid["id"],
                    f"{bid['escrowed_amount']:,}",
                )

        self.db.update_auction(
            auction_id,
            status="cancelled",
            finalised_at=datetime.now(timezone.utc).isoformat(),
        )
        self._last_embed_update.pop(auction_id, None)

        message_id = auction.get("message_id")
        if message_id:
            try:
                msg = await interaction.channel.fetch_message(int(message_id))
                await msg.delete()
            except Exception:
                pass

        embed = build_cancelled_embed(auction)
        await interaction.response.send_message(embed=embed)

        log.info("Auction #%d cancelled by %s", auction_id, interaction.user.display_name)

    @auction_group.command(name="reconcile", description="Reconcile outstanding escrows on closed/cancelled auctions")
    async def auction_reconcile(self, interaction: discord.Interaction):
        if not _is_admin(interaction.user):
            return await interaction.response.send_message(
                "Only admins can reconcile auctions.", ephemeral=True
            )

        escrowed_bids = self.db.get_all_escrowed_bids()
        if not escrowed_bids:
            return await interaction.response.send_message(
                "No outstanding escrows to reconcile.", ephemeral=True
            )

        results: list[str] = []
        for bid in escrowed_bids:
            auction = self.db.get_auction(bid["auction_id"])
            if not auction:
                results.append(f"Bid #{bid['id']}: Auction not found — skipping")
                continue

            auction_id = auction["id"]
            status = auction["status"]

            if status not in ("closed", "cancelled"):
                results.append(f"Bid #{bid['id']}: Auction #{auction_id} still active — skipping")
                continue

            if status == "closed" and auction.get("highest_bidder_id") == bid["bidder_id"] and bid["amount"] == auction["highest_bid"]:
                seller_type = auction.get("seller_type", "player")
                seller_character_id = auction.get("seller_character_id") or None
                bid_char_id = bid.get("bidder_character_id") or None
                settled = await self._settle(
                    bid["bidder_id"],
                    auction["creator_id"],
                    bid["escrowed_amount"],
                    seller_type=seller_type,
                    winner_character_id=bid_char_id,
                    seller_character_id=seller_character_id,
                )
                if settled:
                    self.db.update_bid(bid["id"], escrowed_amount=0)
                    results.append(f"Bid #{bid['id']}: Settled ${bid['escrowed_amount']:,} to seller")
                else:
                    results.append(f"Bid #{bid['id']}: Settle FAILED — ${bid['escrowed_amount']:,} still escrowed")
            else:
                bid_char_id = bid.get("bidder_character_id") or None
                refunded = await self._refund(bid["bidder_id"], bid["escrowed_amount"], character_id=bid_char_id)
                if refunded:
                    self.db.update_bid(bid["id"], escrowed_amount=0)
                    results.append(f"Bid #{bid['id']}: Refunded ${bid['escrowed_amount']:,}")
                else:
                    results.append(f"Bid #{bid['id']}: Refund FAILED — ${bid['escrowed_amount']:,} still escrowed")

        embed = discord.Embed(
            title="Auction Reconciliation",
            description="\n".join(results),
            color=discord.Color.blurple(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @auction_group.command(name="history", description="View recent auction results")
    async def auction_history(self, interaction: discord.Interaction):
        auctions = self.db.get_recent_auctions(limit=10)
        embed = build_history_embed(auctions)
        await interaction.response.send_message(embed=embed, ephemeral=True)
