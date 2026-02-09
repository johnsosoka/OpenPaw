"""Task scheduler builtin for dynamic agent self-scheduling."""

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from openpaw.builtins.base import (
    BaseBuiltinTool,
    BuiltinMetadata,
    BuiltinPrerequisite,
    BuiltinType,
)
from openpaw.stores.cron import (
    DynamicCronStore,
    create_interval_task,
    create_once_task,
)

logger = logging.getLogger(__name__)


class ScheduleAtInput(BaseModel):
    """Input schema for scheduling a one-time action."""

    run_at: str = Field(
        description=(
            "ISO 8601 timestamp when the action should run. "
            "IMPORTANT: Calculate this from the current time shown in the user's message. "
            "For relative times like 'in 5 minutes', add the minutes to the current time. "
            "Example: if current time is '2026-02-06 14:30' and user says 'in 10 minutes', "
            "use '2026-02-06T14:40:00'. Always use the same timezone as the current time. "
            "Format: 'YYYY-MM-DDTHH:MM:SS' (e.g., '2026-02-06T14:45:00')"
        )
    )
    prompt: str = Field(
        description="The instruction or reminder for the future action"
    )


class ScheduleEveryInput(BaseModel):
    """Input schema for scheduling a recurring action."""

    interval_seconds: int = Field(
        description=(
            "Seconds between each execution. Convert user's time to seconds: "
            "1 min = 60, 5 min = 300, 10 min = 600, 30 min = 1800, 1 hour = 3600. "
            "Minimum 60 seconds."
        ),
        ge=60,
    )
    prompt: str = Field(description="The instruction to repeat on each execution")


class CancelScheduledInput(BaseModel):
    """Input schema for canceling a scheduled task."""

    task_id: str = Field(description="The unique ID of the task to cancel")


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

        logger.info(
            f"CronToolBuiltin initialized for workspace: {self.workspace_path.name}"
        )

    def get_langchain_tool(self) -> Any:
        """Return cron tools as a list of LangChain StructuredTools."""
        return [
            self._create_schedule_at_tool(),
            self._create_schedule_every_tool(),
            self._create_list_scheduled_tool(),
            self._create_cancel_scheduled_tool(),
        ]

    def _create_schedule_at_tool(self) -> StructuredTool:
        """Create the schedule_at tool."""

        def schedule_at(run_at: str, prompt: str) -> str:
            """Schedule a one-time action at a specific time.

            Args:
                run_at: ISO 8601 timestamp when the action should run.
                prompt: The instruction for the future action.

            Returns:
                Confirmation message with task ID.
            """
            # Validate max tasks
            current_tasks = self.store.list_tasks()
            if len(current_tasks) >= self.max_tasks:
                return (
                    f"[Error: Maximum task limit reached ({self.max_tasks}). "
                    f"Please cancel some tasks before scheduling new ones.]"
                )

            # Parse timestamp
            try:
                run_at_dt = self._parse_timestamp(run_at)
            except ValueError as e:
                return f"[Error: Invalid timestamp format: {e}]"

            # Validate timestamp is in the future
            now = datetime.now(UTC)
            if run_at_dt <= now:
                return (
                    f"[Error: Timestamp must be in the future. "
                    f"Provided: {run_at_dt.isoformat()}, Current time: {now.isoformat()}]"
                )

            # Create and store task with routing info
            task = create_once_task(
                prompt=prompt,
                run_at=run_at_dt,
                channel=self.default_channel,
                chat_id=self.default_chat_id,
            )
            self.store.add_task(task)

            # Add to live scheduler if available
            self._add_to_live_scheduler(task)

            logger.info(
                f"Scheduled one-time task {task.id} for {run_at_dt.isoformat()}"
            )
            return (
                f"Scheduled task {task.id} to run at {run_at_dt.isoformat()}.\n"
                f"Prompt: {prompt[:100]}{'...' if len(prompt) > 100 else ''}"
            )

        return StructuredTool.from_function(
            func=schedule_at,
            name="schedule_at",
            description=(
                "Schedule a one-time action at a specific timestamp. "
                "Use this for future reminders or delayed actions. "
                "IMPORTANT: Calculate the run_at timestamp by adding the requested delay "
                "to the current time shown in the user's message. For example, if the "
                "current time is '2026-02-06 14:30' and user says 'in 5 minutes', "
                "calculate 14:30 + 5 = 14:35 and use '2026-02-06T14:35:00'. "
                "Keep the same timezone. Format: 'YYYY-MM-DDTHH:MM:SS'."
            ),
            args_schema=ScheduleAtInput,
        )

    def _create_schedule_every_tool(self) -> StructuredTool:
        """Create the schedule_every tool."""

        def schedule_every(interval_seconds: int, prompt: str) -> str:
            """Schedule a recurring action at a fixed interval.

            Args:
                interval_seconds: Seconds between each execution (minimum 60).
                prompt: The instruction to repeat on each execution.

            Returns:
                Confirmation message with task ID.
            """
            # Validate max tasks
            current_tasks = self.store.list_tasks()
            if len(current_tasks) >= self.max_tasks:
                return (
                    f"[Error: Maximum task limit reached ({self.max_tasks}). "
                    f"Please cancel some tasks before scheduling new ones.]"
                )

            # Validate interval
            if interval_seconds < self.min_interval_seconds:
                return (
                    f"[Error: Interval must be at least {self.min_interval_seconds} "
                    f"seconds ({self.min_interval_seconds // 60} minutes)]"
                )

            # Calculate next run time (interval from now)
            next_run = datetime.now(UTC)

            # Create and store task with routing info
            task = create_interval_task(
                prompt=prompt,
                interval_seconds=interval_seconds,
                next_run=next_run,
                channel=self.default_channel,
                chat_id=self.default_chat_id,
            )
            self.store.add_task(task)

            # Add to live scheduler if available
            self._add_to_live_scheduler(task)

            logger.info(
                f"Scheduled recurring task {task.id} every {interval_seconds}s"
            )

            interval_display = self._format_interval(interval_seconds)
            return (
                f"Scheduled recurring task {task.id} to run every {interval_display}.\n"
                f"First run: {next_run.isoformat()}\n"
                f"Prompt: {prompt[:100]}{'...' if len(prompt) > 100 else ''}"
            )

        return StructuredTool.from_function(
            func=schedule_every,
            name="schedule_every",
            description=(
                "Schedule a recurring action at a fixed interval. "
                "Use this for periodic monitoring, status checks, or repeated tasks. "
                "Convert time to seconds: 1 minute = 60, 5 minutes = 300, "
                "10 minutes = 600, 30 minutes = 1800, 1 hour = 3600. "
                f"Minimum interval: {self.min_interval_seconds} seconds."
            ),
            args_schema=ScheduleEveryInput,
        )

    def _create_list_scheduled_tool(self) -> StructuredTool:
        """Create the list_scheduled tool."""

        def list_scheduled() -> str:
            """List all pending scheduled tasks for this workspace.

            Returns:
                Formatted list of scheduled tasks.
            """
            tasks = self.store.list_tasks()

            if not tasks:
                return "No scheduled tasks."

            now = datetime.now(UTC)
            lines = ["Scheduled tasks:\n"]

            for task in tasks:
                # Determine next run time
                if task.task_type == "once":
                    next_run = task.run_at
                    task_type_display = "One-time"
                else:  # interval
                    next_run = task.next_run
                    # interval_seconds is guaranteed for interval tasks
                    assert task.interval_seconds is not None
                    interval_display = self._format_interval(task.interval_seconds)
                    task_type_display = f"Every {interval_display}"

                # Calculate time until next run
                if next_run:
                    time_until = next_run - now
                    time_until_display = self._format_time_until(time_until.total_seconds())
                    next_run_display = f"{next_run.isoformat()} ({time_until_display})"
                else:
                    next_run_display = "Unknown"

                # Format prompt preview
                prompt_preview = task.prompt[:60]
                if len(task.prompt) > 60:
                    prompt_preview += "..."

                lines.append(
                    f"  [{task.id[:8]}] {task_type_display}\n"
                    f"    Next run: {next_run_display}\n"
                    f"    Prompt: {prompt_preview}\n"
                )

            return "\n".join(lines)

        return StructuredTool.from_function(
            func=list_scheduled,
            name="list_scheduled",
            description=(
                "List all pending scheduled tasks for this workspace. "
                "Shows task IDs, types, next run times, and prompts."
            ),
        )

    def _create_cancel_scheduled_tool(self) -> StructuredTool:
        """Create the cancel_scheduled tool."""

        def cancel_scheduled(task_id: str) -> str:
            """Cancel a scheduled task by ID.

            Args:
                task_id: The unique task ID to cancel.

            Returns:
                Confirmation message or error.
            """
            success = self.store.remove_task(task_id)

            if success:
                # Remove from live scheduler if available
                self._remove_from_live_scheduler(task_id)

                logger.info(f"Cancelled scheduled task: {task_id}")
                return f"Successfully cancelled task {task_id}."
            else:
                return f"[Error: Task {task_id} not found]"

        return StructuredTool.from_function(
            func=cancel_scheduled,
            name="cancel_scheduled",
            description=(
                "Cancel a scheduled task by ID. "
                "Use list_scheduled to find task IDs."
            ),
            args_schema=CancelScheduledInput,
        )

    def _parse_timestamp(self, timestamp_str: str) -> datetime:
        """Parse ISO 8601 timestamp string to timezone-aware datetime.

        Args:
            timestamp_str: ISO 8601 formatted timestamp.

        Returns:
            Timezone-aware datetime in UTC.

        Raises:
            ValueError: If timestamp format is invalid.
        """
        try:
            dt = datetime.fromisoformat(timestamp_str)

            # If naive, interpret in workspace timezone
            if dt.tzinfo is None:
                # Interpret naive timestamps in workspace timezone
                workspace_tz = ZoneInfo(self.timezone)
                dt = dt.replace(tzinfo=workspace_tz)
                # Convert to UTC for internal storage
                dt = dt.astimezone(UTC)
            else:
                # Convert to UTC
                dt = dt.astimezone(UTC)

            return dt

        except ValueError as e:
            raise ValueError(
                f"Invalid ISO 8601 timestamp: {timestamp_str}. "
                f"Expected format: 'YYYY-MM-DDTHH:MM:SS' or 'YYYY-MM-DDTHH:MM:SSZ'. "
                f"Error: {e}"
            )

    def _format_interval(self, seconds: int) -> str:
        """Format interval in human-readable form.

        Args:
            seconds: Interval in seconds.

        Returns:
            Human-readable string (e.g., "5 minutes", "2 hours").
        """
        if seconds < 60:
            return f"{seconds} seconds"
        elif seconds < 3600:
            minutes = seconds // 60
            return f"{minutes} minute{'s' if minutes != 1 else ''}"
        elif seconds < 86400:
            hours = seconds // 3600
            return f"{hours} hour{'s' if hours != 1 else ''}"
        else:
            days = seconds // 86400
            return f"{days} day{'s' if days != 1 else ''}"

    def _format_time_until(self, seconds: float) -> str:
        """Format time until next run in human-readable form.

        Args:
            seconds: Seconds until next run (can be negative for overdue).

        Returns:
            Human-readable string (e.g., "in 5 minutes", "2 hours ago").
        """
        if seconds < 0:
            return f"{self._format_interval(int(abs(seconds)))} ago (overdue)"

        if seconds < 60:
            return f"in {int(seconds)} seconds"
        elif seconds < 3600:
            minutes = int(seconds // 60)
            return f"in {minutes} minute{'s' if minutes != 1 else ''}"
        elif seconds < 86400:
            hours = int(seconds // 3600)
            return f"in {hours} hour{'s' if hours != 1 else ''}"
        else:
            days = int(seconds // 86400)
            return f"in {days} day{'s' if days != 1 else ''}"

    def set_scheduler(self, scheduler: Any) -> None:
        """Set the scheduler reference for live task updates.

        Called after CronScheduler is initialized to enable live scheduling.

        Args:
            scheduler: CronScheduler instance.
        """
        self.scheduler = scheduler
        logger.info(f"CronTool connected to live scheduler for workspace: {self.workspace_path.name}")

    def _add_to_live_scheduler(self, task: Any) -> None:
        """Add a task to the live scheduler if available.

        Args:
            task: DynamicCronTask to schedule.
        """
        if self.scheduler:
            try:
                # Use the scheduler's internal method to schedule without re-persisting
                self.scheduler._schedule_dynamic_task(task)
                logger.info(f"Added task {task.id} to live scheduler")
            except Exception as e:
                logger.warning(f"Failed to add task to live scheduler: {e}")
        else:
            logger.debug(
                "No scheduler reference available. "
                "Task will be loaded on next scheduler restart."
            )

    def _remove_from_live_scheduler(self, task_id: str) -> None:
        """Remove a task from the live scheduler if available.

        Args:
            task_id: ID of task to remove.
        """
        if self.scheduler:
            try:
                job_id = f"dynamic_{task_id}"
                if hasattr(self.scheduler, '_scheduler') and self.scheduler._scheduler:
                    self.scheduler._scheduler.remove_job(job_id)
                    logger.info(f"Removed task {task_id} from live scheduler")
            except Exception as e:
                logger.debug(f"Task {task_id} not in live scheduler: {e}")
