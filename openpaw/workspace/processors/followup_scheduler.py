"""Followup scheduling for the message processing loop."""

import logging
from dataclasses import dataclass
from typing import Any, Literal

from openpaw.builtins.tools.cron.scheduler_bridge import _add_to_live_scheduler
from openpaw.core.prompts.system_events import FOLLOWUP_TEMPLATE


@dataclass(frozen=True)
class FollowupResult:
    """Result of checking for a pending followup.

    Attributes:
        action: What the caller should do next.
            - "continue": Process the followup immediately.
            - "break": No followup or delayed followup scheduled; exit loop.
        combined_content: When action is "continue", the new message content.
        new_depth: Updated followup depth when action is "continue".
        scheduled: Whether a delayed followup was scheduled.
    """

    action: Literal["continue", "break"]
    combined_content: str | None = None
    new_depth: int | None = None
    scheduled: bool = False


class FollowupScheduler:
    """Encapsulates followup detection and scheduling inside the message loop.

    Checks for immediate followups (delay_seconds == 0) and either returns
    the new content for the loop to continue, or schedules a delayed followup
    via the cron system and tells the loop to break.
    """

    def __init__(self, builtin_loader: Any, logger: logging.Logger) -> None:
        """Initialize the scheduler.

        Args:
            builtin_loader: BuiltinLoader for accessing the followup and cron tools.
            logger: Logger instance.
        """
        self._builtin_loader = builtin_loader
        self._logger = logger

    def check(
        self,
        session_key: str,
        followup_depth: int,
        max_depth: int = 5,
    ) -> FollowupResult:
        """Check for a pending followup and decide what the loop should do.

        Args:
            session_key: The session identifier (used for delayed scheduling).
            followup_depth: Current followup chain depth.
            max_depth: Maximum allowed followup depth.

        Returns:
            FollowupResult instructing the loop what to do next.
        """
        followup_tool = self._builtin_loader.get_tool_instance("followup")
        if not followup_tool:
            return FollowupResult(action="break")

        followup = followup_tool.get_pending_followup()
        if not followup:
            return FollowupResult(action="break")

        if followup.delay_seconds == 0:
            new_depth = followup_depth + 1
            if new_depth > max_depth:
                self._logger.warning(
                    f"Followup chain depth exceeded ({max_depth}) "
                    f"for session {session_key}"
                )
                return FollowupResult(action="break")

            self._logger.info(
                f"Processing immediate followup (depth={new_depth}): "
                f"{followup.prompt[:100]}"
            )
            return FollowupResult(
                action="continue",
                combined_content=FOLLOWUP_TEMPLATE.format(
                    depth=new_depth, prompt=followup.prompt
                ),
                new_depth=new_depth,
            )

        # Delayed followup
        self._logger.info(
            f"Scheduling delayed followup ({followup.delay_seconds}s): "
            f"{followup.prompt[:100]}"
        )
        self._schedule_delayed(followup, session_key)
        return FollowupResult(action="break", scheduled=True)

    def _schedule_delayed(self, followup: Any, session_key: str) -> None:
        """Schedule a delayed followup via the cron system.

        Args:
            followup: The followup request with delay_seconds and prompt.
            session_key: The session identifier (used for logging only).
        """
        from datetime import UTC, datetime, timedelta

        cron_tool = self._builtin_loader.get_tool_instance("cron")
        if not cron_tool or not cron_tool.scheduler:
            self._logger.warning(
                "Cannot schedule delayed followup: no cron tool/scheduler available"
            )
            return

        if not cron_tool.default_chat_id:
            self._logger.warning(
                "Cannot schedule delayed followup: cron tool has no default_chat_id"
            )
            return

        run_at = datetime.now(UTC) + timedelta(seconds=followup.delay_seconds)
        from openpaw.stores.cron import create_once_task

        task = create_once_task(
            prompt=followup.prompt,
            run_at=run_at,
            channel=cron_tool.default_channel,
            chat_id=cron_tool.default_chat_id,
        )
        cron_tool.store.add_task(task)
        _add_to_live_scheduler(cron_tool.scheduler, task)
        self._logger.info(f"Delayed followup scheduled as cron task {task.id}")
