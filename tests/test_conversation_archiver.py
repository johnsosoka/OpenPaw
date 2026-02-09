"""Tests for ConversationArchiver."""

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from openpaw.runtime.session.archiver import ConversationArchive, ConversationArchiver


@pytest.fixture
def archiver(tmp_path: Path) -> ConversationArchiver:
    """Create a ConversationArchiver for testing."""
    return ConversationArchiver(tmp_path, "test_workspace")


@pytest.fixture
def mock_checkpointer():
    """Create a mock checkpointer with sample messages."""
    checkpointer = AsyncMock()
    checkpoint_tuple = MagicMock()

    # Sample conversation
    checkpoint_tuple.checkpoint = {
        "channel_values": {
            "messages": [
                HumanMessage(content="Hello, can you help me?"),
                AIMessage(content="Of course! What do you need help with?"),
                HumanMessage(content="I need to search for Python async patterns"),
                AIMessage(
                    content="Let me search for that.",
                    tool_calls=[
                        {
                            "name": "brave_search",
                            "args": {"query": "Python asyncio patterns"},
                            "id": "call_123",
                        }
                    ],
                ),
                ToolMessage(
                    content="Found 5 results about Python asyncio patterns...",
                    tool_call_id="call_123",
                ),
                AIMessage(content="Based on my research, here's what I found..."),
            ]
        }
    }

    checkpointer.aget_tuple.return_value = checkpoint_tuple
    return checkpointer


@pytest.fixture
def empty_checkpointer():
    """Create a mock checkpointer with no messages."""
    checkpointer = AsyncMock()
    checkpoint_tuple = MagicMock()
    checkpoint_tuple.checkpoint = {"channel_values": {"messages": []}}
    checkpointer.aget_tuple.return_value = checkpoint_tuple
    return checkpointer


@pytest.mark.asyncio
async def test_archive_creates_files(archiver: ConversationArchiver, mock_checkpointer):
    """Test that archive creates both .md and .json files."""
    archive = await archiver.archive(
        checkpointer=mock_checkpointer,
        thread_id="telegram:123456:conv_2026-02-07T14-30-00",
        session_key="telegram:123456",
        conversation_id="conv_2026-02-07T14-30-00",
    )

    assert archive is not None
    assert archive.markdown_path.exists()
    assert archive.json_path.exists()
    assert archive.message_count == 6


@pytest.mark.asyncio
async def test_archive_markdown_format(archiver: ConversationArchiver, mock_checkpointer):
    """Test that markdown file contains expected sections."""
    archive = await archiver.archive(
        checkpointer=mock_checkpointer,
        thread_id="telegram:123456:conv_2026-02-07T14-30-00",
        session_key="telegram:123456",
        conversation_id="conv_2026-02-07T14-30-00",
    )

    markdown_content = archive.markdown_path.read_text()

    # Check header
    assert "# Conversation Archive" in markdown_content
    assert "**ID:** conv_2026-02-07T14-30-00" in markdown_content
    assert "**Session:** telegram:123456" in markdown_content
    assert "**Workspace:** test_workspace" in markdown_content
    assert "**Messages:** 6" in markdown_content

    # Check message content
    assert "**[User]**" in markdown_content
    assert "Hello, can you help me?" in markdown_content
    assert "**[Agent]**" in markdown_content
    assert "Of course! What do you need help with?" in markdown_content
    assert "**[Tool Call: brave_search]**" in markdown_content
    assert "**[Tool Result]**" in markdown_content


@pytest.mark.asyncio
async def test_archive_json_format(archiver: ConversationArchiver, mock_checkpointer):
    """Test that JSON file has correct structure."""
    archive = await archiver.archive(
        checkpointer=mock_checkpointer,
        thread_id="telegram:123456:conv_2026-02-07T14-30-00",
        session_key="telegram:123456",
        conversation_id="conv_2026-02-07T14-30-00",
    )

    with archive.json_path.open("r") as f:
        data = json.load(f)

    # Check metadata
    assert data["conversation_id"] == "conv_2026-02-07T14-30-00"
    assert data["session_key"] == "telegram:123456"
    assert data["workspace_name"] == "test_workspace"
    assert data["message_count"] == 6
    assert data["summary"] is None
    assert data["tags"] == []

    # Check messages
    assert len(data["messages"]) == 6
    assert data["messages"][0]["role"] == "human"
    assert data["messages"][0]["content"] == "Hello, can you help me?"
    assert data["messages"][1]["role"] == "ai"
    assert data["messages"][3]["role"] == "ai"
    assert data["messages"][3]["tool_calls"] is not None
    assert len(data["messages"][3]["tool_calls"]) == 1
    assert data["messages"][3]["tool_calls"][0]["name"] == "brave_search"
    assert data["messages"][4]["role"] == "tool"
    assert data["messages"][4]["tool_call_id"] == "call_123"


@pytest.mark.asyncio
async def test_archive_empty_conversation(archiver: ConversationArchiver, empty_checkpointer):
    """Test that archive returns None for empty conversation."""
    archive = await archiver.archive(
        checkpointer=empty_checkpointer,
        thread_id="telegram:123456:conv_empty",
        session_key="telegram:123456",
        conversation_id="conv_empty",
    )

    assert archive is None


@pytest.mark.asyncio
async def test_archive_with_summary(archiver: ConversationArchiver, mock_checkpointer):
    """Test that summary section appears in markdown."""
    summary_text = "This conversation was about Python async patterns."

    archive = await archiver.archive(
        checkpointer=mock_checkpointer,
        thread_id="telegram:123456:conv_2026-02-07T14-30-00",
        session_key="telegram:123456",
        conversation_id="conv_2026-02-07T14-30-00",
        summary=summary_text,
    )

    # Check markdown
    markdown_content = archive.markdown_path.read_text()
    assert "## Summary" in markdown_content
    assert summary_text in markdown_content

    # Check JSON
    with archive.json_path.open("r") as f:
        data = json.load(f)
    assert data["summary"] == summary_text


@pytest.mark.asyncio
async def test_archive_with_tool_calls(archiver: ConversationArchiver, mock_checkpointer):
    """Test that tool calls appear in both formats."""
    archive = await archiver.archive(
        checkpointer=mock_checkpointer,
        thread_id="telegram:123456:conv_2026-02-07T14-30-00",
        session_key="telegram:123456",
        conversation_id="conv_2026-02-07T14-30-00",
    )

    # Check markdown
    markdown_content = archive.markdown_path.read_text()
    assert "**[Tool Call: brave_search]**" in markdown_content
    assert "query: Python asyncio patterns" in markdown_content

    # Check JSON
    with archive.json_path.open("r") as f:
        data = json.load(f)

    # Find the AI message with tool call
    ai_messages_with_tools = [
        msg for msg in data["messages"]
        if msg["role"] == "ai" and msg["tool_calls"] is not None
    ]
    assert len(ai_messages_with_tools) == 1
    assert ai_messages_with_tools[0]["tool_calls"][0]["name"] == "brave_search"
    assert ai_messages_with_tools[0]["tool_calls"][0]["args"]["query"] == "Python asyncio patterns"
    assert ai_messages_with_tools[0]["tool_calls"][0]["id"] == "call_123"


@pytest.mark.asyncio
async def test_list_archives(archiver: ConversationArchiver, mock_checkpointer):
    """Test that list_archives returns all archives."""
    # Create multiple archives
    await archiver.archive(
        checkpointer=mock_checkpointer,
        thread_id="telegram:123:conv_1",
        session_key="telegram:123",
        conversation_id="conv_1",
    )

    await archiver.archive(
        checkpointer=mock_checkpointer,
        thread_id="telegram:456:conv_2",
        session_key="telegram:456",
        conversation_id="conv_2",
    )

    await archiver.archive(
        checkpointer=mock_checkpointer,
        thread_id="telegram:789:conv_3",
        session_key="telegram:789",
        conversation_id="conv_3",
    )

    # List archives
    archives = archiver.list_archives()

    assert len(archives) == 3
    assert all(isinstance(a, ConversationArchive) for a in archives)

    # Check that all conversation IDs are present
    conv_ids = {a.conversation_id for a in archives}
    assert conv_ids == {"conv_1", "conv_2", "conv_3"}


@pytest.mark.asyncio
async def test_list_archives_limit(archiver: ConversationArchiver, mock_checkpointer):
    """Test that list_archives respects limit."""
    # Create 5 archives
    for i in range(5):
        await archiver.archive(
            checkpointer=mock_checkpointer,
            thread_id=f"telegram:123:conv_{i}",
            session_key="telegram:123",
            conversation_id=f"conv_{i}",
        )

    # Request only 3
    archives = archiver.list_archives(limit=3)

    assert len(archives) == 3


@pytest.mark.asyncio
async def test_list_archives_sorted_by_ended_at(archiver: ConversationArchiver, mock_checkpointer):
    """Test that list_archives returns archives sorted by ended_at (most recent first)."""
    # Create archives in specific order
    await archiver.archive(
        checkpointer=mock_checkpointer,
        thread_id="telegram:123:conv_old",
        session_key="telegram:123",
        conversation_id="conv_old",
    )

    # Small delay to ensure different timestamps
    import asyncio
    await asyncio.sleep(0.01)

    await archiver.archive(
        checkpointer=mock_checkpointer,
        thread_id="telegram:123:conv_new",
        session_key="telegram:123",
        conversation_id="conv_new",
    )

    archives = archiver.list_archives()

    # Most recent should be first
    assert archives[0].conversation_id == "conv_new"
    assert archives[1].conversation_id == "conv_old"
    assert archives[0].ended_at > archives[1].ended_at


@pytest.mark.asyncio
async def test_archive_with_tags(archiver: ConversationArchiver, mock_checkpointer):
    """Test that tags are stored in JSON metadata."""
    tags = ["shutdown", "manual", "important"]

    archive = await archiver.archive(
        checkpointer=mock_checkpointer,
        thread_id="telegram:123456:conv_tagged",
        session_key="telegram:123456",
        conversation_id="conv_tagged",
        tags=tags,
    )

    # Check in-memory archive object
    assert archive.tags == tags

    # Check JSON file
    with archive.json_path.open("r") as f:
        data = json.load(f)
    assert data["tags"] == tags


@pytest.mark.asyncio
async def test_archive_no_checkpoint(archiver: ConversationArchiver):
    """Test that archive returns None when checkpointer has no checkpoint."""
    checkpointer = AsyncMock()
    checkpointer.aget_tuple.return_value = None

    archive = await archiver.archive(
        checkpointer=checkpointer,
        thread_id="telegram:123:conv_missing",
        session_key="telegram:123",
        conversation_id="conv_missing",
    )

    assert archive is None


@pytest.mark.asyncio
async def test_archive_directory_created(tmp_path: Path):
    """Test that archiver creates memory/conversations directory."""
    archiver = ConversationArchiver(tmp_path, "test_workspace")

    archive_dir = tmp_path / "memory" / "conversations"
    assert archive_dir.exists()
    assert archive_dir.is_dir()


@pytest.mark.asyncio
async def test_conversation_archive_roundtrip(archiver: ConversationArchiver, mock_checkpointer):
    """Test that ConversationArchive can be serialized and deserialized."""
    # Create archive
    original = await archiver.archive(
        checkpointer=mock_checkpointer,
        thread_id="telegram:123:conv_roundtrip",
        session_key="telegram:123",
        conversation_id="conv_roundtrip",
        summary="Test summary",
        tags=["test", "roundtrip"],
    )

    # Serialize to dict
    data = original.to_dict()

    # Deserialize from JSON file
    with original.json_path.open("r") as f:
        json_data = json.load(f)

    restored = ConversationArchive.from_json(json_data, archiver._workspace_path)

    # Verify fields match
    assert restored.conversation_id == original.conversation_id
    assert restored.session_key == original.session_key
    assert restored.workspace_name == original.workspace_name
    assert restored.message_count == original.message_count
    assert restored.summary == original.summary
    assert restored.tags == original.tags
    assert restored.markdown_path == original.markdown_path
    assert restored.json_path == original.json_path


@pytest.mark.asyncio
async def test_list_archives_handles_corrupted_json(archiver: ConversationArchiver, mock_checkpointer):
    """Test that list_archives handles corrupted JSON gracefully."""
    # Create a valid archive
    await archiver.archive(
        checkpointer=mock_checkpointer,
        thread_id="telegram:123:conv_valid",
        session_key="telegram:123",
        conversation_id="conv_valid",
    )

    # Create a corrupted JSON file
    corrupted_path = archiver._archive_dir / "conv_corrupted.json"
    corrupted_path.write_text("{this is not valid json")

    # list_archives should skip corrupted file and return valid archives
    archives = archiver.list_archives()

    assert len(archives) == 1
    assert archives[0].conversation_id == "conv_valid"


@pytest.mark.asyncio
async def test_archive_metadata_fields(archiver: ConversationArchiver, mock_checkpointer):
    """Test that all ConversationArchive metadata fields are populated correctly."""
    archive = await archiver.archive(
        checkpointer=mock_checkpointer,
        thread_id="telegram:123456:conv_2026-02-07T14-30-00",
        session_key="telegram:123456",
        conversation_id="conv_2026-02-07T14-30-00",
        summary="Test summary",
        tags=["tag1", "tag2"],
    )

    assert archive.conversation_id == "conv_2026-02-07T14-30-00"
    assert archive.session_key == "telegram:123456"
    assert archive.workspace_name == "test_workspace"
    assert isinstance(archive.started_at, datetime)
    assert isinstance(archive.ended_at, datetime)
    assert archive.message_count == 6
    assert archive.summary == "Test summary"
    assert archive.tags == ["tag1", "tag2"]
    assert archive.markdown_path.name == "conv_2026-02-07T14-30-00.md"
    assert archive.json_path.name == "conv_2026-02-07T14-30-00.json"


@pytest.mark.asyncio
async def test_archive_timezone_aware_display(tmp_path: Path, mock_checkpointer):
    """Test that markdown timestamps use workspace timezone for display."""
    # Create archiver with America/Denver timezone
    archiver = ConversationArchiver(tmp_path, "test_workspace", timezone="America/Denver")

    # Create a known UTC timestamp
    utc_dt = datetime(2026, 2, 8, 17, 30, 0, tzinfo=ZoneInfo("UTC"))

    # Modify mock_checkpointer to use our known timestamp
    checkpoint_tuple = MagicMock()
    checkpoint_tuple.checkpoint = {
        "channel_values": {
            "messages": [
                HumanMessage(
                    content="Test message",
                    additional_kwargs={"timestamp": utc_dt}
                ),
            ]
        }
    }
    mock_checkpointer.aget_tuple.return_value = checkpoint_tuple

    archive = await archiver.archive(
        checkpointer=mock_checkpointer,
        thread_id="telegram:123:conv_tz_test",
        session_key="telegram:123",
        conversation_id="conv_tz_test",
    )

    # Read markdown content
    markdown_content = archive.markdown_path.read_text()

    # Verify markdown shows MST timezone (America/Denver in winter)
    # 2026-02-08 17:30 UTC = 2026-02-08 10:30 MST
    assert "10:30:00 MST" in markdown_content or "10:30:00 MDT" in markdown_content

    # Verify JSON data remains UTC (no timezone conversion)
    with archive.json_path.open("r") as f:
        data = json.load(f)

    # JSON timestamps should be ISO format UTC strings
    assert data["messages"][0]["timestamp"] == utc_dt.isoformat()
    # Metadata timestamps should also be UTC
    assert "2026-02-08T17:30:00" in data["started_at"]


@pytest.mark.asyncio
async def test_archive_default_timezone_utc(tmp_path: Path, mock_checkpointer):
    """Test that default timezone is UTC when not specified."""
    # Create archiver without timezone parameter (defaults to UTC)
    archiver = ConversationArchiver(tmp_path, "test_workspace")

    archive = await archiver.archive(
        checkpointer=mock_checkpointer,
        thread_id="telegram:123:conv_default_tz",
        session_key="telegram:123",
        conversation_id="conv_default_tz",
    )

    # Read markdown content
    markdown_content = archive.markdown_path.read_text()

    # Verify timestamps show UTC
    assert " UTC" in markdown_content
