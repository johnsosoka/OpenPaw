"""Interrupt handling for the message processing loop."""

import logging

from openpaw.agent.middleware import InterruptSignalError
from openpaw.channels.base import ChannelAdapter
from openpaw.core.prompts.system_events import INTERRUPT_NOTIFICATION
from openpaw.workspace.processors.combiner import ContentCombiner


class InterruptHandler:
    """Encapsulates interrupt-signal handling inside the message loop.

    When an interrupt is detected, the agent's current run is aborted and the
    pending user messages become the new input.
    """

    def __init__(self, logger: logging.Logger, combiner: ContentCombiner) -> None:
        """Initialize the handler.

        Args:
            logger: Logger instance.
            combiner: Content combiner for building combined content from tuples.
        """
        self._logger = logger
        self._combiner = combiner

    async def handle(
        self,
        error: InterruptSignalError,
        channel: ChannelAdapter | None,
        session_key: str,
    ) -> str:
        """Handle an interrupt signal.

        Args:
            error: The interrupt signal containing pending messages.
            channel: Channel adapter for sending the interrupt notification.
            session_key: The session identifier for the notification.

        Returns:
            New combined content built from the pending messages.
        """
        if channel:
            try:
                await channel.send_message(session_key, INTERRUPT_NOTIFICATION)
            except Exception as send_err:
                self._logger.warning(
                    f"Failed to send interrupt notification to {session_key}: {send_err}"
                )

        pending = error.pending_messages
        if pending:
            return self._combiner.build_combined_content_from_tuples(pending)

        return ""
