"""Task management builtin for agent self-tracking of long-running operations."""

import logging
from pathlib import Path
from typing import Any

from openpaw.builtins.base import (
    BaseBuiltinTool,
    BuiltinMetadata,
    BuiltinPrerequisite,
    BuiltinType,
)
from openpaw.builtins.tools.task.tools import (
    create_create_task_tool,
    create_delete_task_tool,
    create_get_task_tool,
    create_list_tasks_tool,
    create_update_task_tool,
)
from openpaw.stores.task import TaskStore

logger = logging.getLogger(__name__)


class TaskToolBuiltin(BaseBuiltinTool):
    """Task tracking for agents managing long-running operations.

    Enables agents to:
    - Create task entries for async/long-running operations
    - Track task status and progress across heartbeat checks
    - List and filter tasks by status or type
    - Update task state as work progresses
    - Record results and outcomes

    Use cases:
    - Deep research (5-30+ minutes)
    - Batch processing jobs
    - External API workflows
    - Deployment monitoring
    - Any operation requiring multiple heartbeat checks

    Config options:
        workspace_path: Path to workspace root (required)
        max_age_days: Auto-cleanup completed tasks older than N days (default: 7)
    """

    metadata = BuiltinMetadata(
        name="task_tracker",
        display_name="Task Tracker",
        description="Track long-running operations across heartbeat invocations",
        builtin_type=BuiltinType.TOOL,
        group="automation",
        prerequisites=BuiltinPrerequisite(),  # No env vars required
    )

    def __init__(self, config: dict[str, Any] | None = None):
        """Initialize the task tool builtin.

        Args:
            config: Configuration dict containing:
                - workspace_path: Path to workspace root (required)
                - task_store: Pre-initialized TaskStore instance (optional, will create if not provided)
                - max_age_days: Cleanup threshold for old tasks (default: 7)
        """
        super().__init__(config)

        # Use injected TaskStore if provided, otherwise create new instance
        if self.config.get("task_store"):
            self.store = self.config["task_store"]
            self.workspace_path = self.store.workspace_path
        else:
            # Fallback for backward compatibility
            workspace_path = self.config.get("workspace_path")
            if not workspace_path:
                raise ValueError("TaskToolBuiltin requires 'workspace_path' in config")

            self.workspace_path = Path(workspace_path)
            self.store = TaskStore(self.workspace_path)

        # Configuration
        self.max_age_days = self.config.get("max_age_days", 7)
        self._timezone = self.config.get("timezone", "UTC")

        logger.info(
            f"TaskToolBuiltin initialized for workspace: {self.workspace_path.name}"
        )

    def get_langchain_tool(self) -> Any:
        """Return task tools as a list of LangChain StructuredTools."""
        return [
            create_list_tasks_tool(self),
            create_create_task_tool(self),
            create_update_task_tool(self),
            create_get_task_tool(self),
            create_delete_task_tool(self),
        ]

    def _format_duration(self, seconds: float) -> str:
        """Format duration in human-readable form.

        Args:
            seconds: Duration in seconds.

        Returns:
            Human-readable string (e.g., "5m", "2h", "3d").
        """
        if seconds < 60:
            return f"{int(seconds)}s"
        elif seconds < 3600:
            minutes = int(seconds / 60)
            return f"{minutes}m"
        elif seconds < 86400:
            hours = int(seconds / 3600)
            return f"{hours}h"
        else:
            days = int(seconds / 86400)
            return f"{days}d"


__all__ = ["TaskToolBuiltin"]
