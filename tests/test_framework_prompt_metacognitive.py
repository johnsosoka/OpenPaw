"""Tests for metacognitive prompting enhancements in framework context."""

from pathlib import Path

import pytest

from openpaw.workspace.loader import AgentWorkspace, WorkspaceLoader


@pytest.fixture
def mock_workspace(tmp_path: Path) -> AgentWorkspace:
    """Create a minimal mock workspace."""
    workspace_path = tmp_path / "test_workspace"
    workspace_path.mkdir()

    # Create required markdown files
    (workspace_path / "AGENT.md").write_text("# Agent")
    (workspace_path / "USER.md").write_text("# User")
    (workspace_path / "SOUL.md").write_text("# Soul")
    (workspace_path / "HEARTBEAT.md").write_text("# Heartbeat with content for testing")

    loader = WorkspaceLoader(tmp_path)
    return loader.load("test_workspace")


class TestSubAgentProactiveGuidance:
    """Test sub-agent spawning section includes proactive delegation guidance."""

    def test_subagent_section_includes_proactive_guidance(
        self, mock_workspace: AgentWorkspace
    ) -> None:
        """Sub-agent section includes 'should consider' and decision criteria."""
        prompt = mock_workspace.build_system_prompt(enabled_builtins=["spawn"])

        # Verify proactive language
        assert "## Sub-Agent Spawning" in prompt
        assert "**Proactive delegation:**" in prompt
        assert "should consider spawning sub-agents" in prompt

        # Verify decision criteria are present
        assert "multiple independent components" in prompt
        assert "researched or processed in parallel" in prompt
        assert "task would take significant time" in prompt
        assert "gather information from multiple sources" in prompt

        # Verify transparency requirement
        assert "always tell the user what you are delegating and why" in prompt
        assert "Do not silently spawn background work" in prompt

    def test_subagent_section_preserves_original_content(
        self, mock_workspace: AgentWorkspace
    ) -> None:
        """Enhanced section still includes original notification content."""
        prompt = mock_workspace.build_system_prompt(enabled_builtins=["spawn"])

        # Original content should still be present
        assert "sub-agent completes" in prompt
        assert "list_subagents" in prompt
        assert "get_subagent_result" in prompt


class TestFollowupProactiveGuidance:
    """Test self-continuation section includes proactive use guidance."""

    def test_followup_section_includes_proactive_guidance(
        self, mock_workspace: AgentWorkspace
    ) -> None:
        """Self-continuation section encourages proactive use."""
        prompt = mock_workspace.build_system_prompt(enabled_builtins=["followup"])

        assert "## Self-Continuation" in prompt
        assert "Completion rule" in prompt
        assert "diagnosed a problem but not yet applied the fix" in prompt
        assert "Is the user's request fully addressed?" in prompt

    def test_followup_section_preserves_original_content(
        self, mock_workspace: AgentWorkspace
    ) -> None:
        """Enhanced section still includes original capability description."""
        prompt = mock_workspace.build_system_prompt(enabled_builtins=["followup"])

        # Original content should still be present
        assert "multi-step workflow" in prompt
        assert "delayed followups" in prompt


class TestTaskManagementProactiveGuidance:
    """Test task management section includes proactive creation guidance."""

    def test_task_section_includes_proactive_guidance(
        self, mock_workspace: AgentWorkspace
    ) -> None:
        """Task management section encourages proactive task creation."""
        prompt = mock_workspace.build_system_prompt(enabled_builtins=["task_tracker"])

        assert "## Task Management" in prompt
        assert "When starting work that may not complete in a single conversation turn" in prompt
        assert "create a task to maintain continuity" in prompt

    def test_task_section_preserves_original_content(
        self, mock_workspace: AgentWorkspace
    ) -> None:
        """Enhanced section still includes original persistence description."""
        prompt = mock_workspace.build_system_prompt(enabled_builtins=["task_tracker"])

        # Original content should still be present
        assert "TASKS.yaml" in prompt
        assert "Tasks persist" in prompt
        assert "Future heartbeats will see your tasks" in prompt


class TestAutonomousPlanningSection:
    """Test new autonomous planning section for capability composition."""

    def test_autonomous_planning_section_present_with_multiple_capabilities(
        self, mock_workspace: AgentWorkspace
    ) -> None:
        """Autonomous planning section appears when multiple capabilities enabled."""
        # Test with multiple capabilities
        prompt = mock_workspace.build_system_prompt(
            enabled_builtins=["spawn", "followup", "task_tracker", "send_message"]
        )

        assert "## Autonomous Planning" in prompt
        assert "plan the FULL scope" in prompt

        # Verify lifecycle steps
        assert "Diagnose" in prompt
        assert "Execute" in prompt
        assert "Verify" in prompt
        assert "Report" in prompt
        assert "Do not stop after diagnosis" in prompt

        # Verify decision criteria questions
        assert "Can parts of this work happen in parallel?" in prompt
        assert "Will this span multiple turns?" in prompt
        assert "Should the user know what is happening?" in prompt

        # Verify proactive action guidance
        assert "Prefer proactive action over asking the user for permission" in prompt
        assert "Explain what you are doing and why" in prompt
        assert "do not wait for approval to use tools you have been given" in prompt

    def test_autonomous_planning_section_present_with_all_builtins(
        self, mock_workspace: AgentWorkspace
    ) -> None:
        """Autonomous planning section appears when enabled_builtins is None."""
        prompt = mock_workspace.build_system_prompt(enabled_builtins=None)

        assert "## Autonomous Planning" in prompt

    def test_autonomous_planning_section_present_with_two_capabilities(
        self, mock_workspace: AgentWorkspace
    ) -> None:
        """Autonomous planning section appears with just two key capabilities."""
        # Test with exactly 2 capabilities
        prompt = mock_workspace.build_system_prompt(enabled_builtins=["spawn", "followup"])

        assert "## Autonomous Planning" in prompt

    def test_autonomous_planning_section_absent_with_one_capability(
        self, mock_workspace: AgentWorkspace
    ) -> None:
        """Autonomous planning section does not appear with only one capability."""
        # Test with just one key capability
        prompt = mock_workspace.build_system_prompt(enabled_builtins=["spawn"])

        assert "## Autonomous Planning" not in prompt

    def test_autonomous_planning_section_absent_with_no_key_capabilities(
        self, mock_workspace: AgentWorkspace
    ) -> None:
        """Autonomous planning section does not appear with no key capabilities."""
        # Test with builtins that aren't key capabilities
        prompt = mock_workspace.build_system_prompt(enabled_builtins=["cron", "send_file"])

        assert "## Autonomous Planning" not in prompt


class TestConditionalInclusion:
    """Test that sections are conditionally included based on enabled_builtins."""

    def test_all_sections_included_when_enabled_builtins_none(
        self, mock_workspace: AgentWorkspace
    ) -> None:
        """All capability sections included when enabled_builtins is None."""
        prompt = mock_workspace.build_system_prompt(enabled_builtins=None)

        # All sections should be present
        assert "## Framework Capabilities" in prompt
        assert "## Task Management" in prompt
        assert "## Self-Continuation" in prompt
        assert "## Sub-Agent Spawning" in prompt
        assert "## Progress Updates" in prompt
        assert "## Self-Scheduling" in prompt
        assert "## Memory Search" in prompt
        assert "## Autonomous Planning" in prompt

    def test_only_specified_sections_included(self, mock_workspace: AgentWorkspace) -> None:
        """Only specified capability sections are included."""
        prompt = mock_workspace.build_system_prompt(enabled_builtins=["task_tracker", "spawn"])

        # Included sections
        assert "## Task Management" in prompt
        assert "## Sub-Agent Spawning" in prompt

        # Excluded sections
        assert "## Self-Continuation" not in prompt
        assert "## Self-Scheduling" not in prompt

    def test_autonomous_planning_threshold_logic(self, mock_workspace: AgentWorkspace) -> None:
        """Autonomous planning appears with 2+ key capabilities, not with 1."""
        # With 1 key capability
        prompt_one = mock_workspace.build_system_prompt(enabled_builtins=["spawn"])
        assert "## Autonomous Planning" not in prompt_one

        # With 2 key capabilities
        prompt_two = mock_workspace.build_system_prompt(enabled_builtins=["spawn", "followup"])
        assert "## Autonomous Planning" in prompt_two

        # With 3 key capabilities
        prompt_three = mock_workspace.build_system_prompt(
            enabled_builtins=["spawn", "followup", "task_tracker"]
        )
        assert "## Autonomous Planning" in prompt_three


class TestPromptTone:
    """Test that enhanced sections maintain consistent proactive tone."""

    def test_proactive_language_consistency(self, mock_workspace: AgentWorkspace) -> None:
        """All enhanced sections use consistent proactive language."""
        prompt = mock_workspace.build_system_prompt(
            enabled_builtins=["spawn", "followup", "task_tracker", "send_message"]
        )

        # Check for proactive language patterns
        proactive_keywords = [
            "should consider",
            "Prefer proactive action",
            "When starting work",
            "Do not stop after diagnosis",
            "Completion rule",
        ]

        for keyword in proactive_keywords:
            assert keyword in prompt, f"Expected proactive keyword '{keyword}' in prompt"

    def test_transparency_requirements_present(self, mock_workspace: AgentWorkspace) -> None:
        """Enhanced sections maintain transparency requirements."""
        prompt = mock_workspace.build_system_prompt(
            enabled_builtins=["spawn", "followup", "send_message"]
        )

        # Check transparency language
        transparency_patterns = [
            "always tell the user",
            "Do not silently",
            "Explain what you are doing",
        ]

        for pattern in transparency_patterns:
            assert pattern in prompt, f"Expected transparency pattern '{pattern}' in prompt"


class TestFrameworkCapabilitySummary:
    """Test the Framework Capabilities summary section."""

    def test_capability_summary_always_present(self, mock_workspace: AgentWorkspace) -> None:
        """Capability summary section is always present regardless of builtins."""
        prompt = mock_workspace.build_system_prompt(enabled_builtins=[])
        assert "## Framework Capabilities" in prompt
        assert "**Filesystem**" in prompt
        assert "**Conversation Archives**" in prompt

    def test_capability_summary_with_all_builtins(self, mock_workspace: AgentWorkspace) -> None:
        """All capability bullets appear when enabled_builtins is None."""
        prompt = mock_workspace.build_system_prompt(enabled_builtins=None)

        assert "## Framework Capabilities" in prompt
        assert "**Filesystem**" in prompt
        assert "**Conversation Archives**" in prompt
        assert "**Task Tracking**" in prompt
        assert "**Sub-Agent Spawning**" in prompt
        assert "**Web Browsing**" in prompt
        assert "**Self-Scheduling**" in prompt
        assert "**Self-Continuation**" in prompt
        assert "**Progress Updates**" in prompt
        assert "**File Sharing**" in prompt
        assert "**Memory Search**" in prompt

    def test_capability_summary_with_subset(self, mock_workspace: AgentWorkspace) -> None:
        """Only enabled capabilities appear in the summary."""
        prompt = mock_workspace.build_system_prompt(
            enabled_builtins=["task_tracker", "browser"]
        )

        assert "## Framework Capabilities" in prompt
        assert "**Filesystem**" in prompt
        assert "**Task Tracking**" in prompt
        assert "**Web Browsing**" in prompt

        # These should not appear
        assert "**Sub-Agent Spawning**" not in prompt
        assert "**Self-Scheduling**" not in prompt
        assert "**Memory Search**" not in prompt

    def test_capability_summary_appears_before_detailed_sections(
        self, mock_workspace: AgentWorkspace
    ) -> None:
        """Capability summary appears before detailed section descriptions."""
        prompt = mock_workspace.build_system_prompt(
            enabled_builtins=["task_tracker", "spawn"]
        )
        capabilities_pos = prompt.index("## Framework Capabilities")
        task_mgmt_pos = prompt.index("## Task Management")
        subagent_pos = prompt.index("## Sub-Agent Spawning")

        assert capabilities_pos < task_mgmt_pos
        assert capabilities_pos < subagent_pos


class TestMemorySearchSection:
    """Test the Memory Search prompt section."""

    def test_memory_search_section_present_when_enabled(
        self, mock_workspace: AgentWorkspace
    ) -> None:
        """Memory search section appears when memory_search is in enabled builtins."""
        prompt = mock_workspace.build_system_prompt(
            enabled_builtins=["memory_search"]
        )
        assert "## Memory Search" in prompt
        assert "search_conversations" in prompt
        assert "past conversations" in prompt

    def test_memory_search_section_present_when_all_builtins(
        self, mock_workspace: AgentWorkspace
    ) -> None:
        """Memory search section appears when enabled_builtins is None."""
        prompt = mock_workspace.build_system_prompt(enabled_builtins=None)
        assert "## Memory Search" in prompt

    def test_memory_search_section_absent_when_not_enabled(
        self, mock_workspace: AgentWorkspace
    ) -> None:
        """Memory search section absent when memory_search not in enabled builtins."""
        prompt = mock_workspace.build_system_prompt(
            enabled_builtins=["task_tracker", "spawn"]
        )
        assert "## Memory Search" not in prompt

    def test_memory_search_includes_use_cases(
        self, mock_workspace: AgentWorkspace
    ) -> None:
        """Memory search section describes when to use it."""
        prompt = mock_workspace.build_system_prompt(
            enabled_builtins=["memory_search"]
        )
        assert "references something discussed in a prior conversation" in prompt
        assert "past decisions, instructions, or findings" in prompt


class TestShellHygieneSection:
    """Test the Shell Hygiene prompt section."""

    def test_shell_hygiene_section_present_when_enabled(
        self, mock_workspace: AgentWorkspace
    ) -> None:
        """Shell hygiene section appears when shell builtin is enabled."""
        prompt = mock_workspace.build_system_prompt(
            enabled_builtins=["shell", "send_message"]
        )
        assert "## Shell Commands" in prompt
        assert "Break complex operations" in prompt

    def test_shell_hygiene_section_present_when_all_builtins(
        self, mock_workspace: AgentWorkspace
    ) -> None:
        """Shell hygiene section appears when enabled_builtins is None."""
        prompt = mock_workspace.build_system_prompt(enabled_builtins=None)
        assert "## Shell Commands" in prompt

    def test_shell_hygiene_section_absent_when_not_enabled(
        self, mock_workspace: AgentWorkspace
    ) -> None:
        """Shell hygiene section absent when shell builtin is not enabled."""
        prompt = mock_workspace.build_system_prompt(
            enabled_builtins=["brave_search", "task_tracker"]
        )
        assert "## Shell Commands" not in prompt

    def test_shell_hygiene_includes_best_practices(
        self, mock_workspace: AgentWorkspace
    ) -> None:
        """Shell hygiene section includes command best practices."""
        prompt = mock_workspace.build_system_prompt(enabled_builtins=["shell"])
        assert "Break complex operations into small, sequential commands" in prompt
        # Check for guidance on avoiding chained operations
        assert "rather than chaining" in prompt.lower() or "chaining" in prompt.lower()


class TestCompletionRule:
    """Test completion rule presence in self-continuation section."""

    def test_completion_rule_present(self, mock_workspace: AgentWorkspace) -> None:
        prompt = mock_workspace.build_system_prompt(enabled_builtins=["followup"])
        assert "Completion rule" in prompt
        assert "Is the user's request fully addressed?" in prompt

    def test_completion_rule_includes_triggers(self, mock_workspace: AgentWorkspace) -> None:
        prompt = mock_workspace.build_system_prompt(enabled_builtins=["followup"])
        assert "diagnosed a problem but not yet applied the fix" in prompt
        assert "partway through a multi-step workflow" in prompt
        assert "verify that your changes worked" in prompt


class TestDiagnoseFixVerifyCycle:
    """Test diagnose-fix-verify-report cycle in autonomous planning."""

    def test_lifecycle_steps_present(self, mock_workspace: AgentWorkspace) -> None:
        prompt = mock_workspace.build_system_prompt(
            enabled_builtins=["spawn", "followup", "task_tracker", "send_message"]
        )
        assert "Diagnose" in prompt
        assert "Execute" in prompt
        assert "Verify" in prompt
        assert "Report" in prompt
        assert "Do not stop after diagnosis" in prompt


class TestShellDiagnosticFollowThrough:
    """Test shell hygiene includes diagnostic follow-through."""

    def test_diagnostic_follow_through_present(self, mock_workspace: AgentWorkspace) -> None:
        prompt = mock_workspace.build_system_prompt(enabled_builtins=["shell"])
        assert "Diagnosing a problem is not the same as fixing it" in prompt


class TestProgressUpdatesNotFinal:
    """Test progress updates section clarifies updates are mid-task."""

    def test_not_final_answer_present(self, mock_workspace: AgentWorkspace) -> None:
        prompt = mock_workspace.build_system_prompt(enabled_builtins=["send_message"])
        assert "not your final answer" in prompt
        assert "continue working" in prompt


class TestWorkEthicSection:
    """Test operational work ethic section."""

    def test_work_ethic_present_when_shell_enabled(self, mock_workspace: AgentWorkspace) -> None:
        prompt = mock_workspace.build_system_prompt(enabled_builtins=["shell"])
        assert "## Operational Work Ethic" in prompt
        assert "Diagnose" in prompt
        assert "Verify" in prompt
        assert "Do not end your turn between steps 1 and 5" in prompt

    def test_work_ethic_absent_when_shell_not_enabled(self, mock_workspace: AgentWorkspace) -> None:
        prompt = mock_workspace.build_system_prompt(enabled_builtins=["brave_search"])
        assert "## Operational Work Ethic" not in prompt

    def test_work_ethic_present_when_all_builtins(self, mock_workspace: AgentWorkspace) -> None:
        prompt = mock_workspace.build_system_prompt(enabled_builtins=None)
        assert "## Operational Work Ethic" in prompt


class TestPlanningSection:
    """Test planning tool guidance section."""

    def test_planning_section_present_when_plan_enabled(self, mock_workspace: AgentWorkspace) -> None:
        prompt = mock_workspace.build_system_prompt(enabled_builtins=["plan"])
        assert "## Planning" in prompt
        assert "write_plan" in prompt
        assert "session-scoped" in prompt.lower() or "session" in prompt.lower()

    def test_planning_section_absent_when_plan_not_enabled(self, mock_workspace: AgentWorkspace) -> None:
        prompt = mock_workspace.build_system_prompt(enabled_builtins=["brave_search"])
        assert "## Planning" not in prompt

    def test_planning_section_present_when_all_builtins(self, mock_workspace: AgentWorkspace) -> None:
        prompt = mock_workspace.build_system_prompt(enabled_builtins=None)
        assert "## Planning" in prompt
