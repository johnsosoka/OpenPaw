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
            enabled_builtins: List of enabled builtin names. If provided,
                task_context is only included when 'task_tracker' is in the list.
                If None (default), task_context is always included for backward compat.

        Returns:
            String containing workspace prompt sections and task management context.
        """
        sections = []

        if self.soul_md:
            sections.append(f"<soul>\n{self.soul_md.strip()}\n</soul>")

        if self.agent_md:
            sections.append(f"<agent>\n{self.agent_md.strip()}\n</agent>")

        if self.user_md:
            sections.append(f"<user>\n{self.user_md.strip()}\n</user>")

        # Only include task context if task_tracker builtin is enabled
        if enabled_builtins is None or "task_tracker" in enabled_builtins:
            task_context = self._build_task_context()
            if task_context:
                sections.append(f"<task_context>\n{task_context}\n</task_context>")

        if self.heartbeat_md:
            sections.append(f"<heartbeat>\n{self.heartbeat_md.strip()}\n</heartbeat>")

        return "\n\n".join(sections)

    def _build_task_context(self) -> str:
        """Build the task management context section for the system prompt.

        Returns:
            Formatted task context explaining TASKS.yaml usage.
        """
        return """## Task Management

You have access to a task management system for tracking long-running operations.

### TASKS.yaml
Your workspace contains a TASKS.yaml file for tracking tasks. You can:
- Create tasks when starting long operations (research, processing, API workflows)
- Update task status as work progresses
- Check tasks during heartbeat to monitor ongoing work

### Task Lifecycle
Tasks progress through the following statuses:
- `pending`: Task created, waiting to start
- `in_progress`: Actively being worked on
- `awaiting_check`: Needs review or verification
- `completed`: Successfully finished
- `failed`: Encountered an error
- `cancelled`: Stopped by user or system

### Task Structure
Each task in TASKS.yaml has these key fields:
- `id`: Unique identifier for the task
- `type`: Category (research, deployment, batch, etc.)
- `status`: Current lifecycle state
- `description`: What the task does
- `expected_duration_minutes`: Estimated time to complete
- `created_at`, `started_at`, `completed_at`: Timing information
- `last_checked_at`, `check_count`: Monitoring metrics
- `notes`: Progress updates (append with each check)
- `metadata`: Tool-specific data
- `result_summary`, `result_path`: Completion details

### Heartbeat Integration
During heartbeat checks, you should:
1. Read TASKS.yaml to review all active tasks
2. Check for tasks past their `expected_duration_minutes` - investigate status
3. Look for tasks marked `awaiting_check` - take action
4. Update `last_checked_at` and `check_count` when checking a task
5. Append progress notes to the `notes` field
6. Notify user of completed tasks if not already done
7. Update status to `completed` or `failed` with appropriate details
8. Clean up old completed tasks (>24 hours) after user notification

### Best Practices
- **Create a task before starting long operations**: This provides transparency to the user
- **Set realistic `expected_duration_minutes`**: Users rely on this for planning
- **Update `notes` with progress**: Help future heartbeats understand what's happened
- **Mark `awaiting_check` when human review needed**: This signals priority
- **Store outputs in workspace filesystem**: Use relative paths in `result_path`
- **Clean up after completion**: Remove tasks from TASKS.yaml after notifying the user
- **Handle failures gracefully**: Set status to `failed` with clear `error_message`

### Example Task Entry
```yaml
tasks:
  - id: "research-abc123"
    type: "research"
    status: "in_progress"
    created_at: "2026-02-06T10:30:00Z"
    started_at: "2026-02-06T10:31:15Z"
    expected_duration_minutes: 20
    last_checked_at: "2026-02-06T10:45:00Z"
    check_count: 2
    description: "Research market trends for Q1 2026"
    metadata:
      tool: "gpt_researcher"
      query: "market trends Q1 2026"
    notes: |
      - Check 1: API call initiated, data collection started
      - Check 2: 60% complete, synthesis phase in progress
```

### When to Create Tasks
Create a task entry when:
- Starting a tool that takes more than 5 minutes
- Triggering an external API with async processing
- Beginning research or data collection
- Initiating a deployment or batch operation
- Any operation where the user should be kept informed of progress"""


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
