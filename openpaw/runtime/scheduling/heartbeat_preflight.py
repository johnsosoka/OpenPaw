"""Heartbeat preflight checks for OpenPaw."""

import logging
from datetime import time
from pathlib import Path

import yaml

from openpaw.core.paths import HEARTBEAT_MD, TASKS_YAML
from openpaw.core.prompts.heartbeat import build_task_summary

logger = logging.getLogger(__name__)


class HeartbeatPreflight:
    """Pre-flight checks to determine if a heartbeat should be skipped."""

    def __init__(self, workspace_path: Path, timezone: str):
        self.workspace_path = workspace_path
        self.timezone = timezone

    @staticmethod
    def parse_active_hours(active_hours: str | None) -> tuple[time, time] | None:
        """Parse active hours string like '08:00-22:00' into start/end times.

        Args:
            active_hours: String in format "HH:MM-HH:MM" or None.

        Returns:
            Tuple of (start_time, end_time) or None if always active.

        Raises:
            ValueError: If the format is invalid.
        """
        if not active_hours:
            return None

        try:
            start_str, end_str = active_hours.split("-")
            start_hour, start_min = map(int, start_str.strip().split(":"))
            end_hour, end_min = map(int, end_str.strip().split(":"))

            start_time = time(start_hour, start_min)
            end_time = time(end_hour, end_min)

            return (start_time, end_time)
        except (ValueError, AttributeError) as e:
            raise ValueError(f"Invalid active_hours format: {active_hours}. Expected 'HH:MM-HH:MM'") from e

    @staticmethod
    def is_within_active_hours(
        active_hours: tuple[time, time] | None, current_time: time
    ) -> bool:
        """Check if current time is within active hours window.

        Args:
            active_hours: Parsed active hours tuple or None.
            current_time: Current time to check.

        Returns:
            True if within active hours or if no active hours are set (always active).
        """
        if active_hours is None:
            return True  # Always active if no hours specified

        start_time, end_time = active_hours

        # Handle case where active hours span midnight
        if start_time <= end_time:
            # Normal case: 08:00-22:00
            return start_time <= current_time <= end_time
        else:
            # Midnight span: 22:00-08:00
            return current_time >= start_time or current_time <= end_time

    @staticmethod
    def is_heartbeat_ok(response: str) -> bool:
        """Check if response indicates no action needed.

        Args:
            response: Agent response text.

        Returns:
            True if response contains HEARTBEAT_OK (case-insensitive).
        """
        return "HEARTBEAT_OK" in response.upper()

    def should_skip_heartbeat(self) -> tuple[bool, str, str | None, int]:
        """Pre-flight check: skip heartbeat if nothing needs attention.

        Checks HEARTBEAT.md and TASKS.yaml to determine if LLM invocation
        can be skipped, saving API costs for idle workspaces.

        Returns:
            Tuple of (should_skip, reason, task_summary, task_count).
            task_summary is None if skipping or no active tasks, otherwise a formatted string.
            task_count is the number of active tasks found (0 if none or on error).
        """
        heartbeat_md = self.workspace_path / str(HEARTBEAT_MD)
        heartbeat_empty = True
        if heartbeat_md.exists():
            try:
                content = heartbeat_md.read_text().strip()
                heartbeat_empty = not content or content == "# Heartbeat" or len(content) < 20
            except OSError:
                heartbeat_empty = False  # Can't read = don't skip

        tasks_file = self.workspace_path / str(TASKS_YAML)
        active_tasks = []
        if tasks_file.exists():
            try:
                with tasks_file.open() as f:
                    data = yaml.safe_load(f)
                tasks = data.get("tasks", []) if data else []
                active_statuses = {"pending", "in_progress", "awaiting_check"}
                active_tasks = [t for t in tasks if t.get("status") in active_statuses]
            except (yaml.YAMLError, OSError) as e:
                logger.warning(f"Failed to read TASKS.yaml during pre-flight: {e}")
                # Can't read = don't skip, but no task summary
                return False, "pre-flight checks passed (TASKS.yaml read error)", None, 0

        if heartbeat_empty and not active_tasks:
            return True, "no active tasks and HEARTBEAT.md is empty", None, 0

        # Build task summary if we're not skipping and have active tasks
        task_summary = build_task_summary(active_tasks) if active_tasks else None
        return False, "pre-flight checks passed", task_summary, len(active_tasks)
