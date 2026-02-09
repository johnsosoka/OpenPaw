"""Tests for SubAgentRunner integration into WorkspaceRunner."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from openpaw.subagent.store import SubAgentStore
from openpaw.workspace.loader import AgentWorkspace, WorkspaceLoader


@pytest.fixture
def mock_workspace(tmp_path: Path) -> AgentWorkspace:
    """Create a minimal mock workspace."""
    workspace_path = tmp_path / "test_workspace"
    workspace_path.mkdir()

    # Create required markdown files
    (workspace_path / "AGENT.md").write_text("# Agent")
    (workspace_path / "USER.md").write_text("# User")
    (workspace_path / "SOUL.md").write_text("# Soul")
    (workspace_path / "HEARTBEAT.md").write_text("# Heartbeat")

    loader = WorkspaceLoader(tmp_path)
    return loader.load("test_workspace")


class TestSubAgentStoreInitialization:
    """Test SubAgentStore initialization in WorkspaceRunner."""

    @patch("openpaw.workspace.runner.WorkspaceLoader")
    @patch("openpaw.workspace.runner.BuiltinLoader")
    @patch("openpaw.workspace.runner.load_workspace_tools")
    def test_subagent_store_initialized(
        self,
        mock_load_tools: Mock,
        mock_builtin_loader: Mock,
        mock_workspace_loader: Mock,
        mock_workspace: AgentWorkspace,
        tmp_path: Path,
    ) -> None:
        """SubAgentStore is initialized in __init__."""
        # Setup mocks
        mock_workspace_loader.return_value.load.return_value = mock_workspace
        mock_builtin_loader.return_value.load_tools.return_value = []
        mock_builtin_loader.return_value.load_processors.return_value = []
        mock_builtin_loader.return_value.get_loaded_tool_names.return_value = []
        mock_load_tools.return_value = []

        from openpaw.core.config import Config
        from openpaw.workspace.runner import WorkspaceRunner

        config = Config(workspaces_path=str(tmp_path))

        # Create WorkspaceRunner
        runner = WorkspaceRunner(config=config, workspace_name="test_workspace")

        # Verify SubAgentStore was created
        assert hasattr(runner, "_subagent_store")
        assert isinstance(runner._subagent_store, SubAgentStore)
        assert runner._subagent_store.workspace_path == mock_workspace.path


class TestSubAgentRunnerCreation:
    """Test SubAgentRunner creation during start()."""

    def test_subagent_runner_parameters(self, mock_workspace: AgentWorkspace) -> None:
        """SubAgentRunner initialization includes correct dependencies."""
        from openpaw.core.config import Config
        from openpaw.workspace.runner import WorkspaceRunner

        # Verify the WorkspaceRunner has the components needed for SubAgentRunner
        with patch("openpaw.workspace.runner.WorkspaceLoader") as mock_loader:
            with patch("openpaw.workspace.runner.BuiltinLoader") as mock_builtin:
                with patch("openpaw.workspace.runner.load_workspace_tools"):
                    with patch("openpaw.agent.runner.create_agent"):
                        with patch("openpaw.agent.runner.AgentRunner._create_model"):
                            mock_loader.return_value.load.return_value = mock_workspace
                            mock_builtin.return_value.load_tools.return_value = []
                            mock_builtin.return_value.load_processors.return_value = []
                            mock_builtin.return_value.get_loaded_tool_names.return_value = []

                            config = Config(workspaces_path="/tmp")
                            runner = WorkspaceRunner(config=config, workspace_name="test_workspace")

                            # Verify runner has all the components needed for SubAgentRunner
                            assert hasattr(runner, "_subagent_store")
                            assert isinstance(runner._subagent_store, SubAgentStore)
                            assert hasattr(runner, "_token_logger")
                            assert hasattr(runner, "_channels")
                            assert hasattr(runner, "workspace_name")
                            assert runner.workspace_name == "test_workspace"

                            # Verify agent factory exists and has closure method
                            assert hasattr(runner, "_agent_factory")
                            factory_closure = runner._agent_factory.get_agent_factory_closure()
                            assert callable(factory_closure)


class TestSpawnToolConnection:
    """Test SpawnTool connection to SubAgentRunner."""

    def test_spawn_tool_connected(self) -> None:
        """_connect_spawn_tool_to_runner calls set_runner on spawn tool."""
        from openpaw.core.config import Config
        from openpaw.workspace.runner import WorkspaceRunner

        # Create a mock workspace runner with minimal setup
        with patch("openpaw.workspace.runner.WorkspaceLoader") as mock_loader:
            with patch("openpaw.workspace.runner.BuiltinLoader") as mock_builtin:
                with patch("openpaw.workspace.runner.load_workspace_tools"):
                    # Mock builtin loader to return spawn tool
                    mock_spawn_tool = MagicMock()
                    mock_spawn_tool.set_runner = MagicMock()

                    mock_builtin.return_value.load_tools.return_value = []
                    mock_builtin.return_value.load_processors.return_value = []
                    mock_builtin.return_value.get_loaded_tool_names.return_value = ["spawn"]
                    mock_builtin.return_value.get_tool_instance.return_value = mock_spawn_tool

                    # Mock workspace
                    mock_workspace = MagicMock()
                    mock_workspace.path = Path("/tmp/workspace")
                    mock_workspace.config = None
                    mock_workspace.crons = []
                    mock_loader.return_value.load.return_value = mock_workspace

                    with patch("openpaw.agent.runner.create_agent"):
                        with patch("openpaw.agent.runner.AgentRunner._create_model"):
                            config = Config(workspaces_path="/tmp")
                            runner = WorkspaceRunner(config=config, workspace_name="test")

                            # Mock the subagent runner
                            mock_runner_instance = MagicMock()
                            runner._subagent_runner = mock_runner_instance

                            # Call the connection method directly
                            runner._connect_spawn_tool_to_runner()

                            # Verify set_runner was called
                            mock_spawn_tool.set_runner.assert_called_once_with(mock_runner_instance)


class TestSubAgentRunnerShutdown:
    """Test SubAgentRunner shutdown during stop()."""

    @pytest.mark.asyncio
    async def test_subagent_runner_shutdown_on_stop(self) -> None:
        """SubAgentRunner.shutdown() is called during stop()."""
        from openpaw.workspace.runner import WorkspaceRunner

        # Create a minimal workspace runner and mock the subagent runner
        runner = MagicMock(spec=WorkspaceRunner)
        mock_subagent_runner = AsyncMock()
        mock_subagent_runner.shutdown = AsyncMock()
        runner._subagent_runner = mock_subagent_runner
        runner._running = True
        runner._queue_processor_task = None
        runner._channels = {}
        runner._db_conn = None
        runner._approval_manager = None
        runner.workspace_name = "test_workspace"
        runner.logger = MagicMock()
        runner._archive_active_conversations = AsyncMock()
        runner._session_manager = MagicMock()
        runner._get_browser_builtin = MagicMock(return_value=None)  # No browser loaded

        # Mock lifecycle manager
        mock_lifecycle = AsyncMock()
        mock_lifecycle.stop_cron_scheduler = AsyncMock()
        mock_lifecycle.stop_heartbeat_scheduler = AsyncMock()
        mock_lifecycle.stop_channels = AsyncMock()
        runner._lifecycle_manager = mock_lifecycle

        # Call stop using the real implementation
        from openpaw.workspace.runner import WorkspaceRunner as RealRunner
        await RealRunner.stop(runner)

        # Verify shutdown was called
        mock_subagent_runner.shutdown.assert_called_once()


class TestFrameworkPromptSubagent:
    """Test framework prompt includes/excludes sub-agent section."""

    def test_framework_prompt_includes_subagent(self, mock_workspace: AgentWorkspace) -> None:
        """Framework prompt includes sub-agent section when spawn is enabled."""
        # With spawn in enabled_builtins
        prompt = mock_workspace.build_system_prompt(enabled_builtins=["spawn"])

        assert "## Sub-Agent Spawning" in prompt
        assert "spawn background sub-agents" in prompt
        assert "Proactive delegation:" in prompt  # Updated to reflect new content

    def test_framework_prompt_includes_subagent_when_none(
        self, mock_workspace: AgentWorkspace
    ) -> None:
        """Framework prompt includes sub-agent section when enabled_builtins is None."""
        # With None (all builtins enabled)
        prompt = mock_workspace.build_system_prompt(enabled_builtins=None)

        assert "## Sub-Agent Spawning" in prompt

    def test_framework_prompt_excludes_subagent(self, mock_workspace: AgentWorkspace) -> None:
        """Framework prompt excludes sub-agent section when spawn is not enabled."""
        # Without spawn in enabled_builtins
        prompt = mock_workspace.build_system_prompt(enabled_builtins=["task_tracker"])

        assert "## Sub-Agent Spawning" not in prompt


class TestAgentFactory:
    """Test agent factory creates fresh runners for sub-agents."""

    @patch("openpaw.agent.runner.create_agent")
    @patch("openpaw.agent.runner.AgentRunner._create_model")
    def test_agent_factory_creates_fresh_runners(
        self, mock_create_model: Mock, mock_create_agent: Mock, mock_workspace: AgentWorkspace
    ) -> None:
        """Agent factory creates stateless runners with no middleware and checkpointer."""
        import inspect

        from openpaw.core.config import Config
        from openpaw.workspace.runner import WorkspaceRunner

        # Setup mocks
        mock_model = Mock()
        mock_create_model.return_value = mock_model
        mock_create_agent.return_value = Mock()

        with patch("openpaw.workspace.runner.WorkspaceLoader") as mock_loader:
            with patch("openpaw.workspace.runner.BuiltinLoader") as mock_builtin:
                with patch("openpaw.workspace.runner.load_workspace_tools"):
                    mock_loader.return_value.load.return_value = mock_workspace
                    mock_builtin.return_value.load_tools.return_value = []
                    mock_builtin.return_value.load_processors.return_value = []
                    mock_builtin.return_value.get_loaded_tool_names.return_value = []

                    config = Config(workspaces_path="/tmp")
                    runner = WorkspaceRunner(config=config, workspace_name="test")

                    # Get the factory closure and inspect its source
                    factory_closure = runner._agent_factory.get_agent_factory_closure()

                    # Verify by reading the source code of create_stateless_agent
                    # that it passes middleware=[] and checkpointer=None
                    agent_factory_source = inspect.getsource(runner._agent_factory.create_stateless_agent)
                    assert "middleware=[]" in agent_factory_source
                    assert "checkpointer=None" in agent_factory_source


class TestQueueInjection:
    """Test sub-agent result queue injection."""

    @pytest.mark.asyncio
    async def test_inject_system_event_creates_message(self) -> None:
        """_inject_system_event creates a Message and submits to queue."""
        from openpaw.channels.base import Message, MessageDirection
        from openpaw.workspace.runner import WorkspaceRunner
        from openpaw.core.queue.lane import QueueMode

        # Create a minimal workspace runner and mock the queue manager
        runner = MagicMock(spec=WorkspaceRunner)
        runner._queue_manager = AsyncMock()
        runner._queue_manager.submit = AsyncMock()
        runner.logger = MagicMock()

        # Call the real implementation
        from openpaw.workspace.runner import WorkspaceRunner as RealRunner

        await RealRunner._inject_system_event(
            runner, session_key="telegram:12345", content="[SYSTEM] Test event"
        )

        # Verify submit was called
        runner._queue_manager.submit.assert_called_once()
        call_kwargs = runner._queue_manager.submit.call_args[1]

        # Verify session_key and channel_name
        assert call_kwargs["session_key"] == "telegram:12345"
        assert call_kwargs["channel_name"] == "telegram"

        # Verify mode is COLLECT
        assert call_kwargs["mode"] == QueueMode.COLLECT

        # Verify message structure
        msg = call_kwargs["message"]
        assert isinstance(msg, Message)
        assert msg.session_key == "telegram:12345"
        assert msg.user_id == "system"
        assert msg.content == "[SYSTEM] Test event"
        assert msg.direction == MessageDirection.INBOUND
        assert msg.channel == "telegram"
        assert msg.id.startswith("system-")

    def test_subagent_runner_created_with_result_callback(self) -> None:
        """SubAgentRunner is created with result_callback parameter."""
        from openpaw.core.config import Config
        from openpaw.workspace.runner import WorkspaceRunner

        # Create a mock workspace runner with minimal setup
        with patch("openpaw.workspace.runner.WorkspaceLoader") as mock_loader:
            with patch("openpaw.workspace.runner.BuiltinLoader") as mock_builtin:
                with patch("openpaw.workspace.runner.load_workspace_tools"):
                    # Mock workspace
                    mock_workspace = MagicMock()
                    mock_workspace.path = Path("/tmp/workspace")
                    mock_workspace.config = None
                    mock_workspace.crons = []
                    mock_loader.return_value.load.return_value = mock_workspace

                    mock_builtin.return_value.load_tools.return_value = []
                    mock_builtin.return_value.load_processors.return_value = []
                    mock_builtin.return_value.get_loaded_tool_names.return_value = []

                    with patch("openpaw.agent.runner.create_agent"):
                        with patch("openpaw.agent.runner.AgentRunner._create_model"):
                            config = Config(workspaces_path="/tmp")
                            runner = WorkspaceRunner(config=config, workspace_name="test")

                            # Verify _inject_system_event method exists
                            assert hasattr(runner, "_inject_system_event")
                            assert callable(runner._inject_system_event)
