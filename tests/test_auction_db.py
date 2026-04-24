import pytest
from datetime import datetime, timezone, timedelta
from amc_peripheral.bot.auction_db import AuctionDB


@pytest.fixture
def db(tmp_path):
    db_path = tmp_path / "test_auctions.db"
    return AuctionDB(str(db_path))


def _create_auction(db, **kwargs):
    defaults = {
        "name": "Test Auction",
        "description": "Test",
        "starting_price": 1000,
        "min_increment": 500,
        "duration_seconds": 3600,
        "finalisation_seconds": 300,
        "image_url": None,
        "channel_id": "123456",
        "creator_id": "999",
        "creator_name": "Admin",
        "seller_type": "player",
        "seller_character_id": 0,
        "closes_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
    }
    defaults.update(kwargs)
    return db.create_auction(**defaults)


class TestAuctionDB:
    def test_create_auction(self, db):
        auction_id = _create_auction(db)
        auction = db.get_auction(auction_id)
        assert auction is not None
        assert auction["name"] == "Test Auction"
        assert auction["status"] == "open"
        assert auction["highest_bid"] == 1000
        assert auction["total_bids"] == 0

    def test_get_active_auction(self, db):
        a1 = _create_auction(db, channel_id="111")
        a2 = _create_auction(db, channel_id="222")
        db.update_auction(a1, status="closed")

        active = db.get_active_auction("111")
        assert active is None

        active = db.get_active_auction("222")
        assert active is not None
        assert active["id"] == a2

    def test_place_bid(self, db):
        auction_id = _create_auction(db)
        db.place_bid(
            auction_id=auction_id,
            bidder_id="111",
            bidder_name="Alice",
            bidder_character_id=42,
            amount=1500,
            escrowed_amount=1500,
        )
        auction = db.get_auction(auction_id)
        assert auction["highest_bid"] == 1500
        assert auction["highest_bidder_id"] == "111"
        assert auction["total_bids"] == 1

    def test_place_bid_increments_total(self, db):
        auction_id = _create_auction(db)
        db.place_bid(auction_id=auction_id, bidder_id="1", bidder_name="A", bidder_character_id=1, amount=1500, escrowed_amount=1500)
        db.place_bid(auction_id=auction_id, bidder_id="2", bidder_name="B", bidder_character_id=2, amount=2000, escrowed_amount=2000)
        db.place_bid(auction_id=auction_id, bidder_id="1", bidder_name="A", bidder_character_id=1, amount=2500, escrowed_amount=2500)
        auction = db.get_auction(auction_id)
        assert auction["total_bids"] == 3

    def test_escrowed_amount_default(self, db):
        auction_id = _create_auction(db)
        bid_id = db.place_bid(
            auction_id=auction_id,
            bidder_id="111",
            bidder_name="Alice",
            bidder_character_id=42,
            amount=1500,
        )
        bid = list(db.db["auction_bids"].rows_where("id = ?", [bid_id]))[0]
        assert bid["escrowed_amount"] == 0

    def test_update_escrowed_amount(self, db):
        auction_id = _create_auction(db)
        bid_id = db.place_bid(
            auction_id=auction_id,
            bidder_id="111",
            bidder_name="Alice",
            bidder_character_id=42,
            amount=1500,
            escrowed_amount=1500,
        )
        db.update_bid(bid_id, escrowed_amount=0)
        bid = list(db.db["auction_bids"].rows_where("id = ?", [bid_id]))[0]
        assert bid["escrowed_amount"] == 0

    def test_get_bidder_active_bid(self, db):
        auction_id = _create_auction(db)
        db.place_bid(auction_id=auction_id, bidder_id="111", bidder_name="Alice", bidder_character_id=1, amount=1500, escrowed_amount=1500)
        db.place_bid(auction_id=auction_id, bidder_id="222", bidder_name="Bob", bidder_character_id=2, amount=2000, escrowed_amount=2000)

        bid = db.get_bidder_active_bid(auction_id, "111")
        assert bid is not None
        assert bid["bidder_id"] == "111"

        bid = db.get_bidder_active_bid(auction_id, "333")
        assert bid is None

    def test_get_escrowed_bids(self, db):
        auction_id = _create_auction(db)
        db.place_bid(auction_id=auction_id, bidder_id="1", bidder_name="A", bidder_character_id=1, amount=1500, escrowed_amount=1500)
        db.place_bid(auction_id=auction_id, bidder_id="2", bidder_name="B", bidder_character_id=2, amount=2000, escrowed_amount=0)

        escrowed = db.get_escrowed_bids(auction_id)
        assert len(escrowed) == 1
        assert escrowed[0]["bidder_id"] == "1"

    def test_cancel_auction_status(self, db):
        auction_id = _create_auction(db)
        db.update_auction(auction_id, status="cancelled", finalised_at=datetime.now(timezone.utc).isoformat())
        auction = db.get_auction(auction_id)
        assert auction["status"] == "cancelled"

    def test_get_all_escrowed_bids(self, db):
        a1 = _create_auction(db, channel_id="111")
        a2 = _create_auction(db, channel_id="222")

        db.place_bid(auction_id=a1, bidder_id="1", bidder_name="A", bidder_character_id=1, amount=1500, escrowed_amount=1500)
        db.place_bid(auction_id=a2, bidder_id="2", bidder_name="B", bidder_character_id=2, amount=3000, escrowed_amount=3000)

        all_escrowed = db.get_all_escrowed_bids()
        assert len(all_escrowed) == 2
