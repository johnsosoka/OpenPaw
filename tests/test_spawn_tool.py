"""Tests for the SpawnToolBuiltin."""

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openpaw.builtins.registry import BuiltinRegistry
from openpaw.builtins.tools.spawn import SpawnToolBuiltin
from openpaw.subagent.runner import SubAgentRunner
from openpaw.subagent.store import SubAgentRequest, SubAgentResult, SubAgentStatus, SubAgentStore


@pytest.fixture
def temp_workspace(tmp_path: Path) -> Path:
    """Create a temporary workspace directory."""
    workspace = tmp_path / "test_workspace"
    workspace.mkdir()
    return workspace


@pytest.fixture
def mock_store(temp_workspace: Path) -> SubAgentStore:
    """Create a mock SubAgentStore."""
    return SubAgentStore(temp_workspace)


@pytest.fixture
def mock_runner(mock_store: SubAgentStore) -> SubAgentRunner:
    """Create a mock SubAgentRunner."""
    runner = MagicMock(spec=SubAgentRunner)
    runner._store = mock_store
    runner.spawn = AsyncMock(return_value="test-id-123")
    runner.cancel = AsyncMock(return_value=True)
    runner.list_active = MagicMock(return_value=[])
    runner.list_recent = MagicMock(return_value=[])
    runner.get_status = MagicMock(return_value=None)
    runner.get_result = MagicMock(return_value=None)
    return runner


@pytest.fixture
def spawn_tool(mock_runner: SubAgentRunner) -> SpawnToolBuiltin:
    """Create a SpawnToolBuiltin instance with mocked runner."""
    tool = SpawnToolBuiltin(config={"max_concurrent": 8})
    tool.set_runner(mock_runner)
    return tool


def test_metadata():
    """Test that metadata is correctly defined."""
    meta = SpawnToolBuiltin.metadata

    assert meta.name == "spawn"
    assert meta.display_name == "Sub-Agent Spawning"
    assert meta.group == "automation"
    assert meta.builtin_type.value == "tool"
    assert len(meta.prerequisites.env_vars) == 0  # No API key required


def test_initialization():
    """Test SpawnToolBuiltin initialization."""
    tool = SpawnToolBuiltin(config={"max_concurrent": 16})

    assert tool.max_concurrent == 16
    assert tool._runner is None


def test_initialization_defaults():
    """Test default configuration values."""
    tool = SpawnToolBuiltin()

    assert tool.max_concurrent == 8
    assert tool._runner is None


def test_set_runner():
    """Test set_runner stores runner reference."""
    tool = SpawnToolBuiltin()
    mock_runner = MagicMock(spec=SubAgentRunner)

    assert tool._runner is None
    tool.set_runner(mock_runner)
    assert tool._runner is mock_runner


def test_get_langchain_tool_returns_four_tools(spawn_tool: SpawnToolBuiltin):
    """Test get_langchain_tool returns 4 tools."""
    tools = spawn_tool.get_langchain_tool()

    assert isinstance(tools, list)
    assert len(tools) == 4

    tool_names = {tool.name for tool in tools}
    assert tool_names == {
        "spawn_agent",
        "list_subagents",
        "get_subagent_result",
        "cancel_subagent",
    }


@pytest.mark.asyncio
async def test_spawn_agent_creates_request_and_calls_runner(
    spawn_tool: SpawnToolBuiltin, mock_runner: SubAgentRunner, mock_store: SubAgentStore
):
    """Test spawn_agent creates request and calls runner.spawn."""
    tools = spawn_tool.get_langchain_tool()
    spawn_agent_tool = next(t for t in tools if t.name == "spawn_agent")

    # Mock session context
    with patch(
        "openpaw.builtins.tools.spawn.get_current_session_key",
        return_value="telegram:123456",
    ):
        # Call the tool (async)
        result = await spawn_agent_tool.coroutine(
            task="Test task", label="test-label", timeout_minutes=15, notify=True
        )

    # Verify result message
    assert "Sub-agent spawned: test-id-123" in result
    assert "Label: test-label" in result
    assert "Timeout: 15min" in result

    # Verify runner.spawn was called
    mock_runner.spawn.assert_called_once()

    # Verify request was created in store
    requests = mock_store.list_recent(limit=10)
    assert len(requests) == 1
    assert requests[0].task == "Test task"
    assert requests[0].label == "test-label"
    assert requests[0].timeout_minutes == 15
    assert requests[0].notify is True
    assert requests[0].session_key == "telegram:123456"


@pytest.mark.asyncio
async def test_spawn_agent_returns_error_when_runner_not_set():
    """Test spawn_agent returns error when runner not set."""
    tool = SpawnToolBuiltin()
    tools = tool.get_langchain_tool()
    spawn_agent_tool = next(t for t in tools if t.name == "spawn_agent")

    # Mock session context
    with patch(
        "openpaw.builtins.tools.spawn.get_current_session_key",
        return_value="telegram:123456",
    ):
        result = await spawn_agent_tool.coroutine(
            task="Test task", label="test-label"
        )

    assert "[Error: Sub-agent spawning not available" in result


@pytest.mark.asyncio
async def test_spawn_agent_returns_error_when_no_session_context(
    spawn_tool: SpawnToolBuiltin,
):
    """Test spawn_agent returns error when no session context."""
    tools = spawn_tool.get_langchain_tool()
    spawn_agent_tool = next(t for t in tools if t.name == "spawn_agent")

    # Mock session context as None
    with patch(
        "openpaw.builtins.tools.spawn.get_current_session_key", return_value=None
    ):
        result = await spawn_agent_tool.coroutine(
            task="Test task", label="test-label"
        )

    assert "[Error: Cannot spawn sub-agent: no active session context]" in result


def test_list_subagents_formats_active_and_recent_correctly(
    spawn_tool: SpawnToolBuiltin, mock_runner: SubAgentRunner
):
    """Test list_subagents formats active and recent correctly."""
    # Create mock requests
    now = datetime.now(UTC)

    active_request = SubAgentRequest(
        id="active-123",
        task="Active task",
        label="active-task",
        status=SubAgentStatus.RUNNING,
        session_key="telegram:123",
        created_at=now,
        started_at=now,
    )

    completed_request = SubAgentRequest(
        id="completed-456",
        task="Completed task",
        label="completed-task",
        status=SubAgentStatus.COMPLETED,
        session_key="telegram:123",
        created_at=now,
        started_at=now,
        completed_at=now,
    )

    mock_runner.list_active.return_value = [active_request]
    mock_runner.list_recent.return_value = [active_request, completed_request]

    tools = spawn_tool.get_langchain_tool()
    list_tool = next(t for t in tools if t.name == "list_subagents")

    result = list_tool.func()

    # Verify formatting
    assert "Active Sub-agents:" in result
    assert "active-1" in result  # Truncated ID ([:8])
    assert "active-task" in result
    assert "running" in result

    assert "Recent (completed):" in result
    assert "complete" in result  # Truncated ID ([:8])
    assert "completed-task" in result
    assert "completed" in result


def test_list_subagents_handles_empty_case(
    spawn_tool: SpawnToolBuiltin, mock_runner: SubAgentRunner
):
    """Test list_subagents handles empty case."""
    mock_runner.list_active.return_value = []
    mock_runner.list_recent.return_value = []

    tools = spawn_tool.get_langchain_tool()
    list_tool = next(t for t in tools if t.name == "list_subagents")

    result = list_tool.func()

    assert result == "No sub-agents found."


def test_get_subagent_result_returns_result_for_completed_agent(
    spawn_tool: SpawnToolBuiltin, mock_runner: SubAgentRunner
):
    """Test get_subagent_result returns result for completed agent."""
    now = datetime.now(UTC)

    request = SubAgentRequest(
        id="test-123",
        task="Test task",
        label="test-label",
        status=SubAgentStatus.COMPLETED,
        session_key="telegram:123",
        created_at=now,
        started_at=now,
        completed_at=now,
    )

    result = SubAgentResult(
        request_id="test-123",
        output="This is the output from the sub-agent",
        token_count=150,
        duration_ms=5000.0,
    )

    mock_runner.get_status.return_value = request
    mock_runner.get_result.return_value = result

    tools = spawn_tool.get_langchain_tool()
    get_result_tool = next(t for t in tools if t.name == "get_subagent_result")

    response = get_result_tool.func(id="test-123")

    assert "Sub-agent: test-label (test-123)" in response
    assert "Status: completed" in response
    assert "Duration: 5s" in response
    assert "Tokens: 150" in response
    assert "This is the output from the sub-agent" in response


def test_get_subagent_result_returns_status_for_running_agent(
    spawn_tool: SpawnToolBuiltin, mock_runner: SubAgentRunner
):
    """Test get_subagent_result returns status for running agent."""
    now = datetime.now(UTC)

    request = SubAgentRequest(
        id="test-123",
        task="Test task",
        label="test-label",
        status=SubAgentStatus.RUNNING,
        session_key="telegram:123",
        created_at=now,
        started_at=now,
    )

    mock_runner.get_status.return_value = request

    tools = spawn_tool.get_langchain_tool()
    get_result_tool = next(t for t in tools if t.name == "get_subagent_result")

    response = get_result_tool.func(id="test-123")

    assert "Sub-agent 'test-label' is still running" in response


def test_get_subagent_result_returns_not_found_message(
    spawn_tool: SpawnToolBuiltin, mock_runner: SubAgentRunner
):
    """Test get_subagent_result returns not-found message."""
    mock_runner.get_status.return_value = None

    tools = spawn_tool.get_langchain_tool()
    get_result_tool = next(t for t in tools if t.name == "get_subagent_result")

    response = get_result_tool.func(id="nonexistent")

    assert "Sub-agent not found: nonexistent" in response


@pytest.mark.asyncio
async def test_cancel_subagent_calls_runner_cancel(
    spawn_tool: SpawnToolBuiltin, mock_runner: SubAgentRunner
):
    """Test cancel_subagent calls runner.cancel."""
    mock_runner.cancel.return_value = True

    tools = spawn_tool.get_langchain_tool()
    cancel_tool = next(t for t in tools if t.name == "cancel_subagent")

    result = await cancel_tool.coroutine(id="test-123")

    assert "Sub-agent test-123 cancelled successfully." in result
    mock_runner.cancel.assert_called_once_with("test-123")


@pytest.mark.asyncio
async def test_cancel_subagent_handles_not_found_case(
    spawn_tool: SpawnToolBuiltin, mock_runner: SubAgentRunner
):
    """Test cancel_subagent handles not-found case."""
    mock_runner.cancel.return_value = False

    tools = spawn_tool.get_langchain_tool()
    cancel_tool = next(t for t in tools if t.name == "cancel_subagent")

    result = await cancel_tool.coroutine(id="nonexistent")

    assert "Sub-agent nonexistent not found or already completed." in result


def test_registration_in_registry():
    """Test SpawnToolBuiltin is registered in the builtin registry."""
    registry = BuiltinRegistry.get_instance()

    # Check tool is registered
    tool_class = registry.get_tool_class("spawn")
    assert tool_class is not None
    assert tool_class == SpawnToolBuiltin


def test_get_subagent_result_truncates_long_output(
    spawn_tool: SpawnToolBuiltin, mock_runner: SubAgentRunner
):
    """Test get_subagent_result truncates output over 5000 chars."""
    now = datetime.now(UTC)

    request = SubAgentRequest(
        id="test-123",
        task="Test task",
        label="test-label",
        status=SubAgentStatus.COMPLETED,
        session_key="telegram:123",
        created_at=now,
        started_at=now,
        completed_at=now,
    )

    # Create output that's over 5000 chars
    long_output = "x" * 6000

    result = SubAgentResult(
        request_id="test-123",
        output=long_output,
        token_count=150,
        duration_ms=5000.0,
    )

    mock_runner.get_status.return_value = request
    mock_runner.get_result.return_value = result

    tools = spawn_tool.get_langchain_tool()
    get_result_tool = next(t for t in tools if t.name == "get_subagent_result")

    response = get_result_tool.func(id="test-123")

    # Verify truncation
    assert len(response) < 6000
    assert "[Output truncated" in response


def test_format_time_ago():
    """Test _format_time_ago formats durations correctly."""
    tool = SpawnToolBuiltin()

    assert tool._format_time_ago(30) == "30s ago"
    assert tool._format_time_ago(90) == "1m ago"
    assert tool._format_time_ago(7200) == "2h ago"
    assert tool._format_time_ago(86400) == "1d ago"


def test_format_duration():
    """Test _format_duration formats durations correctly."""
    tool = SpawnToolBuiltin()

    assert tool._format_duration(30) == "30s"
    assert tool._format_duration(90) == "1m"
    assert tool._format_duration(7200) == "2h"
    assert tool._format_duration(86400) == "1d"


def test_spawn_agent_sync_wrapper(spawn_tool: SpawnToolBuiltin, mock_runner: SubAgentRunner):
    """Test spawn_agent sync wrapper works correctly."""
    tools = spawn_tool.get_langchain_tool()
    spawn_agent_tool = next(t for t in tools if t.name == "spawn_agent")

    # Mock session context
    with patch(
        "openpaw.builtins.tools.spawn.get_current_session_key",
        return_value="telegram:123456",
    ):
        # Call the sync wrapper (func, not coroutine)
        result = spawn_agent_tool.func(
            task="Test task", label="test-label", timeout_minutes=15, notify=True
        )

    # Verify it returns a valid response
    assert "Sub-agent spawned: test-id-123" in result or "[Error:" in result


def test_cancel_subagent_sync_wrapper(spawn_tool: SpawnToolBuiltin, mock_runner: SubAgentRunner):
    """Test cancel_subagent sync wrapper works correctly."""
    mock_runner.cancel.return_value = True

    tools = spawn_tool.get_langchain_tool()
    cancel_tool = next(t for t in tools if t.name == "cancel_subagent")

    # Call the sync wrapper (func, not coroutine)
    result = cancel_tool.func(id="test-123")

    assert "Sub-agent test-123 cancelled successfully." in result or "[Error:" in result
