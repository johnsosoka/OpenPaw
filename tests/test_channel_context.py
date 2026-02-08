"""Tests for shared channel context module."""

import pytest

from openpaw.builtins.tools._channel_context import (
    clear_channel_context,
    get_channel_context,
    set_channel_context,
)


class MockChannel:
    """Mock channel adapter for testing."""

    def __init__(self, name: str):
        self.name = name


def test_set_and_get_channel_context():
    """Test setting and getting channel context."""
    # Arrange
    mock_channel = MockChannel("telegram")
    session_key = "telegram:123456"

    # Act
    set_channel_context(mock_channel, session_key)
    retrieved_channel, retrieved_session_key = get_channel_context()

    # Assert
    assert retrieved_channel is mock_channel
    assert retrieved_session_key == session_key


def test_clear_channel_context():
    """Test clearing channel context."""
    # Arrange
    mock_channel = MockChannel("telegram")
    session_key = "telegram:123456"
    set_channel_context(mock_channel, session_key)

    # Act
    clear_channel_context()
    retrieved_channel, retrieved_session_key = get_channel_context()

    # Assert
    assert retrieved_channel is None
    assert retrieved_session_key is None


def test_get_channel_context_when_not_set():
    """Test getting context when it has never been set."""
    # Arrange - start with fresh context
    clear_channel_context()

    # Act
    retrieved_channel, retrieved_session_key = get_channel_context()

    # Assert
    assert retrieved_channel is None
    assert retrieved_session_key is None


def test_context_isolation_between_calls():
    """Test that context can be set multiple times without interference."""
    # Arrange
    channel1 = MockChannel("telegram")
    session1 = "telegram:111111"
    channel2 = MockChannel("slack")
    session2 = "slack:222222"

    # Act - set first context
    set_channel_context(channel1, session1)
    c1, s1 = get_channel_context()

    # Act - override with second context
    set_channel_context(channel2, session2)
    c2, s2 = get_channel_context()

    # Assert - second context replaced first
    assert c1 is channel1
    assert s1 == session1
    assert c2 is channel2
    assert s2 == session2


def test_set_clear_cycle():
    """Test multiple set/clear cycles."""
    # Arrange
    mock_channel = MockChannel("telegram")
    session_key = "telegram:123456"

    # Cycle 1
    set_channel_context(mock_channel, session_key)
    channel, key = get_channel_context()
    assert channel is mock_channel
    assert key == session_key

    clear_channel_context()
    channel, key = get_channel_context()
    assert channel is None
    assert key is None

    # Cycle 2
    set_channel_context(mock_channel, session_key)
    channel, key = get_channel_context()
    assert channel is mock_channel
    assert key == session_key

    clear_channel_context()
    channel, key = get_channel_context()
    assert channel is None
    assert key is None


@pytest.mark.asyncio
async def test_context_in_async_context():
    """Test that context vars work correctly in async functions."""
    # Arrange
    mock_channel = MockChannel("telegram")
    session_key = "telegram:async123"

    # Act
    set_channel_context(mock_channel, session_key)

    # Simulate async work
    async def get_context_async():
        return get_channel_context()

    retrieved_channel, retrieved_session_key = await get_context_async()

    # Assert
    assert retrieved_channel is mock_channel
    assert retrieved_session_key == session_key

    # Cleanup
    clear_channel_context()
