# Auction Escrow Plan

## Goal

Move from "balance check at bid time" to "funds escrowed at bid time, refunded on outbid, settled on close". This eliminates the double-spend vulnerability where players can spend in-game after bidding.

## Architecture

### How it works now
```
1. Player bids $5,000
2. Bot checks balance >= $5,000 (read-only, no money moves)
3. Bid accepted — player could spend the $5,000 in-game before auction closes
```

### How it will work
```
1. Player bids $5,000
2. Bot calls POST /auction/escrow/ → deducts $5,000 from player's Checking Account into Auction Escrow
3. If player was previously outbid on this auction, their old escrow is refunded first
4. Bid accepted — $5,000 is locked, player cannot spend it in-game
5. If outbid by another player → POST /auction/refund/ → returns escrow to their Checking Account
6. On auction close → winner's escrow goes to seller, all other escrows already refunded
7. On auction cancel → all escrows refunded
```

### Financial flow (double-entry bookkeeping)

**Escrow (hold funds):**
```
Dr. Auction Escrow (ASSET/BANK, character=None)      $5,000
    Cr. Player Checking Account (LIABILITY/BANK)     $5,000
```
- ASSET debit → Auction Escrow balance increases
- LIABILITY credit → Checking Account balance decreases

**Refund (return on outbid):**
```
Dr. Player Checking Account (LIABILITY/BANK)         $5,000
    Cr. Auction Escrow (ASSET/BANK, character=None)  $5,000
```
- LIABILITY debit → Checking Account balance increases (money back)
- ASSET credit → Auction Escrow balance decreases

**Settle (winner → seller on close):**
```
Dr. Auction Escrow (ASSET/BANK, character=None)      $5,000
    Cr. Seller Checking Account (LIABILITY/BANK)     $5,000
```
- ASSET credit → Auction Escrow balance decreases
- LIABILITY credit → Seller's Checking Account balance increases

### Single shared escrow account

Following the Ministry of Commerce pattern, we use one shared system account:
- `ASSET / BANK / character=None / name="Auction Escrow"`

This works because:
- Each bid's escrowed amount is tracked in the auction DB (per-bid)
- The sum of all outstanding escrowed amounts should equal the Auction Escrow account balance
- The account acts as a holding pool — individual obligations are tracked in the auction DB

### DB schema changes (auction_db.py)

Add `escrowed_amount` column to `auction_bids` table:
- `escrowed_amount: int` — how much is currently held in escrow for this bid
- On new bid: escrowed_amount = bid amount
- On refund: escrowed_amount = 0
- On settle: escrowed_amount = 0

### Backend API changes (auction_routes.py)

**POST /auction/escrow/** — Hold funds for a bid
```json
Request:  { "player_discord_id": "123456", "amount": 5000 }
Response: { "player_id": 42, "discord_user_id": 123456, "character_name": "Alice", "balance": 15000 }
Errors:   404 — player not found / no character
          409 — insufficient funds (balance after deducting would be negative)
```

**POST /auction/refund/** — Return escrowed funds
```json
Request:  { "player_discord_id": "123456", "amount": 5000 }
Response: { "player_id": 42, "discord_user_id": 123456, "character_name": "Alice", "balance": 20000 }
Errors:   404 — player not found / no character
```

**POST /auction/settle/** — Transfer winner's escrow to seller
```json
Request:  { "winner_discord_id": "123456", "seller_discord_id": "789012", "amount": 5000 }
Response: { "winner_id": 42, "seller_id": 17, "amount": 5000 }
Errors:   404 — player/character not found
```

**GET /auction/balance/** — Unchanged, still returns checking account balance

### Bot flow changes (auction_cog.py)

#### auction_bid — new flow
```
1. Validate bid (amount, not creator, not highest bidder, min increment)
2. If bidder has an existing bid on this auction, refund it first:
   - Call POST /auction/refund/ with old bid amount
   - Set old bid's escrowed_amount = 0 in DB
3. Escrow new bid amount:
   - Call POST /auction/escrow/ with new bid amount
   - On 409 (insufficient funds): reject bid, old refund already happened (safe — they get their money back)
   - On success: insert bid with escrowed_amount = amount
4. If previous highest bidder exists (and is different person), refund them:
   - Call POST /auction/refund/ with their bid amount
   - Set their bid's escrowed_amount = 0 in DB
5. Update embed, respond
```

Wait — there's a problem with step 4. If we refund the previous highest bidder immediately when outbid, then they could bid again and the double-spend protection would need to account for the refund. Let me rethink.

Actually, the simpler approach: **only one bid per player per auction is escrowed at a time**. When a player bids:
1. If they have a previous bid on this auction, refund it first
2. Escrow the new amount
3. When someone outbids the current highest bidder, refund the old highest bidder

This means only the current highest bidder has funds locked. All previous bidders are free. This is simpler and matches how real auctions work.

But there's a subtlety: the `get_bidder_exposure` double-spend check. With escrowing, the balance already reflects the deduction. So the balance check is now implicit — if the escrow call succeeds, the player had enough money. The `get_bidder_exposure` check becomes unnecessary because funds are physically removed.

Wait, not quite. With escrowing, we need to check if the player can afford the new bid. Their `checking_account.balance` already reflects any previous escrows (because the money was moved out). So we just need: `checking_account.balance >= new_bid_amount`. No need for `get_bidder_exposure` anymore — the accounting does it for us.

Revised bot flow:

#### auction_bid — revised flow
```
1. Validate bid (amount >= 1, not creator, not highest bidder, min increment)
2. Call POST /auction/escrow/ with the new bid amount
   - 409 → insufficient funds, reject
   - 404 → player not found, reject
   - 200 → funds escrowed, continue
3. If this bidder had a previous bid on this auction, refund it:
   - Call POST /auction/refund/ with old bid amount
   - Mark old bid escrowed_amount = 0
4. If there was a different previous highest bidder, refund them:
   - Call POST /auction/refund/ with their bid amount
   - Mark their bid escrowed_amount = 0
5. Insert new bid with escrowed_amount = amount
6. Update auction highest bid/bidder
7. If finalising, extend deadline
8. Update embed, respond
```

Actually wait — step 2 escrows the new amount first, but what if step 3 or 4 fails (refund API error)? The new funds are locked but old funds aren't returned. This is bad.

Better order: refund first, then escrow. But refund first means the balance goes up, so the escrow might succeed when it shouldn't (player couldn't afford both). No — that's actually correct! The player is swapping one escrow for another. If they had $5k escrowed and want to bid $8k, refunding the $5k gives them their balance back, then escrowing $8k checks if they can afford it.

Revised again:

#### auction_bid — final flow
```
1. Validate bid (amount >= 1, not creator, not highest bidder, min increment)
2. If this bidder had a previous bid on this auction, refund it first:
   - Call POST /auction/refund/ with old bid amount
   - Mark old bid escrowed_amount = 0
3. Escrow new bid amount:
   - Call POST /auction/escrow/ with the new bid amount
   - On failure: reject bid (their old bid was already refunded — they got their money back)
4. If there was a different previous highest bidder, refund them:
   - Call POST /auction/refund/ with their bid amount
   - Mark their bid escrowed_amount = 0
5. Insert new bid with escrowed_amount = amount
6. Update auction (highest bid/bidder/total_bids)
7. If finalising, extend deadline
8. Update embed, respond
```

Step 4 could also fail (API error). In that case the old highest bidder's money stays escrowed. We should handle this gracefully — the funds aren't lost, they're in the Auction Escrow account. We need a reconciliation mechanism (see below).

#### _close_auction — revised flow
```
1. Set auction status = closed
2. If there's a winner:
   a. Call POST /auction/settle/ with winner_discord_id, seller_discord_id, winning_amount
   b. Mark winning bid's escrowed_amount = 0
3. Post winner embed with ping
4. Delete live embed
```

Note: all non-winning bids should already have been refunded when they were outbid. But as a safety net, check for any remaining escrowed bids and refund them.

#### auction_cancel — revised flow
```
1. Set auction status = cancelled
2. Refund the current highest bidder (if any):
   a. Call POST /auction/refund/ with their bid amount
   b. Mark bid escrowed_amount = 0
3. Safety: refund any other escrowed bids (shouldn't exist, but belt-and-suspenders)
4. Delete live embed, post cancelled embed
```

### Error handling & reconciliation

If a refund/settle API call fails (backend down, network error):
- The funds are safe in the Auction Escrow account — they're not lost
- Log the error prominently
- The auction DB tracks `escrowed_amount` per bid — this is the source of truth for what's owed
- A reconciliation command can be run later to settle outstanding escrows

Add `/auction reconcile` admin command that:
1. Finds all bids with `escrowed_amount > 0` on closed/cancelled auctions
2. For each: refund or settle as appropriate
3. Reports results

### What about the balance check in _check_balance?

The `_check_balance` method and `GET /auction/balance/` endpoint are still useful for:
- Showing the player their balance in error messages ("Insufficient funds. You have $X")
- The escrow endpoint will return the post-escrow balance

But the explicit `balance >= amount` check in `_check_balance` becomes redundant — the escrow endpoint does it atomically. We can simplify `_check_balance` to just return the balance for display purposes, or remove it entirely and let the escrow response provide the balance.

Decision: **remove `_check_balance`**. The escrow endpoint handles everything:
- Returns balance on success (for display in the confirmation message)
- Returns 409 with balance on insufficient funds (for the error message)
- Returns 404 if player not found

### DB changes summary

**auction_db.py — `auction_bids` table:**
- Add `escrowed_amount: int` column (default 0)

**auction_db.py — new methods:**
- `get_bidder_active_bid(auction_id, bidder_id)` — get the bidder's current bid on an auction (if any)
- `get_escrowed_bids(auction_id)` — get all bids with escrowed_amount > 0 for an auction

**auction_cog.py — removed:**
- `_check_balance` method (replaced by escrow endpoint)
- `get_bidder_exposure` usage (no longer needed — accounting handles it)

**auction_routes.py — new endpoints:**
- `POST /auction/escrow/`
- `POST /auction/refund/`
- `POST /auction/settle/`

**auction_routes.py — modified endpoints:**
- `GET /auction/balance/` — kept for error messages, but no longer used for the main flow

### Edge cases

| Case | Handling |
|------|----------|
| Player bids, then outbid, then bids again | Old escrow refunded → new escrow placed. Net: only new amount held |
| Player bids on two different auctions | Each escrow is independent. Player needs balance for both. |
| Backend down during escrow | Bid rejected, no money moved |
| Backend down during refund on outbid | Old bidder's money stays escrowed. Reconcile later. |
| Backend down during settle on close | Winner's money stays escrowed. Reconcile later. |
| Auction cancelled with escrowed bids | All escrowed bids refunded |
| No bids on auction | No escrow operations, just close with no winner |
| Seller not found during settle | Funds stay in escrow. Admin reconciles manually. |
| Player has no bank account | Escrow returns 404, bid rejected |
| Escrow succeeds but bid insert fails (DB error) | Funds locked but no bid record. Reconcile catches this (escrow account has extra funds with no corresponding bid) |

### Implementation order

1. Add `escrowed_amount` column and new DB methods to `auction_db.py`
2. Add `POST /auction/escrow/`, `/refund/`, `/settle/` to `auction_routes.py`
3. Rewrite `auction_bid` to use escrow flow
4. Rewrite `_close_auction` to settle
5. Rewrite `auction_cancel` to refund all
6. Add `/auction reconcile` command
7. Remove `_check_balance` and `get_bidder_exposure` usage
8. Write all tests

---

## Testing

### Test architecture

Two test files are needed:

1. **`amc-backend/src/amc/test_auction_api.py`** — Backend API tests using Django's `TestCase` + `TestAsyncClient`. Tests the escrow/refund/settle endpoints directly against the database. Uses `CharacterFactory` and `PlayerFactory` for test data. Deposits funds via `register_player_deposit` to set up initial balances.

2. **`amc-backend/src/amc/test_auction_escrow.py`** — Financial integrity tests. Verifies double-entry bookkeeping invariants, account balances, and journal entries after escrow operations. Follows the pattern in `test_ministry.py`.

The bot-side (auction_cog.py) is harder to unit test because it depends on Discord interactions and aiohttp sessions. For now, backend tests provide the critical coverage — they validate that the financial operations are correct. Bot integration testing would require mocking Discord's API and the aiohttp session, which is a separate effort.

### Backend API tests (`test_auction_api.py`)

#### Balance endpoint (GET /auction/balance/)

| Test | Setup | Assertion |
|------|-------|-----------|
| `test_get_balance_existing_player` | Player with character, $10,000 deposited | 200, balance=10000 |
| `test_get_balance_no_character` | Player with no character | 404, "No character found" |
| `test_get_balance_unknown_player` | Non-existent discord_user_id | 404, "Player not found" |
| `test_get_balance_zero` | Player with character, no deposit | 200, balance=0 |
| `test_get_balance_invalid_player_id` | player_id="not_a_number" | 404, "Player not found" |

#### Escrow endpoint (POST /auction/escrow/)

| Test | Setup | Assertion |
|------|-------|-----------|
| `test_escrow_success` | Player has $10,000, escrow $5,000 | 200, balance=5000, escrow account balance=5000 |
| `test_escrow_insufficient_funds` | Player has $3,000, escrow $5,000 | 409, error mentions insufficient funds |
| `test_escrow_exact_balance` | Player has $5,000, escrow $5,000 | 200, balance=0 |
| `test_escrow_zero_balance` | Player has $0, escrow $1 | 409 |
| `test_escrow_player_not_found` | Non-existent discord ID | 404 |
| `test_escrow_no_character` | Player with no character | 404 |
| `test_escrow_negative_amount` | amount=-100 | 422 (validation error) |
| `test_escrow_zero_amount` | amount=0 | 422 (validation error) |
| `test_escrow_updates_checking_account` | Deposit $10k, escrow $5k | Checking account balance=5000 |
| `test_escrow_updates_escrow_account` | Deposit $10k, escrow $5k | Auction Escrow account balance=5000 |
| `test_escrow_creates_journal_entry` | Any successful escrow | JournalEntry count=1, description contains "Auction" |
| `test_escrow_two_players` | Two players each escrow $5k | Escrow account balance=10000 |
| `test_escrow_after_refund` | Player escrowed $5k, refunded, escrow $3k | balance reflects both operations |

#### Refund endpoint (POST /auction/refund/)

| Test | Setup | Assertion |
|------|-------|-----------|
| `test_refund_success` | Player has $5k after escrowing $5k from $10k, refund $5k | 200, balance=10000 |
| `test_refund_player_not_found` | Non-existent discord ID | 404 |
| `test_refund_no_character` | Player with no character | 404 |
| `test_refund_negative_amount` | amount=-100 | 422 |
| `test_refund_updates_checking_account` | Escrow then refund | Checking account restored to original |
| `test_refund_updates_escrow_account` | Escrow $5k, refund $5k | Escrow account balance=0 |
| `test_refund_partial` | Escrow $5k, refund $3k | balance=original-2k, escrow=2k |
| `test_refund_creates_journal_entry` | Any successful refund | JournalEntry exists with "Auction" in description |
| `test_refund_escrow_account_integrity` | Two players escrow, refund one | Escrow account balance=only remaining escrow |

#### Settle endpoint (POST /auction/settle/)

| Test | Setup | Assertion |
|------|-------|-----------|
| `test_settle_success` | Winner escrowed $5k, settle to seller | Seller balance+=5k, escrow account-=5k |
| `test_settle_winner_not_found` | Non-existent winner | 404 |
| `test_settle_seller_not_found` | Non-existent seller | 404 |
| `test_settle_winner_no_character` | Winner with no character | 404 |
| `test_settle_seller_no_character` | Seller with no character | 404 |
| `test_settle_updates_escrow_account` | Settle $5k | Escrow account balance-=5k |
| `test_settle_updates_seller_account` | Seller had $0, settle $5k | Seller checking account=5k |
| `test_settle_creates_journal_entry` | Any successful settle | JournalEntry with "Auction" |
| `test_settle_seller_new_account` | Seller has no checking account yet | Creates account, balance=5k |
| `test_settle_zero_amount` | amount=0 | 422 |

### Financial integrity tests (`test_auction_escrow.py`)

These test the full lifecycle with double-entry bookkeeping invariants.

| Test | Description |
|------|-------------|
| `test_full_auction_lifecycle` | Deposit → escrow → outbid refund → new escrow → settle. Verify all account balances at each step. |
| `test_double_entry_invariant` | After each operation (escrow/refund/settle), verify `sum of all account balances = 0` (the fundamental accounting invariant) |
| `test_escrow_account_equals_outstanding_bids` | After multiple escrows and partial refunds, verify `Auction Escrow account balance = sum of all escrowed_amounts in the DB` |
| `test_journal_entry_balanced` | Every journal entry has total_debits == total_credits |
| `test_no_negative_balances` | After any operation, no account has a negative balance |
| `test_cancel_auction_full_refund` | Multiple bidders escrow → cancel auction → all refunded → escrow account=0, all checking accounts restored |
| `test_settle_transfers_to_seller` | Winner's $5k moves from escrow to seller's checking. Winner's checking unchanged (was already deducted). |
| `test_concurrent_escrows_different_players` | Two players escrow simultaneously (sequential in test, but validates independent account tracking) |
| `test_re_escrow_after_refund` | Player A bids $3k (escrowed), outbid (refunded), bids $5k (escrowed). Verify balance at each step. |
| `test_multiple_auctions_same_player` | Player escrows on auction 1 ($3k) and auction 2 ($5k). Verify checking=original-8k, escrow=8k. |

### Edge case / failure tests

| Test | Description |
|------|-------------|
| `test_escrow_succeeds_but_db_fails` | Escrow API call succeeds (money moved), but simulating a subsequent DB write failure. Verify escrow account has the funds and reconcile can recover. |
| `test_refund_failure_during_outbid` | New bidder's escrow succeeds, but refund of old bidder fails. Verify: new bid recorded, old bid still has escrowed_amount > 0 (for later reconcile). |
| `test_settle_failure` | Auction closes, settle API fails. Verify: auction status=closed, bid still has escrowed_amount > 0. Reconcile should catch it. |
| `test_reconcile_after_failed_refund` | Create scenario with escrowed bids on closed auction. Run reconcile. Verify all funds returned. |
| `test_reconcile_after_failed_settle` | Create scenario where settle failed. Run reconcile. Verify funds transferred to seller. |
| `test_reconcile_idempotent` | Run reconcile twice. Second run does nothing (all escrowed_amounts already 0). |
| `test_escrow_amount_mismatch` | Escrow endpoint called with different amount than what the bid records. Verify financial integrity maintained. |

### Auction DB tests (bot-side, `auction_db.py`)

These test the SQLite persistence layer directly — no Discord or network dependencies.

| Test | Description |
|------|-------------|
| `test_create_auction` | Creates auction, verifies all fields |
| `test_get_active_auction` | Creates two auctions (one closed), only returns the active one |
| `test_place_bid` | Places bid, verifies highest_bid/bidder updated |
| `test_place_bid_increments_total` | Multiple bids, total_bids count correct |
| `test_escrowed_amount_default` | New bid has escrowed_amount=0 by default |
| `test_update_escrowed_amount` | Set escrowed_amount=5000, verify it persists |
| `test_get_bidder_active_bid` | Player bids, gets their bid back; player with no bid returns None |
| `test_get_escrowed_bids` | Multiple bids, some with escrowed_amount=0, only returns escrowed ones |
| `test_get_bidder_exposure` | Player has highest bids across multiple active auctions, sum is correct |
| `test_get_bidder_exposure_excludes_outbid` | Player was outbid, exposure excludes that auction |
| `test_cancel_auction_status` | Verify status transitions to cancelled |

### Auction views tests (bot-side, `auction_views.py`)

| Test | Description |
|------|-------------|
| `test_fmt_amount` | 1000 → "$1,000", 0 → "$0" |
| `test_time_remaining_future` | 1 hour from now → "1h 0m 0s" |
| `test_time_remaining_past` | Past timestamp → "Ended" |
| `test_build_live_embed_open` | Open auction, green color, "OPEN — Accepting Bids" |
| `test_build_live_embed_finalising` | Finalising auction, orange color, "FINALISING — Going Once…" |
| `test_build_live_embed_no_bids` | Shows "Starting at $1,000" not "$1,000 by No bids yet" |
| `test_build_live_embed_with_bids` | Shows "$5,000 by Alice" |
| `test_build_closed_embed_winner` | Shows winner name and amount |
| `test_build_closed_embed_no_bids` | Shows "No bids were placed." |
| `test_build_cancelled_embed` | Red color, "CANCELLED" |
| `test_build_history_embed_mixed` | Mix of closed/cancelled auctions with and without bids |

### Integration test: full auction lifecycle

A manual test procedure for end-to-end validation:

1. **Create auction**: Admin runs `/auction create name:"Test Car" starting_price:1000 min_increment:500 duration:5m`
2. **First bid**: Player A bids $1,500 → escrowed, embed updated
3. **Second bid**: Player B bids $2,000 → Player A refunded, Player B escrowed
4. **Self-outbid blocked**: Player B tries $2,500 → rejected ("already highest bidder")
5. **Low bid rejected**: Player C bids $1,000 → rejected ("minimum $2,500")
6. **Insufficient funds**: Player D (no balance) bids $3,000 → rejected (409)
7. **Wait for close**: Timer fires, auction closes, settle called → seller gets $2,000
8. **Verify balances**: Player A restored, Player B debited $2,000, seller credited $2,000, escrow account = 0
9. **Cancel test**: Create another auction, Player A bids, admin cancels → Player A refunded
10. **Reconcile test**: Simulate failed refund, run `/auction reconcile` → funds recovered
