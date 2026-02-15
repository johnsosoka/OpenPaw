"""Tests for QueueManager peek_pending and consume_pending methods."""

import asyncio

import pytest

from openpaw.core.queue.lane import LaneQueue, QueueMode
from openpaw.core.queue.manager import QueueManager


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


# Tests for Fix 4: In-Flight Items Visibility


@pytest.mark.asyncio
async def test_peek_detects_in_flight_items():
    """Test peek_session_pending detects items between dequeue and session lock."""
    from openpaw.core.queue.lane import LaneQueue, QueueItem

    lane_queue = LaneQueue()
    session_key = "test:123"

    # Manually add item to in_flight dict (simulating dequeued but not yet processing)
    item = QueueItem(session_key=session_key, payload="test", mode=QueueMode.COLLECT)
    lane_queue._in_flight[session_key] = [item]

    # Peek should detect the in-flight item
    result = await lane_queue.peek_session_pending(session_key)
    assert result is True


@pytest.mark.asyncio
async def test_consume_includes_in_flight_items():
    """Test consume_session_pending drains both queue and in-flight."""
    from openpaw.core.queue.lane import LaneQueue, QueueItem

    lane_queue = LaneQueue()
    session_key = "test:123"

    # Add item to queue
    queued_item = QueueItem(session_key=session_key, payload="queued", mode=QueueMode.COLLECT)
    await lane_queue.enqueue(queued_item, lane_name="main")

    # Add item to in_flight (simulating dequeued but not yet processing)
    in_flight_item = QueueItem(session_key=session_key, payload="in_flight", mode=QueueMode.COLLECT)
    lane_queue._in_flight[session_key] = [in_flight_item]

    # Consume should get BOTH items
    consumed = await lane_queue.consume_session_pending(session_key, lane_name="main")

    assert len(consumed) == 2
    # Check that both items are present (order doesn't matter)
    payloads = {item.payload for item in consumed}
    assert payloads == {"queued", "in_flight"}

    # Verify in_flight is now empty for this session
    assert session_key not in lane_queue._in_flight


@pytest.mark.asyncio
async def test_in_flight_tracking_during_process():
    """Test that items are correctly tracked as in-flight during process()."""
    from openpaw.core.queue.lane import LaneQueue, QueueItem

    lane_queue = LaneQueue()
    session_key = "test:123"
    processed_items = []

    async def handler(item: QueueItem):
        """Handler that records when items are processed."""
        # Check if item is in in_flight at start of processing
        in_flight_at_start = bool(lane_queue._in_flight.get(session_key))

        # Simulate work
        await asyncio.sleep(0.01)

        # Check if item is still in in_flight (should be removed by now)
        in_flight_at_end = bool(lane_queue._in_flight.get(session_key))

        processed_items.append({
            "item": item,
            "in_flight_at_start": in_flight_at_start,
            "in_flight_at_end": in_flight_at_end,
        })

    # Enqueue an item
    item = QueueItem(session_key=session_key, payload="test", mode=QueueMode.COLLECT)
    await lane_queue.enqueue(item, lane_name="main")

    # Start processing in background
    process_task = asyncio.create_task(lane_queue.process("main", handler))

    # Give it time to process
    await asyncio.sleep(0.05)

    # Cancel processing task
    process_task.cancel()
    try:
        await process_task
    except asyncio.CancelledError:
        pass

    # Verify item was processed
    assert len(processed_items) == 1
    # Item should NOT be in in_flight at start (removed before handler call)
    assert processed_items[0]["in_flight_at_start"] is False
    # Item should NOT be in in_flight at end
    assert processed_items[0]["in_flight_at_end"] is False
