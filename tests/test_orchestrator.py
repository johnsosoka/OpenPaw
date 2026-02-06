"""Tests for OpenPawOrchestrator runtime control methods."""

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openpaw.orchestrator import OpenPawOrchestrator


@pytest.fixture
def mock_config():
    """Create mock configuration."""
    config = MagicMock()
    config.workspaces_path = "/tmp/workspaces"
    return config


@pytest.fixture
def mock_workspace_runner():
    """Create mock WorkspaceRunner class."""
    with patch("openpaw.orchestrator.WorkspaceRunner") as mock_runner_class:
        # Create a mock instance that the class will return
        mock_instance = MagicMock()
        mock_instance.start = AsyncMock()
        mock_instance.stop = AsyncMock()
        mock_runner_class.return_value = mock_instance
        yield mock_runner_class


@pytest.fixture
def orchestrator(mock_config, mock_workspace_runner):
    """Create orchestrator with no initial workspaces."""
    return OpenPawOrchestrator(mock_config, [])


@pytest.fixture
def orchestrator_with_workspace(mock_config, mock_workspace_runner):
    """Create orchestrator with one running workspace."""
    orch = OpenPawOrchestrator(mock_config, ["test_workspace"])
    return orch


class TestStartWorkspace:
    """Test start_workspace method."""

    async def test_start_workspace_succeeds(self, orchestrator, mock_workspace_runner):
        """Test starting a new workspace succeeds."""
        workspace_name = "new_workspace"

        await orchestrator.start_workspace(workspace_name)

        # Verify WorkspaceRunner was created with correct args
        mock_workspace_runner.assert_called_with(orchestrator.config, workspace_name)

        # Verify runner.start() was called
        runner_instance = mock_workspace_runner.return_value
        runner_instance.start.assert_awaited_once()

        # Verify workspace was added to runners dict
        assert workspace_name in orchestrator.runners
        assert orchestrator.runners[workspace_name] == runner_instance

    async def test_start_workspace_raises_if_already_running(self, orchestrator_with_workspace):
        """Test ValueError raised when workspace already running."""
        with pytest.raises(ValueError, match="already running"):
            await orchestrator_with_workspace.start_workspace("test_workspace")

    async def test_start_workspace_logs_correctly(self, orchestrator, mock_workspace_runner, caplog):
        """Test start_workspace logs info messages."""
        with caplog.at_level(logging.INFO):
            await orchestrator.start_workspace("new_workspace")

        assert "Starting workspace: new_workspace" in caplog.text
        assert "started successfully" in caplog.text


class TestStopWorkspace:
    """Test stop_workspace method."""

    async def test_stop_workspace_removes_from_runners(self, orchestrator_with_workspace):
        """Test stopping existing workspace removes from runners."""
        workspace_name = "test_workspace"

        # Verify workspace exists before stopping
        assert workspace_name in orchestrator_with_workspace.runners
        runner_instance = orchestrator_with_workspace.runners[workspace_name]

        await orchestrator_with_workspace.stop_workspace(workspace_name)

        # Verify runner.stop() was called
        runner_instance.stop.assert_awaited_once()

        # Verify workspace removed from runners dict
        assert workspace_name not in orchestrator_with_workspace.runners

    async def test_stop_workspace_logs_warning_if_not_running(self, orchestrator, caplog):
        """Test stopping non-existent workspace logs warning but doesn't raise."""
        with caplog.at_level(logging.WARNING):
            await orchestrator.stop_workspace("nonexistent_workspace")

        assert "is not running" in caplog.text

    async def test_stop_workspace_logs_correctly(self, orchestrator_with_workspace, caplog):
        """Test stop_workspace logs info messages."""
        with caplog.at_level(logging.INFO):
            await orchestrator_with_workspace.stop_workspace("test_workspace")

        assert "Stopping workspace: test_workspace" in caplog.text
        assert "stopped successfully" in caplog.text


class TestRestartWorkspace:
    """Test restart_workspace method."""

    async def test_restart_calls_stop_then_start(self, orchestrator_with_workspace, mock_workspace_runner):
        """Test restart calls stop then start."""
        workspace_name = "test_workspace"

        # Get initial runner to verify it was stopped
        initial_runner = orchestrator_with_workspace.runners[workspace_name]

        await orchestrator_with_workspace.restart_workspace(workspace_name)

        # Verify initial runner was stopped
        initial_runner.stop.assert_awaited_once()

        # Verify new runner was created and started
        mock_workspace_runner.assert_called_with(orchestrator_with_workspace.config, workspace_name)
        new_runner = mock_workspace_runner.return_value
        new_runner.start.assert_awaited()

        # Verify workspace still in runners dict
        assert workspace_name in orchestrator_with_workspace.runners

    async def test_restart_on_nonexistent_workspace_tries_to_start(self, orchestrator, mock_workspace_runner, caplog):
        """Test restart on non-existent workspace still tries to start."""
        workspace_name = "nonexistent_workspace"

        with caplog.at_level(logging.WARNING):
            await orchestrator.restart_workspace(workspace_name)

        # Should see warning from stop_workspace
        assert "is not running" in caplog.text

        # But should still create and start the workspace
        mock_workspace_runner.assert_called_with(orchestrator.config, workspace_name)
        new_runner = mock_workspace_runner.return_value
        new_runner.start.assert_awaited_once()

    async def test_restart_logs_correctly(self, orchestrator_with_workspace, caplog):
        """Test restart_workspace logs info messages."""
        with caplog.at_level(logging.INFO):
            await orchestrator_with_workspace.restart_workspace("test_workspace")

        assert "Restarting workspace: test_workspace" in caplog.text
        assert "restarted successfully" in caplog.text


class TestReloadWorkspaceConfig:
    """Test reload_workspace_config method."""

    async def test_reload_config_calls_restart(self, orchestrator_with_workspace, mock_workspace_runner):
        """Test reload_workspace_config calls restart_workspace under the hood."""
        workspace_name = "test_workspace"

        # Get initial runner
        initial_runner = orchestrator_with_workspace.runners[workspace_name]

        await orchestrator_with_workspace.reload_workspace_config(workspace_name)

        # Verify restart happened (stop then start)
        initial_runner.stop.assert_awaited_once()
        new_runner = mock_workspace_runner.return_value
        new_runner.start.assert_awaited()

    async def test_reload_config_logs_warning_if_not_running(self, orchestrator, caplog):
        """Test reload_workspace_config logs warning for non-existent workspace."""
        with caplog.at_level(logging.WARNING):
            await orchestrator.reload_workspace_config("nonexistent_workspace")

        assert "is not running" in caplog.text

    async def test_reload_config_logs_info(self, orchestrator_with_workspace, caplog):
        """Test reload_workspace_config logs info message."""
        with caplog.at_level(logging.INFO):
            await orchestrator_with_workspace.reload_workspace_config("test_workspace")

        assert "Reloading config for workspace 'test_workspace'" in caplog.text
        assert "triggering restart" in caplog.text


class TestReloadWorkspacePrompt:
    """Test reload_workspace_prompt method."""

    async def test_reload_prompt_logs_info_for_existing_workspace(self, orchestrator_with_workspace, caplog):
        """Test reload_workspace_prompt logs info message for existing workspace."""
        with caplog.at_level(logging.INFO):
            await orchestrator_with_workspace.reload_workspace_prompt("test_workspace")

        assert "will reload prompt files on next agent invocation" in caplog.text

    async def test_reload_prompt_logs_warning_if_not_running(self, orchestrator, caplog):
        """Test reload_workspace_prompt logs warning for non-existent workspace."""
        with caplog.at_level(logging.WARNING):
            await orchestrator.reload_workspace_prompt("nonexistent_workspace")

        assert "is not running" in caplog.text

    async def test_reload_prompt_does_not_restart_workspace(self, orchestrator_with_workspace):
        """Test reload_workspace_prompt does not trigger restart."""
        workspace_name = "test_workspace"
        runner_instance = orchestrator_with_workspace.runners[workspace_name]

        await orchestrator_with_workspace.reload_workspace_prompt(workspace_name)

        # Verify runner.stop() was NOT called
        runner_instance.stop.assert_not_awaited()


class TestTriggerCron:
    """Test trigger_cron method."""

    async def test_trigger_cron_logs_info_for_existing_workspace(self, orchestrator_with_workspace, caplog):
        """Test trigger_cron logs info message for existing workspace."""
        with caplog.at_level(logging.INFO):
            await orchestrator_with_workspace.trigger_cron("test_workspace", "daily_summary")

        assert "Triggering cron 'daily_summary' in workspace 'test_workspace'" in caplog.text

    async def test_trigger_cron_logs_warning_if_workspace_not_running(self, orchestrator, caplog):
        """Test trigger_cron logs warning for non-existent workspace."""
        with caplog.at_level(logging.WARNING):
            await orchestrator.trigger_cron("nonexistent_workspace", "some_cron")

        assert "is not running" in caplog.text
