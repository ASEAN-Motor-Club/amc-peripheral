"""Claim display: the item page states ownership, and only members see the owner view."""

from __future__ import annotations

from amc_peripheral.workshop.community import CommunityStore

NOW = "2026-11-18T15:00:00Z"
DISCORD = "9001"


def seed_claim(settings, workshop_id: int = 1, *, name: str = "Driver"):
    store = CommunityStore(settings.site_db)
    store.upsert_claim(
        workshop_id=workshop_id,
        discord_id=DISCORD,
        steam_id="76561198000000000",
        character_guid="8F14E45FCEEA167A5A36DEDD4BEA2543",
        now=NOW,
    )
    store.save_profile(discord_id=DISCORD, display_name=name, bio=None, now=NOW)
    return store


async def test_item_page_shows_claim_and_profile_name(client, settings):
    seed_claim(settings)

    response = await client.get("/workshop/items/1/")
    text = await response.text()

    assert response.status == 200
    assert "Claimed" in text
    assert "by Driver" in text
    # Anonymous visitors never get the "this is yours" affordance.
    assert "this is your build" not in text


async def test_unclaimed_item_carries_no_claim_line(client, settings):
    seed_claim(settings, workshop_id=1)

    response = await client.get("/workshop/items/3/")
    text = await response.text()

    assert response.status == 200
    assert "Claimed" not in text


async def test_revoked_claim_is_not_advertised(client, settings):
    store = seed_claim(settings)
    store.revoke_claim(1, "2026-11-18T16:00:00Z")

    text = await (await client.get("/workshop/items/1/")).text()

    assert "Claimed" not in text


async def test_hidden_profile_hides_the_name_but_keeps_the_claim(client, settings):
    store = seed_claim(settings, name="Driver")
    store.set_hidden(hidden=True, discord_id=DISCORD, now=NOW)

    text = await (await client.get("/workshop/items/1/")).text()

    assert "Claimed" in text
    assert "by Driver" not in text
    assert "by a club member" in text
