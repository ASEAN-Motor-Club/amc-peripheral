"""Embed builders for the auction system."""

from datetime import datetime, timezone

import discord


def _fmt_amount(amount: int) -> str:
    return f"${amount:,}"


def _time_remaining(closes_at_str: str) -> str:
    try:
        closes_at = datetime.fromisoformat(closes_at_str)
        now = datetime.now(timezone.utc)
        delta = closes_at - now
        if delta.total_seconds() <= 0:
            return "Ended"
        hours, remainder = divmod(int(delta.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours > 0:
            return f"{hours}h {minutes}m {seconds}s"
        return f"{minutes}m {seconds}s"
    except Exception:
        return "Unknown"


def build_live_embed(auction: dict) -> discord.Embed:
    status = auction.get("status", "open")
    status_label = {
        "open": "OPEN — Accepting Bids",
        "finalising": "FINALISING — Going Once…",
    }.get(status, status.upper())

    color = discord.Color.green() if status == "open" else discord.Color.orange()

    embed = discord.Embed(
        title=f"Auction #{auction['id']}: {auction['name']}",
        description=auction.get("description") or "",
        color=color,
    )

    if auction.get("image_url"):
        embed.set_thumbnail(url=auction["image_url"])

    embed.add_field(
        name="Status",
        value=status_label,
        inline=True,
    )
    embed.add_field(
        name="Starting Price",
        value=_fmt_amount(auction["starting_price"]),
        inline=True,
    )
    embed.add_field(
        name="Min Increment",
        value=_fmt_amount(auction["min_increment"]),
        inline=True,
    )

    highest_bidder = auction.get("highest_bidder_name") or "No bids yet"
    if auction.get("highest_bidder_id"):
        bid_display = f"{_fmt_amount(auction['highest_bid'])} by {highest_bidder}"
    else:
        bid_display = f"Starting at {_fmt_amount(auction['starting_price'])}"
    embed.add_field(
        name="Current Bid",
        value=bid_display,
        inline=False,
    )

    total_bids = auction.get("total_bids", 0)
    embed.add_field(
        name="Total Bids",
        value=str(total_bids),
        inline=True,
    )

    time_left = _time_remaining(auction["closes_at"])
    embed.add_field(
        name="Time Remaining",
        value=time_left,
        inline=True,
    )

    finalisation_seconds = auction.get("finalisation_seconds", 300)
    if finalisation_seconds >= 60:
        finalisation_display = f"{finalisation_seconds // 60}m"
    else:
        finalisation_display = f"{finalisation_seconds}s"
    embed.add_field(
        name="Anti-Snipe Window",
        value=finalisation_display,
        inline=True,
    )

    embed.set_footer(text=f"Created by {auction.get('creator_name', 'Unknown')}" + (" • Treasury Sale" if auction.get("seller_type") == "treasury" else ""))

    return embed


def build_closed_embed(auction: dict) -> discord.Embed:
    embed = discord.Embed(
        title=f"Auction #{auction['id']}: {auction['name']} — CLOSED",
        description=auction.get("description") or "",
        color=discord.Color.gold(),
    )

    if auction.get("image_url"):
        embed.set_thumbnail(url=auction["image_url"])

    winner = auction.get("highest_bidder_name") or "No bids"
    winning_bid = _fmt_amount(auction["highest_bid"])

    if auction.get("highest_bidder_id"):
        embed.add_field(
            name="Winner",
            value=f"{winner} — {winning_bid}",
            inline=False,
        )
    else:
        embed.add_field(
            name="Result",
            value="No bids were placed.",
            inline=False,
        )

    embed.add_field(
        name="Total Bids",
        value=str(auction.get("total_bids", 0)),
        inline=True,
    )
    embed.add_field(
        name="Starting Price",
        value=_fmt_amount(auction["starting_price"]),
        inline=True,
    )

    if auction.get("seller_type") == "treasury":
        footer = "Funds have been transferred to the Treasury automatically."
    else:
        footer = "Funds have been transferred to the seller automatically."
    embed.set_footer(text=footer)

    return embed


def build_cancelled_embed(auction: dict) -> discord.Embed:
    embed = discord.Embed(
        title=f"Auction #{auction['id']}: {auction['name']} — CANCELLED",
        description=auction.get("description") or "",
        color=discord.Color.red(),
    )
    embed.add_field(
        name="Starting Price",
        value=_fmt_amount(auction["starting_price"]),
        inline=True,
    )
    embed.add_field(
        name="Total Bids",
        value=str(auction.get("total_bids", 0)),
        inline=True,
    )
    embed.set_footer(text="This auction has been cancelled by an admin.")
    return embed


def build_history_embed(auctions: list[dict]) -> discord.Embed:
    embed = discord.Embed(
        title="Auction History",
        color=discord.Color.blurple(),
    )

    if not auctions:
        embed.description = "No completed auctions yet."
        return embed

    for a in auctions[:10]:
        status_icon = "✅" if a["status"] == "closed" else "❌"
        has_bids = a.get("highest_bidder_id")
        if has_bids:
            winner = a.get("highest_bidder_name") or "Unknown"
            value = f"Winner: {winner} ({_fmt_amount(a['highest_bid'])})"
        else:
            value = "No bids placed"
        embed.add_field(
            name=f"{status_icon} #{a['id']}: {a['name']}",
            value=value,
            inline=False,
        )

    return embed
