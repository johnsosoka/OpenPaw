"""Tests for user identity injection via ContentCombiner."""

import pytest

from openpaw.model.message import Message
from openpaw.workspace.processors.combiner import ContentCombiner


@pytest.fixture
def combiner_with_aliases():
    """Create ContentCombiner with user aliases configured."""
    return ContentCombiner(user_aliases={123: "John", 456: "Sarah"})


@pytest.fixture
def combiner_no_aliases():
    """Create ContentCombiner with empty aliases."""
    return ContentCombiner(user_aliases={})


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
    def test_resolve_alias_match(self, combiner_with_aliases):
        assert combiner_with_aliases.resolve_user_name("123") == "John"

    def test_resolve_first_name_fallback(self, combiner_with_aliases):
        assert combiner_with_aliases.resolve_user_name("999", {"first_name": "Alice"}) == "Alice"

    def test_resolve_username_fallback(self, combiner_with_aliases):
        assert combiner_with_aliases.resolve_user_name("999", {"username": "alice123"}) == "alice123"

    def test_resolve_system_user_returns_none(self, combiner_with_aliases):
        assert combiner_with_aliases.resolve_user_name("system", {"first_name": "Bot"}) is None

    def test_resolve_empty_aliases_returns_none(self, combiner_no_aliases):
        assert combiner_no_aliases.resolve_user_name("123", {"first_name": "John"}) is None

    def test_resolve_non_numeric_user_id(self, combiner_with_aliases):
        assert combiner_with_aliases.resolve_user_name("user_abc", {"first_name": "Bob"}) == "Bob"

    def test_resolve_alias_precedence_over_metadata(self, combiner_with_aliases):
        assert combiner_with_aliases.resolve_user_name(
            "123",
            {"first_name": "Different", "username": "other"},
        ) == "John"

    def test_resolve_first_name_precedence_over_username(self, combiner_with_aliases):
        assert combiner_with_aliases.resolve_user_name(
            "999",
            {"first_name": "Alice", "username": "alice123"},
        ) == "Alice"

    def test_resolve_no_name_available(self, combiner_with_aliases):
        assert combiner_with_aliases.resolve_user_name("999", {}) is None


class TestBuildCombinedContent:
    def test_combined_single_message_with_alias(self, combiner_with_aliases):
        messages = [make_message("123", "hello")]
        result = combiner_with_aliases.build_combined_content(messages)
        assert result == "[John]: hello"

    def test_combined_multiple_users(self, combiner_with_aliases):
        messages = [
            make_message("123", "hello"),
            make_message("456", "hi"),
        ]
        result = combiner_with_aliases.build_combined_content(messages)
        assert result == "[John]: hello\n[Sarah]: hi"

    def test_combined_no_aliases(self, combiner_no_aliases):
        messages = [
            make_message("123", "hello", metadata={"first_name": "John"}),
            make_message("456", "hi", metadata={"first_name": "Sarah"}),
        ]
        result = combiner_no_aliases.build_combined_content(messages)
        assert result == "hello\nhi"

    def test_combined_mixed_aliased_and_system(self, combiner_with_aliases):
        messages = [
            make_message("123", "hello"),
            make_message("system", "heartbeat check"),
        ]
        result = combiner_with_aliases.build_combined_content(messages)
        assert result == "[John]: hello\nheartbeat check"

    def test_combined_empty_messages(self, combiner_with_aliases):
        result = combiner_with_aliases.build_combined_content([])
        assert result == ""

    def test_combined_single_message_no_name(self, combiner_with_aliases):
        messages = [make_message("999", "hello")]
        result = combiner_with_aliases.build_combined_content(messages)
        assert result == "hello"

    def test_combined_preserves_multiline_content(self, combiner_with_aliases):
        messages = [make_message("123", "line1\nline2\nline3")]
        result = combiner_with_aliases.build_combined_content(messages)
        assert result == "[John]: line1\nline2\nline3"


class TestBuildCombinedContentFromTuples:
    def test_tuples_with_message_objects(self, combiner_with_aliases):
        tuples = [
            ("channel1", make_message("123", "hello")),
            ("channel2", make_message("456", "hi")),
        ]
        result = combiner_with_aliases.build_combined_content_from_tuples(tuples)
        assert result == "[John]: hello\n[Sarah]: hi"

    def test_tuples_with_raw_strings(self, combiner_with_aliases):
        tuples = [
            ("channel1", "raw string 1"),
            ("channel2", "raw string 2"),
        ]
        result = combiner_with_aliases.build_combined_content_from_tuples(tuples)
        assert result == "raw string 1\nraw string 2"

    def test_tuples_mixed(self, combiner_with_aliases):
        tuples = [
            ("channel1", make_message("123", "hello from John")),
            ("channel2", "raw notification"),
            ("channel3", make_message("456", "hi from Sarah")),
        ]
        result = combiner_with_aliases.build_combined_content_from_tuples(tuples)
        assert result == "[John]: hello from John\nraw notification\n[Sarah]: hi from Sarah"

    def test_tuples_empty(self, combiner_with_aliases):
        result = combiner_with_aliases.build_combined_content_from_tuples([])
        assert result == ""

    def test_tuples_system_message_no_prefix(self, combiner_with_aliases):
        tuples = [
            ("channel1", make_message("system", "system event")),
            ("channel2", make_message("123", "user message")),
        ]
        result = combiner_with_aliases.build_combined_content_from_tuples(tuples)
        assert result == "system event\n[John]: user message"

    def test_tuples_no_aliases(self, combiner_no_aliases):
        tuples = [
            ("channel1", make_message("123", "hello", metadata={"first_name": "John"})),
            ("channel2", "raw string"),
        ]
        result = combiner_no_aliases.build_combined_content_from_tuples(tuples)
        assert result == "hello\nraw string"
