"""Error handling for the message processing loop."""

import logging
from dataclasses import dataclass
from typing import Any, Literal

from openpaw.channels.base import ChannelAdapter
from openpaw.core.utils import sanitize_error_for_user
from openpaw.workspace.processors.compactor import AutoCompactor


@dataclass(frozen=True)
class ErrorResult:
    """Result of handling a generic error.

    Attributes:
        action: What the caller should do next.
            - "continue": Continue the loop with the provided content.
            - "break": Exit the loop.
        combined_content: When action is "continue", the new message content to use.
    """

    action: Literal["continue", "break"]
    combined_content: str | None = None


class ErrorHandler:
    """Encapsulates generic error handling inside the message loop.

    Detects context-window overflows and attempts emergency recovery. For all
    other errors, sends a sanitized message to the user and breaks the loop.
    """

    def __init__(
        self,
        logger: logging.Logger,
        compactor: AutoCompactor,
    ) -> None:
        """Initialize the handler.

        Args:
            logger: Logger instance.
            compactor: AutoCompactor for context-overflow detection and recovery.
        """
        self._logger = logger
        self._compactor = compactor

    async def handle(
        self,
        error: Exception,
        channel: ChannelAdapter | None,
        session_key: str,
        thread_id: str,
        agent_runner: Any,
    ) -> ErrorResult:
        """Handle a generic error.

        Args:
            error: The exception that occurred.
            channel: Channel adapter for sending error messages.
            session_key: The session identifier.
            thread_id: The current conversation thread ID.
            agent_runner: The agent runner for recovery operations.

        Returns:
            ErrorResult instructing the loop what to do next.
        """
        self._logger.error(
            f"Error processing messages for {session_key}: {error}",
            exc_info=True,
        )

        if self._compactor.is_context_overflow(error):
            new_tid = await self._compactor.recover_overflow(
                session_key, thread_id, channel, agent_runner
            )
            if new_tid:
                return ErrorResult(
                    action="continue",
                    combined_content=(
                        "[SYSTEM] The previous conversation was too long and has been archived. "
                        "A fresh conversation has started. Please continue from where you left off."
                    ),
                )

        if channel:
            try:
                await channel.send_message(session_key, sanitize_error_for_user(error))
            except Exception as send_err:
                self._logger.warning(
                    f"Failed to send error message to {session_key}: {send_err}"
                )

        return ErrorResult(action="break")
