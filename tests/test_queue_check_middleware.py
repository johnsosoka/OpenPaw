"""Tests for queue check middleware that fires before model calls."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from openpaw.agent.middleware.queue_aware import (
    InterruptSignalError,
    SteerState,
    _queue_manager_var,
    _queue_mode_var,
    _session_key_var,
    _steer_state_var,
)
from openpaw.agent.middleware.queue_check import _queue_check_logic
from openpaw.core.queue.lane import QueueMode


@pytest.fixture
def mock_queue_manager():
    """Create a mock QueueManager."""
    manager = MagicMock()
    manager.peek_pending = AsyncMock()
    manager.consume_pending = AsyncMock()
    return manager


@pytest.fixture
def mock_state():
    """Create a mock AgentState."""
    return MagicMock()


@pytest.fixture
def mock_runtime():
    """Create a mock runtime context."""
    return MagicMock()


@pytest.fixture(autouse=True)
def reset_contextvars():
    """Reset contextvars before and after each test."""
    # Reset before test
    _queue_manager_var.set(None)
    _session_key_var.set(None)
    _queue_mode_var.set(QueueMode.COLLECT)
    _steer_state_var.set(SteerState())

    yield

    # Reset after test
    _queue_manager_var.set(None)
    _session_key_var.set(None)
    _queue_mode_var.set(QueueMode.COLLECT)
    _steer_state_var.set(SteerState())


@pytest.mark.asyncio
async def test_queue_check_noop_in_collect_mode(
    mock_queue_manager, mock_state, mock_runtime
):
    """Collect mode: returns None (no-op)."""
    _queue_manager_var.set(mock_queue_manager)
    _session_key_var.set("test_session")
    _queue_mode_var.set(QueueMode.COLLECT)

    # Even if messages are pending, collect mode should no-op
    mock_queue_manager.peek_pending.return_value = True

    result = await _queue_check_logic(mock_state, mock_runtime)

    # Should return None (continue normally)
    assert result is None

    # Queue should not be checked in collect mode
    mock_queue_manager.peek_pending.assert_not_called()
    mock_queue_manager.consume_pending.assert_not_called()


@pytest.mark.asyncio
async def test_queue_check_noop_when_no_pending(
    mock_queue_manager, mock_state, mock_runtime
):
    """No pending messages: returns None."""
    _queue_manager_var.set(mock_queue_manager)
    _session_key_var.set("test_session")
    _queue_mode_var.set(QueueMode.STEER)

    mock_queue_manager.peek_pending.return_value = False

    result = await _queue_check_logic(mock_state, mock_runtime)

    # Should return None (continue normally)
    assert result is None

    # Queue was checked but nothing consumed
    mock_queue_manager.peek_pending.assert_called_once_with("test_session")
    mock_queue_manager.consume_pending.assert_not_called()


@pytest.mark.asyncio
async def test_queue_check_steer_jumps_to_end(
    mock_queue_manager, mock_state, mock_runtime
):
    """Steer mode with pending: returns jump_to end and sets contextvars."""
    _queue_manager_var.set(mock_queue_manager)
    _session_key_var.set("test_session")
    _queue_mode_var.set(QueueMode.STEER)

    mock_pending = [MagicMock(), MagicMock()]
    mock_queue_manager.peek_pending.return_value = True
    mock_queue_manager.consume_pending.return_value = mock_pending

    result = await _queue_check_logic(mock_state, mock_runtime)

    # Should return jump_to end
    assert result == {"jump_to": "end"}

    # Queue should be consumed
    mock_queue_manager.peek_pending.assert_called_once_with("test_session")
    mock_queue_manager.consume_pending.assert_called_once_with("test_session")

    # SteerState should be set
    state = _steer_state_var.get()
    assert state.steered is True
    assert state.pending_messages == mock_pending


@pytest.mark.asyncio
async def test_queue_check_interrupt_raises(
    mock_queue_manager, mock_state, mock_runtime
):
    """Interrupt mode with pending: raises InterruptSignalError."""
    _queue_manager_var.set(mock_queue_manager)
    _session_key_var.set("test_session")
    _queue_mode_var.set(QueueMode.INTERRUPT)

    mock_pending = [MagicMock(), MagicMock()]
    mock_queue_manager.peek_pending.return_value = True
    mock_queue_manager.consume_pending.return_value = mock_pending

    with pytest.raises(InterruptSignalError) as exc_info:
        await _queue_check_logic(mock_state, mock_runtime)

    # Should raise with pending messages
    assert exc_info.value.pending_messages == mock_pending

    # Queue should be consumed
    mock_queue_manager.peek_pending.assert_called_once_with("test_session")
    mock_queue_manager.consume_pending.assert_called_once_with("test_session")


@pytest.mark.asyncio
async def test_queue_check_skips_if_already_steered(
    mock_queue_manager, mock_state, mock_runtime
):
    """Already steered: jumps to end to terminate the run quickly."""
    _queue_manager_var.set(mock_queue_manager)
    _session_key_var.set("test_session")
    _queue_mode_var.set(QueueMode.STEER)
    _steer_state_var.set(SteerState(steered=True))  # Already steered

    result = await _queue_check_logic(mock_state, mock_runtime)

    # Should jump to end (don't let LLM generate more tool calls)
    assert result == {"jump_to": "end"}

    # Queue should not be checked (decision is already made)
    mock_queue_manager.peek_pending.assert_not_called()
    mock_queue_manager.consume_pending.assert_not_called()


@pytest.mark.asyncio
async def test_queue_check_noop_when_no_manager(mock_state, mock_runtime):
    """No queue manager: returns None."""
    # Don't set queue_manager_var
    _session_key_var.set("test_session")
    _queue_mode_var.set(QueueMode.STEER)

    result = await _queue_check_logic(mock_state, mock_runtime)

    # Should return None (no-op when no manager)
    assert result is None


@pytest.mark.asyncio
async def test_queue_check_noop_when_no_session(
    mock_queue_manager, mock_state, mock_runtime
):
    """No session key: returns None."""
    _queue_manager_var.set(mock_queue_manager)
    # Don't set session_key_var
    _queue_mode_var.set(QueueMode.STEER)

    result = await _queue_check_logic(mock_state, mock_runtime)

    # Should return None (no-op when no session)
    assert result is None

    # Queue should not be checked
    mock_queue_manager.peek_pending.assert_not_called()


@pytest.mark.asyncio
async def test_queue_check_followup_mode_noop(
    mock_queue_manager, mock_state, mock_runtime
):
    """Followup mode: returns None even with pending messages."""
    _queue_manager_var.set(mock_queue_manager)
    _session_key_var.set("test_session")
    _queue_mode_var.set(QueueMode.FOLLOWUP)

    mock_queue_manager.peek_pending.return_value = True

    result = await _queue_check_logic(mock_state, mock_runtime)

    # Should return None (followup mode doesn't interrupt)
    assert result is None

    # Queue was checked but nothing consumed
    mock_queue_manager.peek_pending.assert_called_once_with("test_session")
    mock_queue_manager.consume_pending.assert_not_called()
