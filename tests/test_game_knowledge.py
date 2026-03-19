import sys
from unittest.mock import MagicMock, AsyncMock

# Mock google.cloud.texttospeech BEFORE importing module that uses it
mock_texttospeech = MagicMock()
mock_texttospeech.TextToSpeechClient = MagicMock()
sys.modules["google.cloud.texttospeech"] = mock_texttospeech
sys.modules["google.cloud"] = MagicMock()
sys.modules["google"] = MagicMock()

import pytest  # noqa: E402
from amc_peripheral.knowledge_store import KnowledgeStore  # noqa: E402
from amc_peripheral.radio.game_knowledge import (  # noqa: E402
    ask_game_knowledge,
    _execute_tool,
    _build_tools,
    _extract_heading,
    _lookup_knowledge,
)


@pytest.fixture
def store(tmp_path):
    """Create a KnowledgeStore with test data."""
    s = KnowledgeStore(str(tmp_path / "knowledge.json"))
    s.save("vehicle:Kira_Van", "## Kira Van\nThe Kira Van is a mid-size delivery van.\nMax cargo: 5000kg.", "seed")
    s.save("vehicle:Gosan_Trucks", "## Gosan Trucks\nGosan manufactures heavy-duty trucks.\nThe G7 can carry up to 24000kg.", "seed")
    s.save("location:Gangjung", "## Gangjung\nGangjung is the capital city.\nIt has the main port and train station.", "seed")
    s.save("guide:subsidies", "## Subsidies\nThe government provides delivery subsidies.\nCheck /subsidies for current rates.", "seed")
    return s


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


def test_lookup_exact_match(store):
    """Exact topic match returns content."""
    result = _lookup_knowledge("Kira_Van", store)
    assert "mid-size delivery van" in result


def test_lookup_partial_match(store):
    """Partial keyword match works."""
    result = _lookup_knowledge("gosan", store)
    assert "heavy-duty trucks" in result


def test_lookup_multiple_matches(store):
    """Multiple matches are returned together."""
    result = _lookup_knowledge("vehicle", store)
    assert "Kira" in result
    assert "Gosan" in result


def test_lookup_no_match_shows_available(store):
    """No match returns available keys."""
    result = _lookup_knowledge("nonexistent", store)
    assert "No knowledge found" in result


def test_lookup_content_fallback(store):
    """Falls back to searching content if key doesn't match."""
    result = _lookup_knowledge("24000kg", store)
    assert "Gosan" in result


def test_lookup_empty():
    """Empty query returns no knowledge."""
    # Create an empty store
    from amc_peripheral.knowledge_store import KnowledgeStore
    import tempfile
    import os
    path = os.path.join(tempfile.mkdtemp(), "empty.json")
    empty = KnowledgeStore(path)
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
async def test_execute_tool_lookup_knowledge(store):
    """Test lookup_knowledge tool execution."""
    result = await _execute_tool(
        "lookup_knowledge",
        {"topic": "Kira"},
        AsyncMock(),
        store=store,
    )
    assert "mid-size delivery van" in result


@pytest.mark.asyncio
async def test_execute_tool_list_knowledge(store):
    """Test list_knowledge tool execution."""
    result = await _execute_tool(
        "list_knowledge",
        {"type_filter": "vehicle"},
        AsyncMock(),
        store=store,
    )
    assert "vehicle:Kira_Van" in result
    assert "vehicle:Gosan_Trucks" in result


@pytest.mark.asyncio
async def test_execute_tool_save_knowledge(store):
    """Test save_knowledge tool execution."""
    result = await _execute_tool(
        "save_knowledge",
        {"key": "vehicle:New_Car", "content": "A shiny new car."},
        AsyncMock(),
        store=store,
    )
    assert "Saved" in result
    assert store.get("vehicle:New_Car") == "A shiny new car."


@pytest.mark.asyncio
async def test_execute_tool_save_knowledge_bad_key(store):
    """Test save_knowledge rejects keys without type prefix."""
    result = await _execute_tool(
        "save_knowledge",
        {"key": "no_colon", "content": "Bad key format."},
        AsyncMock(),
        store=store,
    )
    assert "Error" in result


@pytest.mark.asyncio
async def test_execute_tool_remove_knowledge(store):
    """Test remove_knowledge tool execution."""
    result = await _execute_tool(
        "remove_knowledge",
        {"key": "guide:subsidies"},
        AsyncMock(),
        store=store,
    )
    assert "Removed" in result
    assert store.get("guide:subsidies") is None


@pytest.mark.asyncio
async def test_execute_tool_remove_knowledge_missing(store):
    """Test remove_knowledge with nonexistent key."""
    result = await _execute_tool(
        "remove_knowledge",
        {"key": "vehicle:Nonexistent"},
        AsyncMock(),
        store=store,
    )
    assert "No entry found" in result


@pytest.mark.asyncio
async def test_execute_tool_game_db(monkeypatch):
    """Test game DB tool execution."""
    mock_execute = MagicMock(return_value={
        "results": [{"name": "Steel Coil", "weight": 24000}],
        "count": 1,
    })
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
async def test_ask_game_knowledge_returns_answer(store, mock_openai, mock_http_session):
    """Test subagent returns the LLM's text answer."""
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "The heaviest cargo is Steel Coil at 24000kg."
    mock_response.choices[0].message.tool_calls = None

    mock_openai.chat.completions.create = AsyncMock(return_value=mock_response)

    answer = await ask_game_knowledge(
        openai_client=mock_openai,
        knowledge_store=store,
        game_schema="TABLE: cargos\n  Columns: id, name, weight",
        question="What is the heaviest cargo?",
        http_session=mock_http_session,
    )

    assert "Steel Coil" in answer
    assert "24000" in answer

    # Verify system prompt uses compact index, not full knowledge
    call_args = mock_openai.chat.completions.create.call_args
    system_msg = call_args.kwargs["messages"][0]["content"]
    assert "vehicle" in system_msg  # Index categories present
    assert "mid-size delivery van" not in system_msg  # Full content is NOT


@pytest.mark.asyncio
async def test_ask_game_knowledge_handles_empty_response(store, mock_openai, mock_http_session):
    """Test subagent handles empty LLM response gracefully."""
    mock_response = MagicMock()
    mock_response.choices = []

    mock_openai.chat.completions.create = AsyncMock(return_value=mock_response)

    answer = await ask_game_knowledge(
        openai_client=mock_openai,
        knowledge_store=store,
        game_schema="",
        question="test",
        http_session=mock_http_session,
    )

    assert "could not" in answer.lower() or "no answer" in answer.lower()


@pytest.mark.asyncio
async def test_ask_game_knowledge_with_tool_call(store, mock_openai, mock_http_session):
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
    second_response.choices[0].message.content = "The Kira Van is a mid-size delivery van that can carry up to 5000kg."
    second_response.choices[0].message.tool_calls = None

    mock_openai.chat.completions.create = AsyncMock(
        side_effect=[first_response, second_response]
    )

    answer = await ask_game_knowledge(
        openai_client=mock_openai,
        knowledge_store=store,
        game_schema="TABLE: cargos",
        question="What is the Kira Van?",
        http_session=mock_http_session,
    )

    assert "Kira Van" in answer
    assert mock_openai.chat.completions.create.call_count == 2
