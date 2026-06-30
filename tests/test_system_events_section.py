"""Tests for SECTION_SYSTEM_EVENTS in the framework prompt.

Verifies that the system events guidance section is conditionally included
in the agent system prompt based on whether any system event source is active:
- spawn builtin enabled (sub-agent completion notifications)
- cron with delivery: agent (cron output injected into agent queue)
- heartbeat with delivery: agent (heartbeat output injected into agent queue)
"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from openpaw.core.prompts.framework import SECTION_SYSTEM_EVENTS
from openpaw.core.workspace import AgentWorkspace
from openpaw.workspace.loader import WorkspaceLoader


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_cron(
    name: str = "test-cron",
    schedule: str = "0 9 * * *",
    enabled: bool = True,
    delivery: str = "channel",
    prompt: str = "Check system health.",
) -> MagicMock:
    """Build a minimal CronDefinition-like mock."""
    cron = MagicMock()
    cron.name = name
    cron.schedule = schedule
    cron.enabled = enabled
    cron.prompt = prompt
    cron.output = MagicMock()
    cron.output.delivery = delivery
    return cron


def _make_heartbeat_config(delivery: str = "channel") -> MagicMock:
    """Build a minimal HeartbeatConfig-like mock."""
    hb = MagicMock()
    hb.delivery = delivery
    return hb


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_workspace(tmp_path: Path) -> AgentWorkspace:
    """Create a minimal mock workspace with no system event sources."""
    workspace_path = tmp_path / "test_workspace"
    workspace_path.mkdir()

    agent_path = workspace_path / "agent"
    agent_path.mkdir(parents=True, exist_ok=True)
    (agent_path / "AGENT.md").write_text("# Agent")
    (agent_path / "USER.md").write_text("# User")
    (agent_path / "SOUL.md").write_text("# Soul")
    (agent_path / "HEARTBEAT.md").write_text("")

    loader = WorkspaceLoader(tmp_path)
    return loader.load("test_workspace")


# ---------------------------------------------------------------------------
# Section content
# ---------------------------------------------------------------------------


class TestSystemEventsSectionContent:
    """Verify SECTION_SYSTEM_EVENTS text contains required guidance."""

    def test_section_mentions_acknowledge_event(self) -> None:
        """Section still references acknowledge_event (now as optional audit signal)."""
        assert "acknowledge_event" in SECTION_SYSTEM_EVENTS

    def test_section_teaches_send_message_for_user_facing_output(self) -> None:
        """Section instructs agent to use send_message to surface anything for the user."""
        assert "send_message" in SECTION_SYSTEM_EVENTS

    def test_section_teaches_suppress_by_default(self) -> None:
        """Section explains that terminal replies to system events are NOT delivered."""
        assert "NOT delivered" in SECTION_SYSTEM_EVENTS

    def test_section_mentions_system_messages(self) -> None:
        """Section explains that [SYSTEM] messages come from the framework."""
        assert "[SYSTEM]" in SECTION_SYSTEM_EVENTS

    def test_section_mentions_cron_jobs(self) -> None:
        """Section explains cron jobs as a source of system events."""
        assert "cron" in SECTION_SYSTEM_EVENTS.lower()

    def test_section_mentions_sub_agents(self) -> None:
        """Section explains sub-agents as a source of system events."""
        assert "sub-agent" in SECTION_SYSTEM_EVENTS.lower()

    def test_section_explains_not_from_user(self) -> None:
        """Section clarifies that system events are NOT from the user."""
        assert "NOT from the user" in SECTION_SYSTEM_EVENTS

    def test_section_explains_suppression_behavior(self) -> None:
        """Section explains that the tool suppresses delivery, not logging."""
        assert "still recorded" in SECTION_SYSTEM_EVENTS or "still logged" in SECTION_SYSTEM_EVENTS

    def test_section_only_suppresses_system_events(self) -> None:
        """Section clarifies the tool has no effect on user messages."""
        assert "has no effect on user messages" in SECTION_SYSTEM_EVENTS


# ---------------------------------------------------------------------------
# Conditional inclusion: spawn builtin
# ---------------------------------------------------------------------------


class TestSystemEventsSectionWithSpawn:
    """Section is included when spawn builtin is active."""

    def test_section_included_with_spawn_builtin(
        self, mock_workspace: AgentWorkspace
    ) -> None:
        """System events section appears when spawn is in enabled_builtins."""
        prompt = mock_workspace.build_system_prompt(enabled_builtins=["spawn"])
        assert "## System Events" in prompt

    def test_section_included_with_spawn_and_other_builtins(
        self, mock_workspace: AgentWorkspace
    ) -> None:
        """Section appears when spawn is among multiple enabled builtins."""
        prompt = mock_workspace.build_system_prompt(
            enabled_builtins=["spawn", "task_tracker", "followup"]
        )
        assert "## System Events" in prompt

    def test_section_included_when_all_builtins_enabled(
        self, mock_workspace: AgentWorkspace
    ) -> None:
        """Section appears when enabled_builtins is None (all enabled)."""
        prompt = mock_workspace.build_system_prompt(enabled_builtins=None)
        assert "## System Events" in prompt


# ---------------------------------------------------------------------------
# Conditional inclusion: cron with delivery: agent or both
# ---------------------------------------------------------------------------


class TestSystemEventsSectionWithAgentDeliveryCron:
    """Section is included when at least one cron uses delivery: agent or both."""

    def test_section_included_with_agent_delivery_cron(
        self, mock_workspace: AgentWorkspace
    ) -> None:
        """System events section appears when a cron uses delivery: agent."""
        mock_workspace.crons = [_make_cron(delivery="agent")]
        # Exclude spawn to isolate the cron trigger
        prompt = mock_workspace.build_system_prompt(enabled_builtins=["task_tracker"])
        assert "## System Events" in prompt

    def test_section_included_with_both_delivery_cron(
        self, mock_workspace: AgentWorkspace
    ) -> None:
        """System events section appears when a cron uses delivery: both (the default)."""
        mock_workspace.crons = [_make_cron(delivery="both")]
        # Exclude spawn to isolate the cron trigger
        prompt = mock_workspace.build_system_prompt(enabled_builtins=["task_tracker"])
        assert "## System Events" in prompt

    def test_section_included_when_one_of_many_crons_uses_agent_delivery(
        self, mock_workspace: AgentWorkspace
    ) -> None:
        """Section appears when any cron uses agent delivery, not all."""
        mock_workspace.crons = [
            _make_cron(name="channel-cron", delivery="channel"),
            _make_cron(name="agent-cron", delivery="agent"),
        ]
        prompt = mock_workspace.build_system_prompt(enabled_builtins=["task_tracker"])
        assert "## System Events" in prompt

    def test_section_included_when_one_of_many_crons_uses_both_delivery(
        self, mock_workspace: AgentWorkspace
    ) -> None:
        """Section appears when any cron uses both delivery, even if others use channel."""
        mock_workspace.crons = [
            _make_cron(name="channel-cron", delivery="channel"),
            _make_cron(name="both-cron", delivery="both"),
        ]
        prompt = mock_workspace.build_system_prompt(enabled_builtins=["task_tracker"])
        assert "## System Events" in prompt

    def test_section_absent_when_all_crons_use_channel_delivery(
        self, mock_workspace: AgentWorkspace
    ) -> None:
        """Section absent when crons exist but all use channel delivery."""
        mock_workspace.crons = [
            _make_cron(name="cron-a", delivery="channel"),
            _make_cron(name="cron-b", delivery="channel"),
        ]
        # Exclude spawn to isolate the cron trigger; no heartbeat agent delivery
        prompt = mock_workspace.build_system_prompt(enabled_builtins=["task_tracker"])
        assert "## System Events" not in prompt


# ---------------------------------------------------------------------------
# Conditional inclusion: heartbeat with delivery: agent or both
# ---------------------------------------------------------------------------


class TestSystemEventsSectionWithAgentDeliveryHeartbeat:
    """Section is included when heartbeat uses delivery: agent or both."""

    def test_section_included_with_heartbeat_agent_delivery(
        self, mock_workspace: AgentWorkspace
    ) -> None:
        """System events section appears when heartbeat delivery is 'agent'."""
        config = MagicMock()
        config.heartbeat = _make_heartbeat_config(delivery="agent")
        mock_workspace.config = config

        prompt = mock_workspace.build_system_prompt(enabled_builtins=["task_tracker"])
        assert "## System Events" in prompt

    def test_section_included_with_heartbeat_both_delivery(
        self, mock_workspace: AgentWorkspace
    ) -> None:
        """System events section appears when heartbeat delivery is 'both'."""
        config = MagicMock()
        config.heartbeat = _make_heartbeat_config(delivery="both")
        mock_workspace.config = config

        prompt = mock_workspace.build_system_prompt(enabled_builtins=["task_tracker"])
        assert "## System Events" in prompt

    def test_section_absent_with_heartbeat_channel_delivery(
        self, mock_workspace: AgentWorkspace
    ) -> None:
        """Section absent when heartbeat exists but uses channel delivery."""
        config = MagicMock()
        config.heartbeat = _make_heartbeat_config(delivery="channel")
        mock_workspace.config = config

        prompt = mock_workspace.build_system_prompt(enabled_builtins=["task_tracker"])
        assert "## System Events" not in prompt

    def test_section_absent_with_no_heartbeat_config(
        self, mock_workspace: AgentWorkspace
    ) -> None:
        """Section absent when heartbeat config is None."""
        config = MagicMock()
        config.heartbeat = None
        mock_workspace.config = config

        prompt = mock_workspace.build_system_prompt(enabled_builtins=["task_tracker"])
        assert "## System Events" not in prompt


# ---------------------------------------------------------------------------
# Conditional inclusion: absent when no system event sources
# ---------------------------------------------------------------------------


class TestSystemEventsSectionAbsent:
    """Section is not included when no system event sources are active."""

    def test_section_absent_with_no_sources(
        self, mock_workspace: AgentWorkspace
    ) -> None:
        """Section absent when spawn excluded, no crons, no heartbeat agent delivery."""
        # Explicit enabled_builtins without spawn; no crons; no config
        prompt = mock_workspace.build_system_prompt(
            enabled_builtins=["task_tracker", "followup", "send_message"]
        )
        assert "## System Events" not in prompt

    def test_section_absent_with_empty_crons_and_no_spawn(
        self, mock_workspace: AgentWorkspace
    ) -> None:
        """Section absent when cron list is empty and spawn is not enabled."""
        mock_workspace.crons = []
        prompt = mock_workspace.build_system_prompt(
            enabled_builtins=["task_tracker", "followup"]
        )
        assert "## System Events" not in prompt

    def test_section_absent_with_channel_only_builtins(
        self, mock_workspace: AgentWorkspace
    ) -> None:
        """Section absent when only non-spawn channel-related builtins are enabled."""
        prompt = mock_workspace.build_system_prompt(
            enabled_builtins=["brave_search", "send_message", "plan"]
        )
        assert "## System Events" not in prompt
