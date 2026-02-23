"""Tests for user identity injection in MessageProcessor."""

from datetime import datetime
from unittest.mock import MagicMock

import pytest

from openpaw.model.message import Message, MessageDirection
from openpaw.workspace.message_processor import MessageProcessor


@pytest.fixture
def mock_processor_deps():
    """Create mock dependencies for MessageProcessor instantiation."""
    return {
        "agent_runner": MagicMock(),
        "session_manager": MagicMock(),
        "queue_manager": MagicMock(),
        "builtin_loader": MagicMock(),
        "queue_middleware": MagicMock(),
        "approval_middleware": MagicMock(),
        "approval_manager": None,
        "workspace_name": "test_workspace",
        "token_logger": MagicMock(),
        "logger": MagicMock(),
    }


@pytest.fixture
def processor_with_aliases(mock_processor_deps):
    """Create MessageProcessor with user aliases configured."""
    user_aliases = {123: "John", 456: "Sarah"}
    return MessageProcessor(**mock_processor_deps, user_aliases=user_aliases)


@pytest.fixture
def processor_no_aliases(mock_processor_deps):
    """Create MessageProcessor with empty aliases."""
    return MessageProcessor(**mock_processor_deps, user_aliases={})


def make_message(
    user_id: str,
    content: str,
    metadata: dict | None = None,
) -> Message:
    """Helper to create a Message with minimal required fields."""
    return Message(
        id="msg_1",
        channel="telegram",
        session_key="telegram:123",
        user_id=user_id,
        content=content,
        metadata=metadata or {},
    )


class TestResolveUserName:
    def test_resolve_alias_match(self, processor_with_aliases):
        msg = make_message("123", "hello")
        assert processor_with_aliases._resolve_user_name(msg) == "John"

    def test_resolve_first_name_fallback(self, processor_with_aliases):
        msg = make_message("999", "hello", metadata={"first_name": "Alice"})
        assert processor_with_aliases._resolve_user_name(msg) == "Alice"

    def test_resolve_username_fallback(self, processor_with_aliases):
        msg = make_message("999", "hello", metadata={"username": "alice123"})
        assert processor_with_aliases._resolve_user_name(msg) == "alice123"

    def test_resolve_system_user_returns_none(self, processor_with_aliases):
        msg = make_message("system", "heartbeat")
        assert processor_with_aliases._resolve_user_name(msg) is None

    def test_resolve_empty_aliases_returns_none(self, processor_no_aliases):
        msg = make_message("123", "hello", metadata={"first_name": "John"})
        assert processor_no_aliases._resolve_user_name(msg) is None

    def test_resolve_non_numeric_user_id(self, processor_with_aliases):
        msg = make_message("user_abc", "hello", metadata={"first_name": "Bob"})
        assert processor_with_aliases._resolve_user_name(msg) == "Bob"

    def test_resolve_alias_precedence_over_metadata(self, processor_with_aliases):
        msg = make_message(
            "123",
            "hello",
            metadata={"first_name": "Different", "username": "other"},
        )
        assert processor_with_aliases._resolve_user_name(msg) == "John"

    def test_resolve_first_name_precedence_over_username(self, processor_with_aliases):
        msg = make_message(
            "999",
            "hello",
            metadata={"first_name": "Alice", "username": "alice123"},
        )
        assert processor_with_aliases._resolve_user_name(msg) == "Alice"

    def test_resolve_no_name_available(self, processor_with_aliases):
        msg = make_message("999", "hello", metadata={})
        assert processor_with_aliases._resolve_user_name(msg) is None


class TestBuildCombinedContent:
    def test_combined_single_message_with_alias(self, processor_with_aliases):
        messages = [make_message("123", "hello")]
        result = processor_with_aliases._build_combined_content(messages)
        assert result == "[John]: hello"

    def test_combined_multiple_users(self, processor_with_aliases):
        messages = [
            make_message("123", "hello"),
            make_message("456", "hi"),
        ]
        result = processor_with_aliases._build_combined_content(messages)
        assert result == "[John]: hello\n[Sarah]: hi"

    def test_combined_no_aliases(self, processor_no_aliases):
        messages = [
            make_message("123", "hello", metadata={"first_name": "John"}),
            make_message("456", "hi", metadata={"first_name": "Sarah"}),
        ]
        result = processor_no_aliases._build_combined_content(messages)
        assert result == "hello\nhi"

    def test_combined_mixed_aliased_and_system(self, processor_with_aliases):
        messages = [
            make_message("123", "hello"),
            make_message("system", "heartbeat check"),
        ]
        result = processor_with_aliases._build_combined_content(messages)
        assert result == "[John]: hello\nheartbeat check"

    def test_combined_empty_messages(self, processor_with_aliases):
        result = processor_with_aliases._build_combined_content([])
        assert result == ""

    def test_combined_single_message_no_name(self, processor_with_aliases):
        messages = [make_message("999", "hello")]
        result = processor_with_aliases._build_combined_content(messages)
        assert result == "hello"

    def test_combined_preserves_multiline_content(self, processor_with_aliases):
        messages = [make_message("123", "line1\nline2\nline3")]
        result = processor_with_aliases._build_combined_content(messages)
        assert result == "[John]: line1\nline2\nline3"


class TestBuildCombinedContentFromTuples:
    def test_tuples_with_message_objects(self, processor_with_aliases):
        tuples = [
            ("channel1", make_message("123", "hello")),
            ("channel2", make_message("456", "hi")),
        ]
        result = processor_with_aliases._build_combined_content_from_tuples(tuples)
        assert result == "[John]: hello\n[Sarah]: hi"

    def test_tuples_with_raw_strings(self, processor_with_aliases):
        tuples = [
            ("channel1", "raw string 1"),
            ("channel2", "raw string 2"),
        ]
        result = processor_with_aliases._build_combined_content_from_tuples(tuples)
        assert result == "raw string 1\nraw string 2"

    def test_tuples_mixed(self, processor_with_aliases):
        tuples = [
            ("channel1", make_message("123", "hello from John")),
            ("channel2", "raw notification"),
            ("channel3", make_message("456", "hi from Sarah")),
        ]
        result = processor_with_aliases._build_combined_content_from_tuples(tuples)
        assert result == "[John]: hello from John\nraw notification\n[Sarah]: hi from Sarah"

    def test_tuples_empty(self, processor_with_aliases):
        result = processor_with_aliases._build_combined_content_from_tuples([])
        assert result == ""

    def test_tuples_system_message_no_prefix(self, processor_with_aliases):
        tuples = [
            ("channel1", make_message("system", "system event")),
            ("channel2", make_message("123", "user message")),
        ]
        result = processor_with_aliases._build_combined_content_from_tuples(tuples)
        assert result == "system event\n[John]: user message"

    def test_tuples_no_aliases(self, processor_no_aliases):
        tuples = [
            ("channel1", make_message("123", "hello", metadata={"first_name": "John"})),
            ("channel2", "raw string"),
        ]
        result = processor_no_aliases._build_combined_content_from_tuples(tuples)
        assert result == "hello\nraw string"
