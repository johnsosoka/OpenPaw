"""Approval gate tool middleware for human-in-the-loop authorization."""

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware import wrap_tool_call

from openpaw.runtime.approval import ApprovalGateManager

logger = logging.getLogger(__name__)


class ApprovalRequiredError(Exception):
    """Raised when a tool call requires approval and must pause execution."""

    def __init__(self, approval_id: str, tool_name: str, tool_args: dict, tool_call_id: str):
        self.approval_id = approval_id
        self.tool_name = tool_name
        self.tool_args = tool_args
        self.tool_call_id = tool_call_id
        super().__init__(f"Approval required for {tool_name}")


class ApprovalToolMiddleware:
    """Middleware that intercepts tool calls requiring approval.

    When a gated tool is called:
    1. Creates a PendingApproval via ApprovalGateManager
    2. Raises ApprovalRequiredError to pause the agent run
    3. WorkspaceRunner catches the error, sends approval UI to user
    4. On approval: re-runs the agent (which will re-invoke the tool)
    5. On denial: sends denial message to user

    Designed for composition with QueueAwareToolMiddleware in the
    create_agent(middleware=[...]) list.
    """

    def __init__(self) -> None:
        self._manager: ApprovalGateManager | None = None
        self._session_key: str | None = None
        self._thread_id: str | None = None

    def set_context(
        self,
        manager: ApprovalGateManager,
        session_key: str,
        thread_id: str,
    ) -> None:
        """Configure approval context for current invocation."""
        self._manager = manager
        self._session_key = session_key
        self._thread_id = thread_id

    def reset(self) -> None:
        """Reset per-invocation state."""
        self._manager = None
        self._session_key = None
        self._thread_id = None

    def get_middleware(self) -> Any:
        """Return the @wrap_tool_call compatible middleware function."""
        middleware_instance = self

        @wrap_tool_call  # type: ignore[call-overload]
        async def approval_tool_wrapper(
            request: Any, handler: Callable[[Any], Awaitable[Any]]
        ) -> Any:
            return await middleware_instance._check_and_execute(request, handler)

        return approval_tool_wrapper

    async def _check_and_execute(
        self, request: Any, handler: Callable[[Any], Awaitable[Any]]
    ) -> Any:
        """Check if tool requires approval, otherwise execute normally."""
        # If no manager configured, execute normally
        if self._manager is None or self._session_key is None:
            return await handler(request)

        tool_name = request.tool_call.get("name", "")

        # Check if this tool requires approval
        if not self._manager.requires_approval(tool_name):
            return await handler(request)

        # Check if this tool was recently approved (bypass check after user approval)
        if self._manager.check_recent_approval(self._session_key, tool_name):
            logger.info(
                f"Tool {tool_name} has recent approval, executing without prompt"
            )
            result = await handler(request)
            # Clear the approval after successful execution
            self._manager.clear_recent_approval(self._session_key, tool_name)
            return result

        # Tool requires approval - create pending approval and raise
        tool_args = request.tool_call.get("args", {})
        approval = await self._manager.request_approval(
            tool_name=tool_name,
            tool_args=tool_args,
            session_key=self._session_key,
            thread_id=self._thread_id or "",
        )

        logger.info(f"Approval required: {tool_name} (approval_id={approval.id})")

        raise ApprovalRequiredError(
            approval_id=approval.id,
            tool_name=tool_name,
            tool_args=tool_args,
            tool_call_id=request.tool_call.get("id", ""),
        )
