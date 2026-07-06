"""Approval gate handling for the message processing loop."""

import logging
from dataclasses import dataclass
from typing import Any, Literal

from openpaw.agent.harness import AgentHarness
from openpaw.agent.middleware import ApprovalRequiredError
from openpaw.channels.base import ChannelAdapter
from openpaw.core.prompts.system_events import TOOL_DENIED_TEMPLATE
from openpaw.runtime.approval import ApprovalGateManager


@dataclass(frozen=True)
class ApprovalResult:
    """Result of handling an approval-required error.

    Attributes:
        action: What the caller should do next.
            - "retry": Continue the loop with the same message.
            - "deny": Continue the loop with the denial message.
            - "break": Exit the loop.
        combined_content: When action is "deny", the new message content to use.
    """

    action: Literal["retry", "deny", "break"]
    combined_content: str | None = None


class ApprovalGateHandler:
    """Encapsulates the approval-request flow inside the message loop.

    Handles sending approval requests, waiting for user resolution, and
    preparing the loop for the appropriate continuation (retry, deny, or break).
    """

    def __init__(
        self,
        approval_manager: ApprovalGateManager | None,
        token_logger: Any,
        workspace_name: str,
        logger: logging.Logger,
    ) -> None:
        """Initialize the handler.

        Args:
            approval_manager: The approval gate manager instance.
            token_logger: Token usage logger for partial metrics.
            workspace_name: Name of the workspace for metric logging.
            logger: Logger instance.
        """
        self._approval_manager = approval_manager
        self._token_logger = token_logger
        self._workspace_name = workspace_name
        self._logger = logger

    def log_partial_metrics(self, agent_runner: AgentHarness, session_key: str) -> None:
        """Log any partial metrics available from an interrupted run.

        Args:
            agent_runner: The agent runner that may have partial metrics.
            session_key: The session identifier for the log entry.
        """
        metrics = agent_runner.last_metrics
        if metrics:
            self._token_logger.log(
                metrics=metrics,
                workspace=self._workspace_name,
                invocation_type="user",
                session_key=session_key,
            )

    async def handle(
        self,
        error: ApprovalRequiredError,
        channel: ChannelAdapter | None,
        agent_runner: AgentHarness,
        thread_id: str,
        session_key: str,
    ) -> ApprovalResult:
        """Handle an approval-required error.

        Args:
            error: The approval-required error.
            channel: Channel adapter for sending approval UI.
            agent_runner: The agent runner for resolving orphaned tool calls.
            thread_id: The current conversation thread ID.
            session_key: The session identifier.

        Returns:
            ApprovalResult instructing the loop what to do next.
        """
        if not channel or not self._approval_manager:
            return ApprovalResult(action="break")

        tool_config = self._approval_manager.get_tool_config(error.tool_name)
        show_args = tool_config.show_args if tool_config else True

        try:
            await channel.send_approval_request(
                session_key=session_key,
                approval_id=error.approval_id,
                tool_name=error.tool_name,
                tool_args=error.tool_args,
                show_args=show_args,
            )
        except Exception as send_err:
            self._logger.error(
                f"Failed to send approval request for {error.tool_name}: {send_err}",
                exc_info=True,
            )
            return ApprovalResult(action="break")

        approved = await self._approval_manager.wait_for_resolution(error.approval_id)

        if approved:
            self._logger.info(f"Tool {error.tool_name} approved, resuming")
            await self._resolve_orphaned(agent_runner, thread_id, error, approved=True)
            return ApprovalResult(action="retry")

        self._logger.info(f"Tool {error.tool_name} denied")
        await self._resolve_orphaned(agent_runner, thread_id, error, approved=False)
        try:
            await channel.send_message(
                session_key,
                f"Tool '{error.tool_name}' was denied. The agent will be informed.",
            )
        except Exception as send_err:
            self._logger.warning(
                f"Failed to send denial notification for {error.tool_name}: {send_err}"
            )
        return ApprovalResult(
            action="deny",
            combined_content=TOOL_DENIED_TEMPLATE.format(tool_name=error.tool_name),
        )

    async def _resolve_orphaned(
        self,
        agent_runner: AgentHarness,
        thread_id: str,
        error: ApprovalRequiredError,
        approved: bool,
    ) -> None:
        """Resolve orphaned tool calls after an approval decision.

        Args:
            agent_runner: The agent runner.
            thread_id: The conversation thread ID.
            error: The original approval error.
            approved: True if approved, False if denied.
        """
        try:
            if approved:
                response = f"Tool '{error.tool_name}' was approved. Please call it again."
            else:
                response = f"Tool '{error.tool_name}' was denied by user."
            await agent_runner.resolve_orphaned_tool_calls(
                thread_id,
                responses={error.tool_call_id: response},
            )
        except Exception as resolve_err:
            self._logger.error(
                f"Failed to resolve orphaned tool calls: {resolve_err}",
                exc_info=True,
            )
