"""Tests for ApprovalGateHandler."""

import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from openpaw.agent.middleware import ApprovalRequiredError
from openpaw.workspace.processors.approval_handler import ApprovalGateHandler, ApprovalResult


@pytest.fixture
def mock_handler():
    manager = MagicMock()
    manager.get_tool_config.return_value = MagicMock(show_args=True)
    manager.wait_for_resolution = AsyncMock(return_value=True)
    return ApprovalGateHandler(
        approval_manager=manager,
        token_logger=MagicMock(),
        workspace_name="test",
        logger=logging.getLogger("test"),
    )


class TestApprovalResult:
    def test_retry_action(self):
        result = ApprovalResult(action="retry")
        assert result.action == "retry"
        assert result.combined_content is None

    def test_deny_action(self):
        result = ApprovalResult(action="deny", combined_content="denied")
        assert result.action == "deny"
        assert result.combined_content == "denied"

    def test_break_action(self):
        result = ApprovalResult(action="break")
        assert result.action == "break"


class TestHandle:
    @pytest.mark.asyncio
    async def test_no_channel_returns_break(self, mock_handler):
        result = await mock_handler.handle(
            error=ApprovalRequiredError("app_1", "tool", {}, "call_1"),
            channel=None,
            agent_runner=MagicMock(),
            thread_id="t1",
            session_key="s1",
        )
        assert result.action == "break"

    @pytest.mark.asyncio
    async def test_no_approval_manager_returns_break(self):
        handler = ApprovalGateHandler(
            approval_manager=None,
            token_logger=MagicMock(),
            workspace_name="test",
            logger=logging.getLogger("test"),
        )
        result = await handler.handle(
            error=ApprovalRequiredError("app_1", "tool", {}, "call_1"),
            channel=AsyncMock(),
            agent_runner=MagicMock(),
            thread_id="t1",
            session_key="s1",
        )
        assert result.action == "break"

    @pytest.mark.asyncio
    async def test_approved_returns_retry(self, mock_handler):
        channel = AsyncMock()
        result = await mock_handler.handle(
            error=ApprovalRequiredError("app_1", "tool", {}, "call_1"),
            channel=channel,
            agent_runner=MagicMock(),
            thread_id="t1",
            session_key="s1",
        )
        assert result.action == "retry"
        channel.send_approval_request.assert_called_once()

    @pytest.mark.asyncio
    async def test_denied_returns_deny(self, mock_handler):
        mock_handler._approval_manager.wait_for_resolution = AsyncMock(return_value=False)
        channel = AsyncMock()
        result = await mock_handler.handle(
            error=ApprovalRequiredError("app_1", "tool", {}, "call_1"),
            channel=channel,
            agent_runner=MagicMock(),
            thread_id="t1",
            session_key="s1",
        )
        assert result.action == "deny"
        assert result.combined_content is not None
        channel.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_log_partial_metrics(self, mock_handler):
        agent_runner = MagicMock()
        agent_runner.last_metrics = MagicMock()
        mock_handler.log_partial_metrics(agent_runner, "s1")
        mock_handler._token_logger.log.assert_called_once()

    @pytest.mark.asyncio
    async def test_log_partial_metrics_no_metrics(self, mock_handler):
        agent_runner = MagicMock()
        agent_runner.last_metrics = None
        mock_handler.log_partial_metrics(agent_runner, "s1")
        mock_handler._token_logger.log.assert_not_called()
