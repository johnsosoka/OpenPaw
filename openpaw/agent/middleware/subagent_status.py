"""Per-sub-agent tool-event middleware.

Fires a status callback on every tool invocation inside a sub-agent's runner
so the parent's StatusUpdateMiddleware can edit the sub-agent's status message
in real time.
"""

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware.types import AgentMiddleware

from openpaw.agent.middleware.status_update import _resolve_emoji

logger = logging.getLogger(__name__)

# Signature: (subagent_id, event, text, emoji) -> None
StatusCallbackT = Callable[[str, str, str, str | None], Awaitable[None]]


class SubAgentToolMiddleware(AgentMiddleware):
    """Minimal middleware that fires a status callback on each tool invocation.

    Attached to a sub-agent's AgentRunner before _build_agent() so that
    tool-start events are forwarded to the parent WorkspaceRunner's
    StatusUpdateMiddleware.
    """

    def __init__(self, subagent_id: str, callback: StatusCallbackT) -> None:
        """Initialize the middleware.

        Args:
            subagent_id: Unique identifier of the sub-agent request.
            callback: Async callable invoked on each tool start.
        """
        self._subagent_id = subagent_id
        self._callback = callback

    async def awrap_tool_call(self, request: Any, handler: Any) -> Any:
        """Fire the status callback before delegating to the next handler.

        Args:
            request: ToolCallRequest with tool_call dict.
            handler: Async callable that executes the tool.

        Returns:
            Tool result from the handler.
        """
        tool_name = request.tool_call.get("name", "unknown")
        emoji = _resolve_emoji([tool_name])
        try:
            await self._callback(
                self._subagent_id,
                "tool",
                f"Running tool: {tool_name}...",
                emoji,
            )
        except Exception as e:
            logger.debug("SubAgentToolMiddleware callback error: %s", e)
        return await handler(request)
