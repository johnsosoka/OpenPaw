"""AgentWorkspace model — pure data representation of a loaded agent workspace.

This module lives in core/ because AgentWorkspace is a stable data model whose
only dependencies are other core modules (prompts, config). It has no dependency
on the workspace/ or agent/ layers, satisfying the stability contract.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from openpaw.core.paths import AGENT_MD, HEARTBEAT_MD, SOUL_MD, USER_MD
from openpaw.core.prompts.framework import (
    SECTION_AUTONOMOUS_PLANNING,
    SECTION_CHANNEL_CONTEXT,
    SECTION_CHANNEL_HISTORY,
    SECTION_CHANNEL_LOGS,
    SECTION_CONVERSATION_MEMORY,
    SECTION_FILE_SHARING,
    SECTION_FILE_UPLOADS,
    SECTION_HEARTBEAT,
    SECTION_LEARNING,
    SECTION_MEMORY_SEARCH,
    SECTION_PLANNING,
    SECTION_PROGRESS_UPDATES,
    SECTION_REPORT_PROGRESS,
    SECTION_SELF_CONTINUATION,
    SECTION_SELF_SCHEDULING,
    SECTION_SHELL_HYGIENE,
    SECTION_SUB_AGENT_SPAWNING,
    SECTION_SYSTEM_EVENTS,
    SECTION_TASK_MANAGEMENT,
    SECTION_WEB_BROWSING,
    SECTION_WORK_ETHIC,
    SECTION_WORKSPACE_FILESYSTEM,
    build_capability_summary,
    build_cron_context,
    build_framework_orientation,
)

if TYPE_CHECKING:
    from openpaw.core.config import WorkspaceConfig
    from openpaw.core.config.models import CronDefinition

# Import SkillInfo at runtime (not TYPE_CHECKING) — it's a pure dataclass with
# no framework dependencies, so it's safe to import in core/.
from openpaw.model.skill import SkillInfo, SkillStatus

logger = logging.getLogger(__name__)


@dataclass
class AgentWorkspace:
    """Represents a loaded agent workspace with all its components."""

    name: str
    path: Path
    agent_md: str
    user_md: str
    soul_md: str
    heartbeat_md: str
    skills_path: Path
    tools_path: Path
    config: "WorkspaceConfig | None" = None
    crons: "list[CronDefinition]" = field(default_factory=list)
    skills: list[SkillInfo] = field(default_factory=list)
    team_roster: str = ""

    @property
    def learning_enabled(self) -> bool:
        """Whether the learning loop (PRD-001 Phase 1) is on for this workspace."""
        return bool(self.config and self.config.learning.enabled)

    def reload_files(self) -> None:
        """Re-read workspace markdown files from disk.

        Call this when workspace files may have changed (e.g., agent modified
        its own AGENT.md or HEARTBEAT.md) to ensure the next prompt build
        uses current content.
        """
        self.agent_md = self._read_file(self.path / str(AGENT_MD))
        self.user_md = self._read_file(self.path / str(USER_MD))
        self.soul_md = self._read_file(self.path / str(SOUL_MD))
        self.heartbeat_md = self._read_file(self.path / str(HEARTBEAT_MD))
        logger.debug(f"Reloaded workspace files for: {self.name}")

    @staticmethod
    def _read_file(path: Path) -> str:
        """Read file contents, returning empty string if file doesn't exist."""
        if path.exists():
            return path.read_text(encoding="utf-8")
        return ""

    def build_system_prompt(
        self,
        enabled_builtins: list[str] | None = None,
        current_datetime: str | None = None,
        channel_logging_enabled: bool = False,
    ) -> str:
        """Stitch together workspace files into a system prompt.

        The prompt structure follows DeepAgents conventions with clear sections.
        Returns a string suitable for use with create_react_agent.

        Args:
            enabled_builtins: List of enabled builtin names. Used to conditionally
                include framework capabilities (task_tracker, cron, followup, etc.).
                If None (default), all capabilities are included for backward compat.
            current_datetime: Current date/time string to inject into the prompt.
                Ensures agents always know the actual current date, even when the
                workspace markdown files are cached from startup.
            channel_logging_enabled: Whether persistent channel message logging is
                active. When True, includes the Channel Logs section explaining how
                to read and search logs at memory/logs/channel/.

        Returns:
            String containing workspace prompt sections and framework orientation.
        """
        sections = []

        if self.soul_md:
            sections.append(f"<soul>\n{self.soul_md.strip()}\n</soul>")

        if self.agent_md:
            sections.append(f"<agent>\n{self.agent_md.strip()}\n</agent>")

        if self.user_md:
            sections.append(f"<user>\n{self.user_md.strip()}\n</user>")

        # Framework orientation comes before heartbeat
        framework_context = self._build_framework_context(
            enabled_builtins, channel_logging_enabled=channel_logging_enabled
        )
        if framework_context:
            sections.append(f"<framework>\n{framework_context}\n</framework>")

        # Team roster — injected when spawn profiles are configured
        if self.team_roster:
            sections.append(f"<team>\n{self.team_roster}\n</team>")

        # Skills — injected before workspace context so agents know what's available.
        # Staged skills (awaiting /skills approve) are excluded from the prompt.
        # The skill-authoring guide only injects when the learning loop is on.
        injectable_skills = [
            s
            for s in self.skills
            if s.status is not SkillStatus.STAGED
            and not (s.name == "skill-authoring" and not self.learning_enabled)
        ]
        if injectable_skills:
            skills_section = self._build_skills_section(injectable_skills)
            sections.append(f"<skills>\n{skills_section}\n</skills>")

        # Workspace context — tells the agent its workspace name and top-level contents
        workspace_context = self._build_workspace_context()
        sections.append(f"<workspace_context>\n{workspace_context}\n</workspace_context>")

        # Dynamic date injection — ensures agents know the actual current date
        # even when workspace files are cached from startup
        if current_datetime:
            sections.append(f"<current_datetime>\n{current_datetime}\n</current_datetime>")

        if self.heartbeat_md:
            sections.append(f"<heartbeat>\n{self.heartbeat_md.strip()}\n</heartbeat>")

        return "\n\n".join(sections)

    def _build_workspace_context(self) -> str:
        """Build a workspace context block showing the workspace name and top-level contents.

        Lists only top-level directory entries (no recursion). Hidden files and
        directories are skipped. Directories are marked with a trailing '/'.

        Returns:
            Formatted workspace context string.
        """
        lines = [f"Workspace: {self.name}", "Contents:"]

        try:
            entries = sorted(self.path.iterdir(), key=lambda p: p.name)
            for entry in entries:
                name = entry.name
                if name.startswith("."):
                    continue
                if entry.is_dir():
                    lines.append(f"  {name}/")
                else:
                    lines.append(f"  {name}")
        except OSError:
            lines.append("  (unable to list contents)")

        return "\n".join(lines)

    def _build_skills_section(self, skills: list[SkillInfo]) -> str:
        """Build the skills section of the system prompt.

        Renders each skill according to its inject mode:
        - FULL: name, description, separator, and complete content (legacy behavior).
        - SUMMARY: name, description, and a read_file() pointer for on-demand access.

        Args:
            skills: Skills to render (caller has already filtered out
                staged skills).

        Returns:
            Formatted skills section string, ready to wrap in ``<skills>`` tags.
        """
        from openpaw.model.skill import SkillInjectMode

        lines = ["## Available Skills"]

        # Check if any skills use summary mode — add preamble if so
        has_summary = any(
            skill.inject == SkillInjectMode.SUMMARY and skill.read_path
            for skill in skills
        )
        if has_summary:
            lines.append("")
            lines.append(
                "Skills marked with a file path contain detailed reference "
                "content. Use read_file() to load the full skill when you need it."
            )

        for skill in skills:
            lines.append("")
            lines.append(f"### {skill.name}")

            if skill.description:
                lines.append(skill.description)

            if skill.inject == SkillInjectMode.FULL:
                # Full injection: include complete content (legacy behavior)
                lines.append("")
                lines.append("---")
                lines.append(skill.content.strip())
            elif skill.read_path:
                # Summary mode: just a pointer for on-demand loading
                lines.append(f"Full reference: `read_file('{skill.read_path}')`")

        return "\n".join(lines)

    def _build_framework_context(
        self,
        enabled_builtins: list[str] | None,
        channel_logging_enabled: bool = False,
    ) -> str:
        """Build the framework orientation section for the system prompt.

        This explains how the agent exists within the OpenPaw framework and what
        capabilities are available based on enabled builtins.

        Args:
            enabled_builtins: List of enabled builtin names, or None to include all.
            channel_logging_enabled: Whether persistent channel logging is active.
                When True, includes the Channel Logs section.

        Returns:
            Formatted framework context with conditional capability descriptions.
        """
        sections = []

        # ALWAYS include framework orientation with workspace identity
        sections.append(build_framework_orientation(self.name))

        # Workspace filesystem orientation - always included
        sections.append(SECTION_WORKSPACE_FILESYSTEM)

        # Framework Capabilities summary - always included, lists available infrastructure
        capabilities = build_capability_summary(enabled_builtins)
        if capabilities:
            sections.append(capabilities)

        # Heartbeat system - include if heartbeat content exists (non-empty, non-trivial)
        has_heartbeat = bool(self.heartbeat_md and len(self.heartbeat_md.strip()) > 20)
        if has_heartbeat:
            sections.append(SECTION_HEARTBEAT)

        # Task management - include if task_tracker is enabled
        if enabled_builtins is None or "task_tracker" in enabled_builtins:
            sections.append(SECTION_TASK_MANAGEMENT)

        # Self-continuation - include if followup is enabled
        if enabled_builtins is None or "followup" in enabled_builtins:
            sections.append(SECTION_SELF_CONTINUATION)

        # Sub-agent spawning - include if spawn is enabled
        if enabled_builtins is None or "spawn" in enabled_builtins:
            sections.append(SECTION_SUB_AGENT_SPAWNING)

        # Web browsing - include if browser is enabled
        if enabled_builtins is None or "browser" in enabled_builtins:
            sections.append(SECTION_WEB_BROWSING)

        # Progress updates - include if send_message is enabled
        if enabled_builtins is None or "send_message" in enabled_builtins:
            sections.append(SECTION_PROGRESS_UPDATES)

        # Report progress tool - include if report_progress is enabled
        if enabled_builtins is None or "report_progress" in enabled_builtins:
            sections.append(SECTION_REPORT_PROGRESS)

        # File sharing - include if send_file is enabled
        if enabled_builtins is None or "send_file" in enabled_builtins:
            sections.append(SECTION_FILE_SHARING)

        # File uploads - always available (processor-based, no prerequisites)
        sections.append(SECTION_FILE_UPLOADS)

        # Self-scheduling - include if cron tools are enabled
        if enabled_builtins is None or "cron" in enabled_builtins:
            sections.append(SECTION_SELF_SCHEDULING)

        # Scheduled tasks context - include when workspace has configured crons
        if self.crons:
            cron_context = build_cron_context(self.crons)
            if cron_context:
                sections.append(cron_context)

        # Shell hygiene - include if shell tool is enabled
        if enabled_builtins is None or "shell" in enabled_builtins:
            sections.append(SECTION_SHELL_HYGIENE)

        # Operational work ethic - include for shell-enabled agents
        if enabled_builtins is None or "shell" in enabled_builtins:
            sections.append(SECTION_WORK_ETHIC)

        # Planning guidance - include when plan tool is enabled
        if enabled_builtins is None or "plan" in enabled_builtins:
            sections.append(SECTION_PLANNING)

        # Learning loop - include when learning.enabled (PRD-001 F1.1)
        if self.learning_enabled:
            sections.append(SECTION_LEARNING)

        # Autonomous Planning - include when multiple capabilities are available
        # This teaches capability composition for complex requests
        key_capabilities = ["spawn", "followup", "task_tracker", "send_message"]
        has_multiple_capabilities = (
            enabled_builtins is None  # All builtins enabled
            or sum(1 for cap in key_capabilities if cap in enabled_builtins) >= 2
        )
        if has_multiple_capabilities:
            sections.append(SECTION_AUTONOMOUS_PLANNING)

        # System events - include when any system event source is active:
        # spawn builtin (sub-agent completions), cron with delivery: agent or both,
        # or heartbeat with delivery: agent or both
        heartbeat_agent_delivery = (
            self.config is not None
            and self.config.heartbeat is not None
            and self.config.heartbeat.delivery in ("agent", "both")
        )
        cron_agent_delivery = any(
            cron.output.delivery in ("agent", "both")
            for cron in self.crons
            if cron.output is not None
        )
        has_spawn = enabled_builtins is None or "spawn" in enabled_builtins
        if heartbeat_agent_delivery or cron_agent_delivery or has_spawn:
            sections.append(SECTION_SYSTEM_EVENTS)

        # Memory search - include if memory_search is enabled
        if enabled_builtins is None or "memory_search" in enabled_builtins:
            sections.append(SECTION_MEMORY_SEARCH)

        # Channel history browsing - include if channel_history builtin is loaded
        if enabled_builtins is None or "channel_history" in enabled_builtins:
            sections.append(SECTION_CHANNEL_HISTORY)

        # Channel logs - include when persistent channel logging is active
        if channel_logging_enabled:
            sections.append(SECTION_CHANNEL_LOGS)

        # Channel context is always available (group messages prepend recent history)
        sections.append(SECTION_CHANNEL_CONTEXT)

        # Conversation memory is always available (core feature, not a builtin)
        sections.append(SECTION_CONVERSATION_MEMORY)

        return "".join(sections)
