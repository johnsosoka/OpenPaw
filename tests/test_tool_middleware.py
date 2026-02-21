"""Tests for QueueAwareToolMiddleware."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import ToolMessage

from openpaw.agent.middleware.queue_aware import InterruptSignalError, QueueAwareToolMiddleware
from openpaw.runtime.queue.lane import QueueMode


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
    middleware._pending_steer_message = [("telegram", "Message")]
    middleware._steered = True

    # Reset
    middleware.reset()

    # State is cleared
    assert middleware._queue_manager is None
    assert middleware._session_key is None
    assert middleware._queue_mode == QueueMode.COLLECT
    assert middleware._pending_steer_message is None
    assert middleware._steered is False
    assert middleware.was_steered is False
    assert middleware.pending_steer_message is None


@pytest.mark.asyncio
async def test_set_queue_awareness_configures_state(middleware, mock_queue_manager):
    """set_queue_awareness() configures state correctly."""
    middleware.set_queue_awareness(mock_queue_manager, "test_session", QueueMode.INTERRUPT)

    assert middleware._queue_manager is mock_queue_manager
    assert middleware._session_key == "test_session"
    assert middleware._queue_mode == QueueMode.INTERRUPT
    assert middleware._pending_steer_message is None
    assert middleware._steered is False


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

    # Reset peek to still return True (messages were consumed, but steered flag is set)
    # In reality, after consume, peek would return False. But we're testing that
    # once steered, subsequent tools are skipped even if peek returns False now.
    mock_queue_manager.peek_pending.return_value = False
    result2 = await middleware._check_and_execute(request2, mock_handler)

    # Second call should execute normally (no pending messages now)
    mock_handler.assert_called_once_with(request2)
    assert result2.content == "Tool executed successfully"

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
