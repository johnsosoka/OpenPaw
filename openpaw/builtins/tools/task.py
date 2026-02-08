"""Task management builtin for agent self-tracking of long-running operations."""

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from openpaw.builtins.base import (
    BaseBuiltinTool,
    BuiltinMetadata,
    BuiltinPrerequisite,
    BuiltinType,
)
from openpaw.core.timezone import format_for_display
from openpaw.task import (
    TaskPriority,
    TaskStatus,
    TaskStore,
    create_task,
)

logger = logging.getLogger(__name__)


class CreateTaskInput(BaseModel):
    """Input schema for creating a task."""

    description: str = Field(description="Human-readable task description")
    type: str = Field(
        description=(
            "Task category. Common types: 'research', 'deployment', 'batch', "
            "'monitoring', 'custom'. Use standard types when applicable."
        )
    )
    priority: str = Field(
        default="normal",
        description="Priority level: 'low', 'normal', 'high', 'urgent'. Default: 'normal'",
    )
    expected_duration_minutes: int | None = Field(
        default=None,
        description="Estimated runtime in minutes (optional but recommended for transparency)",
    )
    metadata: dict[str, Any] | None = Field(
        default=None,
        description="Tool-specific data as key-value pairs (optional)",
    )


class UpdateTaskInput(BaseModel):
    """Input schema for updating a task."""

    task_id: str = Field(description="Unique task identifier (from list_tasks or create_task)")
    status: str | None = Field(
        default=None,
        description=(
            "New status: 'pending', 'in_progress', 'awaiting_check', 'completed', "
            "'failed', 'cancelled'. Only update when status changes."
        ),
    )
    notes: str | None = Field(
        default=None,
        description="Add progress notes or observations (appended to existing notes)",
    )
    result_summary: str | None = Field(
        default=None,
        description="Brief outcome description (set when completing task)",
    )
    result_path: str | None = Field(
        default=None,
        description="Path to output file relative to workspace (set when completing task)",
    )
    error_message: str | None = Field(
        default=None,
        description="Error details (set when marking task as failed)",
    )


class ListTasksInput(BaseModel):
    """Input schema for listing tasks."""

    status: str | None = Field(
        default=None,
        description=(
            "Filter by status: 'pending', 'in_progress', 'awaiting_check', "
            "'completed', 'failed', 'cancelled'. Omit to list all tasks."
        ),
    )
    type: str | None = Field(
        default=None,
        description="Filter by task type (e.g., 'research', 'deployment'). Omit to list all types.",
    )


class GetTaskInput(BaseModel):
    """Input schema for getting task details."""

    task_id: str = Field(description="Unique task identifier to retrieve")


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
            self._create_list_tasks_tool(),
            self._create_create_task_tool(),
            self._create_update_task_tool(),
            self._create_get_task_tool(),
        ]

    def _create_list_tasks_tool(self) -> StructuredTool:
        """Create the list_tasks tool."""

        def list_tasks(status: str | None = None, type: str | None = None) -> str:
            """List tasks with optional filtering by status or type.

            Args:
                status: Filter by task status (optional).
                type: Filter by task type (optional).

            Returns:
                Formatted summary of matching tasks.
            """
            # Parse status filter
            status_filter = None
            if status:
                try:
                    status_filter = TaskStatus(status)
                except ValueError:
                    valid = ", ".join([s.value for s in TaskStatus])
                    return f"[Error: Invalid status '{status}'. Valid: {valid}]"

            # List tasks with filters
            tasks = self.store.list(status=status_filter, type=type)

            if not tasks:
                if status or type:
                    filter_desc = []
                    if status:
                        filter_desc.append(f"status={status}")
                    if type:
                        filter_desc.append(f"type={type}")
                    return f"No tasks found ({', '.join(filter_desc)})."
                return "No tasks found. Use create_task to start tracking a long-running operation."

            # Sort by priority (urgent first) then created_at (oldest first)
            priority_order = {
                TaskPriority.URGENT: 0,
                TaskPriority.HIGH: 1,
                TaskPriority.NORMAL: 2,
                TaskPriority.LOW: 3,
            }
            tasks_sorted = sorted(
                tasks,
                key=lambda t: (priority_order.get(t.priority, 99), t.created_at),
            )

            # Format output
            lines = ["Tasks:\n"]
            now = datetime.now(UTC)

            for task in tasks_sorted:
                # Status indicator
                status_icon = {
                    TaskStatus.PENDING: "⏸",
                    TaskStatus.IN_PROGRESS: "▶",
                    TaskStatus.AWAITING_CHECK: "⚠",
                    TaskStatus.COMPLETED: "✓",
                    TaskStatus.FAILED: "✗",
                    TaskStatus.CANCELLED: "⊗",
                }.get(task.status, "·")

                # Priority indicator for high/urgent
                priority_marker = ""
                if task.priority == TaskPriority.URGENT:
                    priority_marker = " [URGENT]"
                elif task.priority == TaskPriority.HIGH:
                    priority_marker = " [HIGH]"

                # Time information
                age = now - task.created_at
                age_str = self._format_duration(age.total_seconds())

                time_info = f"created {age_str} ago"
                if task.status == TaskStatus.IN_PROGRESS and task.expected_duration_minutes:
                    elapsed = now - (task.started_at or task.created_at)
                    elapsed_min = int(elapsed.total_seconds() / 60)
                    expected = task.expected_duration_minutes
                    time_info += f" (running {elapsed_min}/{expected}m)"

                # Format description preview
                desc_preview = task.description[:60]
                if len(task.description) > 60:
                    desc_preview += "..."

                lines.append(
                    f"{status_icon} [{task.id[:8]}] {task.type}{priority_marker}\n"
                    f"  Status: {task.status.value} | {time_info}\n"
                    f"  {desc_preview}\n"
                )

            lines.append(f"\nTotal: {len(tasks)} task(s)")
            return "\n".join(lines)

        return StructuredTool.from_function(
            func=list_tasks,
            name="list_tasks",
            description=(
                "List all tracked tasks with optional filtering. "
                "Use this to see pending, in-progress, or completed tasks. "
                "Filter by status ('pending', 'in_progress', 'completed', 'failed') "
                "or type ('research', 'deployment', etc.). "
                "Returns task IDs for use with get_task and update_task."
            ),
            args_schema=ListTasksInput,
        )

    def _create_create_task_tool(self) -> StructuredTool:
        """Create the create_task tool."""

        def create_task_wrapper(
            description: str,
            type: str,
            priority: str = "normal",
            expected_duration_minutes: int | None = None,
            metadata: dict[str, Any] | None = None,
        ) -> str:
            """Create a new task entry for a long-running operation.

            Args:
                description: Human-readable task description.
                type: Task category (research, deployment, batch, monitoring, custom).
                priority: Priority level (low, normal, high, urgent).
                expected_duration_minutes: Estimated runtime in minutes (optional).
                metadata: Tool-specific data as key-value pairs (optional).

            Returns:
                Confirmation message with task ID.
            """
            # Validate priority
            try:
                task_priority = TaskPriority(priority)
            except ValueError:
                valid = ", ".join([p.value for p in TaskPriority])
                return f"[Error: Invalid priority '{priority}'. Valid: {valid}]"

            # Create task
            task = create_task(
                type=type,
                description=description,
                status=TaskStatus.PENDING,
                priority=task_priority,
                expected_duration_minutes=expected_duration_minutes,
                metadata=metadata or {},
            )

            # Persist to store
            try:
                self.store.create(task)
            except ValueError as e:
                return f"[Error: Failed to create task: {e}]"

            logger.info(f"Created task {task.id} ({type}, {priority})")

            # Format response
            duration_info = ""
            if expected_duration_minutes:
                duration_info = f" (estimated: {expected_duration_minutes}m)"

            return (
                f"Created task {task.id}{duration_info}\n"
                f"Type: {type}\n"
                f"Priority: {priority}\n"
                f"Description: {description}\n\n"
                f"Use update_task(task_id='{task.id}', status='in_progress') when starting work."
            )

        return StructuredTool.from_function(
            func=create_task_wrapper,
            name="create_task",
            description=(
                "Track a multi-step background operation (deployments, batch jobs, long-running scripts). "
                "DO NOT use this for simple lookups or searches - use brave_search directly for those. "
                "Only create task entries for operations that: 1) take more than a few minutes, "
                "2) run in the background, or 3) need status tracking across heartbeats. "
                "Returns the task ID for later updates via update_task."
            ),
            args_schema=CreateTaskInput,
        )

    def _create_update_task_tool(self) -> StructuredTool:
        """Create the update_task tool."""

        def update_task_wrapper(
            task_id: str,
            status: str | None = None,
            notes: str | None = None,
            result_summary: str | None = None,
            result_path: str | None = None,
            error_message: str | None = None,
        ) -> str:
            """Update an existing task's status, notes, or results.

            Args:
                task_id: Unique task identifier (from list_tasks or create_task).
                status: New status (optional, only update when status changes).
                notes: Progress notes to append (optional).
                result_summary: Brief outcome description (optional, for completed tasks).
                result_path: Path to output file relative to workspace (optional).
                error_message: Error details (optional, for failed tasks).

            Returns:
                Confirmation message or error.
            """
            # Build update dict
            updates: dict[str, Any] = {}

            # Parse and validate status
            if status:
                try:
                    task_status = TaskStatus(status)
                    updates["status"] = task_status

                    # Auto-set timestamps based on status
                    now = datetime.now(UTC)
                    if task_status == TaskStatus.IN_PROGRESS:
                        updates["started_at"] = now
                    elif task_status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
                        updates["completed_at"] = now

                except ValueError:
                    valid = ", ".join([s.value for s in TaskStatus])
                    return f"[Error: Invalid status '{status}'. Valid: {valid}]"

            # Handle notes (append with timestamp)
            if notes:
                # Get existing task to append to notes
                existing = self.store.get(task_id)
                if existing:
                    timestamp = format_for_display(datetime.now(UTC), self._timezone, "%Y-%m-%d %H:%M %Z")
                    existing_notes = existing.notes or ""
                    if existing_notes:
                        updates["notes"] = f"{existing_notes}\n- [{timestamp}] {notes}"
                    else:
                        updates["notes"] = f"- [{timestamp}] {notes}"
                else:
                    updates["notes"] = notes

            # Other fields
            if result_summary:
                updates["result_summary"] = result_summary
            if result_path:
                updates["result_path"] = result_path
            if error_message:
                updates["error_message"] = error_message

            # Always increment check_count and update last_checked_at
            now = datetime.now(UTC)
            updates["last_checked_at"] = now

            existing = self.store.get(task_id)
            if existing:
                updates["check_count"] = existing.check_count + 1

            # Apply update
            success = self.store.update(task_id, **updates)

            if not success:
                return f"[Error: Task '{task_id}' not found. Use list_tasks to see available tasks.]"

            logger.info(f"Updated task {task_id}: {list(updates.keys())}")

            # Format response
            status_msg = f"Status: {status}" if status else ""
            notes_msg = "Notes updated" if notes else ""
            result_msg = f"Result: {result_summary}" if result_summary else ""

            parts = [p for p in [status_msg, notes_msg, result_msg] if p]
            update_summary = ", ".join(parts) if parts else "Task updated"

            return f"Updated task {task_id}: {update_summary}"

        return StructuredTool.from_function(
            func=update_task_wrapper,
            name="update_task",
            description=(
                "Update an existing task's status, progress notes, or results. "
                "Use this during heartbeats to record task progress, mark completion, or log errors. "
                "IMPORTANT: Always increment check_count by calling this when checking on a task. "
                "Set status='completed' with result_summary when task finishes successfully. "
                "Set status='failed' with error_message when task encounters errors."
            ),
            args_schema=UpdateTaskInput,
        )

    def _create_get_task_tool(self) -> StructuredTool:
        """Create the get_task tool."""

        def get_task(task_id: str) -> str:
            """Get full details for a specific task by ID.

            Args:
                task_id: Unique task identifier.

            Returns:
                Formatted task details including all fields.
            """
            task = self.store.get(task_id)

            if not task:
                return f"[Error: Task '{task_id}' not found. Use list_tasks to see available tasks.]"

            # Format detailed output
            lines = [
                f"Task {task.id}",
                "=" * 60,
                f"Type: {task.type}",
                f"Status: {task.status.value}",
                f"Priority: {task.priority.value}",
                f"Description: {task.description}",
                "",
            ]

            # Timing information
            lines.append("Timing:")
            lines.append(f"  Created: {task.created_at.isoformat()}")
            if task.started_at:
                lines.append(f"  Started: {task.started_at.isoformat()}")
            if task.completed_at:
                lines.append(f"  Completed: {task.completed_at.isoformat()}")
            if task.expected_duration_minutes:
                lines.append(f"  Expected duration: {task.expected_duration_minutes} minutes")
            if task.deadline:
                lines.append(f"  Deadline: {task.deadline.isoformat()}")
            lines.append("")

            # Monitoring information
            lines.append("Monitoring:")
            lines.append(f"  Check count: {task.check_count}")
            if task.last_checked_at:
                lines.append(f"  Last checked: {task.last_checked_at.isoformat()}")
            if task.check_interval_minutes:
                lines.append(f"  Check interval: {task.check_interval_minutes} minutes")
            lines.append("")

            # Notes
            if task.notes:
                lines.append("Notes:")
                lines.append(task.notes)
                lines.append("")

            # Results
            if task.result_summary or task.result_path or task.error_message:
                lines.append("Results:")
                if task.result_summary:
                    lines.append(f"  Summary: {task.result_summary}")
                if task.result_path:
                    lines.append(f"  Output: {task.result_path}")
                if task.error_message:
                    lines.append(f"  Error: {task.error_message}")
                lines.append("")

            # Metadata
            if task.metadata:
                lines.append("Metadata:")
                for key, value in task.metadata.items():
                    lines.append(f"  {key}: {value}")

            return "\n".join(lines)

        return StructuredTool.from_function(
            func=get_task,
            name="get_task",
            description=(
                "Get full details for a specific task by ID. "
                "Use this to see all information about a task including timing, "
                "monitoring data, notes, results, and metadata. "
                "Use list_tasks first to find task IDs."
            ),
            args_schema=GetTaskInput,
        )

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
