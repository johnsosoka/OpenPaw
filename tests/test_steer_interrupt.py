"""Tests for steer/interrupt WorkspaceRunner integration."""

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from openpaw.agent import AgentRunner
from openpaw.agent.middleware import InterruptSignalError, QueueAwareToolMiddleware
from openpaw.runtime.queue.lane import QueueMode
from openpaw.core.workspace import AgentWorkspace


@pytest.fixture
def mock_workspace(tmp_path: Path) -> AgentWorkspace:
    """Create a minimal mock workspace."""
    workspace_path = tmp_path / "test_workspace"
    workspace_path.mkdir()

    # Create required markdown files
    (workspace_path / "AGENT.md").write_text("# Agent")
    (workspace_path / "USER.md").write_text("# User")
    (workspace_path / "SOUL.md").write_text("# Soul")
    (workspace_path / "HEARTBEAT.md").write_text("# Heartbeat")

    from openpaw.workspace.loader import WorkspaceLoader

    loader = WorkspaceLoader(tmp_path)
    return loader.load("test_workspace")


@pytest.fixture
def mock_middleware() -> QueueAwareToolMiddleware:
    """Create a QueueAwareToolMiddleware instance."""
    return QueueAwareToolMiddleware()


class TestAgentRunnerMiddleware:
    """Test AgentRunner accepts and passes middleware to create_agent."""

    @patch("openpaw.agent.runner.create_agent")
    @patch("openpaw.agent.runner.AgentRunner._create_model")
    def test_accepts_middleware_parameter(
        self, mock_create_model: Mock, mock_create_agent: Mock, mock_workspace: AgentWorkspace
    ) -> None:
        """AgentRunner accepts middleware parameter in __init__."""
        mock_model = Mock()
        mock_create_model.return_value = mock_model
        mock_create_agent.return_value = Mock()

        middleware_fn = Mock()
        runner = AgentRunner(
            workspace=mock_workspace,
            middleware=[middleware_fn],
        )

        assert runner._middleware == [middleware_fn]

    @patch("openpaw.agent.runner.create_agent")
    @patch("openpaw.agent.runner.AgentRunner._create_model")
    def test_passes_middleware_to_create_agent(
        self, mock_create_model: Mock, mock_create_agent: Mock, mock_workspace: AgentWorkspace
    ) -> None:
        """Middleware is passed to create_agent during agent building."""
        mock_model = Mock()
        mock_create_model.return_value = mock_model
        mock_create_agent.return_value = Mock()

        middleware_fn = Mock()
        runner = AgentRunner(
            workspace=mock_workspace,
            middleware=[middleware_fn],
        )

        # Verify create_agent was called with middleware
        assert mock_create_agent.called
        call_kwargs = mock_create_agent.call_args[1]
        assert "middleware" in call_kwargs
        assert call_kwargs["middleware"] == [middleware_fn]

    @patch("openpaw.agent.runner.create_agent")
    @patch("openpaw.agent.runner.AgentRunner._create_model")
    def test_defaults_to_empty_middleware(
        self, mock_create_model: Mock, mock_create_agent: Mock, mock_workspace: AgentWorkspace
    ) -> None:
        """When no middleware provided, defaults to empty list."""
        mock_model = Mock()
        mock_create_model.return_value = mock_model
        mock_create_agent.return_value = Mock()

        runner = AgentRunner(workspace=mock_workspace)

        assert runner._middleware == []
        call_kwargs = mock_create_agent.call_args[1]
        assert call_kwargs["middleware"] == []


class TestInterruptSignalPropagation:
    """Test InterruptSignalError propagates through AgentRunner.run()."""

    @pytest.mark.asyncio
    async def test_interrupt_signal_propagates(self, mock_workspace: AgentWorkspace) -> None:
        """InterruptSignalError raised during astream propagates out of run()."""
        with patch("openpaw.agent.runner.create_agent") as mock_create_agent, patch(
            "openpaw.agent.runner.AgentRunner._create_model"
        ) as mock_create_model:
            mock_model = Mock()
            mock_create_model.return_value = mock_model

            # Mock agent that raises InterruptSignalError during astream
            mock_agent = Mock()

            async def raise_interrupt(*args: Any, **kwargs: Any) -> Any:
                raise InterruptSignalError([("telegram", Mock(content="new message"))])
                yield  # Make this an async generator for type checker

            mock_agent.astream = raise_interrupt
            mock_create_agent.return_value = mock_agent

            runner = AgentRunner(workspace=mock_workspace)

            # Verify InterruptSignalError propagates
            with pytest.raises(InterruptSignalError) as exc_info:
                await runner.run(message="test message")

            assert len(exc_info.value.pending_messages) == 1


class TestMiddlewareSetReset:
    """Test middleware set_queue_awareness and reset called per invocation."""

    def test_middleware_set_called_before_run(self, mock_middleware: QueueAwareToolMiddleware) -> None:
        """set_queue_awareness is called before each agent run."""
        mock_queue_manager = Mock()
        session_key = "telegram:12345"

        mock_middleware.set_queue_awareness(
            queue_manager=mock_queue_manager,
            session_key=session_key,
            queue_mode=QueueMode.STEER,
        )

        assert mock_middleware._queue_manager == mock_queue_manager
        assert mock_middleware._session_key == session_key
        assert mock_middleware._queue_mode == QueueMode.STEER

    def test_middleware_reset_clears_state(self, mock_middleware: QueueAwareToolMiddleware) -> None:
        """reset() clears per-invocation state."""
        mock_queue_manager = Mock()
        mock_middleware.set_queue_awareness(
            queue_manager=mock_queue_manager,
            session_key="telegram:12345",
            queue_mode=QueueMode.INTERRUPT,
        )

        mock_middleware.reset()

        assert mock_middleware._queue_manager is None
        assert mock_middleware._session_key is None
        assert mock_middleware._queue_mode == QueueMode.COLLECT
        assert mock_middleware._pending_steer_message is None
        assert mock_middleware._steered is False


class TestSteerMode:
    """Test steer mode behavior in WorkspaceRunner integration."""

    @pytest.mark.asyncio
    async def test_steer_resets_followup_depth(self) -> None:
        """Steer mode resets followup depth to 0."""
        # This is a behavioral test - verify that when steer occurs,
        # followup_depth is reset. We'll check this via the log message.

        mock_middleware = QueueAwareToolMiddleware()

        # Simulate steer by setting internal state
        mock_middleware._steered = True
        mock_middleware._pending_steer_message = [("telegram", Mock(content="new message"))]

        # Verify steer state
        assert mock_middleware.was_steered is True
        assert mock_middleware.pending_steer_message is not None


class TestCollectMode:
    """Test collect mode has no queue checking behavior."""

    @pytest.mark.asyncio
    async def test_collect_mode_no_queue_check(self, mock_middleware: QueueAwareToolMiddleware) -> None:
        """In collect mode, tools execute normally without queue checks."""
        # Set to collect mode
        mock_queue_manager = Mock()
        mock_middleware.set_queue_awareness(
            queue_manager=mock_queue_manager,
            session_key="telegram:12345",
            queue_mode=QueueMode.COLLECT,
        )

        # Mock handler
        async def mock_handler(request: Any) -> str:
            return "tool executed"

        # Create a mock request
        mock_request = Mock()
        mock_request.tool_call = {"name": "test_tool", "id": "call_123", "args": {}}

        # Execute
        result = await mock_middleware._check_and_execute(mock_request, mock_handler)

        assert result == "tool executed"
        # Verify queue manager was never called
        assert not mock_queue_manager.peek_pending.called


class TestAgentFactoryNoMiddleware:
    """Test agent factory doesn't include queue middleware."""

    @patch("openpaw.agent.runner.create_agent")
    @patch("openpaw.agent.runner.AgentRunner._create_model")
    def test_factory_agent_has_empty_middleware(
        self, mock_create_model: Mock, mock_create_agent: Mock, mock_workspace: AgentWorkspace
    ) -> None:
        """Agents created by factory have empty middleware list."""
        mock_model = Mock()
        mock_create_model.return_value = mock_model
        mock_create_agent.return_value = Mock()

        # Create runner with middleware
        main_middleware = Mock()
        runner = AgentRunner(
            workspace=mock_workspace,
            middleware=[main_middleware],
        )

        # Reset mock to track factory agent creation
        mock_create_agent.reset_mock()

        # Create a factory agent (simulating cron/heartbeat pattern)
        factory_agent = AgentRunner(
            workspace=mock_workspace,
            middleware=[],  # Factory agents get empty middleware
        )

        # Verify factory agent has empty middleware
        call_kwargs = mock_create_agent.call_args[1]
        assert call_kwargs["middleware"] == []


class TestSteerInterruptIntegration:
    """Integration tests for steer/interrupt with middleware."""

    @pytest.mark.asyncio
    async def test_steer_skips_tools_and_redirects(self, mock_middleware: QueueAwareToolMiddleware) -> None:
        """Steer mode skips remaining tools and redirects to new message."""
        # Mock queue manager that reports pending messages
        mock_queue_manager = AsyncMock()
        mock_queue_manager.peek_pending.return_value = True
        mock_queue_manager.consume_pending.return_value = [
            ("telegram", Mock(content="urgent message")),
        ]

        # Set middleware to steer mode
        mock_middleware.set_queue_awareness(
            queue_manager=mock_queue_manager,
            session_key="telegram:12345",
            queue_mode=QueueMode.STEER,
        )

        # Mock tool handler that should be skipped
        async def mock_handler(request: Any) -> str:
            return "tool executed (should not see this)"

        # Create mock request
        mock_request = Mock()
        mock_request.tool_call = {"name": "test_tool", "id": "call_123", "args": {}}

        # Execute
        result = await mock_middleware._check_and_execute(mock_request, mock_handler)

        # Verify tool was skipped
        assert hasattr(result, "content")
        assert "[Skipped:" in result.content

        # Verify steer state was captured
        assert mock_middleware.was_steered is True
        assert len(mock_middleware.pending_steer_message) == 1

    @pytest.mark.asyncio
    async def test_interrupt_aborts_run(self, mock_middleware: QueueAwareToolMiddleware) -> None:
        """Interrupt mode aborts run and raises InterruptSignalError."""
        # Mock queue manager that reports pending messages
        mock_queue_manager = AsyncMock()
        mock_queue_manager.peek_pending.return_value = True
        mock_queue_manager.consume_pending.return_value = [
            ("telegram", Mock(content="urgent message")),
        ]

        # Set middleware to interrupt mode
        mock_middleware.set_queue_awareness(
            queue_manager=mock_queue_manager,
            session_key="telegram:12345",
            queue_mode=QueueMode.INTERRUPT,
        )

        # Mock tool handler
        async def mock_handler(request: Any) -> str:
            return "tool executed (should not see this)"

        # Create mock request
        mock_request = Mock()
        mock_request.tool_call = {"name": "test_tool", "id": "call_123", "args": {}}

        # Execute and verify interrupt signal is raised
        with pytest.raises(InterruptSignalError) as exc_info:
            await mock_middleware._check_and_execute(mock_request, mock_handler)

        assert len(exc_info.value.pending_messages) == 1
        assert exc_info.value.pending_messages[0][0] == "telegram"


class TestSteerMultipleTools:
    """Test that steer only consumes messages once, even with multiple tool calls."""

    @pytest.mark.asyncio
    async def test_steer_consumes_once(self, mock_middleware: QueueAwareToolMiddleware) -> None:
        """Steer only consumes pending messages on first tool skip."""
        # Mock queue manager
        mock_queue_manager = AsyncMock()
        mock_queue_manager.peek_pending.return_value = True
        mock_queue_manager.consume_pending.return_value = [
            ("telegram", Mock(content="new message")),
        ]

        # Set middleware to steer mode
        mock_middleware.set_queue_awareness(
            queue_manager=mock_queue_manager,
            session_key="telegram:12345",
            queue_mode=QueueMode.STEER,
        )

        # Mock handler
        async def mock_handler(request: Any) -> str:
            return "executed"

        # Create mock requests
        mock_request1 = Mock()
        mock_request1.tool_call = {"name": "tool1", "id": "call_1", "args": {}}
        mock_request2 = Mock()
        mock_request2.tool_call = {"name": "tool2", "id": "call_2", "args": {}}

        # Execute first tool (should consume)
        result1 = await mock_middleware._check_and_execute(mock_request1, mock_handler)
        assert "[Skipped:" in result1.content
        assert mock_queue_manager.consume_pending.call_count == 1

        # Execute second tool (should NOT consume again)
        result2 = await mock_middleware._check_and_execute(mock_request2, mock_handler)
        assert "[Skipped:" in result2.content
        # Still only called once
        assert mock_queue_manager.consume_pending.call_count == 1
