import pytest
from datetime import datetime, timezone, timedelta
from amc_peripheral.bot.auction_views import (
    _fmt_amount,
    _time_remaining,
    build_live_embed,
    build_closed_embed,
    build_cancelled_embed,
    build_history_embed,
)
import discord


def _make_auction(**kwargs):
    defaults = {
        "id": 1,
        "name": "Test Car",
        "description": "A cool car",
        "starting_price": 1000,
        "min_increment": 500,
        "duration_seconds": 3600,
        "finalisation_seconds": 300,
        "image_url": "",
        "channel_id": "123",
        "creator_id": "999",
        "creator_name": "Admin",
        "seller_type": "player",
        "status": "open",
        "highest_bid": 1000,
        "highest_bidder_id": "",
        "highest_bidder_name": "",
        "total_bids": 0,
        "closes_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        "finalised_at": "",
        "message_id": "",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    defaults.update(kwargs)
    return defaults


class TestFmtAmount:
    def test_thousands(self):
        assert _fmt_amount(1000) == "$1,000"

    def test_zero(self):
        assert _fmt_amount(0) == "$0"

    def test_large(self):
        assert _fmt_amount(1000000) == "$1,000,000"


class TestTimeRemaining:
    def test_future(self):
        future = (datetime.now(timezone.utc) + timedelta(hours=1, minutes=5)).isoformat()
        result = _time_remaining(future)
        assert "h" in result

    def test_past(self):
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        result = _time_remaining(past)
        assert result == "Ended"

    def test_minutes(self):
        future = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
        result = _time_remaining(future)
        assert "m" in result


class TestBuildLiveEmbed:
    def test_open(self):
        auction = _make_auction(status="open")
        embed = build_live_embed(auction)
        assert embed.color == discord.Color.green()
        assert "OPEN" in str(embed.fields[0].value)

    def test_finalising(self):
        auction = _make_auction(status="finalising")
        embed = build_live_embed(auction)
        assert embed.color == discord.Color.orange()
        assert "FINALISING" in str(embed.fields[0].value)

    def test_no_bids(self):
        auction = _make_auction()
        embed = build_live_embed(auction)
        bid_field = [f for f in embed.fields if f.name == "Current Bid"][0]
        assert "Starting at" in bid_field.value

    def test_with_bids(self):
        auction = _make_auction(
            highest_bid=5000,
            highest_bidder_id="111",
            highest_bidder_name="Alice",
        )
        embed = build_live_embed(auction)
        bid_field = [f for f in embed.fields if f.name == "Current Bid"][0]
        assert "$5,000" in bid_field.value
        assert "Alice" in bid_field.value


class TestBuildClosedEmbed:
    def test_winner(self):
        auction = _make_auction(
            status="closed",
            highest_bid=5000,
            highest_bidder_id="111",
            highest_bidder_name="Alice",
        )
        embed = build_closed_embed(auction)
        winner_field = [f for f in embed.fields if f.name == "Winner"][0]
        assert "Alice" in winner_field.value
        assert "$5,000" in winner_field.value

    def test_no_bids(self):
        auction = _make_auction(status="closed")
        embed = build_closed_embed(auction)
        result_field = [f for f in embed.fields if f.name == "Result"][0]
        assert "No bids" in result_field.value


class TestBuildCancelledEmbed:
    def test_cancelled(self):
        auction = _make_auction(status="cancelled")
        embed = build_cancelled_embed(auction)
        assert embed.color == discord.Color.red()
        assert "CANCELLED" in embed.title


class TestBuildHistoryEmbed:
    def test_mixed(self):
        auctions = [
            _make_auction(id=1, name="Car", status="closed", highest_bidder_id="1", highest_bidder_name="Alice", highest_bid=5000),
            _make_auction(id=2, name="Boat", status="cancelled", highest_bidder_id="", highest_bidder_name=""),
            _make_auction(id=3, name="Bike", status="closed", highest_bidder_id="2", highest_bidder_name="Bob", highest_bid=3000),
        ]
        embed = build_history_embed(auctions)
        assert len(embed.fields) == 3

    def test_empty(self):
        embed = build_history_embed([])
        assert "No completed auctions" in embed.description

    def test_no_bids_entry(self):
        auctions = [
            _make_auction(id=1, name="Car", status="cancelled", highest_bidder_id="", highest_bidder_name=""),
        ]
        embed = build_history_embed(auctions)
        assert "No bids placed" in embed.fields[0].value
