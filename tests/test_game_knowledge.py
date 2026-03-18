import sys
from unittest.mock import MagicMock, AsyncMock, patch

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
)


@pytest.fixture
def mock_openai():
    return AsyncMock()


@pytest.fixture
def mock_http_session():
    return AsyncMock()


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
        knowledge_text="Some game knowledge",
        game_schema="TABLE: cargos\n  Columns: id, name, weight",
        question="What is the heaviest cargo?",
        http_session=mock_http_session,
    )

    assert "Steel Coil" in answer
    assert "24000" in answer


@pytest.mark.asyncio
async def test_ask_game_knowledge_handles_empty_response(mock_openai, mock_http_session):
    """Test subagent handles empty LLM response gracefully."""
    mock_response = MagicMock()
    mock_response.choices = []

    mock_openai.chat.completions.create = AsyncMock(return_value=mock_response)

    answer = await ask_game_knowledge(
        openai_client=mock_openai,
        knowledge_text="",
        game_schema="",
        question="test",
        http_session=mock_http_session,
    )

    assert "could not" in answer.lower() or "no answer" in answer.lower()


@pytest.mark.asyncio
async def test_ask_game_knowledge_with_tool_call(mock_openai, mock_http_session):
    """Test subagent handles a tool call loop: LLM calls tool, then gives final answer."""
    # First call: LLM wants to use a tool
    tool_call = MagicMock()
    tool_call.id = "call_123"
    tool_call.function.name = "query_game_database"
    tool_call.function.arguments = '{"sql": "SELECT name FROM cargos LIMIT 1"}'

    first_response = MagicMock()
    first_response.choices = [MagicMock()]
    first_response.choices[0].message.content = None
    first_response.choices[0].message.tool_calls = [tool_call]

    # Second call: LLM gives final answer
    second_response = MagicMock()
    second_response.choices = [MagicMock()]
    second_response.choices[0].message.content = "Based on the query, the cargo is Steel."
    second_response.choices[0].message.tool_calls = None

    mock_openai.chat.completions.create = AsyncMock(
        side_effect=[first_response, second_response]
    )

    with patch(
        "amc_peripheral.radio.game_knowledge._execute_tool",
        new_callable=AsyncMock,
        return_value='[{"name": "Steel"}]',
    ):
        answer = await ask_game_knowledge(
            openai_client=mock_openai,
            knowledge_text="Game knowledge",
            game_schema="TABLE: cargos",
            question="What cargo exists?",
            http_session=mock_http_session,
        )

    assert "Steel" in answer
    assert mock_openai.chat.completions.create.call_count == 2


@pytest.mark.asyncio
async def test_build_tools_includes_all_tools():
    """Test that all expected tools are built."""
    tools = _build_tools("TABLE: cargos\n  Columns: id, name")
    tool_names = [t["function"]["name"] for t in tools]

    assert "query_game_database" in tool_names
    assert "get_current_subsidies" in tool_names
    assert "get_server_commands" in tool_names


@pytest.mark.asyncio
async def test_build_tools_empty_schema():
    """Test tools build with empty schema."""
    tools = _build_tools("")
    assert len(tools) == 3  # All 3 tools still defined


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
