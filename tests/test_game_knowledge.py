import sys
from unittest.mock import MagicMock, AsyncMock

# Mock google.cloud.texttospeech BEFORE importing module that uses it
mock_texttospeech = MagicMock()
mock_texttospeech.TextToSpeechClient = MagicMock()
sys.modules["google.cloud.texttospeech"] = mock_texttospeech
sys.modules["google.cloud"] = MagicMock()
sys.modules["google"] = MagicMock()

import pytest  # noqa: E402
from amc_peripheral.radio.game_knowledge import (  # noqa: E402
    ask_game_knowledge,
    _execute_tool,
    _build_tools,
    _extract_heading,
    _lookup_knowledge,
)


SAMPLE_TOPICS = {
    "Vehicles > Kira Van": "## Kira Van\nThe Kira Van is a mid-size delivery van.\nMax cargo: 5000kg.",
    "Vehicles > Gosan Trucks": "## Gosan Trucks\nGosan manufactures heavy-duty trucks.\nThe G7 can carry up to 24000kg.",
    "Locations > Gangjung": "## Gangjung\nGangjung is the capital city.\nIt has the main port and train station.",
    "Economy > Subsidies": "## Subsidies\nThe government provides delivery subsidies.\nCheck /subsidies for current rates.",
}

SAMPLE_INDEX = (
    "Available game knowledge topics (call `ask_game_knowledge` for details on any of these):\n"
    "- Vehicles > Kira Van\n"
    "- Vehicles > Gosan Trucks\n"
    "- Locations > Gangjung\n"
    "- Economy > Subsidies"
)


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


def test_lookup_exact_match():
    """Exact topic match returns content."""
    result = _lookup_knowledge("Kira Van", SAMPLE_TOPICS)
    assert "Kira Van is a mid-size delivery van" in result


def test_lookup_partial_match():
    """Partial keyword match works."""
    result = _lookup_knowledge("gosan", SAMPLE_TOPICS)
    assert "heavy-duty trucks" in result


def test_lookup_multiple_matches():
    """Multiple matches are returned together."""
    result = _lookup_knowledge("Vehicles", SAMPLE_TOPICS)
    assert "Kira Van" in result
    assert "Gosan" in result


def test_lookup_no_match_shows_available():
    """No match returns available topics."""
    result = _lookup_knowledge("nonexistent", SAMPLE_TOPICS)
    assert "No knowledge found" in result
    assert "Kira Van" in result  # Lists available topics


def test_lookup_content_fallback():
    """Falls back to searching content if key doesn't match."""
    result = _lookup_knowledge("24000kg", SAMPLE_TOPICS)
    assert "Gosan" in result


def test_lookup_empty():
    """Empty query or empty topics returns no knowledge."""
    assert "No knowledge available" in _lookup_knowledge("", SAMPLE_TOPICS)
    assert "No knowledge available" in _lookup_knowledge("test", {})


# --- _build_tools tests ---


@pytest.mark.asyncio
async def test_build_tools_includes_all_tools():
    """Test that all expected tools are built."""
    tools = _build_tools("TABLE: cargos\n  Columns: id, name")
    tool_names = [t["function"]["name"] for t in tools]

    assert "lookup_knowledge" in tool_names
    assert "query_game_database" in tool_names
    assert "get_current_subsidies" in tool_names
    assert "get_server_commands" in tool_names


@pytest.mark.asyncio
async def test_build_tools_empty_schema():
    """Test tools build with empty schema."""
    tools = _build_tools("")
    assert len(tools) == 4  # lookup_knowledge + 3 others


# --- _execute_tool tests ---


@pytest.mark.asyncio
async def test_execute_tool_lookup_knowledge():
    """Test lookup_knowledge tool execution."""
    result = await _execute_tool(
        "lookup_knowledge",
        {"topic": "Kira Van"},
        AsyncMock(),
        knowledge_topics=SAMPLE_TOPICS,
    )
    assert "mid-size delivery van" in result


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
async def test_ask_game_knowledge_returns_answer(mock_openai, mock_http_session):
    """Test subagent returns the LLM's text answer."""
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "The heaviest cargo is Steel Coil at 24000kg."
    mock_response.choices[0].message.tool_calls = None

    mock_openai.chat.completions.create = AsyncMock(return_value=mock_response)

    answer = await ask_game_knowledge(
        openai_client=mock_openai,
        knowledge_topics=SAMPLE_TOPICS,
        knowledge_index=SAMPLE_INDEX,
        game_schema="TABLE: cargos\n  Columns: id, name, weight",
        question="What is the heaviest cargo?",
        http_session=mock_http_session,
    )

    assert "Steel Coil" in answer
    assert "24000" in answer

    # Verify system prompt uses index, not full knowledge
    call_args = mock_openai.chat.completions.create.call_args
    system_msg = call_args.kwargs["messages"][0]["content"]
    assert "Kira Van" in system_msg  # Index is included
    assert "mid-size delivery van" not in system_msg  # Full content is NOT included


@pytest.mark.asyncio
async def test_ask_game_knowledge_handles_empty_response(mock_openai, mock_http_session):
    """Test subagent handles empty LLM response gracefully."""
    mock_response = MagicMock()
    mock_response.choices = []

    mock_openai.chat.completions.create = AsyncMock(return_value=mock_response)

    answer = await ask_game_knowledge(
        openai_client=mock_openai,
        knowledge_topics={},
        knowledge_index="",
        game_schema="",
        question="test",
        http_session=mock_http_session,
    )

    assert "could not" in answer.lower() or "no answer" in answer.lower()


@pytest.mark.asyncio
async def test_ask_game_knowledge_with_tool_call(mock_openai, mock_http_session):
    """Test subagent handles a tool call loop: LLM calls tool, then gives final answer."""
    # First call: LLM wants to use lookup_knowledge
    tool_call = MagicMock()
    tool_call.id = "call_123"
    tool_call.function.name = "lookup_knowledge"
    tool_call.function.arguments = '{"topic": "Kira Van"}'

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
        knowledge_topics=SAMPLE_TOPICS,
        knowledge_index=SAMPLE_INDEX,
        game_schema="TABLE: cargos",
        question="What is the Kira Van?",
        http_session=mock_http_session,
    )

    assert "Kira Van" in answer
    assert mock_openai.chat.completions.create.call_count == 2
