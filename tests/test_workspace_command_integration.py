"""Integration tests for command system in WorkspaceRunner."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openpaw.channels.commands.router import CommandRouter
from openpaw.core.config import Config


@pytest.fixture
def mock_workspace(tmp_path: Path):
    """Create a mock workspace structure."""
    workspace_path = tmp_path / "test_workspace"
    workspace_path.mkdir()

    # Create required workspace files
    (workspace_path / "AGENT.md").write_text("# Agent\nTest agent")
    (workspace_path / "USER.md").write_text("# User\nTest user")
    (workspace_path / "SOUL.md").write_text("# Soul\nTest soul")
    (workspace_path / "HEARTBEAT.md").write_text("# Heartbeat\nTest heartbeat")

    return workspace_path


@pytest.fixture
def mock_config():
    """Create a minimal mock config."""
    config = MagicMock(spec=Config)
    config.workspaces_path = Path("/mock/workspaces")
    config.logging = MagicMock()
    config.logging.per_workspace = False
    config.logging.directory = Path("/mock/logs")
    config.logging.max_size_mb = 10
    config.logging.backup_count = 3
    config.lanes = MagicMock()
    config.lanes.main_concurrency = 1
    config.lanes.subagent_concurrency = 1
    config.lanes.cron_concurrency = 1
    config.queue = MagicMock()
    config.queue.mode = "collect"
    config.queue.debounce_ms = 1000
    config.queue.cap = 100
    config.queue.drop_policy = "oldest"
    config.agent = MagicMock()
    config.agent.model = "anthropic:claude-sonnet-4-20250514"
    config.agent.api_key = "test-key"
    config.agent.max_turns = 10
    config.agent.temperature = 0.7
    config.builtins = MagicMock()
    config.tool_timeouts = MagicMock()
    config.tool_timeouts.default_seconds = 120
    config.tool_timeouts.overrides = {}
    return config


@pytest.mark.asyncio
async def test_workspace_runner_initializes_command_router(mock_config, mock_workspace, tmp_path):
    """Test that WorkspaceRunner properly initializes CommandRouter on startup."""
    from openpaw.workspace.runner import WorkspaceRunner

    # Mock workspace loader
    with (
        patch("openpaw.workspace.runner.WorkspaceLoader") as mock_loader_cls,
        patch("openpaw.workspace.runner.load_workspace_tools", return_value=[]),
        patch("openpaw.workspace.runner.BuiltinLoader") as mock_builtin_loader_cls,
    ):
        # Configure workspace mock
        mock_workspace_obj = MagicMock()
        mock_workspace_obj.path = mock_workspace
        mock_workspace_obj.config = None
        mock_workspace_obj.crons = []
        mock_workspace_obj.tools_path = mock_workspace / "tools"
        mock_workspace_obj.markdown_files = {
            "AGENT.md": "Agent content",
            "USER.md": "User content",
            "SOUL.md": "Soul content",
            "HEARTBEAT.md": "Heartbeat content",
        }

        mock_loader = MagicMock()
        mock_loader.load.return_value = mock_workspace_obj
        mock_loader_cls.return_value = mock_loader

        # Configure builtin loader mock
        mock_builtin_loader = MagicMock()
        mock_builtin_loader.load_tools.return_value = []
        mock_builtin_loader.load_processors.return_value = []
        mock_builtin_loader.get_loaded_tool_names.return_value = []
        mock_builtin_loader.get_tool_instance.return_value = None
        mock_builtin_loader_cls.return_value = mock_builtin_loader

        # Create WorkspaceRunner
        runner = WorkspaceRunner(config=mock_config, workspace_name="test_workspace")

        # Verify CommandRouter was initialized
        assert hasattr(runner, "_command_router")
        assert isinstance(runner._command_router, CommandRouter)


@pytest.mark.asyncio
async def test_workspace_runner_registers_framework_commands(mock_config, mock_workspace):
    """Test that WorkspaceRunner registers all framework commands."""
    from openpaw.workspace.runner import WorkspaceRunner

    with (
        patch("openpaw.workspace.runner.WorkspaceLoader") as mock_loader_cls,
        patch("openpaw.workspace.runner.load_workspace_tools", return_value=[]),
        patch("openpaw.workspace.runner.BuiltinLoader") as mock_builtin_loader_cls,
    ):
        # Configure workspace mock
        mock_workspace_obj = MagicMock()
        mock_workspace_obj.path = mock_workspace
        mock_workspace_obj.config = None
        mock_workspace_obj.crons = []
        mock_workspace_obj.tools_path = mock_workspace / "tools"
        mock_workspace_obj.markdown_files = {
            "AGENT.md": "Agent content",
            "USER.md": "User content",
            "SOUL.md": "Soul content",
            "HEARTBEAT.md": "Heartbeat content",
        }

        mock_loader = MagicMock()
        mock_loader.load.return_value = mock_workspace_obj
        mock_loader_cls.return_value = mock_loader

        # Configure builtin loader mock
        mock_builtin_loader = MagicMock()
        mock_builtin_loader.load_tools.return_value = []
        mock_builtin_loader.load_processors.return_value = []
        mock_builtin_loader.get_loaded_tool_names.return_value = []
        mock_builtin_loader.get_tool_instance.return_value = None
        mock_builtin_loader_cls.return_value = mock_builtin_loader

        # Create WorkspaceRunner
        runner = WorkspaceRunner(config=mock_config, workspace_name="test_workspace")

        # Verify framework commands were registered
        registered_commands = runner._command_router.list_commands(include_hidden=True)
        command_names = {cmd.name for cmd in registered_commands}

        # Should have all framework commands
        expected_commands = {"start", "new", "help", "queue", "status"}
        assert expected_commands.issubset(command_names)


@pytest.mark.asyncio
async def test_workspace_runner_build_command_context(mock_config, mock_workspace):
    """Test that _build_command_context creates valid CommandContext."""
    from openpaw.channels.base import Message, MessageDirection
    from openpaw.workspace.runner import WorkspaceRunner

    with (
        patch("openpaw.workspace.runner.WorkspaceLoader") as mock_loader_cls,
        patch("openpaw.workspace.runner.load_workspace_tools", return_value=[]),
        patch("openpaw.workspace.runner.BuiltinLoader") as mock_builtin_loader_cls,
    ):
        # Configure workspace mock
        mock_workspace_obj = MagicMock()
        mock_workspace_obj.path = mock_workspace
        mock_workspace_obj.config = None
        mock_workspace_obj.crons = []
        mock_workspace_obj.tools_path = mock_workspace / "tools"
        mock_workspace_obj.markdown_files = {
            "AGENT.md": "Agent content",
            "USER.md": "User content",
            "SOUL.md": "Soul content",
            "HEARTBEAT.md": "Heartbeat content",
        }

        mock_loader = MagicMock()
        mock_loader.load.return_value = mock_workspace_obj
        mock_loader_cls.return_value = mock_loader

        # Configure builtin loader mock
        mock_builtin_loader = MagicMock()
        mock_builtin_loader.load_tools.return_value = []
        mock_builtin_loader.load_processors.return_value = []
        mock_builtin_loader.get_loaded_tool_names.return_value = []
        mock_builtin_loader.get_tool_instance.return_value = None
        mock_builtin_loader_cls.return_value = mock_builtin_loader

        # Create WorkspaceRunner
        runner = WorkspaceRunner(config=mock_config, workspace_name="test_workspace")

        # Manually start checkpointer setup (normally done in start())
        runner._checkpointer = MagicMock()

        # Add a mock channel
        mock_channel = MagicMock()
        runner._channels["telegram"] = mock_channel

        # Create test message
        message = Message(
            id="test-123",
            channel="telegram",
            session_key="telegram:user123",
            user_id="user123",
            content="/help",
            direction=MessageDirection.INBOUND,
        )

        # Build command context
        context = runner._build_command_context(message)

        # Verify context fields
        assert context.channel == mock_channel
        assert context.session_manager == runner._session_manager
        assert context.checkpointer == runner._checkpointer
        assert context.agent_runner == runner._agent_runner
        assert context.workspace_name == "test_workspace"
        assert context.workspace_path == mock_workspace
        assert context.queue_manager == runner._queue_manager
        assert context.command_router == runner._command_router


@pytest.mark.asyncio
async def test_workspace_runner_build_command_context_missing_channel_raises(
    mock_config, mock_workspace
):
    """Test that _build_command_context raises error when channel not found."""
    from openpaw.channels.base import Message, MessageDirection
    from openpaw.workspace.runner import WorkspaceRunner

    with (
        patch("openpaw.workspace.runner.WorkspaceLoader") as mock_loader_cls,
        patch("openpaw.workspace.runner.load_workspace_tools", return_value=[]),
        patch("openpaw.workspace.runner.BuiltinLoader") as mock_builtin_loader_cls,
    ):
        # Configure workspace mock
        mock_workspace_obj = MagicMock()
        mock_workspace_obj.path = mock_workspace
        mock_workspace_obj.config = None
        mock_workspace_obj.crons = []
        mock_workspace_obj.tools_path = mock_workspace / "tools"
        mock_workspace_obj.markdown_files = {
            "AGENT.md": "Agent content",
            "USER.md": "User content",
            "SOUL.md": "Soul content",
            "HEARTBEAT.md": "Heartbeat content",
        }

        mock_loader = MagicMock()
        mock_loader.load.return_value = mock_workspace_obj
        mock_loader_cls.return_value = mock_loader

        # Configure builtin loader mock
        mock_builtin_loader = MagicMock()
        mock_builtin_loader.load_tools.return_value = []
        mock_builtin_loader.load_processors.return_value = []
        mock_builtin_loader.get_loaded_tool_names.return_value = []
        mock_builtin_loader.get_tool_instance.return_value = None
        mock_builtin_loader_cls.return_value = mock_builtin_loader

        # Create WorkspaceRunner
        runner = WorkspaceRunner(config=mock_config, workspace_name="test_workspace")

        # Create test message for non-existent channel
        message = Message(
            id="test-123",
            channel="nonexistent",
            session_key="nonexistent:user123",
            user_id="user123",
            content="/help",
            direction=MessageDirection.INBOUND,
        )

        # Attempt to build context should raise
        with pytest.raises(RuntimeError, match="No channel found"):
            runner._build_command_context(message)
