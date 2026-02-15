"""Tests for Message domain model."""

from datetime import datetime

import pytest

from openpaw.domain.message import Attachment, Message, MessageDirection


@pytest.fixture
def sample_message():
    """Create a sample message for testing."""
    return Message(
        id="msg_123",
        channel="telegram",
        session_key="telegram:456",
        user_id="456",
        content="Hello, world!",
        direction=MessageDirection.INBOUND,
        timestamp=datetime(2026, 2, 14, 12, 0, 0),
        reply_to_id="msg_122",
        metadata={"original_key": "original_value", "shared_key": "old_value"},
        attachments=[
            Attachment(type="image", filename="photo.jpg", mime_type="image/jpeg")
        ],
    )


def test_with_updates_content_only(sample_message):
    """Test updating content only."""
    updated = sample_message.with_updates(content="New content")

    assert updated.content == "New content"
    assert updated.metadata == sample_message.metadata
    assert updated.id == sample_message.id
    assert updated.channel == sample_message.channel
    assert updated.session_key == sample_message.session_key
    assert updated.user_id == sample_message.user_id
    assert updated.direction == sample_message.direction
    assert updated.timestamp == sample_message.timestamp
    assert updated.reply_to_id == sample_message.reply_to_id
    assert updated.attachments == sample_message.attachments


def test_with_updates_metadata_only(sample_message):
    """Test updating metadata only (no content change)."""
    updated = sample_message.with_updates(new_key="new_value", another_key=42)

    assert updated.content == sample_message.content
    assert updated.metadata == {
        "original_key": "original_value",
        "shared_key": "old_value",
        "new_key": "new_value",
        "another_key": 42,
    }
    assert updated.id == sample_message.id


def test_with_updates_both_content_and_metadata(sample_message):
    """Test updating both content and metadata."""
    updated = sample_message.with_updates(
        content="Updated content", processor="test_processor", status="processed"
    )

    assert updated.content == "Updated content"
    assert updated.metadata == {
        "original_key": "original_value",
        "shared_key": "old_value",
        "processor": "test_processor",
        "status": "processed",
    }


def test_with_updates_no_arguments(sample_message):
    """Test with_updates with no arguments returns equivalent message."""
    updated = sample_message.with_updates()

    assert updated.content == sample_message.content
    assert updated.metadata == sample_message.metadata
    assert updated.id == sample_message.id
    assert updated.channel == sample_message.channel
    assert updated.session_key == sample_message.session_key
    assert updated.user_id == sample_message.user_id
    assert updated.direction == sample_message.direction
    assert updated.timestamp == sample_message.timestamp
    assert updated.reply_to_id == sample_message.reply_to_id
    assert updated.attachments == sample_message.attachments


def test_with_updates_metadata_merging(sample_message):
    """Test metadata merging: existing keys preserved, new keys added."""
    updated = sample_message.with_updates(new_key="added")

    assert "original_key" in updated.metadata
    assert "shared_key" in updated.metadata
    assert "new_key" in updated.metadata
    assert updated.metadata["original_key"] == "original_value"
    assert updated.metadata["new_key"] == "added"


def test_with_updates_metadata_override(sample_message):
    """Test metadata override: overlapping key uses new value."""
    updated = sample_message.with_updates(shared_key="new_value")

    assert updated.metadata["shared_key"] == "new_value"
    assert updated.metadata["original_key"] == "original_value"


def test_with_updates_attachments_shared_reference(sample_message):
    """Test attachments are shared by reference (same list object)."""
    updated = sample_message.with_updates(content="Changed")

    assert updated.attachments is sample_message.attachments
    assert len(updated.attachments) == 1
    assert updated.attachments[0].filename == "photo.jpg"


def test_with_updates_original_not_mutated(sample_message):
    """Test original message is not mutated."""
    original_content = sample_message.content
    original_metadata = sample_message.metadata.copy()

    sample_message.with_updates(content="New content", new_key="new_value")

    assert sample_message.content == original_content
    assert sample_message.metadata == original_metadata


def test_with_updates_all_identity_fields_preserved(sample_message):
    """Test all identity fields preserved across update."""
    updated = sample_message.with_updates(
        content="Different content", metadata_key="metadata_value"
    )

    assert updated.id == "msg_123"
    assert updated.channel == "telegram"
    assert updated.session_key == "telegram:456"
    assert updated.user_id == "456"
    assert updated.direction == MessageDirection.INBOUND
    assert updated.timestamp == datetime(2026, 2, 14, 12, 0, 0)
    assert updated.reply_to_id == "msg_122"


def test_with_updates_empty_metadata_message():
    """Test with_updates on message with empty metadata."""
    msg = Message(
        id="msg_1",
        channel="test",
        session_key="test:1",
        user_id="1",
        content="Test",
    )

    updated = msg.with_updates(new_key="value")

    assert updated.metadata == {"new_key": "value"}


def test_with_updates_complex_metadata_values():
    """Test with_updates handles complex metadata values."""
    msg = Message(
        id="msg_1",
        channel="test",
        session_key="test:1",
        user_id="1",
        content="Test",
        metadata={"list": [1, 2, 3], "dict": {"nested": "value"}},
    )

    updated = msg.with_updates(
        new_list=[4, 5, 6], new_dict={"another": "nested"}
    )

    assert updated.metadata["list"] == [1, 2, 3]
    assert updated.metadata["dict"] == {"nested": "value"}
    assert updated.metadata["new_list"] == [4, 5, 6]
    assert updated.metadata["new_dict"] == {"another": "nested"}
