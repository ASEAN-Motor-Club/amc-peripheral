"""SQLite persistence layer for the auction system."""

from datetime import datetime, timezone

from sqlite_utils import Database


class AuctionDB:
    def __init__(self, db_path: str):
        self.db = Database(db_path)
        self.db.conn.execute("PRAGMA busy_timeout = 5000")
        self._ensure_tables()

    def _ensure_tables(self):
        if "auctions" not in self.db.table_names():
            # pyrefly: ignore [missing-attribute]
            self.db["auctions"].create(
                {
                    "id": int,
                    "name": str,
                    "description": str,
                    "starting_price": int,
                    "min_increment": int,
                    "duration_seconds": int,
                    "finalisation_seconds": int,
                    "image_url": str,
                    "channel_id": str,
                    "creator_id": str,
                    "creator_name": str,
                    "seller_type": str,
                    "seller_character_id": int,
                    "status": str,
                    "highest_bid": int,
                    "highest_bidder_id": str,
                    "highest_bidder_name": str,
                    "total_bids": int,
                    "closes_at": str,
                    "finalised_at": str,
                    "message_id": str,
                    "created_at": str,
                },
                pk="id",
            )
            # pyrefly: ignore [missing-attribute]
            self.db["auctions"].create_index(["channel_id", "status"])
            # pyrefly: ignore [missing-attribute]
            self.db["auctions"].create_index(["status"])

        if "auction_bids" not in self.db.table_names():
            # pyrefly: ignore [missing-attribute]
            self.db["auction_bids"].create(
                {
                    "id": int,
                    "auction_id": int,
                    "bidder_id": str,
                    "bidder_name": str,
                    "bidder_character_id": int,
                    "amount": int,
                    "escrowed_amount": int,
                    "bid_at": str,
                },
                pk="id",
            )
            # pyrefly: ignore [missing-attribute]
            self.db["auction_bids"].create_index(["auction_id"])
            # pyrefly: ignore [missing-attribute]
            self.db["auction_bids"].create_index(["bidder_id"])

    def create_auction(
        self,
        *,
        name: str,
        description: str,
        starting_price: int,
        min_increment: int,
        duration_seconds: int,
        finalisation_seconds: int,
        image_url: str | None,
        channel_id: str,
        creator_id: str,
        creator_name: str,
        seller_type: str,
        seller_character_id: int,
        closes_at: str,
    ) -> int:
        now = datetime.now(timezone.utc).isoformat()
        row = {
            "name": name,
            "description": description or "",
            "starting_price": starting_price,
            "min_increment": min_increment,
            "duration_seconds": duration_seconds,
            "finalisation_seconds": finalisation_seconds,
            "image_url": image_url or "",
            "channel_id": channel_id,
            "creator_id": creator_id,
            "creator_name": creator_name,
            "seller_type": seller_type,
            "seller_character_id": seller_character_id,
            "status": "open",
            "highest_bid": starting_price,
            "highest_bidder_id": "",
            "highest_bidder_name": "",
            "total_bids": 0,
            "closes_at": closes_at,
            "finalised_at": "",
            "message_id": "",
            "created_at": now,
        }
        # pyrefly: ignore [missing-attribute]
        return self.db["auctions"].insert(row).last_pk

    def get_active_auction(self, channel_id: str) -> dict | None:
        rows = list(
            self.db["auctions"].rows_where(
                "channel_id = ? AND status IN ('open', 'finalising')",
                [channel_id],
                order_by="id desc",
                limit=1,
            )
        )
        return rows[0] if rows else None

    def get_auction(self, auction_id: int) -> dict | None:
        rows = list(self.db["auctions"].rows_where("id = ?", [auction_id]))
        return rows[0] if rows else None

    def update_auction(self, auction_id: int, **kwargs) -> None:
        # pyrefly: ignore [missing-attribute]
        self.db["auctions"].update(auction_id, kwargs)

    def place_bid(
        self,
        *,
        auction_id: int,
        bidder_id: str,
        bidder_name: str,
        bidder_character_id: int,
        amount: int,
        escrowed_amount: int = 0,
    ) -> int:
        now = datetime.now(timezone.utc).isoformat()
        row = {
            "auction_id": auction_id,
            "bidder_id": bidder_id,
            "bidder_name": bidder_name,
            "bidder_character_id": bidder_character_id,
            "amount": amount,
            "escrowed_amount": escrowed_amount,
            "bid_at": now,
        }
        # pyrefly: ignore [missing-attribute]
        bid_id = self.db["auction_bids"].insert(row).last_pk

        total_bids = list(
            self.db.query(
                "SELECT COUNT(*) as cnt FROM auction_bids WHERE auction_id = ?",
                [auction_id],
            )
        )[0]["cnt"]

        self.update_auction(
            auction_id,
            highest_bid=amount,
            highest_bidder_id=bidder_id,
            highest_bidder_name=bidder_name,
            total_bids=total_bids,
        )
        return bid_id

    def set_message_id(self, auction_id: int, message_id: str) -> None:
        self.update_auction(auction_id, message_id=message_id)

    def update_bid(self, bid_id: int, **kwargs) -> None:
        # pyrefly: ignore [missing-attribute]
        self.db["auction_bids"].update(bid_id, kwargs)

    def get_bidder_active_bid(self, auction_id: int, bidder_id: str) -> dict | None:
        rows = list(
            self.db["auction_bids"].rows_where(
                "auction_id = ? AND bidder_id = ?",
                [auction_id, bidder_id],
                order_by="id desc",
                limit=1,
            )
        )
        return rows[0] if rows else None

    def get_escrowed_bids(self, auction_id: int) -> list[dict]:
        return list(
            self.db["auction_bids"].rows_where(
                "auction_id = ? AND escrowed_amount > 0",
                [auction_id],
                order_by="id asc",
            )
        )

    def get_all_escrowed_bids(self) -> list[dict]:
        return list(
            self.db["auction_bids"].rows_where(
                "escrowed_amount > 0",
                order_by="id asc",
            )
        )

    def get_open_auctions(self) -> list[dict]:
        return list(
            self.db["auctions"].rows_where(
                "status IN ('open', 'finalising')",
                order_by="closes_at asc",
            )
        )

    def get_recent_auctions(self, limit: int = 10) -> list[dict]:
        return list(
            self.db["auctions"].rows_where(
                "status IN ('closed', 'cancelled')",
                order_by="finalised_at desc",
                limit=limit,
            )
        )

    def get_bids(self, auction_id: int, limit: int = 50) -> list[dict]:
        return list(
            self.db["auction_bids"].rows_where(
                "auction_id = ?",
                [auction_id],
                order_by="bid_at desc",
                limit=limit,
            )
        )
