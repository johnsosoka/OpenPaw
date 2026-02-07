"""Agent self-continuation tool for multi-step autonomous workflows."""

import contextvars
import logging
from dataclasses import dataclass
from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from openpaw.builtins.base import (
    BaseBuiltinTool,
    BuiltinMetadata,
    BuiltinPrerequisite,
    BuiltinType,
)

logger = logging.getLogger(__name__)


@dataclass
class FollowupRequest:
    """Stored followup request from an agent invocation."""

    prompt: str
    delay_seconds: int


# Per-session context variables for thread-safe state isolation
_pending_followup: contextvars.ContextVar[FollowupRequest | None] = contextvars.ContextVar(
    '_pending_followup', default=None
)
_current_depth: contextvars.ContextVar[int] = contextvars.ContextVar(
    '_current_depth', default=0
)


class RequestFollowupInput(BaseModel):
    """Input schema for request_followup tool."""

    prompt: str = Field(
        description=(
            "Instructions for your next invocation. Be specific about what "
            "to do next, what to check, or what the next step is."
        )
    )
    delay_seconds: int = Field(
        default=0,
        description=(
            "Seconds to wait before re-invoking. 0 = immediately after "
            "current response is sent. Use delay for time-dependent checks."
        ),
        ge=0,
    )


class FollowupTool(BaseBuiltinTool):
    """Enables agents to request self-continuation after responding.

    After the agent sends its response, WorkspaceRunner checks for pending
    followup. If set, it re-invokes the agent with the followup prompt,
    preserving session/thread for conversation continuity.

    This enables multi-step autonomous workflows where the agent can
    chain actions without requiring user intervention.
    """

    metadata = BuiltinMetadata(
        name="followup",
        display_name="Request Followup",
        description="Request self-continuation after current response",
        builtin_type=BuiltinType.TOOL,
        group="automation",
        prerequisites=BuiltinPrerequisite(),
    )

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(config)
        self._max_chain_depth = self.config.get("max_chain_depth", 5)

    def get_pending_followup(self) -> FollowupRequest | None:
        """Get and clear the pending followup request.

        Called by WorkspaceRunner after each agent invocation.

        Returns:
            FollowupRequest if one was set, None otherwise.
        """
        followup = _pending_followup.get()
        _pending_followup.set(None)
        return followup

    def set_chain_depth(self, depth: int) -> None:
        """Set current followup chain depth (0 = original invocation)."""
        _current_depth.set(depth)

    def reset(self) -> None:
        """Reset tool state between sessions."""
        _pending_followup.set(None)
        _current_depth.set(0)

    def get_langchain_tool(self) -> Any:
        """Return the request_followup LangChain tool."""
        tool_instance = self

        def request_followup(prompt: str, delay_seconds: int = 0) -> str:
            """Request to continue working after your current response is sent.

            Call this when you need to:
            - Continue a multi-step task
            - Check back on something after a delay
            - Process results that aren't ready yet
            - Chain multiple autonomous actions

            After your response is delivered, you will be re-invoked with the
            prompt you provide. Your conversation history is preserved.

            Args:
                prompt: Instructions for your next invocation.
                delay_seconds: Wait time before re-invoking (0 = immediate).

            Returns:
                Confirmation message.
            """
            current_depth = _current_depth.get()
            pending = _pending_followup.get()

            if current_depth >= tool_instance._max_chain_depth:
                return (
                    f"Error: Maximum followup chain depth reached "
                    f"({tool_instance._max_chain_depth}). "
                    f"Use schedule_at for delayed actions instead."
                )

            if pending is not None:
                return (
                    "Error: A followup is already pending for this invocation. "
                    "Only one followup per response is allowed."
                )

            followup_request = FollowupRequest(
                prompt=prompt,
                delay_seconds=delay_seconds,
            )
            _pending_followup.set(followup_request)

            logger.info(
                f"Followup requested (depth={current_depth}, "
                f"delay={delay_seconds}s): {prompt[:100]}"
            )

            if delay_seconds == 0:
                return (
                    "Followup scheduled. After your current response is sent, "
                    "you will be immediately re-invoked with this prompt. "
                    "Finish your current response to the user first."
                )
            else:
                return (
                    f"Followup scheduled for {delay_seconds} seconds from now. "
                    f"After the delay, you will be re-invoked with this prompt."
                )

        return StructuredTool.from_function(
            func=request_followup,
            name="request_followup",
            description=(
                "Request to continue working after your current response is sent. "
                "Use for multi-step autonomous workflows. After your response is "
                "delivered, you'll be re-invoked with the prompt you provide. "
                "Your conversation context is preserved. "
                f"Max chain depth: {tool_instance._max_chain_depth}."
            ),
            args_schema=RequestFollowupInput,
        )
