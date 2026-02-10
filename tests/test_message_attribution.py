"""Tests for multi-user message attribution in MessageProcessor."""

from datetime import UTC, datetime

import pytest

from openpaw.channels.base import Message, MessageDirection


def test_single_user_no_attribution():
    """Test that single-user batches don't get attribution prefixes."""
    from openpaw.workspace.message_processor import MessageProcessor

    # Create a mock MessageProcessor (we only need the method)
    processor = _create_mock_processor()

    messages = [
        Message(
            id="1",
            channel="telegram",
            session_key="telegram:123",
            user_id="user_123",
            content="Hello",
            timestamp=datetime.now(UTC),
        ),
        Message(
            id="2",
            channel="telegram",
            session_key="telegram:123",
            user_id="user_123",
            content="How are you?",
            timestamp=datetime.now(UTC),
        ),
    ]

    result = processor._build_combined_content(messages)

    # Single user - no attribution
    assert result == "Hello\nHow are you?"
    assert "[" not in result


def test_multi_user_with_attribution():
    """Test that multi-user batches get attribution prefixes."""
    from openpaw.workspace.message_processor import MessageProcessor

    processor = _create_mock_processor()

    messages = [
        Message(
            id="1",
            channel="telegram",
            session_key="telegram:group1",
            user_id="user_123",
            content="Hello everyone",
            metadata={"first_name": "Alice"},
            timestamp=datetime.now(UTC),
        ),
        Message(
            id="2",
            channel="telegram",
            session_key="telegram:group1",
            user_id="user_456",
            content="Hi Alice!",
            metadata={"first_name": "Bob"},
            timestamp=datetime.now(UTC),
        ),
        Message(
            id="3",
            channel="telegram",
            session_key="telegram:group1",
            user_id="user_123",
            content="How's it going?",
            metadata={"first_name": "Alice"},
            timestamp=datetime.now(UTC),
        ),
    ]

    result = processor._build_combined_content(messages)

    # Multi-user - each message gets attribution
    assert result == "[Alice]: Hello everyone\n[Bob]: Hi Alice!\n[Alice]: How's it going?"


def test_system_messages_no_attribution():
    """Test that system messages are never attributed, even in multi-user batches."""
    from openpaw.workspace.message_processor import MessageProcessor

    processor = _create_mock_processor()

    messages = [
        Message(
            id="1",
            channel="telegram",
            session_key="telegram:group1",
            user_id="user_123",
            content="Starting task",
            metadata={"first_name": "Alice"},
            timestamp=datetime.now(UTC),
        ),
        Message(
            id="2",
            channel="telegram",
            session_key="telegram:group1",
            user_id="system",
            content="[SYSTEM] Task completed successfully",
            timestamp=datetime.now(UTC),
        ),
        Message(
            id="3",
            channel="telegram",
            session_key="telegram:group1",
            user_id="user_456",
            content="Great!",
            metadata={"first_name": "Bob"},
            timestamp=datetime.now(UTC),
        ),
    ]

    result = processor._build_combined_content(messages)

    # System messages don't get attribution prefix
    expected = (
        "[Alice]: Starting task\n"
        "[SYSTEM] Task completed successfully\n"
        "[Bob]: Great!"
    )
    assert result == expected


def test_display_name_fallback_chain():
    """Test display name resolution: first_name > username > user_id."""
    from openpaw.workspace.message_processor import MessageProcessor

    processor = _create_mock_processor()

    messages = [
        Message(
            id="1",
            channel="telegram",
            session_key="telegram:group1",
            user_id="user_123",
            content="I have first_name",
            metadata={"first_name": "Alice", "username": "alice_wonderland"},
            timestamp=datetime.now(UTC),
        ),
        Message(
            id="2",
            channel="telegram",
            session_key="telegram:group1",
            user_id="user_456",
            content="I have username only",
            metadata={"username": "bob_builder"},
            timestamp=datetime.now(UTC),
        ),
        Message(
            id="3",
            channel="telegram",
            session_key="telegram:group1",
            user_id="user_789",
            content="I have neither",
            metadata={},
            timestamp=datetime.now(UTC),
        ),
    ]

    result = processor._build_combined_content(messages)

    # Test fallback chain
    expected = (
        "[Alice]: I have first_name\n"
        "[bob_builder]: I have username only\n"
        "[user_789]: I have neither"
    )
    assert result == expected


def test_empty_messages():
    """Test that empty message list returns empty string."""
    from openpaw.workspace.message_processor import MessageProcessor

    processor = _create_mock_processor()

    result = processor._build_combined_content([])

    assert result == ""


def test_all_system_messages_no_attribution():
    """Test that batches with only system messages don't get attribution."""
    from openpaw.workspace.message_processor import MessageProcessor

    processor = _create_mock_processor()

    messages = [
        Message(
            id="1",
            channel="telegram",
            session_key="telegram:123",
            user_id="system",
            content="[SYSTEM] First message",
            timestamp=datetime.now(UTC),
        ),
        Message(
            id="2",
            channel="telegram",
            session_key="telegram:123",
            user_id="system",
            content="[SYSTEM] Second message",
            timestamp=datetime.now(UTC),
        ),
    ]

    result = processor._build_combined_content(messages)

    # All system messages - no attribution
    assert result == "[SYSTEM] First message\n[SYSTEM] Second message"
    assert "]: " not in result  # No attribution prefix pattern


def test_mixed_system_and_single_user():
    """Test that system messages mixed with single user don't trigger attribution."""
    from openpaw.workspace.message_processor import MessageProcessor

    processor = _create_mock_processor()

    messages = [
        Message(
            id="1",
            channel="telegram",
            session_key="telegram:123",
            user_id="user_123",
            content="User message",
            metadata={"first_name": "Alice"},
            timestamp=datetime.now(UTC),
        ),
        Message(
            id="2",
            channel="telegram",
            session_key="telegram:123",
            user_id="system",
            content="[SYSTEM] System message",
            timestamp=datetime.now(UTC),
        ),
    ]

    result = processor._build_combined_content(messages)

    # Single non-system user + system messages = no attribution
    assert result == "User message\n[SYSTEM] System message"
    assert "[Alice]:" not in result


def test_attribution_with_special_characters_in_name():
    """Test that display names with special characters are handled correctly."""
    from openpaw.workspace.message_processor import MessageProcessor

    processor = _create_mock_processor()

    messages = [
        Message(
            id="1",
            channel="telegram",
            session_key="telegram:group1",
            user_id="user_123",
            content="Message one",
            metadata={"first_name": "Alice [Admin]"},
            timestamp=datetime.now(UTC),
        ),
        Message(
            id="2",
            channel="telegram",
            session_key="telegram:group1",
            user_id="user_456",
            content="Message two",
            metadata={"first_name": "Bob: The Builder"},
            timestamp=datetime.now(UTC),
        ),
    ]

    result = processor._build_combined_content(messages)

    # Names with special chars should work fine
    expected = "[Alice [Admin]]: Message one\n[Bob: The Builder]: Message two"
    assert result == expected


def _create_mock_processor():
    """Create a minimal MessageProcessor instance for testing _build_combined_content."""
    from unittest.mock import MagicMock

    from openpaw.workspace.message_processor import MessageProcessor

    # Create mock dependencies
    agent_runner = MagicMock()
    session_manager = MagicMock()
    queue_manager = MagicMock()
    builtin_loader = MagicMock()
    queue_middleware = MagicMock()
    approval_middleware = MagicMock()
    approval_manager = None
    workspace_name = "test_workspace"
    token_logger = MagicMock()
    logger = MagicMock()

    processor = MessageProcessor(
        agent_runner=agent_runner,
        session_manager=session_manager,
        queue_manager=queue_manager,
        builtin_loader=builtin_loader,
        queue_middleware=queue_middleware,
        approval_middleware=approval_middleware,
        approval_manager=approval_manager,
        workspace_name=workspace_name,
        token_logger=token_logger,
        logger=logger,
    )

    return processor
