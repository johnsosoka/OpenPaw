"""Agent workspace loading and management."""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from openpaw.core.config import WorkspaceConfig
    from openpaw.cron.loader import CronDefinition


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

    def build_system_prompt(self, enabled_builtins: list[str] | None = None) -> str:
        """Stitch together workspace files into a system prompt.

        The prompt structure follows DeepAgents conventions with clear sections.
        Returns a string suitable for use with create_react_agent.

        Args:
            enabled_builtins: List of enabled builtin names. Used to conditionally
                include framework capabilities (task_tracker, cron, followup, etc.).
                If None (default), all capabilities are included for backward compat.

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
        framework_context = self._build_framework_context(enabled_builtins)
        if framework_context:
            sections.append(f"<framework>\n{framework_context}\n</framework>")

        if self.heartbeat_md:
            sections.append(f"<heartbeat>\n{self.heartbeat_md.strip()}\n</heartbeat>")

        return "\n\n".join(sections)

    def _build_framework_context(self, enabled_builtins: list[str] | None) -> str:
        """Build the framework orientation section for the system prompt.

        This explains how the agent exists within the OpenPaw framework and what
        capabilities are available based on enabled builtins.

        Args:
            enabled_builtins: List of enabled builtin names, or None to include all.

        Returns:
            Formatted framework context with conditional capability descriptions.
        """
        sections = []

        # ALWAYS include framework orientation
        sections.append(
            "You are a persistent autonomous agent running in the OpenPaw framework. "
            "Your workspace directory is your long-term memory—files you write today will "
            "be there tomorrow. You are encouraged to organize your workspace: create "
            "subdirectories, maintain notes, keep state files. You can freely read, write, "
            "and edit files in your workspace. This is YOUR space—use it to stay organized "
            "and maintain continuity across conversations."
        )

        # Heartbeat system - include if heartbeat content exists (non-empty, non-trivial)
        has_heartbeat = bool(self.heartbeat_md and len(self.heartbeat_md.strip()) > 20)
        if has_heartbeat:
            sections.append(
                "\n\n## Heartbeat System\n\n"
                "You receive periodic wake-up calls to check on ongoing work. Use these "
                "heartbeats to review tasks, monitor long-running operations, and send "
                "proactive updates. HEARTBEAT.md is your scratchpad for things to check "
                "on next time you wake up. If there's nothing requiring attention, respond "
                "with exactly 'HEARTBEAT_OK' to avoid sending unnecessary messages."
            )

        # Task management - include if task_tracker is enabled
        if enabled_builtins is None or "task_tracker" in enabled_builtins:
            sections.append(
                "\n\n## Task Management\n\n"
                "You have a task tracking system (TASKS.yaml) for managing work across "
                "sessions. Tasks persist—use them to remember what you're working on. "
                "Future heartbeats will see your tasks and can continue where you left off. "
                "Create tasks for long operations, update them as you progress, and clean "
                "up when complete."
            )

        # Self-continuation - include if followup is enabled
        if enabled_builtins is None or "followup" in enabled_builtins:
            sections.append(
                "\n\n## Self-Continuation\n\n"
                "You can request to be re-invoked after your current response completes. "
                "Use this for multi-step workflows that don't need user input between steps. "
                "You can also schedule delayed followups for time-dependent checks (e.g., "
                "'check this again in 5 minutes')."
            )

        # Progress updates - include if send_message is enabled
        if enabled_builtins is None or "send_message" in enabled_builtins:
            sections.append(
                "\n\n## Progress Updates\n\n"
                "You can send messages to the user while you continue working. Don't make "
                "the user wait in silence during long operations—send progress updates to "
                "keep them informed about what you're doing."
            )

        # File sharing - include if send_file is enabled
        if enabled_builtins is None or "send_file" in enabled_builtins:
            sections.append(
                "\n\n## File Sharing\n\n"
                "You can send files from your workspace to the user using the send_file tool. "
                "Write or generate files in your workspace, then use send_file to deliver them. "
                "Supported: PDFs, images, documents, text files, and more."
            )

        # File uploads - always available (processor-based, no prerequisites)
        sections.append(
            "\n\n## File Uploads\n\n"
            "When users send you files (documents, images, audio, etc.), they are "
            "automatically saved to your uploads/ directory, organized by date. "
            "You'll see a notification in the message like [Saved to: uploads/...]. "
            "You can read, reference, and process these files using your filesystem tools. "
            "Supported document types (PDF, DOCX, etc.) are also automatically converted "
            "to markdown for easier reading."
        )

        # Self-scheduling - include if cron tools are enabled
        if enabled_builtins is None or "cron" in enabled_builtins:
            sections.append(
                "\n\n## Self-Scheduling\n\n"
                "You can schedule future actions—one-time or recurring. Use this for "
                "reminders, periodic checks, or deferred work. Schedule tasks that should "
                "happen at a specific time or on a regular interval."
            )

        # Conversation memory is always available (core feature, not a builtin)
        sections.append(
            "\n\n## Conversation Memory\n\n"
            "Your conversations are automatically saved to disk and persist across restarts. "
            "When you or the user starts a new conversation (via /new), the previous conversation "
            "is archived in memory/conversations/ as both markdown and JSON files.\n\n"
            "You can read these archives with your filesystem tools to reference past interactions. "
            "Use /new to start a fresh conversation when the current topic is complete."
        )

        return "".join(sections)


class WorkspaceLoader:
    """Loads agent workspaces from filesystem."""

    REQUIRED_FILES = ["AGENT.md", "USER.md", "SOUL.md", "HEARTBEAT.md"]
    SKILLS_DIR = "skills"
    TOOLS_DIR = "tools"

    def __init__(self, workspaces_root: Path):
        """Initialize the workspace loader.

        Args:
            workspaces_root: Root directory containing agent workspace folders.
        """
        self.workspaces_root = Path(workspaces_root)

    def list_workspaces(self) -> list[str]:
        """List all valid workspace names in the workspaces root.

        Returns:
            List of workspace directory names that contain required files.
        """
        if not self.workspaces_root.exists():
            return []

        workspaces = []
        for path in self.workspaces_root.iterdir():
            if path.is_dir() and not path.name.startswith("."):
                if self._is_valid_workspace(path):
                    workspaces.append(path.name)
        return sorted(workspaces)

    def _is_valid_workspace(self, path: Path) -> bool:
        """Check if a directory contains required workspace files."""
        return all((path / f).exists() for f in self.REQUIRED_FILES)

    def load(self, workspace_name: str) -> AgentWorkspace:
        """Load an agent workspace by name.

        Args:
            workspace_name: Name of the workspace directory.

        Returns:
            Loaded AgentWorkspace instance.

        Raises:
            FileNotFoundError: If workspace or required files don't exist.
        """
        workspace_path = self.workspaces_root / workspace_name

        if not workspace_path.exists():
            raise FileNotFoundError(f"Workspace not found: {workspace_path}")

        missing = [f for f in self.REQUIRED_FILES if not (workspace_path / f).exists()]
        if missing:
            raise FileNotFoundError(f"Missing required files in {workspace_name}: {missing}")

        skills_path = workspace_path / self.SKILLS_DIR
        tools_path = workspace_path / self.TOOLS_DIR

        # Load optional workspace config and crons
        workspace_config = self._load_workspace_config(workspace_path)
        crons = self._load_crons(workspace_path)

        return AgentWorkspace(
            name=workspace_name,
            path=workspace_path,
            agent_md=self._read_file(workspace_path / "AGENT.md"),
            user_md=self._read_file(workspace_path / "USER.md"),
            soul_md=self._read_file(workspace_path / "SOUL.md"),
            heartbeat_md=self._read_file(workspace_path / "HEARTBEAT.md"),
            skills_path=skills_path,
            tools_path=tools_path,
            config=workspace_config,
            crons=crons,
        )

    def _read_file(self, path: Path) -> str:
        """Read file contents, returning empty string if file doesn't exist."""
        if path.exists():
            return path.read_text(encoding="utf-8")
        return ""

    def _load_workspace_config(self, workspace_path: Path) -> "WorkspaceConfig | None":
        """Load agent.yaml configuration from workspace if it exists.

        Args:
            workspace_path: Path to the workspace directory.

        Returns:
            WorkspaceConfig object or None if agent.yaml doesn't exist.
        """
        config_file = workspace_path / "agent.yaml"
        if not config_file.exists():
            return None

        with config_file.open() as f:
            data = yaml.safe_load(f) or {}

        # Import expand_env_vars_recursive at runtime to avoid circular imports
        from openpaw.core.config import WorkspaceConfig, expand_env_vars_recursive

        # Apply environment variable substitution
        data = expand_env_vars_recursive(data)

        return WorkspaceConfig(**data)

    def _load_crons(self, workspace_path: Path) -> "list[CronDefinition]":
        """Load all cron definitions from workspace's crons/ directory.

        Args:
            workspace_path: Path to the workspace directory.

        Returns:
            List of CronDefinition objects, empty list if crons/ doesn't exist.
        """
        crons_dir = workspace_path / "crons"
        if not crons_dir.exists() or not crons_dir.is_dir():
            return []

        # Import at runtime to avoid circular import
        from openpaw.core.config import expand_env_vars_recursive
        from openpaw.cron.loader import CronDefinition

        cron_definitions = []
        for cron_file in sorted(crons_dir.glob("*.yaml")):
            try:
                with cron_file.open() as f:
                    data = yaml.safe_load(f) or {}

                # Apply environment variable substitution
                data = expand_env_vars_recursive(data)

                cron_definitions.append(CronDefinition(**data))
            except Exception as e:
                # Log warning but continue loading other crons
                logger.warning(f"Failed to load cron file {cron_file.name}: {e}")
                continue

        return cron_definitions
