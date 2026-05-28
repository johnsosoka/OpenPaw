"""Sub-agent notification formatting and delivery.

Extracts notification logic from the runner into a dedicated helper that
formats completion / timeout / failure messages and delivers them via the
configured callback or channel.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping

from openpaw.channels.base import ChannelAdapter
from openpaw.core.prompts.system_events import (
    SUBAGENT_COMPLETED_SHORT_TEMPLATE,
    SUBAGENT_COMPLETED_TEMPLATE,
    SUBAGENT_FAILED_TEMPLATE,
    SUBAGENT_TIMED_OUT_TEMPLATE,
)
from openpaw.model.subagent import SubAgentRequest, SubAgentResult

from .formatter import build_origin_suffix

logger = logging.getLogger(__name__)


class SubAgentNotifier:
    """Formats and sends sub-agent completion notifications.

    Supports two delivery modes:
    - Queue injection via ``result_callback`` (preferred)
    - Direct channel messaging as a fallback
    """

    def __init__(
        self,
        channels: Mapping[str, ChannelAdapter],
        result_callback: Callable[[str, str], Awaitable[None]] | None,
    ):
        """Initialize the notifier.

        Args:
            channels: Mapping of channel names to adapter instances.
            result_callback: Optional callback for queue injection of
                notifications. Called with ``(session_key, content)``.
        """
        self._channels = channels
        self._result_callback = result_callback

    def format_notification(
        self, request: SubAgentRequest, result: SubAgentResult
    ) -> str:
        """Format a notification message for sub-agent completion.

        Args:
            request: The original sub-agent request.
            result: The execution result.

        Returns:
            Formatted notification content with ``[SYSTEM]`` prefix.
        """
        origin_suffix = build_origin_suffix(request)

        log_suffix = (
            f"\nFull session log: {result.session_log_path}"
            if result.session_log_path
            else ""
        )

        # Determine status and format message
        if result.error:
            if "timed out" in result.error.lower():
                return SUBAGENT_TIMED_OUT_TEMPLATE.format(
                    label=request.label,
                    timeout_minutes=request.timeout_minutes,
                    origin_suffix=origin_suffix,
                ) + log_suffix
            else:
                return SUBAGENT_FAILED_TEMPLATE.format(
                    label=request.label,
                    error=result.error,
                    origin_suffix=origin_suffix,
                ) + log_suffix
        else:
            output = result.output
            if len(output) > 500:
                output = output[:500]
                return SUBAGENT_COMPLETED_TEMPLATE.format(
                    label=request.label,
                    output=output,
                    request_id=request.id,
                    origin_suffix=origin_suffix,
                ) + log_suffix
            else:
                return SUBAGENT_COMPLETED_SHORT_TEMPLATE.format(
                    label=request.label,
                    output=output,
                    origin_suffix=origin_suffix,
                ) + log_suffix

    async def send_notification(
        self, request: SubAgentRequest, result: SubAgentResult
    ) -> None:
        """Send completion notification to the requesting session.

        Args:
            request: The original sub-agent request.
            result: The execution result.
        """
        try:
            # Format the notification content
            content = self.format_notification(request, result)

            # Use result callback if provided (queue injection)
            if self._result_callback:
                await self._result_callback(request.session_key, content)
                logger.debug(f"Queued notification for sub-agent {request.id}")
            else:
                # Fallback: direct channel send (backwards compatibility)
                parts = request.session_key.split(":", 1)
                if len(parts) != 2:
                    logger.warning(
                        f"Invalid session_key format for notification: {request.session_key}"
                    )
                    return

                channel_name = parts[0]
                channel = self._channels.get(channel_name)

                if not channel:
                    logger.warning(f"Channel not found for notification: {channel_name}")
                    return

                await channel.send_message(session_key=request.session_key, content=content)
                logger.debug(f"Sent notification for sub-agent {request.id}")

        except Exception as e:
            logger.warning(
                f"Failed to send notification for sub-agent {request.id}: {e}",
                exc_info=True,
            )
