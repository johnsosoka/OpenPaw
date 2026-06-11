"""Tests for ReportProgressTool."""

import pytest

from openpaw.builtins.tools._channel_context import (
    clear_channel_context,
    get_channel_context,
)
from openpaw.builtins.tools.report_progress import ReportProgressTool


class MockChannel:
    """Mock channel adapter for testing."""

    def __init__(self):
        self.sent_messages: list[tuple[str, str]] = []

    async def send_message(self, session_key: str, content: str) -> None:
        self.sent_messages.append((session_key, content))


@pytest.fixture
def tool():
    """Create a fresh ReportProgressTool for each test."""
    return ReportProgressTool()


@pytest.fixture
def mock_channel():
    """Create a fresh MockChannel for each test."""
    return MockChannel()


# ---------------------------------------------------------------------------
# Context management
# ---------------------------------------------------------------------------


def test_set_session_context_updates_shared_context(tool, mock_channel):
    tool.set_session_context(mock_channel, "telegram:123456")
    channel, session_key = get_channel_context()
    assert channel is mock_channel
    assert session_key == "telegram:123456"
    clear_channel_context()


def test_clear_session_context_clears_shared_context(tool, mock_channel):
    tool.set_session_context(mock_channel, "telegram:123456")
    tool.clear_session_context()
    channel, session_key = get_channel_context()
    assert channel is None
    assert session_key is None


# ---------------------------------------------------------------------------
# Async execution
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_execution_basic(tool, mock_channel):
    tool.set_session_context(mock_channel, "telegram:123456")
    langchain_tool = tool.get_langchain_tool()

    result = await langchain_tool.coroutine("Analyzing data")

    assert "Progress reported" in result
    assert len(mock_channel.sent_messages) == 1
    assert mock_channel.sent_messages[0] == ("telegram:123456", "📊 Analyzing data")
    clear_channel_context()


@pytest.mark.asyncio
async def test_async_execution_with_detail(tool, mock_channel):
    tool.set_session_context(mock_channel, "telegram:123456")
    langchain_tool = tool.get_langchain_tool()

    result = await langchain_tool.coroutine("Analyzing data", detail="Processing batch 3 of 10")

    assert "Progress reported" in result
    assert len(mock_channel.sent_messages) == 1
    assert mock_channel.sent_messages[0] == (
        "telegram:123456",
        "📊 Analyzing data — Processing batch 3 of 10",
    )
    clear_channel_context()


@pytest.mark.asyncio
async def test_async_execution_with_percent(tool, mock_channel):
    tool.set_session_context(mock_channel, "telegram:123456")
    langchain_tool = tool.get_langchain_tool()

    result = await langchain_tool.coroutine("Analyzing data", percent=50)

    assert "Progress reported" in result
    assert len(mock_channel.sent_messages) == 1
    assert mock_channel.sent_messages[0] == (
        "telegram:123456",
        "📊 Analyzing data (50%)",
    )
    clear_channel_context()


@pytest.mark.asyncio
async def test_async_execution_with_all_fields(tool, mock_channel):
    tool.set_session_context(mock_channel, "telegram:123456")
    langchain_tool = tool.get_langchain_tool()

    result = await langchain_tool.coroutine(
        "Analyzing data",
        detail="Processing batch 3 of 10",
        percent=50,
    )

    assert "Progress reported" in result
    assert len(mock_channel.sent_messages) == 1
    assert mock_channel.sent_messages[0] == (
        "telegram:123456",
        "📊 Analyzing data — Processing batch 3 of 10 (50%)",
    )
    clear_channel_context()


@pytest.mark.asyncio
async def test_async_execution_with_custom_emoji(tool, mock_channel):
    tool.set_session_context(mock_channel, "telegram:123456")
    langchain_tool = tool.get_langchain_tool()

    result = await langchain_tool.coroutine("Analyzing data", emoji="🔥")

    assert "Progress reported" in result
    assert len(mock_channel.sent_messages) == 1
    assert mock_channel.sent_messages[0] == (
        "telegram:123456",
        "🔥 Analyzing data",
    )
    clear_channel_context()


@pytest.mark.asyncio
async def test_async_execution_without_context(tool):
    clear_channel_context()
    langchain_tool = tool.get_langchain_tool()

    result = await langchain_tool.coroutine("Analyzing data")

    assert "Error" in result
    assert "not available" in result


# ---------------------------------------------------------------------------
# Sync execution
# ---------------------------------------------------------------------------


def test_sync_execution_with_context(tool, mock_channel):
    tool.set_session_context(mock_channel, "telegram:123456")
    langchain_tool = tool.get_langchain_tool()

    result = langchain_tool.func("Analyzing data")

    assert "Progress reported" in result
    assert len(mock_channel.sent_messages) == 1
    assert mock_channel.sent_messages[0] == ("telegram:123456", "📊 Analyzing data")
    clear_channel_context()


def test_sync_execution_without_context(tool):
    clear_channel_context()
    langchain_tool = tool.get_langchain_tool()

    result = langchain_tool.func("Analyzing data")

    assert "Error" in result
    assert "not available" in result


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------


def test_metadata(tool):
    assert tool.metadata.name == "report_progress"
    assert tool.metadata.display_name == "Report Progress"
    assert tool.metadata.builtin_type.value == "tool"
    assert tool.metadata.group == "communication"
