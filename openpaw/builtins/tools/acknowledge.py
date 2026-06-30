"""Silent acknowledgment tool for system events."""

import logging
import threading
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
class AcknowledgeRequest:
    """Stored acknowledgment from an agent invocation."""

    reason: str


class AcknowledgeEventInput(BaseModel):
    """Input schema for acknowledge_event tool."""

    reason: str = Field(
        description=(
            "Brief explanation of why no user-facing response is needed. "
            "This is logged for audit purposes."
        )
    )


class AcknowledgeTool(BaseBuiltinTool):
    """Provides an optional audit signal for [SYSTEM]-event processing.

    In the main-agent path, terminal responses to [SYSTEM] events (cron result,
    heartbeat injection, sub-agent completion) are suppressed automatically —
    calling this tool is NOT required for silence. Its only effect in the main-agent
    path is to attach an audit note to the suppress log line.

    On the heartbeat executor path, this tool still gates the heartbeat's own
    channel delivery — the heartbeat executor reads get_pending_ack() to decide
    whether to send the heartbeat result to the channel.

    Uses instance attribute instead of contextvars because LangGraph's astream()
    executes tools in child asyncio.Tasks whose contextvar writes are not visible
    to the parent coroutine.
    """

    metadata = BuiltinMetadata(
        name="acknowledge",
        display_name="Acknowledge Event",
        description="Audit-log acknowledgment for system events (delivery suppressed automatically in main-agent path)",
        builtin_type=BuiltinType.TOOL,
        group="automation",
        prerequisites=BuiltinPrerequisite(),  # Always available, no API keys needed
    )

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(config)
        self._pending_ack: AcknowledgeRequest | None = None
        self._lock = threading.Lock()

    def get_pending_ack(self) -> AcknowledgeRequest | None:
        """Get and clear the pending acknowledgment.

        Called by MessageProcessor after each agent invocation.

        Returns:
            AcknowledgeRequest if one was set, None otherwise.
        """
        with self._lock:
            ack = self._pending_ack
            self._pending_ack = None
            return ack

    def reset(self) -> None:
        """Reset tool state between sessions."""
        with self._lock:
            self._pending_ack = None

    def get_langchain_tool(self) -> Any:
        """Return the acknowledge_event LangChain tool."""
        tool_instance = self

        def acknowledge_event(reason: str) -> str:
            """Optionally record that a [SYSTEM] event was reviewed and needs no user-facing action.

            In the main-agent path, terminal responses to system events are suppressed
            automatically — you do NOT need to call this to stay silent. If you call it,
            the reason is logged as an audit note alongside the suppression log line.

            To surface something for the user, use send_message instead.

            On the heartbeat path only, this tool still gates the heartbeat's own
            channel delivery.

            Args:
                reason: Brief explanation of why no user-facing response is needed.
                        This is logged for audit purposes.

            Returns:
                Confirmation message.
            """
            with tool_instance._lock:
                if tool_instance._pending_ack is not None:
                    return (
                        "An acknowledgment is already pending for this invocation. "
                        "Only one acknowledge_event per response is allowed."
                    )

                tool_instance._pending_ack = AcknowledgeRequest(reason=reason)

            logger.info(f"System event acknowledged: {reason[:200]}")

            return (
                "Event acknowledged. Your response will NOT be sent to the user. "
                "You may still include notes in your response for conversation "
                "history — they will be recorded but not delivered."
            )

        return StructuredTool.from_function(
            func=acknowledge_event,
            name="acknowledge_event",
            description=(
                "Optionally record that a [SYSTEM] event (cron result, heartbeat, "
                "sub-agent completion) was reviewed and needs no user-facing action. "
                "In the main agent path, terminal responses to system events are "
                "suppressed automatically — this tool adds an audit note only. "
                "Use send_message to surface anything the user must see. "
                "(On the heartbeat path this still gates the heartbeat's own delivery.)"
            ),
            args_schema=AcknowledgeEventInput,
        )
