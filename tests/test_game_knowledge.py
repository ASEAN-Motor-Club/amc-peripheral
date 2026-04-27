import sys
from unittest.mock import MagicMock, AsyncMock

# Mock google.cloud.texttospeech BEFORE importing module that uses it
mock_texttospeech = MagicMock()
mock_texttospeech.TextToSpeechClient = MagicMock()
sys.modules["google.cloud.texttospeech"] = mock_texttospeech
sys.modules["google.cloud"] = MagicMock()
sys.modules["google"] = MagicMock()

import pytest  # noqa: E402

from amc_peripheral.wiki.storage import WikiStorage  # noqa: E402
from amc_peripheral.wiki.index import WikiIndex  # noqa: E402
from amc_peripheral.radio.game_knowledge import (  # noqa: E402
    ask_game_knowledge,
    _execute_tool,
    _build_tools,
    _extract_heading,
    _lookup_knowledge,
)


@pytest.fixture
def wiki_storage(tmp_path):
    """A WikiStorage populated with the kind of entries that used to live in KnowledgeStore."""
    storage = WikiStorage(db_path=str(tmp_path / "wiki.db"))
    storage.create_page(
        title="vehicle:Kira_Van",
        category="vehicle",
        content="## Kira Van\nThe Kira Van is a mid-size delivery van.\nMax cargo: 5000kg.",
        summary="Mid-size delivery van",
    )
    storage.create_page(
        title="vehicle:Gosan_Trucks",
        category="vehicle",
        content="## Gosan Trucks\nGosan manufactures heavy-duty trucks.\nThe G7 can carry up to 24000kg.",
        summary="Gosan truck lineup",
    )
    storage.create_page(
        title="location:Gangjung",
        category="location",
        content="## Gangjung\nGangjung is the capital city.\nIt has the main port and train station.",
        summary="Capital city",
    )
    storage.create_page(
        title="guide:subsidies",
        category="guide",
        content="## Subsidies\nThe government provides delivery subsidies.\nCheck /subsidies for current rates.",
        summary="Subsidy guide",
    )
    return storage


@pytest.fixture
def wiki_index(wiki_storage):
    return WikiIndex(wiki_storage)


@pytest.fixture
def mock_openai():
    return AsyncMock()


@pytest.fixture
def mock_http_session():
    return AsyncMock()


# --- _extract_heading tests ---


def test_extract_heading_markdown():
    """Extract heading from markdown content."""
    assert _extract_heading("## Kira Van\nSome details") == "Kira Van"
    assert _extract_heading("### Gosan G7\nSpecs") == "Gosan G7"
    assert _extract_heading("# Top Level\nContent") == "Top Level"


def test_extract_heading_no_markdown():
    """Falls back to first non-empty line."""
    assert _extract_heading("Just a plain message\nwith more text") == "Just a plain message"


def test_extract_heading_empty():
    """Returns 'Untitled' for empty content."""
    assert _extract_heading("") == "Untitled"
    assert _extract_heading("   \n\n   ") == "Untitled"


# --- _lookup_knowledge tests ---


def test_lookup_exact_match(wiki_storage):
    """Exact topic match returns content."""
    result = _lookup_knowledge("Kira_Van", wiki_storage)
    assert "mid-size delivery van" in result


def test_lookup_partial_match(wiki_storage):
    """Partial keyword match works."""
    result = _lookup_knowledge("gosan", wiki_storage)
    assert "heavy-duty trucks" in result


def test_lookup_multiple_matches(wiki_storage):
    """Multiple matches are returned together."""
    result = _lookup_knowledge("vehicle", wiki_storage)
    assert "Kira" in result
    assert "Gosan" in result


def test_lookup_no_match_shows_available(wiki_storage):
    """No match returns available titles."""
    result = _lookup_knowledge("nonexistent", wiki_storage)
    assert "No wiki pages found" in result


def test_lookup_content_fallback(wiki_storage):
    """Falls back to searching content if title doesn't match."""
    result = _lookup_knowledge("24000kg", wiki_storage)
    assert "Gosan" in result


def test_lookup_empty(tmp_path):
    """Empty wiki returns 'Wiki is empty' marker."""
    empty = WikiStorage(db_path=str(tmp_path / "empty.db"))
    assert "empty" in _lookup_knowledge("test", empty).lower()


# --- _build_tools tests ---


@pytest.mark.asyncio
async def test_build_tools_includes_all_tools():
    """Test that all expected tools are built."""
    tools = _build_tools("TABLE: cargos\n  Columns: id, name")
    tool_names = [t["function"]["name"] for t in tools]

    assert "lookup_knowledge" in tool_names
    assert "list_knowledge" in tool_names
    assert "save_knowledge" in tool_names
    assert "remove_knowledge" in tool_names
    assert "query_game_database" in tool_names
    assert "get_current_subsidies" in tool_names
    assert "get_server_commands" in tool_names


@pytest.mark.asyncio
async def test_build_tools_empty_schema():
    """Test tools build with empty schema."""
    tools = _build_tools("")
    assert len(tools) == 7  # lookup + list + save + remove + query + subsidies + commands


# --- _execute_tool tests ---


@pytest.mark.asyncio
async def test_execute_tool_lookup_knowledge(wiki_storage):
    """Test lookup_knowledge tool execution routes through the wiki."""
    result = await _execute_tool(
        "lookup_knowledge",
        {"topic": "Kira"},
        AsyncMock(),
        wiki_storage=wiki_storage,
    )
    assert "mid-size delivery van" in result


@pytest.mark.asyncio
async def test_execute_tool_list_knowledge(wiki_storage):
    """Test list_knowledge tool execution filters by category."""
    result = await _execute_tool(
        "list_knowledge",
        {"type_filter": "vehicle"},
        AsyncMock(),
        wiki_storage=wiki_storage,
    )
    assert "vehicle:Kira_Van" in result
    assert "vehicle:Gosan_Trucks" in result


@pytest.mark.asyncio
async def test_execute_tool_save_knowledge_creates_page(wiki_storage):
    """save_knowledge creates a new wiki page when the key is new."""
    result = await _execute_tool(
        "save_knowledge",
        {"key": "vehicle:New_Car", "content": "A shiny new car."},
        AsyncMock(),
        wiki_storage=wiki_storage,
    )
    assert "Saved" in result
    page = wiki_storage.get_page_by_slug("vehicle:New_Car")
    assert page is not None
    assert page["category"] == "vehicle"
    assert "shiny new car" in page["content"]


@pytest.mark.asyncio
async def test_execute_tool_save_knowledge_updates_page(wiki_storage):
    """save_knowledge updates an existing wiki page instead of duplicating it."""
    result = await _execute_tool(
        "save_knowledge",
        {
            "key": "vehicle:Kira_Van",
            "content": "## Kira Van (updated)\nUpdated description.",
        },
        AsyncMock(),
        wiki_storage=wiki_storage,
    )
    assert "Updated" in result
    page = wiki_storage.get_page_by_slug("vehicle:Kira_Van")
    assert page is not None
    assert "Updated description" in page["content"]


@pytest.mark.asyncio
async def test_execute_tool_save_knowledge_bad_key(wiki_storage):
    """save_knowledge rejects keys without a type prefix."""
    result = await _execute_tool(
        "save_knowledge",
        {"key": "no_colon", "content": "Bad key format."},
        AsyncMock(),
        wiki_storage=wiki_storage,
    )
    assert "Error" in result
    assert wiki_storage.get_page_by_slug("no_colon") is None


@pytest.mark.asyncio
async def test_execute_tool_save_knowledge_indexes_in_retrieval(wiki_storage):
    """When wiki_retrieval is provided, save_knowledge re-indexes the page."""
    retrieval = MagicMock()
    result = await _execute_tool(
        "save_knowledge",
        {"key": "guide:new-drivers", "content": "Tips for new drivers."},
        AsyncMock(),
        wiki_storage=wiki_storage,
        wiki_retrieval=retrieval,
    )
    assert "Saved" in result
    retrieval.index_page.assert_called_once()
    kwargs = retrieval.index_page.call_args.kwargs
    assert kwargs["title"] == "guide:new-drivers"
    assert kwargs["category"] == "guide"


@pytest.mark.asyncio
async def test_execute_tool_remove_knowledge(wiki_storage):
    """remove_knowledge deletes the wiki page."""
    result = await _execute_tool(
        "remove_knowledge",
        {"key": "guide:subsidies"},
        AsyncMock(),
        wiki_storage=wiki_storage,
    )
    assert "Removed" in result
    assert wiki_storage.get_page_by_slug("guide:subsidies") is None


@pytest.mark.asyncio
async def test_execute_tool_remove_knowledge_missing(wiki_storage):
    """remove_knowledge with a nonexistent key returns a friendly message."""
    result = await _execute_tool(
        "remove_knowledge",
        {"key": "vehicle:Nonexistent"},
        AsyncMock(),
        wiki_storage=wiki_storage,
    )
    assert "No entry found" in result


@pytest.mark.asyncio
async def test_execute_tool_remove_knowledge_removes_from_retrieval(wiki_storage):
    """remove_knowledge also removes the page from ChromaDB."""
    retrieval = MagicMock()
    page_id = wiki_storage.get_page_by_slug("guide:subsidies")["id"]
    await _execute_tool(
        "remove_knowledge",
        {"key": "guide:subsidies"},
        AsyncMock(),
        wiki_storage=wiki_storage,
        wiki_retrieval=retrieval,
    )
    retrieval.remove_page.assert_called_once_with(page_id)


@pytest.mark.asyncio
async def test_execute_tool_game_db(monkeypatch):
    """Test game DB tool execution."""
    mock_execute = MagicMock(
        return_value={
            "results": [{"name": "Steel Coil", "weight": 24000}],
            "count": 1,
        }
    )
    monkeypatch.setattr("amc_peripheral.bot.game_db.execute_raw_query", mock_execute)

    result = await _execute_tool(
        "query_game_database",
        {"sql": "SELECT name, weight FROM cargos"},
        AsyncMock(),
    )

    assert "Steel Coil" in result
    assert "24000" in result


@pytest.mark.asyncio
async def test_execute_tool_game_db_error(monkeypatch):
    """Test game DB tool handles query errors."""
    mock_execute = MagicMock(return_value={"error": "no such table: foo"})
    monkeypatch.setattr("amc_peripheral.bot.game_db.execute_raw_query", mock_execute)

    result = await _execute_tool(
        "query_game_database",
        {"sql": "SELECT * FROM foo"},
        AsyncMock(),
    )

    assert "failed" in result.lower()


@pytest.mark.asyncio
async def test_execute_tool_subsidies():
    """Test subsidies tool execution."""
    mock_session = AsyncMock()
    mock_resp = AsyncMock()
    mock_resp.json = AsyncMock(return_value={"subsidies_text": "Coal: +50%"})
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)
    mock_session.get = MagicMock(return_value=mock_resp)

    result = await _execute_tool("get_current_subsidies", {}, mock_session)

    assert "Coal" in result


@pytest.mark.asyncio
async def test_execute_tool_unknown():
    """Test unknown tool returns error."""
    result = await _execute_tool("nonexistent_tool", {}, AsyncMock())
    assert "Unknown tool" in result


# --- ask_game_knowledge integration tests ---


@pytest.mark.asyncio
async def test_ask_game_knowledge_returns_answer(
    wiki_storage, wiki_index, mock_openai, mock_http_session
):
    """Test subagent returns the LLM's text answer."""
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "The heaviest cargo is Steel Coil at 24000kg."
    mock_response.choices[0].message.tool_calls = None

    mock_openai.chat.completions.create = AsyncMock(return_value=mock_response)

    answer = await ask_game_knowledge(
        openai_client=mock_openai,
        wiki_storage=wiki_storage,
        wiki_retrieval=None,
        wiki_index=wiki_index,
        game_schema="TABLE: cargos\n  Columns: id, name, weight",
        question="What is the heaviest cargo?",
        http_session=mock_http_session,
    )

    assert "Steel Coil" in answer
    assert "24000" in answer

    # Verify system prompt uses compact wiki index, not full content
    call_args = mock_openai.chat.completions.create.call_args
    system_msg = call_args.kwargs["messages"][0]["content"]
    assert "vehicle" in system_msg  # Index categories present
    assert "mid-size delivery van" not in system_msg  # Full content is NOT


@pytest.mark.asyncio
async def test_ask_game_knowledge_handles_empty_response(
    wiki_storage, wiki_index, mock_openai, mock_http_session
):
    """Test subagent handles empty LLM response gracefully."""
    mock_response = MagicMock()
    mock_response.choices = []

    mock_openai.chat.completions.create = AsyncMock(return_value=mock_response)

    answer = await ask_game_knowledge(
        openai_client=mock_openai,
        wiki_storage=wiki_storage,
        wiki_retrieval=None,
        wiki_index=wiki_index,
        game_schema="",
        question="test",
        http_session=mock_http_session,
    )

    assert "could not" in answer.lower() or "no answer" in answer.lower()


@pytest.mark.asyncio
async def test_ask_game_knowledge_with_tool_call(
    wiki_storage, wiki_index, mock_openai, mock_http_session
):
    """Test subagent handles a tool call loop: LLM calls tool, then gives final answer."""
    # First call: LLM wants to use lookup_knowledge
    tool_call = MagicMock()
    tool_call.id = "call_123"
    tool_call.function.name = "lookup_knowledge"
    tool_call.function.arguments = '{"topic": "Kira"}'

    first_response = MagicMock()
    first_response.choices = [MagicMock()]
    first_response.choices[0].message.content = None
    first_response.choices[0].message.tool_calls = [tool_call]

    # Second call: LLM gives final answer
    second_response = MagicMock()
    second_response.choices = [MagicMock()]
    second_response.choices[0].message.content = (
        "The Kira Van is a mid-size delivery van that can carry up to 5000kg."
    )
    second_response.choices[0].message.tool_calls = None

    mock_openai.chat.completions.create = AsyncMock(
        side_effect=[first_response, second_response]
    )

    answer = await ask_game_knowledge(
        openai_client=mock_openai,
        wiki_storage=wiki_storage,
        wiki_retrieval=None,
        wiki_index=wiki_index,
        game_schema="TABLE: cargos",
        question="What is the Kira Van?",
        http_session=mock_http_session,
    )

    assert "Kira Van" in answer
    assert mock_openai.chat.completions.create.call_count == 2
