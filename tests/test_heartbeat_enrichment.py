"""Tests for heartbeat JSONL enrichment with token counts and task counts."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest
import yaml

from openpaw.core.config import HeartbeatConfig
from openpaw.agent.metrics import InvocationMetrics
from openpaw.runtime.scheduling.heartbeat import HeartbeatScheduler


@pytest.fixture
def workspace_path(tmp_path: Path) -> Path:
    """Create a temporary workspace directory."""
    return tmp_path / "test_workspace"


@pytest.fixture
def heartbeat_config() -> HeartbeatConfig:
    """Create a test heartbeat configuration."""
    return HeartbeatConfig(
        enabled=True,
        interval_minutes=30,
        suppress_ok=True,
        target_channel="telegram",
        target_chat_id="123456789",
    )


@pytest.fixture
def mock_agent_runner() -> Mock:
    """Create a mock agent runner with metrics."""
    runner = Mock()
    runner.run = AsyncMock(return_value="Test response")
    runner.last_metrics = InvocationMetrics(
        input_tokens=4500,
        output_tokens=650,
        total_tokens=5150,
        llm_calls=2,
        duration_ms=3200.0,
        model="anthropic:claude-sonnet-4-20250514",
    )
    runner.last_tools_used = []
    return runner


@pytest.fixture
def mock_agent_factory(mock_agent_runner: Mock) -> Mock:
    """Create a mock agent factory."""
    return Mock(return_value=mock_agent_runner)


@pytest.fixture
def mock_token_logger() -> Mock:
    """Create a mock token logger."""
    logger = Mock()
    logger.log = Mock()
    return logger


@pytest.fixture
def mock_channels() -> dict:
    """Create mock channel mapping."""
    channel = Mock()
    channel.build_session_key = Mock(return_value="telegram:123456789")
    channel.send_message = AsyncMock()
    return {"telegram": channel}


@pytest.fixture
def scheduler(
    workspace_path: Path,
    heartbeat_config: HeartbeatConfig,
    mock_agent_factory: Mock,
    mock_channels: dict,
    mock_token_logger: Mock,
) -> HeartbeatScheduler:
    """Create a heartbeat scheduler instance."""
    workspace_path.mkdir(parents=True, exist_ok=True)
    (workspace_path / "data").mkdir(parents=True, exist_ok=True)
    return HeartbeatScheduler(
        workspace_name="test_workspace",
        workspace_path=workspace_path,
        agent_factory=mock_agent_factory,
        channels=mock_channels,
        config=heartbeat_config,
        token_logger=mock_token_logger,
    )


def create_tasks_yaml(workspace_path: Path, tasks: list[dict]) -> None:
    """Create a TASKS.yaml file with given tasks."""
    (workspace_path / "data").mkdir(parents=True, exist_ok=True)
    tasks_file = workspace_path / "data" / "TASKS.yaml"
    with tasks_file.open("w") as f:
        yaml.dump({"tasks": tasks}, f)


def read_heartbeat_log(workspace_path: Path) -> list[dict]:
    """Read and parse heartbeat_log.jsonl."""
    log_file = workspace_path / "data" / "heartbeat_log.jsonl"
    if not log_file.exists():
        return []

    entries = []
    with log_file.open() as f:
        for line in f:
            entries.append(json.loads(line))
    return entries


class TestHeartbeatJSONLEnrichment:
    """Test heartbeat JSONL log enrichment with token and task counts."""

    @pytest.mark.asyncio
    async def test_heartbeat_ran_includes_token_counts(
        self,
        scheduler: HeartbeatScheduler,
        workspace_path: Path,
        mock_token_logger: Mock,
    ):
        """Test that successful heartbeat includes token metrics in JSONL."""
        # Create tasks to prevent skip
        create_tasks_yaml(
            workspace_path,
            [
                {"id": "task1", "status": "in_progress", "description": "Test task"},
            ],
        )

        # Run heartbeat
        await scheduler._run_heartbeat()

        # Read JSONL log
        entries = read_heartbeat_log(workspace_path)
        assert len(entries) == 1

        entry = entries[0]
        assert entry["outcome"] == "ran"
        assert entry["workspace"] == "test_workspace"
        assert entry["input_tokens"] == 4500
        assert entry["output_tokens"] == 650
        assert entry["total_tokens"] == 5150
        assert entry["llm_calls"] == 2
        assert entry["task_count"] == 1
        assert "duration_ms" in entry
        assert entry["duration_ms"] >= 0  # Can be 0 in tests due to fast mocking

        # Verify token_usage.jsonl was also logged
        mock_token_logger.log.assert_called_once()
        call_args = mock_token_logger.log.call_args
        assert call_args.kwargs["workspace"] == "test_workspace"
        assert call_args.kwargs["invocation_type"] == "heartbeat"
        assert call_args.kwargs["metrics"].input_tokens == 4500

    @pytest.mark.asyncio
    async def test_heartbeat_ok_includes_token_counts(
        self,
        scheduler: HeartbeatScheduler,
        workspace_path: Path,
        mock_agent_runner: Mock,
        mock_token_logger: Mock,
    ):
        """Test that HEARTBEAT_OK outcome includes token metrics."""
        # Create tasks
        create_tasks_yaml(
            workspace_path,
            [
                {"id": "task1", "status": "pending", "description": "Test task"},
            ],
        )

        # Make agent return HEARTBEAT_OK
        mock_agent_runner.run.return_value = "HEARTBEAT_OK"

        # Run heartbeat
        await scheduler._run_heartbeat()

        # Read JSONL log
        entries = read_heartbeat_log(workspace_path)
        assert len(entries) == 1

        entry = entries[0]
        assert entry["outcome"] == "heartbeat_ok"
        assert entry["input_tokens"] == 4500
        assert entry["output_tokens"] == 650
        assert entry["total_tokens"] == 5150
        assert entry["llm_calls"] == 2
        assert entry["task_count"] == 1

        # Token logger should still be called for HEARTBEAT_OK
        mock_token_logger.log.assert_called_once()

    @pytest.mark.asyncio
    async def test_heartbeat_skipped_no_token_counts(
        self,
        scheduler: HeartbeatScheduler,
        workspace_path: Path,
        mock_token_logger: Mock,
    ):
        """Test that skipped heartbeats don't include token counts."""
        # Create empty HEARTBEAT.md and no tasks (triggers skip).
        # NOTE: path will move to agent/HEARTBEAT.md after workspace restructure.
        heartbeat_md = workspace_path / "HEARTBEAT.md"
        heartbeat_md.write_text("")

        # Run heartbeat
        await scheduler._run_heartbeat()

        # Read JSONL log
        entries = read_heartbeat_log(workspace_path)
        assert len(entries) == 1

        entry = entries[0]
        assert entry["outcome"] == "skipped"
        assert entry["workspace"] == "test_workspace"
        assert "input_tokens" not in entry
        assert "output_tokens" not in entry
        assert "total_tokens" not in entry
        assert "llm_calls" not in entry
        assert entry["task_count"] == 0

        # Token logger should NOT be called for skipped heartbeats
        mock_token_logger.log.assert_not_called()

    @pytest.mark.asyncio
    async def test_heartbeat_task_count_multiple_tasks(
        self,
        scheduler: HeartbeatScheduler,
        workspace_path: Path,
    ):
        """Test task_count reflects correct number of active tasks."""
        # Create multiple tasks with different statuses
        create_tasks_yaml(
            workspace_path,
            [
                {"id": "task1", "status": "in_progress", "description": "Task 1"},
                {"id": "task2", "status": "pending", "description": "Task 2"},
                {"id": "task3", "status": "awaiting_check", "description": "Task 3"},
                {"id": "task4", "status": "completed", "description": "Task 4"},
                {"id": "task5", "status": "cancelled", "description": "Task 5"},
            ],
        )

        # Run heartbeat
        await scheduler._run_heartbeat()

        # Read JSONL log
        entries = read_heartbeat_log(workspace_path)
        assert len(entries) == 1

        entry = entries[0]
        # Only in_progress, pending, awaiting_check count as active
        assert entry["task_count"] == 3

    @pytest.mark.asyncio
    async def test_heartbeat_task_count_no_tasks(
        self,
        scheduler: HeartbeatScheduler,
        workspace_path: Path,
    ):
        """Test task_count is None when no TASKS.yaml exists."""
        # Create HEARTBEAT.md with content to prevent skip.
        # NOTE: path will move to agent/HEARTBEAT.md after workspace restructure.
        heartbeat_md = workspace_path / "HEARTBEAT.md"
        heartbeat_md.write_text("# Heartbeat\n\nSome pending work here")

        # Run heartbeat (no TASKS.yaml)
        await scheduler._run_heartbeat()

        # Read JSONL log
        entries = read_heartbeat_log(workspace_path)
        assert len(entries) == 1

        entry = entries[0]
        # task_count should be 0 when TASKS.yaml doesn't exist
        assert entry["task_count"] == 0

    @pytest.mark.asyncio
    async def test_heartbeat_no_metrics_available(
        self,
        scheduler: HeartbeatScheduler,
        workspace_path: Path,
        mock_agent_runner: Mock,
        mock_token_logger: Mock,
    ):
        """Test graceful handling when agent doesn't provide metrics."""
        # Create tasks
        create_tasks_yaml(
            workspace_path,
            [
                {"id": "task1", "status": "in_progress", "description": "Test task"},
            ],
        )

        # Remove metrics from agent runner
        mock_agent_runner.last_metrics = None

        # Run heartbeat
        await scheduler._run_heartbeat()

        # Read JSONL log
        entries = read_heartbeat_log(workspace_path)
        assert len(entries) == 1

        entry = entries[0]
        assert entry["outcome"] == "ran"
        # Token fields should not be present
        assert "input_tokens" not in entry
        assert "output_tokens" not in entry
        assert "total_tokens" not in entry
        assert "llm_calls" not in entry
        # task_count should still be present
        assert entry["task_count"] == 1

        # Token logger should not be called when no metrics
        mock_token_logger.log.assert_not_called()

    @pytest.mark.asyncio
    async def test_heartbeat_error_includes_partial_metrics(
        self,
        scheduler: HeartbeatScheduler,
        workspace_path: Path,
        mock_token_logger: Mock,
    ):
        """Test that errors during heartbeat still record task_count."""
        # Create tasks
        create_tasks_yaml(
            workspace_path,
            [
                {"id": "task1", "status": "in_progress", "description": "Test task"},
            ],
        )

        # Make agent raise an exception
        scheduler.agent_factory = Mock(side_effect=RuntimeError("Test error"))

        # Run heartbeat
        await scheduler._run_heartbeat()

        # Read JSONL log
        entries = read_heartbeat_log(workspace_path)
        assert len(entries) == 1

        entry = entries[0]
        assert entry["outcome"] == "error"
        assert entry["error"] == "Test error"
        assert entry["task_count"] == 1
        # No token metrics on error
        assert "input_tokens" not in entry

        # Token logger should not be called on error
        mock_token_logger.log.assert_not_called()

    @pytest.mark.asyncio
    async def test_token_logger_receives_correct_session_key(
        self,
        scheduler: HeartbeatScheduler,
        workspace_path: Path,
        mock_token_logger: Mock,
        mock_channels: dict,
    ):
        """Test that token logger receives correct session_key."""
        # Create tasks
        create_tasks_yaml(
            workspace_path,
            [
                {"id": "task1", "status": "in_progress", "description": "Test task"},
            ],
        )

        # Run heartbeat
        await scheduler._run_heartbeat()

        # Verify token logger was called with correct session_key
        mock_token_logger.log.assert_called_once()
        call_args = mock_token_logger.log.call_args
        assert call_args.kwargs["session_key"] == "telegram:123456789"

    @pytest.mark.asyncio
    async def test_heartbeat_outside_active_hours_no_metrics(
        self,
        workspace_path: Path,
        heartbeat_config: HeartbeatConfig,
        mock_agent_factory: Mock,
        mock_channels: dict,
        mock_token_logger: Mock,
    ):
        """Test that heartbeats outside active hours don't generate metrics."""
        heartbeat_config.active_hours = "23:00-23:30"

        scheduler = HeartbeatScheduler(
            workspace_name="test_workspace",
            workspace_path=workspace_path,
            agent_factory=mock_agent_factory,
            channels=mock_channels,
            config=heartbeat_config,
            token_logger=mock_token_logger,
        )

        workspace_path.mkdir(parents=True, exist_ok=True)
        (workspace_path / "data").mkdir(parents=True, exist_ok=True)

        # Mock active hours check to guarantee outside-hours behavior
        scheduler._is_within_active_hours = Mock(return_value=False)  # type: ignore[method-assign]

        # Run heartbeat
        await scheduler._run_heartbeat()

        # Read JSONL log
        entries = read_heartbeat_log(workspace_path)
        assert len(entries) == 1

        entry = entries[0]
        assert entry["outcome"] == "skipped"
        assert entry["reason"] == "outside active hours"
        # No token metrics or task_count
        assert "input_tokens" not in entry
        assert "task_count" not in entry

        # Token logger should not be called
        mock_token_logger.log.assert_not_called()
