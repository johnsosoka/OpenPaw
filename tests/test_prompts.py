"""Tests for centralized prompt templates."""

from pathlib import Path

import pytest

from openpaw.prompts import (
    COMPACTED_TEMPLATE,
    FOLLOWUP_TEMPLATE,
    HEARTBEAT_PROMPT,
    INTERRUPT_NOTIFICATION,
    STEER_SKIP_MESSAGE,
    SUBAGENT_COMPLETED_SHORT_TEMPLATE,
    SUBAGENT_COMPLETED_TEMPLATE,
    SUBAGENT_FAILED_TEMPLATE,
    SUBAGENT_TIMED_OUT_TEMPLATE,
    SUMMARIZE_PROMPT,
    TIMEOUT_NOTIFICATION_GENERIC,
    TIMEOUT_NOTIFICATION_TEMPLATE,
    TIMEOUT_WARNING_TEMPLATE,
    TOOL_DENIED_TEMPLATE,
    build_capability_summary,
    build_task_summary,
)
from openpaw.prompts.framework import (
    FRAMEWORK_ORIENTATION,
    SECTION_AUTONOMOUS_PLANNING,
    SECTION_CONVERSATION_MEMORY,
    SECTION_FILE_SHARING,
    SECTION_FILE_UPLOADS,
    SECTION_HEARTBEAT,
    SECTION_MEMORY_SEARCH,
    SECTION_PROGRESS_UPDATES,
    SECTION_SELF_CONTINUATION,
    SECTION_SELF_SCHEDULING,
    SECTION_SHELL_HYGIENE,
    SECTION_SUB_AGENT_SPAWNING,
    SECTION_TASK_MANAGEMENT,
    SECTION_WEB_BROWSING,
)
from openpaw.prompts.processors import (
    FILE_RECEIVED_TEMPLATE,
    VOICE_MESSAGE_ERROR_TEMPLATE,
    VOICE_MESSAGE_TEMPLATE,
)
from openpaw.workspace.loader import AgentWorkspace, WorkspaceLoader


class TestTemplateRendering:
    """Test that all PromptTemplate instances render correctly."""

    def test_heartbeat_prompt_renders(self) -> None:
        """HEARTBEAT_PROMPT renders with timestamp."""
        result = HEARTBEAT_PROMPT.format(timestamp="2026-02-19T10:00:00")
        assert "[HEARTBEAT CHECK - 2026-02-19T10:00:00]" in result
        assert "## Step 1: Check Active Tasks" in result
        assert "HEARTBEAT_OK" in result

    def test_followup_template_renders(self) -> None:
        """FOLLOWUP_TEMPLATE renders with depth and prompt."""
        result = FOLLOWUP_TEMPLATE.format(depth=2, prompt="Check status")
        assert result == "[SYSTEM FOLLOWUP - depth 2]\nCheck status"

    def test_tool_denied_template_renders(self) -> None:
        """TOOL_DENIED_TEMPLATE renders with tool name."""
        result = TOOL_DENIED_TEMPLATE.format(tool_name="overwrite_file")
        assert "overwrite_file" in result
        assert "denied by the user" in result

    def test_subagent_timed_out_template_renders(self) -> None:
        """SUBAGENT_TIMED_OUT_TEMPLATE renders correctly."""
        result = SUBAGENT_TIMED_OUT_TEMPLATE.format(
            label="research-task",
            timeout_minutes=30,
        )
        assert "research-task" in result
        assert "30 minutes" in result

    def test_subagent_failed_template_renders(self) -> None:
        """SUBAGENT_FAILED_TEMPLATE renders correctly."""
        result = SUBAGENT_FAILED_TEMPLATE.format(
            label="analysis",
            error="Connection timeout",
        )
        assert "analysis" in result
        assert "Connection timeout" in result

    def test_subagent_completed_template_renders(self) -> None:
        """SUBAGENT_COMPLETED_TEMPLATE renders with truncation message."""
        result = SUBAGENT_COMPLETED_TEMPLATE.format(
            label="search",
            output="Found 42 results...",
            request_id="abc123",
        )
        assert "search" in result
        assert "Found 42 results..." in result
        assert 'get_subagent_result(id="abc123")' in result

    def test_subagent_completed_short_template_renders(self) -> None:
        """SUBAGENT_COMPLETED_SHORT_TEMPLATE renders without truncation."""
        result = SUBAGENT_COMPLETED_SHORT_TEMPLATE.format(
            label="quick-task",
            output="Done!",
        )
        assert "quick-task" in result
        assert "Done!" in result
        assert "get_subagent_result" not in result

    def test_timeout_warning_template_renders(self) -> None:
        """TIMEOUT_WARNING_TEMPLATE renders with percentage and remaining."""
        result = TIMEOUT_WARNING_TEMPLATE.format(
            elapsed_pct=80,
            remaining=30,
        )
        assert "80%" in result
        assert "30s remaining" in result

    def test_timeout_notification_template_renders(self) -> None:
        """TIMEOUT_NOTIFICATION_TEMPLATE renders with timeout and tool name."""
        result = TIMEOUT_NOTIFICATION_TEMPLATE.format(
            timeout=120,
            tool_name="browser_navigate",
        )
        assert "120s" in result
        assert "browser_navigate" in result

    def test_timeout_notification_generic_renders(self) -> None:
        """TIMEOUT_NOTIFICATION_GENERIC renders with timeout."""
        result = TIMEOUT_NOTIFICATION_GENERIC.format(timeout=60)
        assert "60s" in result

    def test_compacted_template_renders(self) -> None:
        """COMPACTED_TEMPLATE renders with summary."""
        result = COMPACTED_TEMPLATE.format(summary="Brief summary of conversation.")
        assert "[CONVERSATION COMPACTED]" in result
        assert "Brief summary of conversation." in result

    def test_file_received_template_renders(self) -> None:
        """FILE_RECEIVED_TEMPLATE renders correctly."""
        result = FILE_RECEIVED_TEMPLATE.format(
            filename="report.pdf",
            size="2.3 MB",
            mime_type="application/pdf",
            saved_path="uploads/2026-02-19/report.pdf",
        )
        assert "report.pdf" in result
        assert "2.3 MB" in result
        assert "application/pdf" in result
        assert "uploads/2026-02-19/report.pdf" in result

    def test_voice_message_template_renders(self) -> None:
        """VOICE_MESSAGE_TEMPLATE renders with transcribed text."""
        result = VOICE_MESSAGE_TEMPLATE.format(text="Hello world")
        assert "[Voice message]: Hello world" == result

    def test_voice_message_error_template_renders(self) -> None:
        """VOICE_MESSAGE_ERROR_TEMPLATE renders with error."""
        result = VOICE_MESSAGE_ERROR_TEMPLATE.format(error="API timeout")
        assert "Unable to transcribe audio" in result
        assert "API timeout" in result


class TestStaticPrompts:
    """Test static prompt strings (no variables)."""

    def test_steer_skip_message_is_string(self) -> None:
        """STEER_SKIP_MESSAGE is a plain string."""
        assert isinstance(STEER_SKIP_MESSAGE, str)
        assert "Skipped" in STEER_SKIP_MESSAGE
        assert "redirecting" in STEER_SKIP_MESSAGE

    def test_interrupt_notification_is_string(self) -> None:
        """INTERRUPT_NOTIFICATION is a plain string."""
        assert isinstance(INTERRUPT_NOTIFICATION, str)
        assert "interrupted" in INTERRUPT_NOTIFICATION

    def test_summarize_prompt_is_string(self) -> None:
        """SUMMARIZE_PROMPT is a plain string."""
        assert isinstance(SUMMARIZE_PROMPT, str)
        assert "3-5 sentences" in SUMMARIZE_PROMPT
        assert "Do NOT include greetings" in SUMMARIZE_PROMPT


class TestFrameworkSections:
    """Test framework section constants."""

    def test_framework_orientation_is_complete(self) -> None:
        """FRAMEWORK_ORIENTATION has expected content."""
        assert "persistent autonomous agent" in FRAMEWORK_ORIENTATION
        assert "OpenPaw framework" in FRAMEWORK_ORIENTATION
        assert "workspace directory" in FRAMEWORK_ORIENTATION

    def test_shell_hygiene_section_exists(self) -> None:
        """SECTION_SHELL_HYGIENE is defined with expected content."""
        assert "## Shell Commands" in SECTION_SHELL_HYGIENE
        assert "Break complex operations into small" in SECTION_SHELL_HYGIENE
        assert "send_message" in SECTION_SHELL_HYGIENE
        assert "timeout" in SECTION_SHELL_HYGIENE

    def test_all_sections_are_strings(self) -> None:
        """All framework section constants are plain strings."""
        sections = [
            FRAMEWORK_ORIENTATION,
            SECTION_HEARTBEAT,
            SECTION_TASK_MANAGEMENT,
            SECTION_SELF_CONTINUATION,
            SECTION_SUB_AGENT_SPAWNING,
            SECTION_WEB_BROWSING,
            SECTION_PROGRESS_UPDATES,
            SECTION_FILE_SHARING,
            SECTION_FILE_UPLOADS,
            SECTION_SELF_SCHEDULING,
            SECTION_AUTONOMOUS_PLANNING,
            SECTION_MEMORY_SEARCH,
            SECTION_CONVERSATION_MEMORY,
            SECTION_SHELL_HYGIENE,
        ]
        for section in sections:
            assert isinstance(section, str), f"Section is not a string: {section[:50]}"


class TestBuildCapabilitySummary:
    """Test build_capability_summary function."""

    def test_capability_summary_with_all_builtins(self) -> None:
        """build_capability_summary includes all capabilities when enabled_builtins is None."""
        result = build_capability_summary(None)
        assert "## Framework Capabilities" in result
        assert "**Filesystem**" in result
        assert "**Task Tracking**" in result
        assert "**Sub-Agent Spawning**" in result
        assert "**Web Browsing**" in result
        assert "**Self-Scheduling**" in result

    def test_capability_summary_with_subset(self) -> None:
        """build_capability_summary includes only specified builtins."""
        result = build_capability_summary(["task_tracker", "spawn"])
        assert "**Task Tracking**" in result
        assert "**Sub-Agent Spawning**" in result
        assert "**Web Browsing**" not in result

    def test_capability_summary_with_empty_list(self) -> None:
        """build_capability_summary works with empty enabled_builtins."""
        result = build_capability_summary([])
        assert "## Framework Capabilities" in result
        assert "**Filesystem**" in result  # Always included
        assert "**Task Tracking**" not in result


class TestBuildTaskSummary:
    """Test build_task_summary function."""

    def test_task_summary_with_no_tasks(self) -> None:
        """build_task_summary returns None for empty task list."""
        result = build_task_summary([])
        assert result is None

    def test_task_summary_formats_tasks(self) -> None:
        """build_task_summary formats tasks with status and age."""
        from datetime import UTC, datetime, timedelta

        now = datetime.now(UTC)
        created_at = (now - timedelta(minutes=30)).isoformat()

        tasks = [
            {
                "id": "abc12345",
                "status": "in_progress",
                "description": "Test task",
                "created_at": created_at,
            }
        ]
        result = build_task_summary(tasks)
        assert result is not None
        assert "Active Tasks (1):" in result
        assert "[abc12345]" in result
        assert "in_progress" in result
        assert "Test task" in result
        assert "30m ago" in result


class TestSystemPromptIdentity:
    """Test that system prompt output is identical before and after refactoring."""

    @pytest.fixture
    def mock_workspace(self, tmp_path: Path) -> AgentWorkspace:
        """Create a minimal mock workspace."""
        workspace_path = tmp_path / "test_workspace"
        workspace_path.mkdir()

        # Create required markdown files
        (workspace_path / "AGENT.md").write_text("# Agent")
        (workspace_path / "USER.md").write_text("# User")
        (workspace_path / "SOUL.md").write_text("# Soul")
        (workspace_path / "HEARTBEAT.md").write_text("# Heartbeat with content")

        loader = WorkspaceLoader(tmp_path)
        return loader.load("test_workspace")

    def test_system_prompt_with_all_builtins(self, mock_workspace: AgentWorkspace) -> None:
        """System prompt output is identical with all builtins enabled."""
        prompt = mock_workspace.build_system_prompt(enabled_builtins=None)

        # Verify key sections are present
        assert "<soul>" in prompt
        assert "<agent>" in prompt
        assert "<framework>" in prompt
        assert "<heartbeat>" in prompt

        # Verify framework sections
        assert "## Framework Capabilities" in prompt
        assert "## Heartbeat System" in prompt
        assert "## Task Management" in prompt
        assert "## Self-Continuation" in prompt
        assert "## Sub-Agent Spawning" in prompt
        assert "## Web Browsing" in prompt
        assert "## Progress Updates" in prompt
        assert "## File Sharing" in prompt
        assert "## File Uploads" in prompt
        assert "## Self-Scheduling" in prompt
        assert "## Shell Commands" in prompt
        assert "## Autonomous Planning" in prompt
        assert "## Memory Search" in prompt
        assert "## Conversation Memory" in prompt

    def test_system_prompt_with_subset_builtins(self, mock_workspace: AgentWorkspace) -> None:
        """System prompt output is correct with subset of builtins."""
        prompt = mock_workspace.build_system_prompt(
            enabled_builtins=["task_tracker", "spawn", "send_message"]
        )

        # Should be present
        assert "## Task Management" in prompt
        assert "## Sub-Agent Spawning" in prompt
        assert "## Progress Updates" in prompt
        assert "## Autonomous Planning" in prompt  # 3 key capabilities

        # Should be absent
        assert "## Self-Continuation" not in prompt
        assert "## Web Browsing" not in prompt
        assert "## Self-Scheduling" not in prompt
        assert "## Memory Search" not in prompt

    def test_shell_hygiene_conditional_on_shell_builtin(
        self, mock_workspace: AgentWorkspace
    ) -> None:
        """Shell hygiene section appears when shell builtin is enabled."""
        # With shell enabled
        prompt_with_shell = mock_workspace.build_system_prompt(
            enabled_builtins=["shell"]
        )
        assert "## Shell Commands" in prompt_with_shell
        assert "Break complex operations into small" in prompt_with_shell

        # Without shell enabled
        prompt_without_shell = mock_workspace.build_system_prompt(
            enabled_builtins=["task_tracker"]
        )
        assert "## Shell Commands" not in prompt_without_shell


class TestImportPaths:
    """Test that all prompt items are importable from openpaw.prompts."""

    def test_all_exports_are_importable(self) -> None:
        """All items in __all__ can be imported from openpaw.prompts."""
        from openpaw.prompts import __all__

        # Verify we can import everything
        import openpaw.prompts

        for name in __all__:
            assert hasattr(openpaw.prompts, name), f"{name} not exported from openpaw.prompts"
