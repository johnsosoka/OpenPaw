"""Tests for send_file builtin tool."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from openpaw.builtins.tools._channel_context import (
    clear_channel_context,
    set_channel_context,
)
from openpaw.builtins.tools.send_file import SendFileTool


@pytest.fixture
def workspace_path(tmp_path: Path) -> Path:
    """Create a temporary workspace directory."""
    workspace = tmp_path / "test_workspace"
    workspace.mkdir()
    return workspace


@pytest.fixture
def send_file_tool(workspace_path: Path) -> SendFileTool:
    """Create a SendFileTool instance with workspace path."""
    config = {"workspace_path": str(workspace_path)}
    return SendFileTool(config=config)


@pytest.fixture
def mock_channel() -> MagicMock:
    """Create a mock channel adapter."""
    channel = MagicMock()
    channel.send_file = AsyncMock()
    return channel


@pytest.fixture(autouse=True)
def cleanup_context() -> None:
    """Clear channel context after each test."""
    yield
    clear_channel_context()


def test_send_file_tool_metadata() -> None:
    """Test SendFileTool has correct metadata."""
    tool = SendFileTool()
    assert tool.metadata.name == "send_file"
    assert tool.metadata.display_name == "Send File"
    assert tool.metadata.group == "communication"
    assert tool.metadata.prerequisites.is_satisfied()  # No API key needed


def test_send_file_tool_workspace_path_from_config(workspace_path: Path) -> None:
    """Test workspace_path is extracted from config."""
    config = {"workspace_path": str(workspace_path)}
    tool = SendFileTool(config=config)
    assert tool.workspace_path == workspace_path


def test_send_file_tool_no_workspace_path() -> None:
    """Test tool handles missing workspace_path gracefully."""
    tool = SendFileTool(config={})
    langchain_tool = tool.get_langchain_tool()

    result = langchain_tool.invoke({"file_path": "test.txt"})
    assert "workspace_path not configured" in result


def test_send_file_tool_no_session_context(send_file_tool: SendFileTool, workspace_path: Path) -> None:
    """Test tool returns error when session context is not set."""
    # Create a test file
    test_file = workspace_path / "test.txt"
    test_file.write_text("test content")

    langchain_tool = send_file_tool.get_langchain_tool()
    result = langchain_tool.invoke({"file_path": "test.txt"})
    assert "no active session" in result


def test_send_file_tool_file_not_found(
    send_file_tool: SendFileTool,
    mock_channel: MagicMock,
) -> None:
    """Test tool returns error when file doesn't exist."""
    set_channel_context(mock_channel, "telegram:123")

    langchain_tool = send_file_tool.get_langchain_tool()
    result = langchain_tool.invoke({"file_path": "nonexistent.txt"})
    assert "File not found" in result


def test_send_file_tool_path_is_directory(
    send_file_tool: SendFileTool,
    mock_channel: MagicMock,
    workspace_path: Path,
) -> None:
    """Test tool returns error when path is a directory."""
    # Create a directory
    test_dir = workspace_path / "test_dir"
    test_dir.mkdir()

    set_channel_context(mock_channel, "telegram:123")

    langchain_tool = send_file_tool.get_langchain_tool()
    result = langchain_tool.invoke({"file_path": "test_dir"})
    assert "not a file" in result


def test_send_file_tool_path_traversal_blocked(
    send_file_tool: SendFileTool,
    mock_channel: MagicMock,
) -> None:
    """Test tool blocks path traversal attempts."""
    set_channel_context(mock_channel, "telegram:123")

    langchain_tool = send_file_tool.get_langchain_tool()

    # Test various path traversal attempts
    result = langchain_tool.invoke({"file_path": "../etc/passwd"})
    assert "Invalid file path" in result

    result = langchain_tool.invoke({"file_path": "/etc/passwd"})
    assert "Invalid file path" in result

    result = langchain_tool.invoke({"file_path": "~/secret.txt"})
    assert "Invalid file path" in result


def test_send_file_tool_file_too_large(
    send_file_tool: SendFileTool,
    mock_channel: MagicMock,
    workspace_path: Path,
) -> None:
    """Test tool returns error when file exceeds size limit."""
    # Override max_file_size for testing
    send_file_tool.max_file_size = 100  # 100 bytes

    # Create a file larger than the limit
    large_file = workspace_path / "large.bin"
    large_file.write_bytes(b"x" * 200)

    set_channel_context(mock_channel, "telegram:123")

    langchain_tool = send_file_tool.get_langchain_tool()
    result = langchain_tool.invoke({"file_path": "large.bin"})
    assert "exceeds maximum size" in result


def test_send_file_tool_channel_no_send_file_support(
    send_file_tool: SendFileTool,
    workspace_path: Path,
) -> None:
    """Test tool returns error when channel doesn't support file sending."""
    # Create a mock channel without send_file method
    channel = MagicMock(spec=[])  # Empty spec = no methods
    set_channel_context(channel, "test:123")

    # Create a test file
    test_file = workspace_path / "test.txt"
    test_file.write_text("test content")

    langchain_tool = send_file_tool.get_langchain_tool()
    result = langchain_tool.invoke({"file_path": "test.txt"})
    assert "does not support file sending" in result


@pytest.mark.asyncio
async def test_send_file_tool_success_async(
    send_file_tool: SendFileTool,
    mock_channel: MagicMock,
    workspace_path: Path,
) -> None:
    """Test successful file send (async)."""
    # Create a test file
    test_file = workspace_path / "report.pdf"
    test_content = b"PDF content here"
    test_file.write_bytes(test_content)

    set_channel_context(mock_channel, "telegram:123456")

    langchain_tool = send_file_tool.get_langchain_tool()
    result = await langchain_tool.ainvoke({"file_path": "report.pdf"})

    assert "File sent: report.pdf" in result
    assert "KB" in result

    # Verify channel.send_file was called correctly
    mock_channel.send_file.assert_called_once()
    call_args = mock_channel.send_file.call_args
    assert call_args[0][0] == "telegram:123456"  # session_key
    assert call_args[0][1] == test_content  # file_data
    assert call_args[0][2] == "report.pdf"  # filename
    assert call_args[0][3] == "application/pdf"  # mime_type (inferred)
    assert call_args[0][4] is None  # caption


@pytest.mark.asyncio
async def test_send_file_tool_with_caption(
    send_file_tool: SendFileTool,
    mock_channel: MagicMock,
    workspace_path: Path,
) -> None:
    """Test file send with caption."""
    test_file = workspace_path / "chart.png"
    test_file.write_bytes(b"PNG data")

    set_channel_context(mock_channel, "telegram:789")

    langchain_tool = send_file_tool.get_langchain_tool()
    result = await langchain_tool.ainvoke({
        "file_path": "chart.png",
        "caption": "Here's the visualization you requested",
    })

    assert "File sent: chart.png" in result

    # Verify caption was passed
    call_args = mock_channel.send_file.call_args
    assert call_args[0][4] == "Here's the visualization you requested"


@pytest.mark.asyncio
async def test_send_file_tool_with_filename_override(
    send_file_tool: SendFileTool,
    mock_channel: MagicMock,
    workspace_path: Path,
) -> None:
    """Test file send with custom display filename."""
    test_file = workspace_path / "temp123.log"
    test_file.write_bytes(b"log content")

    set_channel_context(mock_channel, "telegram:999")

    langchain_tool = send_file_tool.get_langchain_tool()
    result = await langchain_tool.ainvoke({
        "file_path": "temp123.log",
        "filename": "system-debug.log",
    })

    assert "File sent: system-debug.log" in result

    # Verify custom filename was used
    call_args = mock_channel.send_file.call_args
    assert call_args[0][2] == "system-debug.log"  # display filename


@pytest.mark.asyncio
async def test_send_file_tool_mime_type_inference(
    send_file_tool: SendFileTool,
    mock_channel: MagicMock,
    workspace_path: Path,
) -> None:
    """Test MIME type is correctly inferred."""
    test_cases = [
        ("document.pdf", "application/pdf"),
        ("image.png", "image/png"),
        ("data.json", "application/json"),
        ("style.css", "text/css"),
        ("unknown.unknownext", None),  # Unknown extension
    ]

    for filename, expected_mime in test_cases:
        test_file = workspace_path / filename
        test_file.write_bytes(b"content")

        set_channel_context(mock_channel, "telegram:123")
        langchain_tool = send_file_tool.get_langchain_tool()

        await langchain_tool.ainvoke({"file_path": filename})

        call_args = mock_channel.send_file.call_args
        assert call_args[0][3] == expected_mime

        mock_channel.send_file.reset_mock()


@pytest.mark.asyncio
async def test_send_file_tool_channel_error(
    send_file_tool: SendFileTool,
    mock_channel: MagicMock,
    workspace_path: Path,
) -> None:
    """Test tool handles channel errors gracefully."""
    test_file = workspace_path / "test.txt"
    test_file.write_text("content")

    # Mock channel.send_file to raise an error
    mock_channel.send_file.side_effect = RuntimeError("Network error")

    set_channel_context(mock_channel, "telegram:123")

    langchain_tool = send_file_tool.get_langchain_tool()
    result = await langchain_tool.ainvoke({"file_path": "test.txt"})

    assert "Failed to send file" in result
    assert "Network error" in result


def test_send_file_tool_sync_version(
    send_file_tool: SendFileTool,
    mock_channel: MagicMock,
    workspace_path: Path,
) -> None:
    """Test synchronous version works (for LangChain compatibility)."""
    test_file = workspace_path / "sync_test.txt"
    test_file.write_text("sync content")

    set_channel_context(mock_channel, "telegram:456")

    langchain_tool = send_file_tool.get_langchain_tool()

    # Use invoke (sync) instead of ainvoke
    result = langchain_tool.invoke({"file_path": "sync_test.txt"})

    assert "File sent: sync_test.txt" in result
    mock_channel.send_file.assert_called_once()


@pytest.mark.asyncio
async def test_send_file_tool_subdirectory(
    send_file_tool: SendFileTool,
    mock_channel: MagicMock,
    workspace_path: Path,
) -> None:
    """Test sending files from subdirectories."""
    # Create subdirectory
    reports_dir = workspace_path / "reports"
    reports_dir.mkdir()
    test_file = reports_dir / "monthly.csv"
    test_file.write_text("data")

    set_channel_context(mock_channel, "telegram:123")

    langchain_tool = send_file_tool.get_langchain_tool()
    result = await langchain_tool.ainvoke({"file_path": "reports/monthly.csv"})

    assert "File sent: monthly.csv" in result
    mock_channel.send_file.assert_called_once()


def test_send_file_tool_max_size_from_config(workspace_path: Path) -> None:
    """Test max_file_size can be configured."""
    config = {
        "workspace_path": str(workspace_path),
        "max_file_size": 1024,  # 1KB
    }
    tool = SendFileTool(config=config)
    assert tool.max_file_size == 1024
