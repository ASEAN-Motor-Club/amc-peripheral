"""Tests for the game-knowledge subagent tool-guidance fixes.

Background (freeman "Air City" failure, 2026-09-16): the subagent's
`lookup_knowledge` tool read ONLY the DJ wiki (0 pages) and its empty-wiki
result said nothing about where game data actually lives, so the model
burned its small iteration budget on raw SQL guesses and never reached
`lookup_vehicle`. Fixes under test:
- `lookup_knowledge` searches BOTH wikis (game DokuWiki corpus via
  wiki_kb + the DJ wiki) and returns labeled sections (freeman:
  "making the lookup search both wikis");
- the tool description clarifies the two sources (freeman: "clarifying
  the tool calls");
- MAX_ITERATIONS raised 3 -> 5 so one wrong first step doesn't exhaust
  the loop.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from amc_peripheral.radio import game_knowledge


@pytest.fixture()
def empty_storage():
    """A WikiStorage on a fresh in-memory DB (0 pages)."""
    storage = game_knowledge.WikiStorage(db_path=":memory:")
    yield storage
    storage.conn.close()


class TestLookupKnowledgeSearchesBothWikis:
    """lookup_knowledge returns labeled sections from BOTH sources."""

    def test_game_wiki_hit_found_via_empty_dj_wiki(self, empty_storage):
        # the Air City case: DJ wiki empty, game wiki has the vehicle page
        result = game_knowledge._lookup_knowledge("Air City", empty_storage)
        assert "[Game wiki]" in result
        assert "vehicle" in result
        assert "Air City" in result

    def test_game_wiki_section_points_at_lookup_verbs(self, empty_storage):
        result = game_knowledge._lookup_knowledge("Air City", empty_storage)
        assert "lookup_vehicle" in result

    def test_dj_wiki_section_always_present(self, empty_storage):
        result = game_knowledge._lookup_knowledge("Air City", empty_storage)
        assert "[DJ wiki]" in result

    def test_dj_wiki_hit_returned_labeled(self, empty_storage):
        empty_storage.create_page(
            title="Friday convoy",
            category="event",
            content="Weekly convoy organized by the community.",
        )
        result = game_knowledge._lookup_knowledge("convoy", empty_storage)
        assert "[DJ wiki]" in result
        assert "Friday convoy" in result

    def test_no_hits_still_names_both_sources(self, empty_storage):
        result = game_knowledge._lookup_knowledge("zzz_nomatch_zzz", empty_storage)
        assert "[Game wiki]" in result
        assert "[DJ wiki]" in result
        # and the no-hit guidance still nudges toward the lookup verbs
        assert "lookup_vehicle" in result

    def test_empty_topic_still_short_circuits(self, empty_storage):
        result = game_knowledge._lookup_knowledge("", empty_storage)
        assert result == "No knowledge available."


class TestToolDescription:
    def test_description_clarifies_both_sources(self):
        tools = game_knowledge._build_tools("schema text")
        desc = next(
            t["function"]["description"]
            for t in tools
            if t["function"]["name"] == "lookup_knowledge"
        )
        assert "game wiki" in desc.lower()
        assert "dj wiki" in desc.lower()
        assert "lookup_vehicle" in desc


class TestMaxIterations:
    def test_max_iterations_is_five(self):
        assert game_knowledge.MAX_ITERATIONS == 5


class TestSqlToolIsAmcOnly:
    """freeman: remove the SQL game-knowledge tool; keep query_amc_database
    for player/server data with a description that says game facts come
    from the wiki, never SQL."""

    def test_no_query_game_database_tool(self):
        tools = game_knowledge._build_tools("guide text")
        names = [t["function"]["name"] for t in tools]
        assert "query_game_database" not in names

    def test_query_amc_database_description_scopes_to_player_data(self):
        tools = game_knowledge._build_tools("guide text")
        desc = next(
            t["function"]["description"]
            for t in tools
            if t["function"]["name"] == "query_amc_database"
        )
        # positive scope: player/server operations data
        assert "players" in desc.lower()
        assert "deliveries" in desc.lower() or "jobs" in desc.lower()
        # negative scope: not for game knowledge
        assert "do not" in desc.lower() or "not" in desc.lower()
        assert "no game data tables" in desc.lower()
        # redirect: names the wiki tools for game facts
        assert "lookup_vehicle" in desc
        assert "lookup_knowledge" in desc

    @pytest.mark.asyncio
    async def test_sql_tool_still_executes_against_backend_db(self, monkeypatch):
        mock_execute = MagicMock(
            return_value={"results": [{"player": "x"}], "count": 1}
        )
        monkeypatch.setattr("amc_peripheral.bot.backend_db.execute_query", mock_execute)
        result = await game_knowledge._execute_tool(
            "query_amc_database",
            {"sql": "SELECT player FROM amc_player"},
            AsyncMock(),
        )
        assert "player" in result.lower()

    def test_system_prompt_bans_sql_for_game_facts(self, empty_storage):
        """The subagent system prompt must say game facts come only from
        wiki tools and that query_amc_database has no game tables."""
        import inspect

        src = inspect.getsource(game_knowledge.ask_game_knowledge)
        assert "ONLY from the wiki" in src
        assert "never from SQL" in src
        assert "NO game tables" in src
