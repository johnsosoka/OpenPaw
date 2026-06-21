"""Integration tests for send_message tool with shared channel context."""

import pytest

from openpaw.builtins.tools._channel_context import (
    clear_channel_context,
    get_channel_context,
)
from openpaw.builtins.tools.send_message import SendMessageTool


class MockChannel:
    """Mock channel adapter for testing."""

    def __init__(self, name: str):
        self.name = name
        self.sent_messages = []

    async def send_message(self, session_key: str, content: str):
        """Record sent messages."""
        self.sent_messages.append((session_key, content))


def test_send_message_tool_uses_shared_context():
    """Test that SendMessageTool uses shared channel context."""
    # Arrange
    tool = SendMessageTool()
    mock_channel = MockChannel("telegram")
    session_key = "telegram:123456"

    # Act - set context via tool method
    tool.set_session_context(mock_channel, session_key)

    # Assert - context is available via shared module
    retrieved_channel, retrieved_session_key = get_channel_context()
    assert retrieved_channel is mock_channel
    assert retrieved_session_key == session_key

    # Cleanup
    clear_channel_context()


def test_send_message_tool_clear_uses_shared_context():
    """Test that clearing tool context clears shared context."""
    # Arrange
    tool = SendMessageTool()
    mock_channel = MockChannel("telegram")
    session_key = "telegram:123456"
    tool.set_session_context(mock_channel, session_key)

    # Act - clear via tool method
    tool.clear_session_context()

    # Assert - shared context is cleared
    retrieved_channel, retrieved_session_key = get_channel_context()
    assert retrieved_channel is None
    assert retrieved_session_key is None


@pytest.mark.asyncio
async def test_send_message_tool_async_with_context():
    """Test that send_message async tool function uses shared context."""
    # Arrange
    tool = SendMessageTool()
    langchain_tool = tool.get_langchain_tool()
    mock_channel = MockChannel("telegram")
    session_key = "telegram:123456"

    # Set context
    tool.set_session_context(mock_channel, session_key)

    # Act - invoke the tool async
    result = await langchain_tool.coroutine("Test message")

    # Assert
    assert "Message sent" in result
    assert len(mock_channel.sent_messages) == 1
    assert mock_channel.sent_messages[0] == (session_key, "Test message")

    # Cleanup
    tool.clear_session_context()


@pytest.mark.asyncio
async def test_send_message_tool_async_without_context():
    """Test that send_message returns error when context not set."""
    # Arrange
    tool = SendMessageTool()
    langchain_tool = tool.get_langchain_tool()

    # Ensure context is clear
    clear_channel_context()

    # Act
    result = await langchain_tool.coroutine("Test message")

    # Assert
    assert "Error" in result
    assert "not available" in result


def test_send_message_tool_sync_without_context():
    """Test that send_message sync returns error when context not set."""
    # Arrange
    tool = SendMessageTool()
    langchain_tool = tool.get_langchain_tool()

    # Ensure context is clear
    clear_channel_context()

    # Act
    result = langchain_tool.func("Test message")

    # Assert
    assert "Error" in result
    assert "not available" in result


def test_multiple_tools_share_same_context():
    """Test that multiple tool instances share the same context."""
    # Arrange
    tool1 = SendMessageTool()
    tool2 = SendMessageTool()
    mock_channel = MockChannel("telegram")
    session_key = "telegram:123456"

    # Act - set via tool1
    tool1.set_session_context(mock_channel, session_key)

    # Assert - tool2 sees the same context
    retrieved_channel, retrieved_session_key = get_channel_context()
    assert retrieved_channel is mock_channel
    assert retrieved_session_key == session_key

    # Act - clear via tool2
    tool2.clear_session_context()

    # Assert - context is cleared for both
    retrieved_channel, retrieved_session_key = get_channel_context()
    assert retrieved_channel is None
    assert retrieved_session_key is None
