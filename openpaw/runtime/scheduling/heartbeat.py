"""HeartbeatScheduler for periodic agent task evaluation."""

import logging
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from openpaw.agent.session_logger import SessionLogger
from openpaw.core.config import HeartbeatConfig
from openpaw.core.prompts.heartbeat import HEARTBEAT_PROMPT  # noqa: F401
from openpaw.core.timezone import workspace_now
from openpaw.runtime.scheduling.heartbeat_executor import HeartbeatExecutor
from openpaw.runtime.scheduling.heartbeat_preflight import HeartbeatPreflight
from openpaw.runtime.scheduling.heartbeat_prompt import HeartbeatPromptBuilder

logger = logging.getLogger(__name__)


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
        agent_factory: Callable[..., Any],
        channels: Mapping[str, Any],
        config: HeartbeatConfig,
        timezone: str = "UTC",
        token_logger: Any | None = None,
        result_callback: Callable[[str, str], Awaitable[None]] | None = None,
        session_logger: SessionLogger | None = None,
        ack_tool: Any | None = None,
    ):
        """Initialize the heartbeat scheduler."""
        self.workspace_name = workspace_name
        self.workspace_path = workspace_path
        self.agent_factory = agent_factory
        self.channels = channels
        self.config = config
        self._timezone = timezone
        self._token_logger = token_logger
        self._result_callback = result_callback
        self._session_logger = session_logger
        self._ack_tool = ack_tool
        self._scheduler: AsyncIOScheduler | None = None
        self._job: Any = None

        self._preflight = HeartbeatPreflight(workspace_path, timezone)
        self._prompt_builder = HeartbeatPromptBuilder()
        self._active_hours = self._preflight.parse_active_hours(config.active_hours)
        self._executor = HeartbeatExecutor(
            workspace_path=workspace_path,
            workspace_name=workspace_name,
            config=config,
            token_logger=token_logger,
            result_callback=result_callback,
            session_logger=session_logger,
            ack_tool=ack_tool,
        )

    @staticmethod
    def _resolve_heartbeat_session_key(channel: Any, config: HeartbeatConfig) -> str | None:
        """Resolve session key from heartbeat config."""
        return HeartbeatExecutor._resolve_heartbeat_session_key(channel, config)

    def _parse_active_hours(self, active_hours: str | None) -> Any:
        """Parse active hours string like '08:00-22:00' into start/end times."""
        return self._preflight.parse_active_hours(active_hours)

    def _is_within_active_hours(self) -> bool:
        """Check if current time is within active hours window."""
        current_time = workspace_now(self._timezone).time()
        return self._preflight.is_within_active_hours(self._active_hours, current_time)

    def _is_heartbeat_ok(self, response: str) -> bool:
        """Check if response indicates no action needed."""
        return self._preflight.is_heartbeat_ok(response)

    def _build_task_summary(self, tasks: list[dict[str, Any]]) -> str | None:
        """Build a compact task summary from TASKS.yaml data."""
        return self._prompt_builder.build_task_summary(tasks)

    def _build_heartbeat_prompt(self, task_summary: str | None = None) -> str:
        """Build the heartbeat prompt with current timestamp and optional task summary."""
        timestamp = workspace_now(self._timezone).isoformat()
        return self._prompt_builder.build_heartbeat_prompt(timestamp, task_summary)

    def _should_skip_heartbeat(self) -> tuple[bool, str, str | None, int]:
        """Pre-flight check: skip heartbeat if nothing needs attention."""
        return self._preflight.should_skip_heartbeat()

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
        response: str | None = None,
        tools_used: list[str] | None = None,
    ) -> None:
        """Append heartbeat event to workspace JSONL log."""
        self._executor.record_heartbeat_event(
            outcome=outcome,
            reason=reason,
            duration_ms=duration_ms,
            error=error,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            llm_calls=llm_calls,
            task_count=task_count,
            response=response,
            tools_used=tools_used,
        )

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
        # Check active hours
        if not self._is_within_active_hours():
            logger.debug(
                f"Heartbeat skipped for '{self.workspace_name}' "
                f"(outside active hours: {self.config.active_hours})"
            )
            self._executor.record_heartbeat_event("skipped", reason="outside active hours")
            return

        # Pre-flight check (returns task count alongside summary)
        should_skip, reason, task_summary, task_count = self._should_skip_heartbeat()

        if should_skip:
            logger.info(f"Heartbeat skipped for '{self.workspace_name}': {reason}")
            self._executor.record_heartbeat_event("skipped", reason=reason, task_count=0)
            return

        await self._executor.run_heartbeat(
            preflight=self._preflight,
            prompt_builder=self._prompt_builder,
            timezone=self._timezone,
            task_summary=task_summary,
            task_count=task_count,
            agent_factory=self.agent_factory,
            channels=self.channels,
        )
