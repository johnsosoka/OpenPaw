"""Tests for QueueAwareToolMiddleware."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import ToolMessage

from openpaw.agent.middleware.queue_aware import (
    STEER_EXEMPT_TOOLS,
    InterruptSignalError,
    QueueAwareToolMiddleware,
    SteerState,
    _queue_manager_var,
    _queue_mode_var,
    _session_key_var,
    _steer_state_var,
)
from openpaw.core.queue.lane import QueueMode


@pytest.fixture
def middleware():
    """Create a QueueAwareToolMiddleware instance for testing."""
    return QueueAwareToolMiddleware()


@pytest.fixture
def mock_queue_manager():
    """Create a mock QueueManager."""
    manager = MagicMock()
    manager.peek_pending = AsyncMock()
    manager.consume_pending = AsyncMock()
    return manager


@pytest.fixture
def mock_request():
    """Create a mock tool request."""
    request = MagicMock()
    request.tool_call = {
        "id": "test-tool-call-id",
        "name": "test_tool",
        "args": {"arg1": "value1"},
    }
    return request


@pytest.fixture
def mock_handler():
    """Create a mock async handler that returns a ToolMessage."""

    async def handler(request):
        return ToolMessage(
            content="Tool executed successfully", tool_call_id=request.tool_call["id"]
        )

    return AsyncMock(side_effect=handler)


@pytest.mark.asyncio
async def test_collect_mode_executes_normally(middleware, mock_queue_manager, mock_request, mock_handler):
    """Collect mode: tool executes normally (no-op)."""
    middleware.set_queue_awareness(mock_queue_manager, "test_session", QueueMode.COLLECT)

    # Even if messages are pending, collect mode executes normally
    mock_queue_manager.peek_pending.return_value = True

    result = await middleware._check_and_execute(mock_request, mock_handler)

    # Handler was called
    mock_handler.assert_called_once_with(mock_request)
    assert result.content == "Tool executed successfully"

    # Queue was not checked
    mock_queue_manager.peek_pending.assert_not_called()
    mock_queue_manager.consume_pending.assert_not_called()


@pytest.mark.asyncio
async def test_no_queue_awareness_executes_normally(middleware, mock_request, mock_handler):
    """No queue awareness set: tool executes normally."""
    # Don't call set_queue_awareness
    result = await middleware._check_and_execute(mock_request, mock_handler)

    # Handler was called
    mock_handler.assert_called_once_with(mock_request)
    assert result.content == "Tool executed successfully"


@pytest.mark.asyncio
async def test_steer_mode_no_pending_executes_normally(
    middleware, mock_queue_manager, mock_request, mock_handler
):
    """Steer mode with no pending: tool executes normally."""
    middleware.set_queue_awareness(mock_queue_manager, "test_session", QueueMode.STEER)
    mock_queue_manager.peek_pending.return_value = False

    result = await middleware._check_and_execute(mock_request, mock_handler)

    # Handler was called
    mock_handler.assert_called_once_with(mock_request)
    assert result.content == "Tool executed successfully"

    # Queue was checked but not consumed
    mock_queue_manager.peek_pending.assert_called_once_with("test_session")
    mock_queue_manager.consume_pending.assert_not_called()


@pytest.mark.asyncio
async def test_steer_mode_with_pending_skips_tool(middleware, mock_queue_manager, mock_request, mock_handler):
    """Steer mode with pending: tool skipped, pending messages stored."""
    middleware.set_queue_awareness(mock_queue_manager, "test_session", QueueMode.STEER)
    mock_queue_manager.peek_pending.return_value = True
    mock_queue_manager.consume_pending.return_value = [
        ("telegram", "New message 1"),
        ("telegram", "New message 2"),
    ]

    result = await middleware._check_and_execute(mock_request, mock_handler)

    # Handler was NOT called
    mock_handler.assert_not_called()

    # Queue was checked and consumed
    mock_queue_manager.peek_pending.assert_called_once_with("test_session")
    mock_queue_manager.consume_pending.assert_called_once_with("test_session")

    # Result is a skip message
    assert isinstance(result, ToolMessage)
    assert "[Skipped: user sent new message" in result.content
    assert result.tool_call_id == "test-tool-call-id"

    # Middleware stored pending messages
    assert middleware.was_steered is True
    assert middleware.pending_steer_message == [
        ("telegram", "New message 1"),
        ("telegram", "New message 2"),
    ]


@pytest.mark.asyncio
async def test_interrupt_mode_with_pending_raises_signal(
    middleware, mock_queue_manager, mock_request, mock_handler
):
    """Interrupt mode with pending: InterruptSignalError raised with messages."""
    middleware.set_queue_awareness(mock_queue_manager, "test_session", QueueMode.INTERRUPT)
    mock_queue_manager.peek_pending.return_value = True
    mock_queue_manager.consume_pending.return_value = [("telegram", "Interrupt message")]

    with pytest.raises(InterruptSignalError) as exc_info:
        await middleware._check_and_execute(mock_request, mock_handler)

    # Handler was NOT called
    mock_handler.assert_not_called()

    # Queue was checked and consumed
    mock_queue_manager.peek_pending.assert_called_once_with("test_session")
    mock_queue_manager.consume_pending.assert_called_once_with("test_session")

    # Exception carries the pending messages
    assert exc_info.value.pending_messages == [("telegram", "Interrupt message")]


@pytest.mark.asyncio
async def test_interrupt_mode_no_pending_executes_normally(
    middleware, mock_queue_manager, mock_request, mock_handler
):
    """Interrupt mode with no pending: tool executes normally."""
    middleware.set_queue_awareness(mock_queue_manager, "test_session", QueueMode.INTERRUPT)
    mock_queue_manager.peek_pending.return_value = False

    result = await middleware._check_and_execute(mock_request, mock_handler)

    # Handler was called
    mock_handler.assert_called_once_with(mock_request)
    assert result.content == "Tool executed successfully"

    # Queue was checked but not consumed
    mock_queue_manager.peek_pending.assert_called_once_with("test_session")
    mock_queue_manager.consume_pending.assert_not_called()


@pytest.mark.asyncio
async def test_reset_clears_state(middleware, mock_queue_manager):
    """reset() clears all state."""
    # Set up state
    middleware.set_queue_awareness(mock_queue_manager, "test_session", QueueMode.STEER)
    _steer_state_var.set(SteerState(steered=True, pending_messages=[("telegram", "Message")]))

    # Reset
    middleware.reset()

    # State is cleared
    assert _queue_manager_var.get() is None
    assert _session_key_var.get() is None
    assert _queue_mode_var.get() == QueueMode.COLLECT
    state = _steer_state_var.get()
    assert state.steered is False
    assert state.pending_messages is None
    assert middleware.was_steered is False
    assert middleware.pending_steer_message is None


@pytest.mark.asyncio
async def test_set_queue_awareness_configures_state(middleware, mock_queue_manager):
    """set_queue_awareness() configures state correctly."""
    middleware.set_queue_awareness(mock_queue_manager, "test_session", QueueMode.INTERRUPT)

    assert _queue_manager_var.get() is mock_queue_manager
    assert _session_key_var.get() == "test_session"
    assert _queue_mode_var.get() == QueueMode.INTERRUPT
    state = _steer_state_var.get()
    assert state.steered is False
    assert state.pending_messages is None


@pytest.mark.asyncio
async def test_was_steered_property_tracks_state(middleware, mock_queue_manager, mock_request, mock_handler):
    """was_steered property tracks steer state."""
    middleware.set_queue_awareness(mock_queue_manager, "test_session", QueueMode.STEER)

    # Initially not steered
    assert middleware.was_steered is False

    # Trigger steer
    mock_queue_manager.peek_pending.return_value = True
    mock_queue_manager.consume_pending.return_value = [("telegram", "Message")]
    await middleware._check_and_execute(mock_request, mock_handler)

    # Now steered
    assert middleware.was_steered is True


@pytest.mark.asyncio
async def test_pending_steer_message_stores_consumed_messages(
    middleware, mock_queue_manager, mock_request, mock_handler
):
    """pending_steer_message stores consumed messages."""
    middleware.set_queue_awareness(mock_queue_manager, "test_session", QueueMode.STEER)
    mock_queue_manager.peek_pending.return_value = True
    mock_queue_manager.consume_pending.return_value = [
        ("telegram", "Message 1"),
        ("telegram", "Message 2"),
    ]

    # Initially None
    assert middleware.pending_steer_message is None

    # Trigger steer
    await middleware._check_and_execute(mock_request, mock_handler)

    # Messages stored
    assert middleware.pending_steer_message == [
        ("telegram", "Message 1"),
        ("telegram", "Message 2"),
    ]


@pytest.mark.asyncio
async def test_multiple_tools_first_triggers_steer_subsequent_skipped(
    middleware, mock_queue_manager, mock_handler
):
    """Multiple tools in batch: first tool triggers steer, subsequent tools also skipped."""
    middleware.set_queue_awareness(mock_queue_manager, "test_session", QueueMode.STEER)
    mock_queue_manager.peek_pending.return_value = True
    mock_queue_manager.consume_pending.return_value = [("telegram", "New message")]

    # First tool call
    request1 = MagicMock()
    request1.tool_call = {"id": "tool-1", "name": "tool_1", "args": {}}
    result1 = await middleware._check_and_execute(request1, mock_handler)

    # First call triggers steer and consumes
    assert middleware.was_steered is True
    assert isinstance(result1, ToolMessage)
    assert "[Skipped" in result1.content
    mock_queue_manager.consume_pending.assert_called_once()

    # Second tool call (simulate subsequent tool in the same batch)
    request2 = MagicMock()
    request2.tool_call = {"id": "tool-2", "name": "tool_2", "args": {}}

    # After consume, peek returns False. But steered flag means non-exempt
    # tools should still be skipped to end the run quickly.
    mock_queue_manager.peek_pending.return_value = False
    result2 = await middleware._check_and_execute(request2, mock_handler)

    # Second call should be skipped (steered, non-exempt, even with no new pending)
    assert isinstance(result2, ToolMessage)
    assert "[Skipped" in result2.content
    mock_handler.assert_not_called()

    # More realistic test: messages are still pending (user keeps typing)
    mock_queue_manager.peek_pending.return_value = True
    request3 = MagicMock()
    request3.tool_call = {"id": "tool-3", "name": "tool_3", "args": {}}
    result3 = await middleware._check_and_execute(request3, mock_handler)

    # Third call should be skipped (still steered, but consume not called again)
    assert isinstance(result3, ToolMessage)
    assert "[Skipped" in result3.content
    # consume_pending only called once (on first steer)
    assert mock_queue_manager.consume_pending.call_count == 1


@pytest.mark.asyncio
async def test_followup_mode_executes_normally(middleware, mock_queue_manager, mock_request, mock_handler):
    """FOLLOWUP mode executes tools normally (fallback behavior)."""
    middleware.set_queue_awareness(mock_queue_manager, "test_session", QueueMode.FOLLOWUP)
    mock_queue_manager.peek_pending.return_value = True

    result = await middleware._check_and_execute(mock_request, mock_handler)

    # Handler was called (FOLLOWUP doesn't interrupt tools)
    mock_handler.assert_called_once_with(mock_request)
    assert result.content == "Tool executed successfully"


@pytest.mark.asyncio
async def test_steer_backlog_mode_executes_normally(
    middleware, mock_queue_manager, mock_request, mock_handler
):
    """STEER_BACKLOG mode executes tools normally (fallback behavior)."""
    middleware.set_queue_awareness(mock_queue_manager, "test_session", QueueMode.STEER_BACKLOG)
    mock_queue_manager.peek_pending.return_value = True

    result = await middleware._check_and_execute(mock_request, mock_handler)

    # Handler was called (STEER_BACKLOG doesn't interrupt tools yet)
    mock_handler.assert_called_once_with(mock_request)
    assert result.content == "Tool executed successfully"


@pytest.mark.asyncio
async def test_contextvar_isolation_between_tasks():
    """ContextVars isolate state between concurrent asyncio tasks."""
    middleware = QueueAwareToolMiddleware()
    manager1 = MagicMock()
    manager1.peek_pending = AsyncMock(return_value=False)
    manager2 = MagicMock()
    manager2.peek_pending = AsyncMock(return_value=False)

    results = {}

    async def task_a():
        middleware.set_queue_awareness(manager1, "session_a", QueueMode.STEER)
        await asyncio.sleep(0.01)  # Yield to let task_b run
        results["a_session"] = _session_key_var.get()
        results["a_mode"] = _queue_mode_var.get()
        middleware.reset()

    async def task_b():
        middleware.set_queue_awareness(manager2, "session_b", QueueMode.INTERRUPT)
        await asyncio.sleep(0.01)  # Yield to let task_a run
        results["b_session"] = _session_key_var.get()
        results["b_mode"] = _queue_mode_var.get()
        middleware.reset()

    await asyncio.gather(task_a(), task_b())

    assert results["a_session"] == "session_a"
    assert results["a_mode"] == QueueMode.STEER
    assert results["b_session"] == "session_b"
    assert results["b_mode"] == QueueMode.INTERRUPT


@pytest.mark.asyncio
async def test_steer_exempt_tool_executes_during_steer(
    middleware, mock_queue_manager, mock_handler
):
    """Steer-exempt tool (send_message) executes normally during steer."""
    middleware.set_queue_awareness(mock_queue_manager, "test_session", QueueMode.STEER)
    mock_queue_manager.peek_pending.return_value = True
    mock_queue_manager.consume_pending.return_value = [("telegram", "New message")]

    # Create request for steer-exempt tool
    request = MagicMock()
    request.tool_call = {
        "id": "test-tool-call-id",
        "name": "send_message",  # Steer-exempt
        "args": {"message": "Progress update"},
    }

    result = await middleware._check_and_execute(request, mock_handler)

    # Handler WAS called (exempt tool executes)
    mock_handler.assert_called_once_with(request)
    assert result.content == "Tool executed successfully"

    # Steer state captured
    assert middleware.was_steered is True
    assert middleware.pending_steer_message == [("telegram", "New message")]

    # Queue was checked and consumed
    mock_queue_manager.peek_pending.assert_called_once_with("test_session")
    mock_queue_manager.consume_pending.assert_called_once_with("test_session")


@pytest.mark.asyncio
async def test_non_exempt_tool_skipped_during_steer(
    middleware, mock_queue_manager, mock_handler
):
    """Non-exempt tool (brave_search) is still skipped during steer."""
    middleware.set_queue_awareness(mock_queue_manager, "test_session", QueueMode.STEER)
    mock_queue_manager.peek_pending.return_value = True
    mock_queue_manager.consume_pending.return_value = [("telegram", "New message")]

    # Create request for non-exempt tool
    request = MagicMock()
    request.tool_call = {
        "id": "test-tool-call-id",
        "name": "brave_search",  # Non-exempt
        "args": {"query": "test"},
    }

    result = await middleware._check_and_execute(request, mock_handler)

    # Handler was NOT called
    mock_handler.assert_not_called()

    # Result is a skip message
    assert isinstance(result, ToolMessage)
    assert "[Skipped: user sent new message" in result.content
    assert result.tool_call_id == "test-tool-call-id"

    # Steer state captured
    assert middleware.was_steered is True


@pytest.mark.asyncio
async def test_exempt_tool_after_steer_already_triggered(
    middleware, mock_queue_manager, mock_handler
):
    """Exempt tool executes even when steer was already triggered by previous tool."""
    middleware.set_queue_awareness(mock_queue_manager, "test_session", QueueMode.STEER)

    # Set up state as if steer already triggered
    _steer_state_var.set(SteerState(steered=True, pending_messages=[("telegram", "Previous message")]))

    # New message arrives
    mock_queue_manager.peek_pending.return_value = True

    # Create request for exempt tool
    request = MagicMock()
    request.tool_call = {
        "id": "test-tool-call-id",
        "name": "update_task",  # Steer-exempt
        "args": {"task_id": "1", "status": "completed"},
    }

    result = await middleware._check_and_execute(request, mock_handler)

    # Handler WAS called (exempt tool executes)
    mock_handler.assert_called_once_with(request)
    assert result.content == "Tool executed successfully"

    # consume_pending NOT called again (already consumed on first steer)
    mock_queue_manager.consume_pending.assert_not_called()


def test_steer_exempt_tools_constant_contains_expected_tools():
    """STEER_EXEMPT_TOOLS constant contains the expected tools."""
    expected = {"send_message", "send_file", "update_task", "create_task"}
    assert STEER_EXEMPT_TOOLS == expected
