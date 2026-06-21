"""Integration tests for send_file tool with loader."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from openpaw.builtins.loader import BuiltinLoader
from openpaw.builtins.registry import BuiltinRegistry
from openpaw.builtins.tools._channel_context import (
    clear_channel_context,
    set_channel_context,
)


@pytest.fixture(autouse=True)
def reset_registry() -> None:
    """Reset the registry singleton before each test."""
    BuiltinRegistry.reset()
    yield
    clear_channel_context()


@pytest.fixture
def workspace_path(tmp_path: Path) -> Path:
    """Create a temporary workspace directory."""
    workspace = tmp_path / "test_workspace"
    workspace.mkdir()
    return workspace


@pytest.fixture
def mock_channel() -> MagicMock:
    """Create a mock channel adapter."""
    channel = MagicMock()
    channel.send_file = AsyncMock()
    return channel


def test_send_file_tool_loaded_by_builtin_loader(workspace_path: Path) -> None:
    """Test that send_file tool is loaded by BuiltinLoader."""
    loader = BuiltinLoader(workspace_path=workspace_path)
    tools = loader.load_tools()

    # Find send_file tool in loaded tools
    send_file_tools = [t for t in tools if t.name == "send_file"]
    assert len(send_file_tools) == 1, "send_file tool should be loaded"


def test_send_file_tool_receives_workspace_path_from_loader(workspace_path: Path) -> None:
    """Test that workspace_path is injected by the loader."""
    loader = BuiltinLoader(workspace_path=workspace_path)
    loader.load_tools()

    # Get the underlying tool instance
    tool_instance = loader.get_tool_instance("send_file")
    assert tool_instance is not None
    assert tool_instance.workspace_path == workspace_path


@pytest.mark.asyncio
async def test_send_file_tool_end_to_end(
    workspace_path: Path,
    mock_channel: MagicMock,
) -> None:
    """Test send_file tool works end-to-end with loader and channel."""
    # Create test file in workspace
    test_file = workspace_path / "report.pdf"
    test_content = b"PDF content"
    test_file.write_bytes(test_content)

    # Load tools via BuiltinLoader
    loader = BuiltinLoader(workspace_path=workspace_path)
    tools = loader.load_tools()

    send_file_tool = [t for t in tools if t.name == "send_file"][0]

    # Set channel context
    set_channel_context(mock_channel, "telegram:123456")

    # Invoke the tool
    result = await send_file_tool.ainvoke({"file_path": "report.pdf"})

    assert "File sent: report.pdf" in result

    # Verify channel.send_file was called correctly
    mock_channel.send_file.assert_called_once()
    call_args = mock_channel.send_file.call_args
    assert call_args[0][0] == "telegram:123456"  # session_key
    assert call_args[0][1] == test_content  # file_data
    assert call_args[0][2] == "report.pdf"  # filename


def test_send_file_tool_not_in_deny_list(workspace_path: Path) -> None:
    """Test that send_file tool can be denied via config."""
    from openpaw.core.config import BuiltinsConfig

    global_config = BuiltinsConfig(deny=["send_file"])
    loader = BuiltinLoader(global_config=global_config, workspace_path=workspace_path)
    tools = loader.load_tools()

    # send_file should be denied
    send_file_tools = [t for t in tools if t.name == "send_file"]
    assert len(send_file_tools) == 0, "send_file tool should be denied"


def test_send_file_tool_in_communication_group(workspace_path: Path) -> None:
    """Test that send_file is in 'communication' group and can be denied by group."""
    from openpaw.core.config import BuiltinsConfig

    global_config = BuiltinsConfig(deny=["group:communication"])
    loader = BuiltinLoader(global_config=global_config, workspace_path=workspace_path)
    tools = loader.load_tools()

    # All communication tools should be denied (send_message, send_file)
    communication_tools = [
        t for t in tools
        if t.name in ("send_message", "send_file")
    ]
    assert len(communication_tools) == 0, "Communication group should be denied"


def test_send_file_tool_max_size_from_config(workspace_path: Path) -> None:
    """Test that max_file_size can be configured via loader."""
    from openpaw.core.config import BuiltinsConfig, SendFileBuiltinConfig

    global_config = BuiltinsConfig(
        send_file=SendFileBuiltinConfig(
            enabled=True,
            config={"max_file_size": 1024}  # 1KB limit
        )
    )
    loader = BuiltinLoader(global_config=global_config, workspace_path=workspace_path)

    # Get the tool instance
    loader.load_tools()
    tool_instance = loader.get_tool_instance("send_file")

    assert tool_instance is not None
    assert tool_instance.max_file_size == 1024
