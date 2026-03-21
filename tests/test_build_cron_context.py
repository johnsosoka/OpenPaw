"""Tests for build_cron_context() in openpaw.core.prompts.framework."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from openpaw.core.prompts.framework import build_cron_context
from openpaw.core.workspace import AgentWorkspace
from openpaw.workspace.loader import WorkspaceLoader


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_cron(
    name: str,
    schedule: str = "0 9 * * *",
    enabled: bool = True,
    delivery: str = "channel",
    prompt: str = "Check system health.\nMore detail here.",
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


# ---------------------------------------------------------------------------
# Unit tests for build_cron_context()
# ---------------------------------------------------------------------------


class TestBuildCronContextEmpty:
    """build_cron_context returns empty string when there are no crons."""

    def test_build_cron_context_empty_list(self) -> None:
        """Empty cron list produces an empty string."""
        result = build_cron_context([])
        assert result == ""

    def test_build_cron_context_none_is_empty(self) -> None:
        """None-equivalent falsy list still returns empty string."""
        result = build_cron_context([])
        assert not result


class TestBuildCronContextWithCrons:
    """build_cron_context formats cron jobs correctly."""

    def test_build_cron_context_includes_header(self) -> None:
        """Section header is present when crons are provided."""
        cron = _make_cron("daily-summary")
        result = build_cron_context([cron])
        assert "## Scheduled Tasks" in result

    def test_build_cron_context_includes_cron_name(self) -> None:
        """Cron name appears in bold markdown."""
        cron = _make_cron("daily-summary")
        result = build_cron_context([cron])
        assert "**daily-summary**" in result

    def test_build_cron_context_includes_schedule(self) -> None:
        """Cron schedule appears in backtick format."""
        cron = _make_cron("daily-summary", schedule="0 9 * * *")
        result = build_cron_context([cron])
        assert "`0 9 * * *`" in result

    def test_build_cron_context_includes_delivery_mode(self) -> None:
        """Delivery mode appears in each cron entry."""
        cron = _make_cron("daily-summary", delivery="agent")
        result = build_cron_context([cron])
        assert "delivery: agent" in result

    def test_build_cron_context_includes_log_paths(self) -> None:
        """Footer references the cron log and sessions paths."""
        cron = _make_cron("daily-summary")
        result = build_cron_context([cron])
        assert "data/cron_log.jsonl" in result
        assert "memory/sessions/cron/" in result

    def test_build_cron_context_multiple_crons(self) -> None:
        """Multiple cron jobs are all listed."""
        crons = [
            _make_cron("morning-check", schedule="0 8 * * *"),
            _make_cron("evening-report", schedule="0 20 * * *"),
        ]
        result = build_cron_context(crons)
        assert "**morning-check**" in result
        assert "**evening-report**" in result
        assert "`0 8 * * *`" in result
        assert "`0 20 * * *`" in result

    def test_build_cron_context_mentions_system_event(self) -> None:
        """Section explains [SYSTEM] event delivery for agent mode."""
        cron = _make_cron("daily-summary")
        result = build_cron_context([cron])
        assert "[SYSTEM] event" in result


class TestBuildCronContextDisabledCrons:
    """build_cron_context shows disabled status for inactive crons."""

    def test_build_cron_context_disabled_shows_status(self) -> None:
        """Disabled cron shows 'disabled' in the entry."""
        cron = _make_cron("old-task", enabled=False)
        result = build_cron_context([cron])
        assert "disabled" in result

    def test_build_cron_context_enabled_shows_status(self) -> None:
        """Enabled cron shows 'enabled' in the entry."""
        cron = _make_cron("active-task", enabled=True)
        result = build_cron_context([cron])
        assert "enabled" in result

    def test_build_cron_context_mixed_enabled_disabled(self) -> None:
        """Both enabled and disabled crons are listed with correct status."""
        crons = [
            _make_cron("active-cron", enabled=True),
            _make_cron("paused-cron", enabled=False),
        ]
        result = build_cron_context(crons)
        assert "**active-cron**" in result
        assert "**paused-cron**" in result
        assert "enabled" in result
        assert "disabled" in result


class TestBuildCronContextPromptPreview:
    """build_cron_context includes the first line of the cron prompt."""

    def test_build_cron_context_uses_first_line_only(self) -> None:
        """Only the first line of the prompt is included as a preview."""
        cron = _make_cron(
            "news-digest",
            prompt="Fetch latest AI news.\nThis line should not appear.\nNor this one.",
        )
        result = build_cron_context([cron])
        assert "Fetch latest AI news." in result
        assert "This line should not appear." not in result

    def test_build_cron_context_prompt_preview_truncated_at_80_chars(self) -> None:
        """Prompt preview is truncated to 80 characters."""
        long_first_line = "A" * 100
        cron = _make_cron("long-prompt-cron", prompt=long_first_line)
        result = build_cron_context([cron])
        assert "A" * 80 in result
        assert "A" * 81 not in result

    def test_build_cron_context_strips_leading_whitespace_from_prompt(self) -> None:
        """Leading whitespace in the prompt is stripped before preview."""
        cron = _make_cron("ws-cron", prompt="  Summarize reports.\nMore text.")
        result = build_cron_context([cron])
        assert "Summarize reports." in result


# ---------------------------------------------------------------------------
# Integration test: cron context appears in build_system_prompt()
# ---------------------------------------------------------------------------


@pytest.fixture
def workspace_with_crons(tmp_path: Path) -> AgentWorkspace:
    """Create a workspace and manually attach cron mocks to test prompt output."""
    workspace_path = tmp_path / "test_workspace"
    agent_path = workspace_path / "agent"
    agent_path.mkdir(parents=True, exist_ok=True)
    (agent_path / "AGENT.md").write_text("# Agent")
    (agent_path / "USER.md").write_text("# User")
    (agent_path / "SOUL.md").write_text("# Soul")
    (agent_path / "HEARTBEAT.md").write_text("")

    loader = WorkspaceLoader(tmp_path)
    workspace = loader.load("test_workspace")

    # Attach mock crons directly to the workspace dataclass
    workspace.crons = [
        _make_cron("daily-digest", schedule="0 9 * * *", delivery="agent"),
        _make_cron("weekly-cleanup", schedule="0 0 * * 0", enabled=False),
    ]
    return workspace


class TestCronContextInSystemPrompt:
    """build_system_prompt() includes cron context when workspace has crons."""

    def test_cron_context_in_system_prompt(
        self, workspace_with_crons: AgentWorkspace
    ) -> None:
        """Cron section appears in the full system prompt output."""
        prompt = workspace_with_crons.build_system_prompt()
        assert "## Scheduled Tasks" in prompt
        assert "**daily-digest**" in prompt
        assert "**weekly-cleanup**" in prompt

    def test_cron_context_shows_delivery_mode(
        self, workspace_with_crons: AgentWorkspace
    ) -> None:
        """Delivery mode for each cron appears in the system prompt."""
        prompt = workspace_with_crons.build_system_prompt()
        assert "delivery: agent" in prompt
        assert "delivery: channel" in prompt

    def test_no_cron_context_when_crons_empty(self, tmp_path: Path) -> None:
        """No cron section when workspace has no configured crons."""
        workspace_path = tmp_path / "empty_workspace"
        agent_path = workspace_path / "agent"
        agent_path.mkdir(parents=True, exist_ok=True)
        (agent_path / "AGENT.md").write_text("# Agent")
        (agent_path / "USER.md").write_text("# User")
        (agent_path / "SOUL.md").write_text("# Soul")
        (agent_path / "HEARTBEAT.md").write_text("")

        loader = WorkspaceLoader(tmp_path)
        workspace = loader.load("empty_workspace")
        # No crons set (default is empty list)

        prompt = workspace.build_system_prompt()
        assert "## Scheduled Tasks" not in prompt
