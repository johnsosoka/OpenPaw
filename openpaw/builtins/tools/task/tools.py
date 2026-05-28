"""Task tool factories for LangChain StructuredTools."""
import logging
from datetime import UTC, datetime
from typing import Any

from langchain_core.tools import StructuredTool

from openpaw.builtins.tools.task.models import (
    CreateTaskInput,
    GetTaskInput,
    ListTasksInput,
    UpdateTaskInput,
)
from openpaw.core.timezone import format_for_display
from openpaw.model.task import TaskPriority, TaskStatus
from openpaw.stores.task import create_task

logger = logging.getLogger(__name__)


def create_list_tasks_tool(task_builtin: Any) -> StructuredTool:
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
        tasks = task_builtin.store.list(status=status_filter, type=type)

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
            age_str = task_builtin._format_duration(age.total_seconds())

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
                f"{status_icon} [{task.id}] {task.type}{priority_marker}\n"
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


def create_create_task_tool(task_builtin: Any) -> StructuredTool:
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
            task_builtin.store.create(task)
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


def create_update_task_tool(task_builtin: Any) -> StructuredTool:
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
            existing = task_builtin.store.get(task_id)
            if existing:
                timestamp = format_for_display(datetime.now(UTC), task_builtin._timezone, "%Y-%m-%d %H:%M %Z")
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

        existing = task_builtin.store.get(task_id)
        if existing:
            updates["check_count"] = existing.check_count + 1

        # Apply update
        success = task_builtin.store.update(task_id, **updates)

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


def create_get_task_tool(task_builtin: Any) -> StructuredTool:
    """Create the get_task tool."""

    def get_task(task_id: str) -> str:
        """Get full details for a specific task by ID.

        Args:
            task_id: Unique task identifier.

        Returns:
            Formatted task details including all fields.
        """
        task = task_builtin.store.get(task_id)

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


def create_delete_task_tool(task_builtin: Any) -> StructuredTool:
    """Create the delete_task tool."""

    def delete_task(task_id: str) -> str:
        """Delete a completed task by ID.

        Only tasks in terminal status (completed, failed, cancelled) can be deleted.
        Use this to clean up old tasks after reviewing their results.

        Args:
            task_id: Unique task identifier.

        Returns:
            Confirmation message or error if task cannot be deleted.
        """
        # Check if task exists
        task = task_builtin.store.get(task_id)
        if not task:
            return f"Task not found: {task_id}"

        # Validate task is in terminal status
        if task.status.value not in ["completed", "failed", "cancelled"]:
            return (
                f"Cannot delete active task. Mark it as completed or cancelled first. "
                f"Current status: {task.status.value}"
            )

        # Delete the task
        success = task_builtin.store.delete(task_id)
        if not success:
            return f"Failed to delete task: {task_id}"

        # Return confirmation with truncated description
        description_preview = task.description[:80] + ("..." if len(task.description) > 80 else "")
        logger.info(f"Deleted task {task_id}: {description_preview}")
        return f"Task deleted: {description_preview}"

    return StructuredTool.from_function(
        func=delete_task,
        name="delete_task",
        description=(
            "Delete a completed task by ID. "
            "Only tasks in terminal status (completed, failed, cancelled) can be deleted. "
            "Use this to clean up old tasks after reviewing their results. "
            "Active tasks must be marked as completed or cancelled before deletion."
        ),
        args_schema=GetTaskInput,  # Reuse GetTaskInput schema (just task_id)
    )
