"""Integration tests for AgentRunner token tracking."""

import pytest
from unittest.mock import Mock, AsyncMock, MagicMock
from pathlib import Path

from openpaw.agent.runner import AgentRunner
from openpaw.agent.metrics import InvocationMetrics
from openpaw.core.workspace import AgentWorkspace


@pytest.fixture
def mock_workspace(tmp_path: Path) -> AgentWorkspace:
    """Create a mock agent workspace for testing."""
    workspace_dir = tmp_path / "test_workspace"
    workspace_dir.mkdir()

    # Create required markdown files
    agent_dir = workspace_dir / "agent"
    agent_dir.mkdir()
    (agent_dir / "AGENT.md").write_text("# Agent\nTest agent")
    (agent_dir / "USER.md").write_text("# User\nTest user")
    (agent_dir / "SOUL.md").write_text("# Soul\nTest soul")
    (agent_dir / "HEARTBEAT.md").write_text("")

    workspace = Mock(spec=AgentWorkspace)
    workspace.name = "test_workspace"
    workspace.path = workspace_dir
    workspace.build_system_prompt = Mock(return_value="Test system prompt")

    return workspace


def test_agent_runner_initializes_with_none_metrics(mock_workspace: AgentWorkspace) -> None:
    """Test that AgentRunner initializes with None metrics."""
    runner = AgentRunner(
        workspace=mock_workspace,
        model="anthropic:claude-sonnet-4-20250514",
        api_key="test-key",
    )

    assert runner.last_metrics is None


def test_agent_runner_exposes_last_metrics_property(mock_workspace: AgentWorkspace) -> None:
    """Test that last_metrics property is accessible."""
    runner = AgentRunner(
        workspace=mock_workspace,
        model="anthropic:claude-sonnet-4-20250514",
        api_key="test-key",
    )

    # Should not raise AttributeError
    metrics = runner.last_metrics
    assert metrics is None


@pytest.mark.asyncio
async def test_agent_runner_populates_metrics_after_run(mock_workspace: AgentWorkspace) -> None:
    """Test that metrics are populated after a successful run (mock-based)."""
    runner = AgentRunner(
        workspace=mock_workspace,
        model="anthropic:claude-sonnet-4-20250514",
        api_key="test-key",
    )

    # Mock the agent to stream updates with messages
    async def mock_astream(*args, **kwargs):
        # Simulate streaming updates (spec-less mock so tool_calls falls back to [])
        msg = Mock(content="Test response", tool_calls=[])
        yield {"model": {"messages": [msg]}}

    runner._agent = Mock()
    runner._agent.astream = mock_astream

    # Run the agent
    response = await runner.run("Test message")

    # Verify metrics were populated (even if zeros due to mock callback)
    assert runner.last_metrics is not None
    assert isinstance(runner.last_metrics, InvocationMetrics)
    assert runner.last_metrics.duration_ms > 0  # Duration should be captured


@pytest.mark.asyncio
async def test_agent_runner_metrics_include_duration(mock_workspace: AgentWorkspace) -> None:
    """Test that metrics include wall-clock duration."""
    runner = AgentRunner(
        workspace=mock_workspace,
        model="anthropic:claude-sonnet-4-20250514",
        api_key="test-key",
    )

    # Mock the agent to stream updates
    async def mock_astream(*args, **kwargs):
        yield {"model": {"messages": [Mock(content="Test response", tool_calls=[])]}}

    runner._agent = Mock()
    runner._agent.astream = mock_astream

    # Run the agent
    await runner.run("Test message")

    # Verify duration is positive
    assert runner.last_metrics is not None
    assert runner.last_metrics.duration_ms > 0
    assert runner.last_metrics.model == "anthropic:claude-sonnet-4-20250514"


@pytest.mark.asyncio
async def test_agent_runner_metrics_on_timeout(mock_workspace: AgentWorkspace) -> None:
    """Test that metrics are still extracted on timeout."""
    runner = AgentRunner(
        workspace=mock_workspace,
        model="anthropic:claude-sonnet-4-20250514",
        api_key="test-key",
        timeout_seconds=0.001,  # Very short timeout
    )

    # Mock the agent to be slow
    async def slow_astream(*args, **kwargs):
        import asyncio
        await asyncio.sleep(1)  # Sleep longer than timeout
        yield {"model": {"messages": [Mock(content="Should not see this")]}}

    runner._agent = Mock()
    runner._agent.astream = slow_astream

    # Run the agent (should timeout)
    response = await runner.run("Test message")

    # Should return timeout message
    assert "ran out of time" in response.lower()

    # Metrics should still be extracted (partial)
    assert runner.last_metrics is not None
    assert isinstance(runner.last_metrics, InvocationMetrics)
    assert runner.last_metrics.duration_ms > 0
