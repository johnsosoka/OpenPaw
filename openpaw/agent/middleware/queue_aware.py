"""Queue-aware tool middleware for steer and interrupt modes."""

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware import wrap_tool_call
from langchain_core.messages import ToolMessage

from openpaw.core.prompts.system_events import STEER_SKIP_MESSAGE
from openpaw.runtime.queue.lane import QueueMode
from openpaw.runtime.queue.manager import QueueManager

logger = logging.getLogger(__name__)


class InterruptSignalError(Exception):
    """Raised when interrupt mode detects a pending message during tool execution.

    Carries the pending messages for immediate processing.
    """

    def __init__(self, pending_messages: list[Any]):
        self.pending_messages = pending_messages
        super().__init__(f"Interrupted: {len(pending_messages)} pending message(s)")


class QueueAwareToolMiddleware:
    """Middleware that checks the queue during tool execution.

    In steer mode: skips remaining tools when queue has pending messages.
    In interrupt mode: raises InterruptSignal to abort the run.
    In collect mode: no-op (tools execute normally).

    Designed to be instantiated once and stored on AgentRunner. Per-invocation
    state is managed via set_queue_awareness() and reset().
    """

    def __init__(self) -> None:
        self._queue_manager: QueueManager | None = None
        self._session_key: str | None = None
        self._queue_mode: QueueMode = QueueMode.COLLECT
        self._pending_steer_message: list[Any] | None = None
        self._steered: bool = False  # Track if steer occurred this invocation

    def set_queue_awareness(
        self,
        queue_manager: QueueManager,
        session_key: str,
        queue_mode: QueueMode,
    ) -> None:
        """Configure queue awareness for current invocation.

        Called before each agent run to set the session context.

        Args:
            queue_manager: The queue manager instance.
            session_key: Session identifier for this invocation.
            queue_mode: Current queue mode for this invocation.
        """
        self._queue_manager = queue_manager
        self._session_key = session_key
        self._queue_mode = queue_mode
        self._pending_steer_message = None
        self._steered = False

    def reset(self) -> None:
        """Reset per-invocation state. Called after each agent run."""
        self._queue_manager = None
        self._session_key = None
        self._queue_mode = QueueMode.COLLECT
        self._pending_steer_message = None
        self._steered = False

    @property
    def pending_steer_message(self) -> list[Any] | None:
        """Get pending messages that caused a steer, if any."""
        return self._pending_steer_message

    @property
    def was_steered(self) -> bool:
        """Whether a steer occurred during the current invocation."""
        return self._steered

    def get_middleware(self) -> Any:
        """Return the wrap_tool_call compatible middleware function.

        This is what gets passed to create_agent(middleware=[...]).

        Returns:
            Middleware function decorated with @wrap_tool_call.
        """
        middleware_instance = self  # Capture reference

        @wrap_tool_call  # type: ignore[call-overload]
        async def queue_aware_tool_wrapper(request: Any, handler: Callable[[Any], Awaitable[Any]]) -> Any:
            """Middleware that checks queue before each tool execution."""
            return await middleware_instance._check_and_execute(request, handler)

        return queue_aware_tool_wrapper

    async def _check_and_execute(self, request: Any, handler: Callable[[Any], Awaitable[Any]]) -> Any:
        """Check queue and either execute tool, skip, or interrupt.

        Args:
            request: ToolCallRequest with tool_call (name, args, id).
            handler: Async function to execute the tool.

        Returns:
            Tool result (either from handler or skip message).

        Raises:
            InterruptSignalError: When interrupt mode detects pending messages.
        """
        tool_name = request.tool_call.get("name", "unknown")
        logger.debug(
            f"Middleware intercepting tool '{tool_name}' "
            f"(mode={self._queue_mode.value}, session={self._session_key})"
        )

        # In collect mode or if no queue awareness set, just execute normally
        if (
            self._queue_mode == QueueMode.COLLECT
            or self._queue_manager is None
            or self._session_key is None
        ):
            logger.debug(f"Middleware pass-through: mode={self._queue_mode.value}")
            return await handler(request)

        # Check for pending messages
        has_pending = await self._queue_manager.peek_pending(self._session_key)
        logger.debug(f"Middleware peek_pending={has_pending} for session={self._session_key}")

        if not has_pending:
            # No pending messages, execute normally
            return await handler(request)

        if self._queue_mode == QueueMode.STEER:
            # Steer: skip tool, store pending messages for post-run consumption
            # Only consume messages once (on first tool skip)
            if not self._steered:
                pending = await self._queue_manager.consume_pending(self._session_key)
                self._pending_steer_message = pending
                self._steered = True
                logger.info(
                    f"Steer triggered: skipping tool {request.tool_call.get('name')} "
                    f"due to {len(pending)} pending message(s)"
                )

            # Return a ToolMessage indicating the tool was skipped
            return ToolMessage(
                content=STEER_SKIP_MESSAGE,
                tool_call_id=request.tool_call["id"],
            )

        if self._queue_mode == QueueMode.INTERRUPT:
            # Interrupt: consume messages and raise signal
            pending = await self._queue_manager.consume_pending(self._session_key)
            logger.info(
                f"Interrupt triggered: aborting tool {request.tool_call.get('name')} "
                f"due to {len(pending)} pending message(s)"
            )
            raise InterruptSignalError(pending)

        # Fallback: execute normally (for FOLLOWUP and any future modes)
        return await handler(request)
