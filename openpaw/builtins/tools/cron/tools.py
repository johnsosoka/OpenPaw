"""Tool factory functions for cron scheduling."""

import logging
from datetime import UTC, datetime
from typing import Any

from langchain_core.tools import StructuredTool

from openpaw.builtins.tools._channel_context import get_current_session_key
from openpaw.stores.cron import create_interval_task, create_once_task

from .formatting import _format_interval, _format_time_until, _parse_timestamp
from .models import CancelScheduledInput, ScheduleAtInput, ScheduleEveryInput
from .scheduler_bridge import _add_to_live_scheduler, _remove_from_live_scheduler

logger = logging.getLogger(__name__)


def _create_schedule_at_tool(builtin: Any) -> StructuredTool:
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
        current_tasks = builtin.store.list_tasks()
        if len(current_tasks) >= builtin.max_tasks:
            return (
                f"[Error: Maximum task limit reached ({builtin.max_tasks}). "
                f"Please cancel some tasks before scheduling new ones.]"
            )

        # Parse timestamp
        try:
            run_at_dt = _parse_timestamp(run_at, builtin.timezone)
        except ValueError as e:
            return f"[Error: Invalid timestamp format: {e}]"

        # Validate timestamp is in the future
        now = datetime.now(UTC)
        if run_at_dt <= now:
            return (
                f"[Error: Timestamp must be in the future. "
                f"Provided: {run_at_dt.isoformat()}, Current time: {now.isoformat()}]"
            )

        # Resolve chat_id from the active session so the task is routed back
        # to the user who scheduled it, not the startup default.
        session_key = get_current_session_key()
        chat_id = builtin.default_chat_id  # fallback
        if session_key:
            try:
                chat_id = int(session_key.rsplit(":", 1)[-1])
            except (ValueError, IndexError):
                pass  # keep default

        # Enrich prompt with user identity for stateless cron agent
        user_name = builtin.user_aliases.get(chat_id) if chat_id else None
        if user_name:
            prompt = f"[Scheduled for user: {user_name}]\n{prompt}"

        # Create and store task with routing info
        task = create_once_task(
            prompt=prompt,
            run_at=run_at_dt,
            channel=builtin.default_channel,
            chat_id=chat_id,
        )
        builtin.store.add_task(task)

        # Add to live scheduler if available
        _add_to_live_scheduler(builtin.scheduler, task)

        logger.info(f"Scheduled one-time task {task.id} for {run_at_dt.isoformat()}")
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


def _create_schedule_every_tool(builtin: Any) -> StructuredTool:
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
        current_tasks = builtin.store.list_tasks()
        if len(current_tasks) >= builtin.max_tasks:
            return (
                f"[Error: Maximum task limit reached ({builtin.max_tasks}). "
                f"Please cancel some tasks before scheduling new ones.]"
            )

        # Validate interval
        if interval_seconds < builtin.min_interval_seconds:
            return (
                f"[Error: Interval must be at least {builtin.min_interval_seconds} "
                f"seconds ({builtin.min_interval_seconds // 60} minutes)]"
            )

        # Calculate next run time (interval from now)
        next_run = datetime.now(UTC)

        # Resolve chat_id from the active session so the task is routed back
        # to the user who scheduled it, not the startup default.
        session_key = get_current_session_key()
        chat_id = builtin.default_chat_id  # fallback
        if session_key:
            try:
                chat_id = int(session_key.rsplit(":", 1)[-1])
            except (ValueError, IndexError):
                pass  # keep default

        # Enrich prompt with user identity for stateless cron agent
        user_name = builtin.user_aliases.get(chat_id) if chat_id else None
        if user_name:
            prompt = f"[Scheduled for user: {user_name}]\n{prompt}"

        # Create and store task with routing info
        task = create_interval_task(
            prompt=prompt,
            interval_seconds=interval_seconds,
            next_run=next_run,
            channel=builtin.default_channel,
            chat_id=chat_id,
        )
        builtin.store.add_task(task)

        # Add to live scheduler if available
        _add_to_live_scheduler(builtin.scheduler, task)

        logger.info(f"Scheduled recurring task {task.id} every {interval_seconds}s")

        interval_display = _format_interval(interval_seconds)
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
            f"Minimum interval: {builtin.min_interval_seconds} seconds."
        ),
        args_schema=ScheduleEveryInput,
    )


def _create_list_scheduled_tool(builtin: Any) -> StructuredTool:
    """Create the list_scheduled tool."""

    def list_scheduled() -> str:
        """List all pending scheduled tasks for this workspace.

        Returns:
            Formatted list of scheduled tasks.
        """
        tasks = builtin.store.list_tasks()

        # Filter out expired one-shot tasks (defense against stale entries)
        now = datetime.now(UTC)
        tasks = [
            t for t in tasks
            if not (t.task_type == "once" and t.run_at and t.run_at < now)
        ]

        if not tasks:
            return "No scheduled tasks."
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
                interval_display = _format_interval(task.interval_seconds)
                task_type_display = f"Every {interval_display}"

            # Calculate time until next run
            if next_run:
                time_until = next_run - now
                time_until_display = _format_time_until(time_until.total_seconds())
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


def _create_cancel_scheduled_tool(builtin: Any) -> StructuredTool:
    """Create the cancel_scheduled tool."""

    def cancel_scheduled(task_id: str) -> str:
        """Cancel a scheduled task by ID or short prefix.

        Args:
            task_id: The unique task ID or short prefix as shown by list_scheduled.

        Returns:
            Confirmation message or error.
        """
        try:
            full_id = builtin.store.remove_task(task_id)
        except ValueError as e:
            return f"[Error: {e}]"

        if full_id is not None:
            # Remove from live scheduler using the resolved full UUID
            _remove_from_live_scheduler(builtin.scheduler, full_id)

            logger.info(f"Cancelled scheduled task: {full_id}")
            return f"Successfully cancelled task {full_id}."
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
