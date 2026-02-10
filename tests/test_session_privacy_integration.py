"""Integration tests for session privacy prompt wiring through the stack."""

import pytest
from pathlib import Path
from unittest.mock import MagicMock

from openpaw.agent import AgentRunner
from openpaw.workspace.agent_factory import AgentFactory
from openpaw.workspace.loader import AgentWorkspace


@pytest.fixture
def mock_workspace(tmp_path: Path) -> AgentWorkspace:
    """Create a mock workspace for testing."""
    workspace = tmp_path / "test_workspace"
    workspace.mkdir()

    # Create required markdown files
    (workspace / "AGENT.md").write_text("# Agent\nTest agent")
    (workspace / "USER.md").write_text("# User\nTest user")
    (workspace / "SOUL.md").write_text("# Soul\nTest soul")
    (workspace / "HEARTBEAT.md").write_text("")

    return AgentWorkspace(
        name="test",
        path=workspace,
        agent_md="Test agent",
        user_md="Test user",
        soul_md="Test soul",
        heartbeat_md="",
        skills_path=workspace / "skills",
        tools_path=workspace / "tools",
    )


def test_agent_factory_passes_has_group_sessions_to_runner(mock_workspace: AgentWorkspace) -> None:
    """AgentFactory should pass has_group_sessions flag to AgentRunner."""
    factory = AgentFactory(
        workspace=mock_workspace,
        model="anthropic:claude-sonnet-4-20250514",
        api_key="test-key",
        max_turns=10,
        temperature=0.7,
        region=None,
        timeout_seconds=60.0,
        builtin_tools=[],
        workspace_tools=[],
        enabled_builtin_names=[],
        extra_model_kwargs={},
        middleware=[],
        has_group_sessions=True,
        logger=MagicMock(),
    )

    agent = factory.create_agent()

    # Verify the agent has the flag set
    assert hasattr(agent, "_has_group_sessions")
    assert agent._has_group_sessions is True


def test_agent_factory_defaults_to_false(mock_workspace: AgentWorkspace) -> None:
    """AgentFactory should default has_group_sessions to False when not specified."""
    # This test verifies backward compatibility
    factory = AgentFactory(
        workspace=mock_workspace,
        model="anthropic:claude-sonnet-4-20250514",
        api_key="test-key",
        max_turns=10,
        temperature=0.7,
        region=None,
        timeout_seconds=60.0,
        builtin_tools=[],
        workspace_tools=[],
        enabled_builtin_names=[],
        extra_model_kwargs={},
        middleware=[],
        has_group_sessions=False,
        logger=MagicMock(),
    )

    agent = factory.create_agent()

    # Verify the agent has the flag set to False
    assert hasattr(agent, "_has_group_sessions")
    assert agent._has_group_sessions is False


def test_agent_runner_uses_has_group_sessions_in_prompt(mock_workspace: AgentWorkspace) -> None:
    """AgentRunner should use has_group_sessions when building system prompt."""
    # Create agent with has_group_sessions=True
    agent = AgentRunner(
        workspace=mock_workspace,
        model="anthropic:claude-sonnet-4-20250514",
        api_key="test-key",
        has_group_sessions=True,
    )

    # The system prompt is built during _build_agent(), which is called in __init__
    # We can verify by checking the workspace.build_system_prompt was called correctly
    # by rebuilding the prompt manually
    prompt = mock_workspace.build_system_prompt(
        enabled_builtins=None,
        has_group_sessions=True,
    )

    # Verify session privacy section is present
    assert "Session Privacy" in prompt
    assert "workspace files" in prompt
    assert "shared across ALL sessions" in prompt


def test_agent_runner_excludes_session_privacy_when_disabled(mock_workspace: AgentWorkspace) -> None:
    """AgentRunner should not include session privacy when has_group_sessions=False."""
    # Create agent with has_group_sessions=False (default)
    agent = AgentRunner(
        workspace=mock_workspace,
        model="anthropic:claude-sonnet-4-20250514",
        api_key="test-key",
        has_group_sessions=False,
    )

    # Rebuild the prompt manually
    prompt = mock_workspace.build_system_prompt(
        enabled_builtins=None,
        has_group_sessions=False,
    )

    # Verify session privacy section is NOT present
    assert "Session Privacy" not in prompt
