"""Queue check middleware that fires before each model call."""

import logging
from typing import Any

from langchain.agents import AgentState
from langchain.agents.middleware import before_model

from openpaw.agent.middleware.queue_aware import (
    InterruptSignalError,
    _queue_manager_var,
    _queue_mode_var,
    _session_key_var,
    _steer_state_var,
)
from openpaw.core.queue.lane import QueueMode

logger = logging.getLogger(__name__)


async def _queue_check_logic(state: AgentState, runtime: Any) -> dict[str, Any] | None:
    """Core logic for queue checking before model calls.

    Extracted into a separate function for testability.

    Args:
        state: Current agent state (unused).
        runtime: Runtime context (unused).

    Returns:
        None if execution should continue normally.
        {"jump_to": "end"} in steer mode to skip remaining model calls.

    Raises:
        InterruptSignalError: When interrupt mode detects pending messages.
    """
    # Read from contextvars (shared with queue_aware.py)
    queue_mode = _queue_mode_var.get()
    queue_manager = _queue_manager_var.get()
    session_key = _session_key_var.get()

    logger.debug(
        f"Queue check before model call (mode={queue_mode.value}, session={session_key})"
    )

    # In collect mode or if no queue awareness set, no-op
    if queue_mode == QueueMode.COLLECT or queue_manager is None or session_key is None:
        logger.debug(f"Queue check pass-through: mode={queue_mode.value}")
        return None

    steer_state = _steer_state_var.get()

    # If already steered, terminate immediately — don't let the LLM
    # generate more tool calls. The steer redirect happens post-run.
    if steer_state and steer_state.steered:
        logger.debug("Already steered, jumping to end")
        return {"jump_to": "end"}

    # Check for pending messages
    has_pending = await queue_manager.peek_pending(session_key)
    logger.debug(f"Queue check peek_pending={has_pending} for session={session_key}")

    if not has_pending:
        # No pending messages, continue normally
        return None

    if queue_mode == QueueMode.STEER:
        # Steer: consume pending messages and jump to end
        pending = await queue_manager.consume_pending(session_key)
        # Mutate the shared object — visible across copy_context() boundary
        if steer_state:
            steer_state.pending_messages = pending
            steer_state.steered = True
        logger.info(
            f"Steer triggered (before model): jumping to end "
            f"due to {len(pending)} pending message(s)"
        )
        return {"jump_to": "end"}

    if queue_mode == QueueMode.INTERRUPT:
        # Interrupt: consume messages and raise signal
        pending = await queue_manager.consume_pending(session_key)
        logger.info(
            f"Interrupt triggered (before model): aborting "
            f"due to {len(pending)} pending message(s)"
        )
        raise InterruptSignalError(pending)

    # Fallback: continue normally (for FOLLOWUP and any future modes)
    return None


@before_model(can_jump_to=["end"])
async def queue_check_before_model(state: AgentState, runtime: Any) -> dict[str, Any] | None:
    """Check queue for pending messages before each LLM model call.

    This middleware complements the @wrap_tool_call middleware by checking
    for pending messages at LLM boundaries, not just tool boundaries. This
    closes the blind spot where long model calls could miss user interruptions.

    Args:
        state: Current agent state.
        runtime: Runtime context (unused).

    Returns:
        None if execution should continue normally.
        {"jump_to": "end"} in steer mode to skip remaining model calls.

    Raises:
        InterruptSignalError: When interrupt mode detects pending messages.
    """
    return await _queue_check_logic(state, runtime)


def get_queue_check_middleware() -> Any:
    """Return the @before_model middleware instance.

    Returns:
        AgentMiddleware instance produced by the @before_model decorator.
    """
    return queue_check_before_model
