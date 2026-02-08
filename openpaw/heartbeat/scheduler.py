"""HeartbeatScheduler for periodic agent task evaluation."""

import json
import logging
from collections.abc import Callable, Mapping
from datetime import datetime, time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from openpaw.channels.base import ChannelAdapter
from openpaw.core.config import HeartbeatConfig

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


# Heartbeat prompt template with timestamp injection
HEARTBEAT_PROMPT = """[HEARTBEAT CHECK - {timestamp}]

## Step 1: Check Active Tasks
Use your task management tools to review active work:
1. Call list_tasks() to see all in-progress and pending tasks
2. For in-progress tasks past their expected duration, investigate and update status
3. For awaiting_check tasks, take the appropriate action
4. Update task status and notes as you work through each item

## Step 2: Review HEARTBEAT.md
Check your HEARTBEAT.md file for any non-task items requiring attention:
- Time-sensitive reminders or monitors
- Pending status checks (PRs, builds, deployments)
- User notifications that need to be sent

## Step 3: Take Action or Stand Down
If you found items needing attention:
- Take appropriate action (check APIs, read files, notify user)
- Update HEARTBEAT.md with completed items
- Update task statuses with progress notes

If nothing requires immediate attention, respond exactly: HEARTBEAT_OK

Do NOT repeat previously completed tasks or invent new ones.
"""

HEARTBEAT_LOG_FILENAME = "heartbeat_log.jsonl"


class HeartbeatScheduler:
    """Sends periodic heartbeat prompts to agents for proactive task evaluation.

    Heartbeat checks run at a configured interval and prompt the agent to review
    pending tasks in HEARTBEAT.md. If nothing needs attention, the agent responds
    with "HEARTBEAT_OK" which is suppressed from channel output.
    """

    def __init__(
        self,
        workspace_name: str,
        workspace_path: Path,
        agent_factory: Callable[[], Any],
        channels: Mapping[str, ChannelAdapter],
        config: HeartbeatConfig,
        token_logger: Any | None = None,
    ):
        """Initialize the heartbeat scheduler.

        Args:
            workspace_name: Name of the agent workspace.
            workspace_path: Path to the workspace directory.
            agent_factory: Factory function to create fresh agent instances (no checkpointer).
            channels: Dictionary mapping channel types to channel instances for routing.
            config: Heartbeat configuration settings.
            token_logger: Optional TokenUsageLogger for logging token metrics.
        """
        self.workspace_name = workspace_name
        self.workspace_path = workspace_path
        self.agent_factory = agent_factory
        self.channels = channels
        self.config = config
        self._token_logger = token_logger
        self._scheduler: AsyncIOScheduler | None = None
        self._job: Any = None

        # Parse active hours at initialization
        self._active_hours = self._parse_active_hours(config.active_hours)

    def _parse_active_hours(self, active_hours: str | None) -> tuple[time, time] | None:
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

    def _is_within_active_hours(self) -> bool:
        """Check if current time is within active hours window.

        Returns:
            True if within active hours or if no active hours are set (always active).
        """
        if self._active_hours is None:
            return True  # Always active if no hours specified

        current_time = datetime.now().time()
        start_time, end_time = self._active_hours

        # Handle case where active hours span midnight
        if start_time <= end_time:
            # Normal case: 08:00-22:00
            return start_time <= current_time <= end_time
        else:
            # Midnight span: 22:00-08:00
            return current_time >= start_time or current_time <= end_time

    def _is_heartbeat_ok(self, response: str) -> bool:
        """Check if response indicates no action needed.

        Args:
            response: Agent response text.

        Returns:
            True if response contains HEARTBEAT_OK (case-insensitive).
        """
        return "HEARTBEAT_OK" in response.upper()

    def _build_task_summary(self, tasks: list[dict[str, Any]]) -> str | None:
        """Build a compact task summary from TASKS.yaml data.

        Args:
            tasks: List of task dictionaries (already filtered to active tasks).

        Returns:
            Formatted task summary string, or None if no tasks.
        """
        from datetime import UTC

        if not tasks:
            return None

        lines = [f"Active Tasks ({len(tasks)}):"]
        now = datetime.now(UTC)

        for task in tasks:
            task_id = task.get("id", "unknown")
            # Show first 8 chars of ID
            short_id = task_id[:8] if len(task_id) > 8 else task_id
            status = task.get("status", "unknown")
            title = task.get("description", "Untitled")

            # Calculate age based on created_at or started_at
            created_str = task.get("started_at") or task.get("created_at")
            age_str = "unknown age"
            if created_str:
                try:
                    created_at = datetime.fromisoformat(created_str)
                    # Ensure both datetimes are timezone-aware for comparison
                    if created_at.tzinfo is None:
                        # Assume UTC if no timezone info
                        created_at = created_at.replace(tzinfo=UTC)
                    delta = now - created_at

                    # Format as "Xm ago", "Xh ago", "Xd ago"
                    total_minutes = int(delta.total_seconds() / 60)
                    if total_minutes < 60:
                        age_str = f"{total_minutes}m ago"
                    elif total_minutes < 1440:  # Less than 24 hours
                        hours = total_minutes // 60
                        age_str = f"{hours}h ago"
                    else:
                        days = total_minutes // 1440
                        age_str = f"{days}d ago"
                except (ValueError, TypeError):
                    pass

            # Format: - [abc12345] in_progress | "Market analysis" (started 15m ago)
            status_verb = "running" if status == "in_progress" else "created"
            lines.append(f'- [{short_id}] {status} | "{title}" ({status_verb} {age_str})')

        return "\n".join(lines)

    def _build_heartbeat_prompt(self, task_summary: str | None = None) -> str:
        """Build the heartbeat prompt with current timestamp and optional task summary.

        Args:
            task_summary: Optional compact task summary to inject into the prompt.

        Returns:
            Formatted heartbeat prompt string.
        """
        timestamp = datetime.now().isoformat()
        prompt = HEARTBEAT_PROMPT.format(timestamp=timestamp)

        if task_summary:
            prompt += f"\n<active_tasks>\n{task_summary}\n</active_tasks>"

        return prompt

    def _should_skip_heartbeat(self) -> tuple[bool, str, str | None, int]:
        """Pre-flight check: skip heartbeat if nothing needs attention.

        Checks HEARTBEAT.md and TASKS.yaml to determine if LLM invocation
        can be skipped, saving API costs for idle workspaces.

        Returns:
            Tuple of (should_skip, reason, task_summary, task_count).
            task_summary is None if skipping or no active tasks, otherwise a formatted string.
            task_count is the number of active tasks found (0 if none or on error).
        """
        heartbeat_md = self.workspace_path / "HEARTBEAT.md"
        heartbeat_empty = True
        if heartbeat_md.exists():
            try:
                content = heartbeat_md.read_text().strip()
                heartbeat_empty = not content or content == "# Heartbeat" or len(content) < 20
            except OSError:
                heartbeat_empty = False  # Can't read = don't skip

        tasks_file = self.workspace_path / "TASKS.yaml"
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
        task_summary = self._build_task_summary(active_tasks) if active_tasks else None
        return False, "pre-flight checks passed", task_summary, len(active_tasks)

    def _record_heartbeat_event(
        self,
        outcome: str,
        reason: str | None = None,
        duration_ms: float | None = None,
        error: str | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        total_tokens: int | None = None,
        llm_calls: int | None = None,
        task_count: int | None = None,
    ) -> None:
        """Append heartbeat event to workspace JSONL log.

        Args:
            outcome: Event outcome (ran, skipped, heartbeat_ok, error).
            reason: Reason for skip or additional context.
            duration_ms: Execution duration in milliseconds.
            error: Error message if applicable.
            input_tokens: Input token count from invocation.
            output_tokens: Output token count from invocation.
            total_tokens: Total token count from invocation.
            llm_calls: Number of LLM calls made.
            task_count: Number of active tasks when heartbeat ran.
        """
        from datetime import UTC, datetime

        log_path = self.workspace_path / HEARTBEAT_LOG_FILENAME
        event: dict[str, str | float | int] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "workspace": self.workspace_name,
            "outcome": outcome,
        }
        if reason:
            event["reason"] = reason
        if duration_ms is not None:
            event["duration_ms"] = round(duration_ms, 1)
        if error:
            event["error"] = error
        if input_tokens is not None:
            event["input_tokens"] = input_tokens
        if output_tokens is not None:
            event["output_tokens"] = output_tokens
        if total_tokens is not None:
            event["total_tokens"] = total_tokens
        if llm_calls is not None:
            event["llm_calls"] = llm_calls
        if task_count is not None:
            event["task_count"] = task_count

        try:
            with log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(event) + "\n")
        except OSError as e:
            logger.warning(f"Failed to write heartbeat log: {e}")

    async def start(self) -> None:
        """Start the heartbeat scheduler with interval trigger."""
        if not self.config.enabled:
            logger.info(f"Heartbeat scheduler disabled for workspace: {self.workspace_name}")
            return

        self._scheduler = AsyncIOScheduler()

        # Create interval trigger
        trigger = IntervalTrigger(minutes=self.config.interval_minutes)

        # Schedule the heartbeat job
        self._job = self._scheduler.add_job(
            func=self._run_heartbeat,
            trigger=trigger,
            id=f"heartbeat_{self.workspace_name}",
            name=f"Heartbeat: {self.workspace_name}",
            replace_existing=True,
        )

        self._scheduler.start()
        logger.info(
            f"Heartbeat scheduler started for workspace '{self.workspace_name}' "
            f"(interval: {self.config.interval_minutes}m, "
            f"active_hours: {self.config.active_hours or 'always'})"
        )

    async def stop(self) -> None:
        """Stop the heartbeat scheduler gracefully."""
        if self._scheduler and self._scheduler.running:
            self._scheduler.shutdown(wait=True)
            logger.info(f"Heartbeat scheduler stopped for workspace: {self.workspace_name}")

    async def _run_heartbeat(self) -> None:
        """Execute a heartbeat check with pre-flight skip and event logging."""
        import time as time_module

        # Check active hours
        if not self._is_within_active_hours():
            logger.debug(
                f"Heartbeat skipped for '{self.workspace_name}' "
                f"(outside active hours: {self.config.active_hours})"
            )
            self._record_heartbeat_event("skipped", reason="outside active hours")
            return

        # Pre-flight check (returns task count alongside summary)
        should_skip, reason, task_summary, task_count = self._should_skip_heartbeat()

        if should_skip:
            logger.info(f"Heartbeat skipped for '{self.workspace_name}': {reason}")
            self._record_heartbeat_event("skipped", reason=reason, task_count=0)
            return

        logger.info(f"Running heartbeat check for workspace: {self.workspace_name}")
        start_time = time_module.monotonic()

        try:
            agent_runner = self.agent_factory()
            heartbeat_prompt = self._build_heartbeat_prompt(task_summary=task_summary)
            response = await agent_runner.run(message=heartbeat_prompt)
            duration_ms = (time_module.monotonic() - start_time) * 1000

            # Extract token metrics from agent runner
            metrics = agent_runner.last_metrics
            input_tokens = metrics.input_tokens if metrics else None
            output_tokens = metrics.output_tokens if metrics else None
            total_tokens = metrics.total_tokens if metrics else None
            llm_calls = metrics.llm_calls if metrics else None

            if self.config.suppress_ok and self._is_heartbeat_ok(response):
                logger.debug(f"Heartbeat OK for workspace: {self.workspace_name} (suppressed)")
                self._record_heartbeat_event(
                    "heartbeat_ok",
                    duration_ms=duration_ms,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    total_tokens=total_tokens,
                    llm_calls=llm_calls,
                    task_count=task_count,
                )

                # Log to token_usage.jsonl if available
                if self._token_logger and metrics:
                    self._token_logger.log(
                        metrics=metrics,
                        workspace=self.workspace_name,
                        invocation_type="heartbeat",
                        session_key=None,
                    )
                return

            channel = self.channels.get(self.config.target_channel)
            if not channel:
                logger.error(
                    f"Heartbeat channel not found: {self.config.target_channel} "
                    f"(workspace: {self.workspace_name})"
                )
                self._record_heartbeat_event(
                    "error",
                    error="channel not found",
                    duration_ms=duration_ms,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    total_tokens=total_tokens,
                    llm_calls=llm_calls,
                    task_count=task_count,
                )

                # Log to token_usage.jsonl even on error
                if self._token_logger and metrics:
                    self._token_logger.log(
                        metrics=metrics,
                        workspace=self.workspace_name,
                        invocation_type="heartbeat",
                        session_key=None,
                    )
                return

            if self.config.target_channel == "telegram" and self.config.target_chat_id:
                session_key = channel.build_session_key(self.config.target_chat_id)
                await channel.send_message(session_key=session_key, content=response)
                logger.info(f"Heartbeat notification sent to {self.config.target_channel}/{session_key}")
                self._record_heartbeat_event(
                    "ran",
                    duration_ms=duration_ms,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    total_tokens=total_tokens,
                    llm_calls=llm_calls,
                    task_count=task_count,
                )

                # Log to token_usage.jsonl
                if self._token_logger and metrics:
                    self._token_logger.log(
                        metrics=metrics,
                        workspace=self.workspace_name,
                        invocation_type="heartbeat",
                        session_key=session_key,
                    )
            else:
                logger.warning(
                    f"Heartbeat response generated but no routing configured "
                    f"(workspace: {self.workspace_name}, response length: {len(response)})"
                )
                self._record_heartbeat_event(
                    "ran",
                    reason="no routing configured",
                    duration_ms=duration_ms,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    total_tokens=total_tokens,
                    llm_calls=llm_calls,
                    task_count=task_count,
                )

                # Log to token_usage.jsonl
                if self._token_logger and metrics:
                    self._token_logger.log(
                        metrics=metrics,
                        workspace=self.workspace_name,
                        invocation_type="heartbeat",
                        session_key=None,
                    )

        except Exception as e:
            duration_ms = (time_module.monotonic() - start_time) * 1000
            logger.error(
                f"Heartbeat check failed for workspace '{self.workspace_name}': {e}",
                exc_info=True,
            )
            self._record_heartbeat_event(
                "error",
                error=str(e),
                duration_ms=duration_ms,
                task_count=task_count,
            )
