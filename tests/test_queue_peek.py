"""Tests for QueueManager peek_pending and consume_pending methods."""

import asyncio
from collections import deque

import pytest

from openpaw.runtime.queue.lane import LaneQueue, QueueMode
from openpaw.runtime.queue.manager import QueueManager, SessionQueue


@pytest.fixture
def queue_manager():
    """Create a QueueManager instance for testing."""
    lane_queue = LaneQueue()
    return QueueManager(lane_queue)


@pytest.mark.asyncio
async def test_peek_pending_empty_session(queue_manager):
    """peek_pending returns False for empty/unknown session."""
    result = await queue_manager.peek_pending("unknown_session")
    assert result is False


@pytest.mark.asyncio
async def test_peek_pending_with_messages(queue_manager):
    """peek_pending returns True when messages exist."""
    # Create a session with messages
    session = await queue_manager._get_or_create_session("test_session")
    session.messages.append(("telegram", "Hello"))
    session.messages.append(("telegram", "World"))

    result = await queue_manager.peek_pending("test_session")
    assert result is True


@pytest.mark.asyncio
async def test_peek_pending_is_nondestructive(queue_manager):
    """peek_pending is non-destructive (messages remain after peek)."""
    # Create a session with messages
    session = await queue_manager._get_or_create_session("test_session")
    session.messages.append(("telegram", "Message 1"))
    session.messages.append(("telegram", "Message 2"))

    # Peek multiple times
    result1 = await queue_manager.peek_pending("test_session")
    result2 = await queue_manager.peek_pending("test_session")

    assert result1 is True
    assert result2 is True
    assert len(session.messages) == 2  # Messages still there


@pytest.mark.asyncio
async def test_consume_pending_returns_and_removes_messages(queue_manager):
    """consume_pending returns and removes all messages."""
    # Create a session with messages
    session = await queue_manager._get_or_create_session("test_session")
    session.messages.append(("telegram", "Message 1"))
    session.messages.append(("telegram", "Message 2"))
    session.messages.append(("discord", "Message 3"))

    # Consume messages
    messages = await queue_manager.consume_pending("test_session")

    assert len(messages) == 3
    assert messages[0] == ("telegram", "Message 1")
    assert messages[1] == ("telegram", "Message 2")
    assert messages[2] == ("discord", "Message 3")
    assert len(session.messages) == 0  # Queue is now empty


@pytest.mark.asyncio
async def test_consume_pending_empty_session(queue_manager):
    """consume_pending returns empty list for empty/unknown session."""
    # Unknown session
    result1 = await queue_manager.consume_pending("unknown_session")
    assert result1 == []

    # Known session but empty
    await queue_manager._get_or_create_session("test_session")
    result2 = await queue_manager.consume_pending("test_session")
    assert result2 == []


@pytest.mark.asyncio
async def test_consume_pending_cancels_debounce_task(queue_manager):
    """consume_pending cancels pending debounce task."""
    # Create a session with a debounce task
    session = await queue_manager._get_or_create_session("test_session")
    session.messages.append(("telegram", "Message"))

    # Create a mock debounce task
    async def mock_debounce():
        await asyncio.sleep(10)  # Long sleep to ensure it's cancellable

    session._debounce_task = asyncio.create_task(mock_debounce())
    task = session._debounce_task

    # Consume messages (should cancel the task)
    await queue_manager.consume_pending("test_session")

    # Give the event loop a chance to process the cancellation
    await asyncio.sleep(0)

    # Verify task was cancelled
    assert task.cancelled() is True
    assert session._debounce_task is None


@pytest.mark.asyncio
async def test_peek_and_consume_workflow(queue_manager):
    """Test typical workflow: peek, then consume if pending."""
    session_key = "test_session"

    # Initially no messages
    assert await queue_manager.peek_pending(session_key) is False

    # Add messages
    session = await queue_manager._get_or_create_session(session_key)
    session.messages.append(("telegram", "Message 1"))
    session.messages.append(("telegram", "Message 2"))

    # Peek detects messages
    assert await queue_manager.peek_pending(session_key) is True

    # Consume them
    messages = await queue_manager.consume_pending(session_key)
    assert len(messages) == 2

    # No longer pending
    assert await queue_manager.peek_pending(session_key) is False


@pytest.mark.asyncio
async def test_peek_pending_ignores_non_steer_eligible(queue_manager):
    """peek_pending returns False when only non-steer-eligible items are in lane queue."""
    session_key = "test_session"

    # Submit a system event (steer_eligible=False)
    await queue_manager.submit(
        session_key=session_key,
        channel_name="telegram",
        message="system event",
        steer_eligible=False,
    )

    # peek_pending should return False (system event not steer-eligible)
    result = await queue_manager.peek_pending(session_key)
    assert result is False


@pytest.mark.asyncio
async def test_peek_pending_detects_steer_eligible_alongside_non_eligible(queue_manager):
    """peek_pending returns True when steer-eligible items exist alongside non-eligible."""
    session_key = "test_session"

    # Submit a system event (non-steer-eligible, bypasses buffer)
    await queue_manager.submit(
        session_key=session_key,
        channel_name="telegram",
        message="system event",
        steer_eligible=False,
    )

    # Submit a user message to session buffer (steer-eligible by default)
    session = await queue_manager._get_or_create_session(session_key)
    session.messages.append(("telegram", "user message"))

    # peek_pending should return True (user message in buffer)
    result = await queue_manager.peek_pending(session_key)
    assert result is True


@pytest.mark.asyncio
async def test_non_steer_eligible_bypasses_session_buffer(queue_manager):
    """Non-steer-eligible items go directly to lane queue, skipping session buffer."""
    session_key = "test_session"

    # Submit with steer_eligible=False
    await queue_manager.submit(
        session_key=session_key,
        channel_name="telegram",
        message="system event",
        steer_eligible=False,
    )

    # Session buffer should be empty (item bypassed it)
    async with queue_manager._lock:
        if session_key in queue_manager._sessions:
            assert len(queue_manager._sessions[session_key].messages) == 0

    # But the lane queue should have the item
    lane = queue_manager.lane_queue.get_lane("main")
    async with lane._lock:
        assert len(lane.queue) == 1
        assert lane.queue[0].steer_eligible is False


@pytest.mark.asyncio
async def test_consume_pending_drains_all_regardless_of_steer_eligible(queue_manager):
    """consume_pending returns all items including non-steer-eligible ones."""
    session_key = "test_session"

    # Submit a system event (non-steer-eligible)
    await queue_manager.submit(
        session_key=session_key,
        channel_name="telegram",
        message="system event",
        steer_eligible=False,
    )

    # Also add a user message to session buffer
    session = await queue_manager._get_or_create_session(session_key)
    session.messages.append(("telegram", "user message"))

    # Consume should return both
    messages = await queue_manager.consume_pending(session_key)
    assert len(messages) == 2
