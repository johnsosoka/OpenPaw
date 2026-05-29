"""Task scheduler builtin for dynamic agent self-scheduling.

Re-exports public symbols for backward compatibility.
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from openpaw.builtins.base import (
    BaseBuiltinTool,
    BuiltinMetadata,
    BuiltinPrerequisite,
    BuiltinType,
)
from openpaw.stores.cron import DynamicCronStore

from .formatting import _format_interval as _fmt_interval
from .formatting import _format_time_until as _fmt_time_until
from .formatting import _parse_timestamp as _parse_ts
from .models import CancelScheduledInput, ScheduleAtInput, ScheduleEveryInput
from .scheduler_bridge import set_scheduler as _set_scheduler_ref
from .tools import (
    _create_cancel_scheduled_tool,
    _create_list_scheduled_tool,
    _create_schedule_at_tool,
    _create_schedule_every_tool,
)

logger = logging.getLogger(__name__)

__all__ = [
    "CronToolBuiltin",
    "ScheduleAtInput",
    "ScheduleEveryInput",
    "CancelScheduledInput",
]


class CronToolBuiltin(BaseBuiltinTool):
    """Task scheduler for agents to schedule their own follow-up actions.

    Enables agents to:
    - Schedule one-time actions at specific times
    - Schedule recurring actions at intervals
    - List and cancel scheduled tasks

    Examples:
        - "Check on this PR in 20 minutes"
        - "Monitor deployment status every 30 minutes"
        - "Remind me about the meeting at 2pm"

    Config options:
        min_interval_seconds: Minimum allowed interval (default: 300 = 5 minutes)
        max_tasks: Maximum number of scheduled tasks per workspace (default: 50)
        timezone: Workspace timezone for display (default: UTC)
    """

    metadata = BuiltinMetadata(
        name="cron",
        display_name="Task Scheduler",
        description="Schedule future actions and reminders",
        builtin_type=BuiltinType.TOOL,
        group="automation",
        prerequisites=BuiltinPrerequisite(),  # No env vars required
    )

    def __init__(self, config: dict[str, Any] | None = None):
        """Initialize the cron tool builtin.

        Args:
            config: Configuration dict containing:
                - workspace_path: Path to workspace root (required)
                - cron_scheduler: CronScheduler instance for live updates (optional)
                - min_interval_seconds: Minimum interval (default: 300)
                - max_tasks: Maximum tasks (default: 50)
                - timezone: Display timezone (default: UTC)
        """
        super().__init__(config)

        # Extract workspace path
        workspace_path = self.config.get("workspace_path")
        if not workspace_path:
            raise ValueError("CronToolBuiltin requires 'workspace_path' in config")

        self.workspace_path = Path(workspace_path)
        self.store = DynamicCronStore(self.workspace_path)

        # Optional scheduler reference for live updates
        self.scheduler = self.config.get("cron_scheduler")

        # Configuration
        self.min_interval_seconds = self.config.get("min_interval_seconds", 300)
        self.max_tasks = self.config.get("max_tasks", 50)
        self.timezone = self.config.get("timezone", "UTC")

        # Routing config for scheduled task responses
        self.default_channel = self.config.get("default_channel", "telegram")
        self.default_chat_id = self.config.get("default_chat_id")

        # User identity for prompt enrichment
        self.user_aliases: dict[int, str] = self.config.get("user_aliases", {})

        logger.info(
            f"CronToolBuiltin initialized for workspace: {self.workspace_path.name}"
        )

    def get_langchain_tool(self) -> Any:
        """Return cron tools as a list of LangChain StructuredTools."""
        return [
            _create_schedule_at_tool(self),
            _create_schedule_every_tool(self),
            _create_list_scheduled_tool(self),
            _create_cancel_scheduled_tool(self),
        ]

    def set_scheduler(self, scheduler: Any) -> None:
        """Set the scheduler reference for live task updates.

        Called after CronScheduler is initialized to enable live scheduling.

        Args:
            scheduler: CronScheduler instance.
        """
        _set_scheduler_ref(self, scheduler)

    def _parse_timestamp(self, timestamp_str: str) -> datetime:
        """Parse ISO 8601 timestamp string to timezone-aware datetime."""
        return _parse_ts(timestamp_str, self.timezone)

    def _format_interval(self, seconds: int) -> str:
        """Format interval in human-readable form."""
        return _fmt_interval(seconds)

    def _format_time_until(self, seconds: float) -> str:
        """Format time until next run in human-readable form."""
        return _fmt_time_until(seconds)
