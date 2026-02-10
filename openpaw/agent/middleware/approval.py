"""Approval gate tool middleware for human-in-the-loop authorization."""

import contextvars
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware import wrap_tool_call

from openpaw.stores.approval import ApprovalGateManager

logger = logging.getLogger(__name__)

# Context variables for per-invocation state (multi-user safety)
_approval_manager_var: contextvars.ContextVar[ApprovalGateManager | None] = contextvars.ContextVar(
    "_approval_manager", default=None
)
_approval_session_key_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "_approval_session_key", default=None
)
_approval_thread_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "_approval_thread_id", default=None
)


class ApprovalRequiredError(Exception):
    """Raised when a tool call requires approval and must pause execution."""

    def __init__(self, approval_id: str, tool_name: str, tool_args: dict):
        self.approval_id = approval_id
        self.tool_name = tool_name
        self.tool_args = tool_args
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
    create_agent(middleware=[...]) list. State stored in contextvars for multi-user safety.
    """

    def __init__(self) -> None:
        """Initialize middleware. State is stored in contextvars, not instance attributes."""
        logger.debug("ApprovalToolMiddleware initialized (using contextvars)")

    def set_context(
        self,
        manager: ApprovalGateManager,
        session_key: str,
        thread_id: str,
    ) -> None:
        """Configure approval context for current invocation."""
        _approval_manager_var.set(manager)
        _approval_session_key_var.set(session_key)
        _approval_thread_id_var.set(thread_id)

    def reset(self) -> None:
        """Reset per-invocation state."""
        _approval_manager_var.set(None)
        _approval_session_key_var.set(None)
        _approval_thread_id_var.set(None)

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
        # Read from contextvars
        manager = _approval_manager_var.get()
        session_key = _approval_session_key_var.get()
        thread_id = _approval_thread_id_var.get()

        # If no manager configured, execute normally
        if manager is None or session_key is None:
            return await handler(request)

        tool_name = request.tool_call.get("name", "")

        # Check if this tool requires approval
        if not manager.requires_approval(tool_name):
            return await handler(request)

        # Check if this tool was recently approved (bypass check after user approval)
        if manager.check_recent_approval(session_key, tool_name):
            logger.info(
                f"Tool {tool_name} has recent approval, executing without prompt"
            )
            result = await handler(request)
            # Clear the approval after successful execution
            manager.clear_recent_approval(session_key, tool_name)
            return result

        # Tool requires approval - create pending approval and raise
        tool_args = request.tool_call.get("args", {})
        approval = await manager.request_approval(
            tool_name=tool_name,
            tool_args=tool_args,
            session_key=session_key,
            thread_id=thread_id or "",
        )

        logger.info(f"Approval required: {tool_name} (approval_id={approval.id})")

        raise ApprovalRequiredError(
            approval_id=approval.id,
            tool_name=tool_name,
            tool_args=tool_args,
        )
