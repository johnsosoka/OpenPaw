"""Per-tool-call timeout middleware to prevent budget exhaustion."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware import wrap_tool_call
from langchain_core.messages import ToolMessage

from openpaw.core.config.models import ToolTimeoutsConfig

logger = logging.getLogger(__name__)


class ToolTimeoutMiddleware:
    """Middleware that wraps tool calls with asyncio.timeout().

    Prevents any single tool from consuming the entire agent run budget.
    Uses per-tool overrides if configured, otherwise applies default timeout.

    Designed to be the first middleware in the chain (timeout → queue → approval).
    """

    def __init__(self, config: ToolTimeoutsConfig) -> None:
        """Initialize with timeout configuration.

        Args:
            config: ToolTimeoutsConfig with default_seconds and overrides dict.
        """
        self._config = config

    def _get_timeout(self, tool_name: str) -> int:
        """Get timeout for a specific tool.

        Args:
            tool_name: Name of the tool being executed.

        Returns:
            Timeout in seconds (checks overrides first, then default).
        """
        return self._config.overrides.get(tool_name, self._config.default_seconds)

    def get_middleware(self) -> Any:
        """Return the @wrap_tool_call compatible middleware function.

        Returns:
            Middleware function decorated with @wrap_tool_call.
        """
        middleware_instance = self

        @wrap_tool_call  # type: ignore[call-overload]
        async def tool_timeout_wrapper(
            request: Any, handler: Callable[[Any], Awaitable[Any]]
        ) -> Any:
            """Middleware that wraps tool execution with asyncio.timeout()."""
            return await middleware_instance._execute_with_timeout(request, handler)

        return tool_timeout_wrapper

    async def _execute_with_timeout(
        self, request: Any, handler: Callable[[Any], Awaitable[Any]]
    ) -> Any:
        """Execute tool with timeout, return ToolMessage if timeout fires.

        Args:
            request: ToolCallRequest with tool_call (name, args, id).
            handler: Async function to execute the tool.

        Returns:
            Tool result or ToolMessage with timeout notification.
        """
        tool_name = request.tool_call.get("name", "unknown")
        timeout_seconds = self._get_timeout(tool_name)

        logger.debug(
            f"Executing tool '{tool_name}' with {timeout_seconds}s timeout"
        )

        try:
            async with asyncio.timeout(timeout_seconds):
                return await handler(request)
        except TimeoutError:
            logger.warning(
                f"Tool '{tool_name}' timed out after {timeout_seconds}s"
            )
            return ToolMessage(
                content=(
                    f"[Tool '{tool_name}' timed out after {timeout_seconds}s. "
                    "Try a different approach or break the operation into smaller steps.]"
                ),
                tool_call_id=request.tool_call["id"],
            )
