"""Queue-aware tool middleware for steer and interrupt modes."""

import contextvars
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware import wrap_tool_call
from langchain_core.messages import ToolMessage

from openpaw.core.queue.lane import QueueMode
from openpaw.core.queue.manager import QueueManager

logger = logging.getLogger(__name__)

# Context variables for per-invocation state (multi-user safety)
_queue_manager_var: contextvars.ContextVar[QueueManager | None] = contextvars.ContextVar(
    "_queue_manager", default=None
)
_session_key_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "_queue_session_key", default=None
)
_queue_mode_var: contextvars.ContextVar[QueueMode] = contextvars.ContextVar(
    "_queue_mode", default=QueueMode.COLLECT
)
_pending_steer_message_var: contextvars.ContextVar[list[Any] | None] = contextvars.ContextVar(
    "_pending_steer_message", default=None
)
_steered_var: contextvars.ContextVar[bool] = contextvars.ContextVar("_steered", default=False)


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
    state is managed via contextvars for multi-user safety.
    """

    def __init__(self) -> None:
        """Initialize middleware. State is stored in contextvars, not instance attributes."""
        logger.debug("QueueAwareToolMiddleware initialized (using contextvars)")

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
        _queue_manager_var.set(queue_manager)
        _session_key_var.set(session_key)
        _queue_mode_var.set(queue_mode)
        _pending_steer_message_var.set(None)
        _steered_var.set(False)

    def reset(self) -> None:
        """Reset per-invocation state. Called after each agent run."""
        _queue_manager_var.set(None)
        _session_key_var.set(None)
        _queue_mode_var.set(QueueMode.COLLECT)
        _pending_steer_message_var.set(None)
        _steered_var.set(False)

    @property
    def pending_steer_message(self) -> list[Any] | None:
        """Get pending messages that caused a steer, if any."""
        return _pending_steer_message_var.get()

    @property
    def was_steered(self) -> bool:
        """Whether a steer occurred during the current invocation."""
        return _steered_var.get()

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
        # Read from contextvars
        queue_mode = _queue_mode_var.get()
        queue_manager = _queue_manager_var.get()
        session_key = _session_key_var.get()

        tool_name = request.tool_call.get("name", "unknown")
        logger.debug(
            f"Middleware intercepting tool '{tool_name}' "
            f"(mode={queue_mode.value}, session={session_key})"
        )

        # In collect mode or if no queue awareness set, just execute normally
        if (
            queue_mode == QueueMode.COLLECT
            or queue_manager is None
            or session_key is None
        ):
            logger.debug(f"Middleware pass-through: mode={queue_mode.value}")
            return await handler(request)

        # Check for pending messages
        has_pending = await queue_manager.peek_pending(session_key)
        logger.debug(f"Middleware peek_pending={has_pending} for session={session_key}")

        if not has_pending:
            # No pending messages, execute normally
            return await handler(request)

        if queue_mode == QueueMode.STEER:
            # Steer: skip tool, store pending messages for post-run consumption
            # Only consume messages once (on first tool skip)
            steered = _steered_var.get()
            if not steered:
                pending = await queue_manager.consume_pending(session_key)
                _pending_steer_message_var.set(pending)
                _steered_var.set(True)
                logger.info(
                    f"Steer triggered: skipping tool {request.tool_call.get('name')} "
                    f"due to {len(pending)} pending message(s)"
                )

            # Return a ToolMessage indicating the tool was skipped
            return ToolMessage(
                content="[Skipped: user sent new message — redirecting]",
                tool_call_id=request.tool_call["id"],
            )

        if queue_mode == QueueMode.INTERRUPT:
            # Interrupt: consume messages and raise signal
            pending = await queue_manager.consume_pending(session_key)
            logger.info(
                f"Interrupt triggered: aborting tool {request.tool_call.get('name')} "
                f"due to {len(pending)} pending message(s)"
            )
            raise InterruptSignalError(pending)

        # Fallback: execute normally (for FOLLOWUP and any future modes)
        return await handler(request)
