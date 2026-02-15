"""Tests for typing indicator functionality."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from openpaw.channels.base import MessageDirection
from openpaw.channels.telegram import TelegramChannel
from openpaw.domain.message import Message


@pytest.mark.asyncio
async def test_send_typing_action_extracts_chat_id() -> None:
    """Test that send_typing_action correctly extracts chat_id from session_key."""
    channel = TelegramChannel(
        token="test-token",
        allowed_users=[12345],
        workspace_name="test",
    )

    # Mock the Telegram application and bot
    mock_app = MagicMock()
    mock_bot = AsyncMock()
    mock_app.bot = mock_bot
    channel._app = mock_app

    # Call send_typing_action with a properly formatted session_key
    await channel.send_typing_action("telegram:67890")

    # Verify send_chat_action was called with correct parameters
    mock_bot.send_chat_action.assert_called_once_with(
        chat_id=67890,
        action="typing",
    )


@pytest.mark.asyncio
async def test_send_typing_action_handles_errors_gracefully() -> None:
    """Test that send_typing_action doesn't raise exceptions on failure."""
    channel = TelegramChannel(
        token="test-token",
        allowed_users=[12345],
        workspace_name="test",
    )

    # Mock the Telegram application with a bot that raises an exception
    mock_app = MagicMock()
    mock_bot = AsyncMock()
    mock_bot.send_chat_action.side_effect = Exception("Network error")
    mock_app.bot = mock_bot
    channel._app = mock_app

    # Should not raise an exception
    await channel.send_typing_action("telegram:67890")


@pytest.mark.asyncio
async def test_send_typing_action_when_app_not_started() -> None:
    """Test that send_typing_action is a no-op when channel not started."""
    channel = TelegramChannel(
        token="test-token",
        allowed_users=[12345],
        workspace_name="test",
    )

    # _app is None when channel not started
    assert channel._app is None

    # Should not raise an exception
    await channel.send_typing_action("telegram:67890")


@pytest.mark.asyncio
async def test_send_typing_action_with_malformed_session_key() -> None:
    """Test that send_typing_action handles malformed session keys gracefully."""
    channel = TelegramChannel(
        token="test-token",
        allowed_users=[12345],
        workspace_name="test",
    )

    # Mock the Telegram application and bot
    mock_app = MagicMock()
    mock_bot = AsyncMock()
    mock_app.bot = mock_bot
    channel._app = mock_app

    # Test with session key without colon (falls back to using whole string)
    await channel.send_typing_action("12345")
    mock_bot.send_chat_action.assert_called_once_with(
        chat_id=12345,
        action="typing",
    )


@pytest.mark.asyncio
async def test_base_channel_send_typing_action_is_noop() -> None:
    """Test that base ChannelAdapter send_typing_action is a no-op."""
    from openpaw.channels.base import ChannelAdapter

    # Create a minimal concrete implementation
    class TestChannel(ChannelAdapter):
        name = "test"

        async def start(self) -> None:
            pass

        async def stop(self) -> None:
            pass

        async def send_message(self, session_key: str, content: str, **kwargs) -> Message:
            return Message(
                id="1",
                channel=self.name,
                session_key=session_key,
                user_id="bot",
                content=content,
                direction=MessageDirection.OUTBOUND,
                timestamp=datetime.now(),
            )

        def on_message(self, callback) -> None:
            pass

    channel = TestChannel()

    # Should not raise an exception (no-op by default)
    await channel.send_typing_action("test:123")


@pytest.mark.asyncio
async def test_typing_indicator_sent_when_session_active() -> None:
    """Test that typing indicator is sent when session lock is held."""
    from openpaw.core.queue.lane import LaneQueue

    # Create a lane queue
    lane_queue = LaneQueue()

    # Create a mock message
    message = Message(
        id="1",
        channel="telegram",
        session_key="telegram:12345",
        user_id="67890",
        content="Hello",
        direction=MessageDirection.INBOUND,
        timestamp=datetime.now(),
    )

    # Create a mock channel with send_typing_action
    mock_channel = AsyncMock()
    mock_channel.send_typing_action = AsyncMock()

    # Acquire the session lock to simulate an active agent run
    session_lock = await lane_queue.get_session_lock(message.session_key)

    async with session_lock:
        # Check if lock is held
        if session_lock.locked():
            await mock_channel.send_typing_action(message.session_key)

    # Verify typing indicator was sent
    mock_channel.send_typing_action.assert_called_once_with(message.session_key)


@pytest.mark.asyncio
async def test_typing_indicator_not_sent_when_session_idle() -> None:
    """Test that typing indicator is not sent when session lock is not held."""
    from openpaw.core.queue.lane import LaneQueue

    # Create a lane queue
    lane_queue = LaneQueue()

    # Create a mock message
    message = Message(
        id="1",
        channel="telegram",
        session_key="telegram:12345",
        user_id="67890",
        content="Hello",
        direction=MessageDirection.INBOUND,
        timestamp=datetime.now(),
    )

    # Create a mock channel with send_typing_action
    mock_channel = AsyncMock()
    mock_channel.send_typing_action = AsyncMock()

    # Get the session lock but don't acquire it (session is idle)
    session_lock = await lane_queue.get_session_lock(message.session_key)

    # Check if lock is held (it shouldn't be)
    if session_lock.locked():
        await mock_channel.send_typing_action(message.session_key)

    # Verify typing indicator was NOT sent
    mock_channel.send_typing_action.assert_not_called()


@pytest.mark.asyncio
async def test_typing_indicator_concurrent_messages() -> None:
    """Test typing indicator behavior with multiple concurrent messages."""
    from openpaw.core.queue.lane import LaneQueue

    lane_queue = LaneQueue()
    session_key = "telegram:12345"

    # Create a mock channel
    mock_channel = AsyncMock()
    mock_channel.send_typing_action = AsyncMock()

    # Acquire session lock to simulate active processing
    session_lock = await lane_queue.get_session_lock(session_key)

    async with session_lock:
        # Simulate multiple messages arriving during processing
        for i in range(3):
            check_lock = await lane_queue.get_session_lock(session_key)
            if check_lock.locked():
                await mock_channel.send_typing_action(session_key)

    # Verify typing indicator was sent for each message
    assert mock_channel.send_typing_action.call_count == 3
