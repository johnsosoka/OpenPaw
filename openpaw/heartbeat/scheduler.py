"""HeartbeatScheduler for periodic agent task evaluation."""

import logging
from collections.abc import Callable, Mapping
from datetime import time
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from openpaw.channels.base import ChannelAdapter
from openpaw.core.config import HeartbeatConfig
from openpaw.core.timezone import workspace_now

logger = logging.getLogger(__name__)


# Heartbeat prompt template with timestamp injection
HEARTBEAT_PROMPT = """[HEARTBEAT CHECK - {timestamp}]

Review your HEARTBEAT.md file for pending tasks. For each task, evaluate:
- Is it time-sensitive and due now?
- Does it require a status check (API call, file read)?
- Should the user be notified of any updates?

If nothing requires immediate attention, respond exactly: HEARTBEAT_OK

Otherwise, take appropriate action:
- Check pending monitors (PRs, builds, deployments)
- Update HEARTBEAT.md with any completed items
- Notify the user of significant events

Do NOT repeat previously completed tasks or invent new ones.
"""


class HeartbeatScheduler:
    """Sends periodic heartbeat prompts to agents for proactive task evaluation.

    Heartbeat checks run at a configured interval and prompt the agent to review
    pending tasks in HEARTBEAT.md. If nothing needs attention, the agent responds
    with "HEARTBEAT_OK" which is suppressed from channel output.
    """

    def __init__(
        self,
        workspace_name: str,
        agent_factory: Callable[[], Any],
        channels: Mapping[str, ChannelAdapter],
        config: HeartbeatConfig,
        timezone: str = "UTC",
    ):
        """Initialize the heartbeat scheduler.

        Args:
            workspace_name: Name of the agent workspace.
            agent_factory: Factory function to create fresh agent instances (no checkpointer).
            channels: Dictionary mapping channel types to channel instances for routing.
            config: Heartbeat configuration settings.
            timezone: IANA timezone identifier for workspace timezone (default: "UTC").
        """
        self.workspace_name = workspace_name
        self.agent_factory = agent_factory
        self.channels = channels
        self.config = config
        self._timezone = timezone
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

        current_time = workspace_now(self._timezone).time()
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

    def _build_heartbeat_prompt(self) -> str:
        """Build the heartbeat prompt with current timestamp.

        Returns:
            Formatted heartbeat prompt string.
        """
        timestamp = workspace_now(self._timezone).isoformat()
        return HEARTBEAT_PROMPT.format(timestamp=timestamp)

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
        """Execute a heartbeat check.

        Creates a fresh agent instance, injects the heartbeat prompt, and routes
        the response to the configured channel (unless HEARTBEAT_OK).
        """
        # Check if within active hours
        if not self._is_within_active_hours():
            logger.debug(
                f"Heartbeat skipped for '{self.workspace_name}' (outside active hours: {self.config.active_hours})"
            )
            return

        logger.info(f"Running heartbeat check for workspace: {self.workspace_name}")

        try:
            # Build fresh agent instance (no conversation memory)
            agent_runner = self.agent_factory()

            # Inject heartbeat prompt
            heartbeat_prompt = self._build_heartbeat_prompt()
            response = await agent_runner.run(message=heartbeat_prompt)

            # Check for HEARTBEAT_OK
            if self.config.suppress_ok and self._is_heartbeat_ok(response):
                logger.debug(f"Heartbeat OK for workspace: {self.workspace_name} (suppressed)")
                return

            # Route response to channel
            channel = self.channels.get(self.config.target_channel)
            if not channel:
                logger.error(
                    f"Heartbeat channel not found: {self.config.target_channel} "
                    f"(workspace: {self.workspace_name})"
                )
                return

            # Build session key for routing
            if self.config.target_channel == "telegram" and self.config.target_chat_id:
                session_key = channel.build_session_key(self.config.target_chat_id)
                await channel.send_message(session_key=session_key, content=response)
                logger.info(f"Heartbeat notification sent to {self.config.target_channel}/{session_key}")
            else:
                logger.warning(
                    f"Heartbeat response generated but no routing configured "
                    f"(workspace: {self.workspace_name}, response length: {len(response)})"
                )

        except Exception as e:
            logger.error(f"Heartbeat check failed for workspace '{self.workspace_name}': {e}", exc_info=True)
