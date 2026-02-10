"""Tests for session privacy prompt injection."""

import pytest
from pathlib import Path

from openpaw.workspace.loader import AgentWorkspace


@pytest.fixture
def workspace_path(tmp_path: Path) -> Path:
    """Create a minimal workspace for testing."""
    workspace = tmp_path / "test_workspace"
    workspace.mkdir()

    # Create required markdown files
    (workspace / "AGENT.md").write_text("# Agent\nTest agent")
    (workspace / "USER.md").write_text("# User\nTest user")
    (workspace / "SOUL.md").write_text("# Soul\nTest soul")
    (workspace / "HEARTBEAT.md").write_text("")

    return workspace


def test_session_privacy_not_included_by_default(workspace_path: Path) -> None:
    """Session Privacy section should not be present when has_group_sessions=False."""
    workspace = AgentWorkspace(
        name="test",
        path=workspace_path,
        agent_md="Test agent",
        user_md="Test user",
        soul_md="Test soul",
        heartbeat_md="",
        skills_path=workspace_path / "skills",
        tools_path=workspace_path / "tools",
    )

    prompt = workspace.build_system_prompt(
        enabled_builtins=None,
        has_group_sessions=False,
    )

    # Should NOT contain session privacy section
    assert "Session Privacy" not in prompt
    assert "workspace files" not in prompt or "shared across ALL sessions" not in prompt


def test_session_privacy_included_when_enabled(workspace_path: Path) -> None:
    """Session Privacy section should be present when has_group_sessions=True."""
    workspace = AgentWorkspace(
        name="test",
        path=workspace_path,
        agent_md="Test agent",
        user_md="Test user",
        soul_md="Test soul",
        heartbeat_md="",
        skills_path=workspace_path / "skills",
        tools_path=workspace_path / "tools",
    )

    prompt = workspace.build_system_prompt(
        enabled_builtins=None,
        has_group_sessions=True,
    )

    # Should contain session privacy section
    assert "Session Privacy" in prompt

    # Verify key phrases are present
    assert "workspace files" in prompt
    assert "isolated history" in prompt
    assert "sensitive information" in prompt
    assert "shared across ALL sessions" in prompt
    assert "private DM" in prompt
    assert "group/channel conversations" in prompt


def test_session_privacy_contains_attribution_guidance(workspace_path: Path) -> None:
    """Session privacy section should mention message attribution."""
    workspace = AgentWorkspace(
        name="test",
        path=workspace_path,
        agent_md="Test agent",
        user_md="Test user",
        soul_md="Test soul",
        heartbeat_md="",
        skills_path=workspace_path / "skills",
        tools_path=workspace_path / "tools",
    )

    prompt = workspace.build_system_prompt(
        enabled_builtins=None,
        has_group_sessions=True,
    )

    # Should mention attributed messages
    assert "[Anna]: message" in prompt or "attributed" in prompt
    assert "address the appropriate user by name" in prompt or "who asked what" in prompt


def test_session_privacy_placement_in_prompt(workspace_path: Path) -> None:
    """Session Privacy section should appear after Conversation Memory."""
    workspace = AgentWorkspace(
        name="test",
        path=workspace_path,
        agent_md="Test agent",
        user_md="Test user",
        soul_md="Test soul",
        heartbeat_md="",
        skills_path=workspace_path / "skills",
        tools_path=workspace_path / "tools",
    )

    prompt = workspace.build_system_prompt(
        enabled_builtins=None,
        has_group_sessions=True,
    )

    # Find positions
    conversation_memory_pos = prompt.find("Conversation Memory")
    session_privacy_pos = prompt.find("Session Privacy")

    # Both should exist
    assert conversation_memory_pos != -1
    assert session_privacy_pos != -1

    # Session Privacy should come after Conversation Memory
    assert session_privacy_pos > conversation_memory_pos
