"""Tests for approval gates functionality."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from openpaw.core.config.models import ApprovalGatesConfig, ToolApprovalConfig
from openpaw.runtime.approval import ApprovalGateManager
from openpaw.agent.middleware.approval import ApprovalRequiredError, ApprovalToolMiddleware
from openpaw.agent.runner import AgentRunner


class TestApprovalConfig:
    """Test approval configuration models."""

    def test_approval_config_defaults(self):
        """ApprovalGatesConfig has correct defaults."""
        config = ApprovalGatesConfig()
        assert config.enabled is False
        assert config.default_action == "deny"
        assert config.timeout_seconds == 120
        assert config.tools == {}

    def test_tool_approval_config(self):
        """ToolApprovalConfig has correct defaults."""
        config = ToolApprovalConfig(require_approval=True)
        assert config.require_approval is True
        assert config.show_args is True


class TestApprovalGateManager:
    """Test approval gate manager."""

    def test_requires_approval(self):
        """Manager correctly identifies tools requiring approval."""
        config = ApprovalGatesConfig(
            enabled=True,
            tools={
                "dangerous_tool": ToolApprovalConfig(require_approval=True),
                "safe_tool": ToolApprovalConfig(require_approval=False),
            },
        )
        manager = ApprovalGateManager(config)

        assert manager.requires_approval("dangerous_tool") is True
        assert manager.requires_approval("safe_tool") is False
        assert manager.requires_approval("unknown_tool") is False

    def test_disabled_config(self):
        """Disabled approval gates don't require approval."""
        config = ApprovalGatesConfig(
            enabled=False,
            tools={"tool": ToolApprovalConfig(require_approval=True)},
        )
        manager = ApprovalGateManager(config)
        assert manager.requires_approval("tool") is False

    async def test_request_and_resolve_approval(self):
        """Full approve flow works correctly."""
        config = ApprovalGatesConfig(enabled=True)
        manager = ApprovalGateManager(config)

        # Request approval
        approval = await manager.request_approval(
            tool_name="test_tool",
            tool_args={"arg1": "value1"},
            session_key="test:123",
            thread_id="thread_1",
        )

        assert approval.tool_name == "test_tool"
        assert approval.session_key == "test:123"
        assert approval.resolved is False

        # Resolve approval
        success = manager.resolve(approval.id, approved=True)
        assert success is True

        # Check resolution
        resolved_approval = manager._pending[approval.id]
        assert resolved_approval.resolved is True
        assert resolved_approval.approved is True

    async def test_request_and_deny_approval(self):
        """Full deny flow works correctly."""
        config = ApprovalGatesConfig(enabled=True)
        manager = ApprovalGateManager(config)

        approval = await manager.request_approval(
            tool_name="test_tool",
            tool_args={},
            session_key="test:123",
            thread_id="thread_1",
        )

        success = manager.resolve(approval.id, approved=False)
        assert success is True

        # Denied entries are cleaned up immediately
        assert approval.id not in manager._pending
        assert approval.approved is False

    async def test_approval_timeout_default_deny(self):
        """Timeout applies default_action=deny."""
        config = ApprovalGatesConfig(
            enabled=True, timeout_seconds=1, default_action="deny"
        )
        manager = ApprovalGateManager(config)

        approval = await manager.request_approval(
            tool_name="test_tool",
            tool_args={},
            session_key="test:123",
            thread_id="thread_1",
        )

        # Wait for timeout
        await asyncio.sleep(1.2)

        # Denied entries (including timed-out denials) are cleaned up immediately
        assert approval.id not in manager._pending
        assert approval.resolved is True
        assert approval.approved is False

    async def test_approval_timeout_default_approve(self):
        """Timeout applies default_action=approve."""
        config = ApprovalGatesConfig(
            enabled=True, timeout_seconds=1, default_action="approve"
        )
        manager = ApprovalGateManager(config)

        approval = await manager.request_approval(
            tool_name="test_tool",
            tool_args={},
            session_key="test:123",
            thread_id="thread_1",
        )

        # Wait for timeout
        await asyncio.sleep(1.2)

        resolved_approval = manager._pending[approval.id]
        assert resolved_approval.resolved is True
        assert resolved_approval.approved is True

    async def test_wait_for_resolution(self):
        """wait_for_resolution blocks until approval is resolved."""
        config = ApprovalGatesConfig(enabled=True)
        manager = ApprovalGateManager(config)

        approval = await manager.request_approval(
            tool_name="test_tool",
            tool_args={},
            session_key="test:123",
            thread_id="thread_1",
        )

        async def resolve_after_delay():
            await asyncio.sleep(0.05)
            manager.resolve(approval.id, approved=True)

        # Start resolution task
        asyncio.create_task(resolve_after_delay())

        # Wait should block until resolved
        result = await manager.wait_for_resolution(approval.id)
        assert result is True

    async def test_multiple_pending_approvals(self):
        """Multiple approvals tracked independently."""
        config = ApprovalGatesConfig(enabled=True)
        manager = ApprovalGateManager(config)

        approval1 = await manager.request_approval(
            "tool1", {}, "session1", "thread1"
        )
        approval2 = await manager.request_approval(
            "tool2", {}, "session2", "thread2"
        )

        pending = manager.get_pending()
        assert len(pending) == 2

        # Resolve one
        manager.resolve(approval1.id, approved=True)

        pending = manager.get_pending()
        assert len(pending) == 1
        assert pending[0].id == approval2.id

    async def test_cleanup(self):
        """cleanup cancels timeouts and clears resolved approvals."""
        config = ApprovalGatesConfig(enabled=True, timeout_seconds=10)
        manager = ApprovalGateManager(config)

        # Create approval (starts timeout task)
        await manager.request_approval("tool1", {}, "session1", "thread1")

        # Cleanup should cancel timeout tasks
        await manager.cleanup()
        assert len(manager._timeout_tasks) == 0

    async def test_check_recent_approval(self):
        """check_recent_approval finds resolved+approved entries."""
        config = ApprovalGatesConfig(enabled=True)
        manager = ApprovalGateManager(config)

        approval = await manager.request_approval(
            "test_tool", {}, "session:123", "thread1"
        )

        # Not approved yet
        assert (
            manager.check_recent_approval("session:123", "test_tool") is False
        )

        # Approve it
        manager.resolve(approval.id, approved=True)

        # Now should find it
        assert (
            manager.check_recent_approval("session:123", "test_tool") is True
        )

    async def test_clear_recent_approval(self):
        """clear_recent_approval removes approved entries."""
        config = ApprovalGatesConfig(enabled=True)
        manager = ApprovalGateManager(config)

        approval = await manager.request_approval(
            "test_tool", {}, "session:123", "thread1"
        )
        manager.resolve(approval.id, approved=True)

        assert (
            manager.check_recent_approval("session:123", "test_tool") is True
        )

        manager.clear_recent_approval("session:123", "test_tool")

        assert (
            manager.check_recent_approval("session:123", "test_tool") is False
        )


class TestApprovalToolMiddleware:
    """Test approval tool middleware."""

    async def test_middleware_no_manager_executes_normally(self):
        """When no manager set, tools run normally."""
        middleware = ApprovalToolMiddleware()

        # Create mock request and handler
        mock_request = MagicMock()
        mock_request.tool_call = {"name": "test_tool", "args": {}}
        mock_handler = AsyncMock(return_value="tool_result")

        # Should execute normally (no manager set)
        result = await middleware._check_and_execute(mock_request, mock_handler)
        assert result == "tool_result"
        mock_handler.assert_called_once()

    async def test_middleware_ungated_tool_executes(self):
        """Tool not in config runs normally."""
        config = ApprovalGatesConfig(
            enabled=True,
            tools={"dangerous_tool": ToolApprovalConfig(require_approval=True)},
        )
        manager = ApprovalGateManager(config)

        middleware = ApprovalToolMiddleware()
        middleware.set_context(manager, "session:123", "thread1")

        mock_request = MagicMock()
        mock_request.tool_call = {"name": "safe_tool", "args": {}}
        mock_handler = AsyncMock(return_value="tool_result")

        result = await middleware._check_and_execute(mock_request, mock_handler)
        assert result == "tool_result"
        mock_handler.assert_called_once()

    async def test_middleware_gated_tool_raises(self):
        """Gated tool raises ApprovalRequiredError."""
        config = ApprovalGatesConfig(
            enabled=True,
            tools={"dangerous_tool": ToolApprovalConfig(require_approval=True)},
        )
        manager = ApprovalGateManager(config)

        middleware = ApprovalToolMiddleware()
        middleware.set_context(manager, "session:123", "thread1")

        mock_request = MagicMock()
        mock_request.tool_call = {"name": "dangerous_tool", "args": {"arg": "value"}, "id": "call_abc123"}
        mock_handler = AsyncMock()

        with pytest.raises(ApprovalRequiredError) as exc_info:
            await middleware._check_and_execute(mock_request, mock_handler)

        assert exc_info.value.tool_name == "dangerous_tool"
        assert exc_info.value.tool_args == {"arg": "value"}
        assert len(exc_info.value.approval_id) > 0
        assert exc_info.value.tool_call_id == "call_abc123"

        # Handler should NOT have been called
        mock_handler.assert_not_called()

    async def test_middleware_recent_approval_bypass(self):
        """Tool with recent approval executes without prompt."""
        config = ApprovalGatesConfig(
            enabled=True,
            tools={"dangerous_tool": ToolApprovalConfig(require_approval=True)},
        )
        manager = ApprovalGateManager(config)

        # Create and approve an approval
        approval = await manager.request_approval(
            "dangerous_tool", {"arg": "value"}, "session:123", "thread1"
        )
        manager.resolve(approval.id, approved=True)

        middleware = ApprovalToolMiddleware()
        middleware.set_context(manager, "session:123", "thread1")

        mock_request = MagicMock()
        mock_request.tool_call = {"name": "dangerous_tool", "args": {"arg": "value"}}
        mock_handler = AsyncMock(return_value="tool_result")

        # Should execute without raising (recent approval exists)
        result = await middleware._check_and_execute(mock_request, mock_handler)
        assert result == "tool_result"
        mock_handler.assert_called_once()

        # Approval should be cleared after execution
        assert (
            manager.check_recent_approval("session:123", "dangerous_tool")
            is False
        )


class TestChannelApprovalIntegration:
    """Test channel approval integration."""

    async def test_channel_approval_request(self):
        """Base class sends text fallback."""
        from openpaw.channels.base import ChannelAdapter

        # Create minimal channel subclass
        class TestChannel(ChannelAdapter):
            async def start(self):
                pass

            async def stop(self):
                pass

            async def send_message(self, session_key, content, **kwargs):
                return content

            def on_message(self, callback):
                pass

        channel = TestChannel()
        channel.name = "test"

        # Mock send_message to capture call
        messages = []

        async def capture_message(session_key, content, **kwargs):
            messages.append(content)

        channel.send_message = capture_message

        # Send approval request
        await channel.send_approval_request(
            session_key="test:123",
            approval_id="abc123",
            tool_name="dangerous_tool",
            tool_args={"arg1": "value1"},
            show_args=True,
        )

        # Check message was sent
        assert len(messages) == 1
        assert "dangerous_tool" in messages[0]
        assert "abc123" in messages[0]
        assert "value1" in messages[0]


class TestResolveOrphanedToolCalls:
    """Test orphaned tool call resolution in AgentRunner."""

    async def test_resolve_with_no_checkpointer(self):
        """No-op when checkpointer is None."""
        runner = MagicMock(spec=AgentRunner)
        runner.checkpointer = None
        # Call the real method with mocked self
        await AgentRunner.resolve_orphaned_tool_calls(runner, "thread1")
        # Should not raise

    async def test_resolve_with_orphaned_calls(self):
        """Injects synthetic ToolMessages for orphaned tool_calls."""
        from langchain_core.messages import AIMessage, ToolMessage

        # Build mock state with orphaned tool_calls
        ai_msg = AIMessage(
            content="I'll overwrite the file.",
            tool_calls=[{"id": "call_xyz", "name": "overwrite_file", "args": {"path": "test.txt"}}],
        )
        mock_state = MagicMock()
        mock_state.values = {"messages": [ai_msg]}

        mock_agent = AsyncMock()
        mock_agent.aget_state = AsyncMock(return_value=mock_state)
        mock_agent.aupdate_state = AsyncMock()

        runner = MagicMock(spec=AgentRunner)
        runner.checkpointer = MagicMock()
        runner._agent = mock_agent

        await AgentRunner.resolve_orphaned_tool_calls(
            runner,
            "thread1",
            responses={"call_xyz": "Tool denied."},
        )

        # Verify aupdate_state was called with synthetic ToolMessage
        mock_agent.aupdate_state.assert_called_once()
        call_args = mock_agent.aupdate_state.call_args
        injected_messages = call_args[1]["messages"] if "messages" in call_args[1] else call_args[0][1]["messages"]
        assert len(injected_messages) == 1
        assert isinstance(injected_messages[0], ToolMessage)
        assert injected_messages[0].tool_call_id == "call_xyz"
        assert injected_messages[0].content == "Tool denied."

    async def test_resolve_skips_already_resolved(self):
        """Does not inject for tool_calls that already have ToolMessages."""
        from langchain_core.messages import AIMessage, ToolMessage

        ai_msg = AIMessage(
            content="Running tool.",
            tool_calls=[{"id": "call_1", "name": "ls", "args": {}}],
        )
        tool_msg = ToolMessage(content="file.txt", tool_call_id="call_1")
        mock_state = MagicMock()
        mock_state.values = {"messages": [ai_msg, tool_msg]}

        mock_agent = AsyncMock()
        mock_agent.aget_state = AsyncMock(return_value=mock_state)
        mock_agent.aupdate_state = AsyncMock()

        runner = MagicMock(spec=AgentRunner)
        runner.checkpointer = MagicMock()
        runner._agent = mock_agent

        await AgentRunner.resolve_orphaned_tool_calls(runner, "thread1")

        # Should NOT call aupdate_state since no orphans
        mock_agent.aupdate_state.assert_not_called()

    async def test_resolve_with_empty_state(self):
        """No-op when state is empty."""
        mock_state = MagicMock()
        mock_state.values = {}

        mock_agent = AsyncMock()
        mock_agent.aget_state = AsyncMock(return_value=mock_state)

        runner = MagicMock(spec=AgentRunner)
        runner.checkpointer = MagicMock()
        runner._agent = mock_agent

        await AgentRunner.resolve_orphaned_tool_calls(runner, "thread1")
        # Should not raise
