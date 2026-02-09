"""Approval gate manager for human-in-the-loop tool authorization."""

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from openpaw.core.config.approval import ApprovalGatesConfig, ToolApprovalConfig

logger = logging.getLogger(__name__)


@dataclass
class PendingApproval:
    """Represents a tool call awaiting user approval."""

    id: str
    tool_name: str
    tool_args: dict[str, Any]
    session_key: str
    thread_id: str
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    resolved: bool = False
    approved: bool | None = None
    _event: asyncio.Event = field(default_factory=asyncio.Event, repr=False)


class ApprovalGateManager:
    """Manages pending approval requests and their resolution.

    Lifecycle:
    1. Middleware detects gated tool call → creates PendingApproval
    2. Channel sends approval request to user (inline keyboard)
    3. User approves/denies → resolve() called
    4. Middleware either executes tool or returns denial
    5. Timeout triggers default action if user doesn't respond
    """

    def __init__(self, config: ApprovalGatesConfig) -> None:
        self._config = config
        self._pending: dict[str, PendingApproval] = {}
        self._timeout_tasks: dict[str, asyncio.Task[None]] = {}

    def requires_approval(self, tool_name: str) -> bool:
        """Check if a tool requires approval."""
        if not self._config.enabled:
            return False
        tool_config = self._config.tools.get(tool_name)
        if tool_config is None:
            return False
        return tool_config.require_approval

    def get_tool_config(self, tool_name: str) -> ToolApprovalConfig | None:
        """Get approval config for a specific tool."""
        return self._config.tools.get(tool_name)

    async def request_approval(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        session_key: str,
        thread_id: str,
    ) -> PendingApproval:
        """Create a pending approval request."""
        approval = PendingApproval(
            id=str(uuid.uuid4())[:8],
            tool_name=tool_name,
            tool_args=tool_args,
            session_key=session_key,
            thread_id=thread_id,
        )
        self._pending[approval.id] = approval

        # Start timeout task
        timeout_task = asyncio.create_task(self._timeout_handler(approval.id))
        self._timeout_tasks[approval.id] = timeout_task

        return approval

    async def wait_for_resolution(self, approval_id: str) -> bool:
        """Wait for an approval to be resolved. Returns True if approved."""
        approval = self._pending.get(approval_id)
        if not approval:
            return False
        await approval._event.wait()
        return approval.approved or False

    def resolve(self, approval_id: str, approved: bool) -> bool:
        """Resolve a pending approval."""
        approval = self._pending.get(approval_id)
        if not approval or approval.resolved:
            return False

        approval.resolved = True
        approval.approved = approved
        approval._event.set()

        # Cancel timeout
        timeout_task = self._timeout_tasks.pop(approval_id, None)
        if timeout_task and not timeout_task.done():
            timeout_task.cancel()

        # Clean up denied entries immediately (approved entries stay
        # until clear_recent_approval() is called after tool execution)
        if not approved:
            del self._pending[approval_id]

        return True

    async def _timeout_handler(self, approval_id: str) -> None:
        """Auto-resolve after timeout."""
        try:
            await asyncio.sleep(self._config.timeout_seconds)
            approval = self._pending.get(approval_id)
            if approval and not approval.resolved:
                default_approved = self._config.default_action == "approve"
                self.resolve(approval_id, default_approved)
                logger.info(
                    f"Approval {approval_id} timed out, "
                    f"applied default: {self._config.default_action}"
                )
        except asyncio.CancelledError:
            pass

    def get_pending(
        self, session_key: str | None = None
    ) -> list[PendingApproval]:
        """Get pending approvals, optionally filtered by session."""
        pending = [a for a in self._pending.values() if not a.resolved]
        if session_key:
            pending = [a for a in pending if a.session_key == session_key]
        return pending

    def check_recent_approval(
        self, session_key: str, tool_name: str
    ) -> bool:
        """Check if a tool was recently approved for this session.

        Used to bypass approval check after user approves during re-run.
        Returns True if there's a resolved+approved entry for this tool/session.
        """
        for approval in self._pending.values():
            if (
                approval.session_key == session_key
                and approval.tool_name == tool_name
                and approval.resolved
                and approval.approved
            ):
                return True
        return False

    def clear_recent_approval(self, session_key: str, tool_name: str) -> None:
        """Clear a recent approval after tool execution completes."""
        to_remove = []
        for approval_id, approval in self._pending.items():
            if (
                approval.session_key == session_key
                and approval.tool_name == tool_name
                and approval.resolved
                and approval.approved
            ):
                to_remove.append(approval_id)
        for approval_id in to_remove:
            del self._pending[approval_id]

    async def cleanup(self) -> None:
        """Clean up resolved approvals and cancel timeouts."""
        # Cancel all timeout tasks
        for task in self._timeout_tasks.values():
            if not task.done():
                task.cancel()
        # Await cancellation to avoid lingering tasks
        if self._timeout_tasks:
            await asyncio.gather(*self._timeout_tasks.values(), return_exceptions=True)
        self._timeout_tasks.clear()

        # Remove resolved approvals
        self._pending = {
            k: v for k, v in self._pending.items() if not v.resolved
        }
