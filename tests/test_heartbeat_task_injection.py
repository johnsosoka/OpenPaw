"""Tests for heartbeat task summary injection."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock

import pytest

from openpaw.core.config import HeartbeatConfig
from openpaw.heartbeat.scheduler import HeartbeatScheduler


@pytest.fixture
def mock_agent_factory():
    """Create a mock agent factory."""
    return Mock(return_value=Mock())


@pytest.fixture
def mock_channels():
    """Create mock channels."""
    return {"telegram": Mock()}


@pytest.fixture
def heartbeat_config():
    """Create a basic heartbeat configuration."""
    return HeartbeatConfig(
        enabled=True,
        interval_minutes=30,
        suppress_ok=True,
        target_channel="telegram",
        target_chat_id="123456789",
    )


@pytest.fixture
def scheduler(tmp_path, mock_agent_factory, mock_channels, heartbeat_config):
    """Create a HeartbeatScheduler instance."""
    return HeartbeatScheduler(
        workspace_name="test_workspace",
        workspace_path=tmp_path,
        agent_factory=mock_agent_factory,
        channels=mock_channels,
        config=heartbeat_config,
    )


class TestBuildTaskSummary:
    """Test the _build_task_summary helper method."""

    def test_empty_tasks_returns_none(self, scheduler):
        """Empty task list returns None."""
        result = scheduler._build_task_summary([])
        assert result is None

    def test_single_task_recent(self, scheduler):
        """Single recent task formats correctly."""
        now = datetime.now(UTC)
        created_at = (now - timedelta(minutes=15)).isoformat()

        tasks = [
            {
                "id": "abc12345-6789-abcd-ef01-234567890abc",
                "status": "in_progress",
                "description": "Market analysis",
                "started_at": created_at,
            }
        ]

        result = scheduler._build_task_summary(tasks)
        assert result is not None
        assert "Active Tasks (1):" in result
        assert "[abc12345]" in result
        assert "in_progress" in result
        assert '"Market analysis"' in result
        assert "15m ago" in result or "14m ago" in result  # Allow for timing variance
        assert "running" in result

    def test_multiple_tasks_different_ages(self, scheduler):
        """Multiple tasks with different ages format correctly."""
        now = datetime.now(UTC)

        tasks = [
            {
                "id": "task-001",
                "status": "in_progress",
                "description": "Task A",
                "started_at": (now - timedelta(minutes=15)).isoformat(),
            },
            {
                "id": "task-002",
                "status": "awaiting_check",
                "description": "Task B",
                "created_at": (now - timedelta(hours=2)).isoformat(),
            },
            {
                "id": "task-003",
                "status": "pending",
                "description": "Task C",
                "created_at": (now - timedelta(minutes=5)).isoformat(),
            },
        ]

        result = scheduler._build_task_summary(tasks)
        assert result is not None
        assert "Active Tasks (3):" in result
        assert "[task-001]" in result
        assert "[task-002]" in result
        assert "[task-003]" in result
        assert "in_progress" in result
        assert "awaiting_check" in result
        assert "pending" in result

    def test_task_age_hours(self, scheduler):
        """Tasks older than an hour show hours."""
        now = datetime.now(UTC)
        created_at = (now - timedelta(hours=3)).isoformat()

        tasks = [
            {
                "id": "task-hour",
                "status": "pending",
                "description": "Old task",
                "created_at": created_at,
            }
        ]

        result = scheduler._build_task_summary(tasks)
        assert "3h ago" in result or "2h ago" in result  # Allow for timing variance

    def test_task_age_days(self, scheduler):
        """Tasks older than a day show days."""
        now = datetime.now(UTC)
        created_at = (now - timedelta(days=2)).isoformat()

        tasks = [
            {
                "id": "task-day",
                "status": "pending",
                "description": "Very old task",
                "created_at": created_at,
            }
        ]

        result = scheduler._build_task_summary(tasks)
        assert "2d ago" in result or "1d ago" in result  # Allow for timing variance

    def test_missing_timestamps_graceful(self, scheduler):
        """Tasks with missing timestamps handle gracefully."""
        tasks = [
            {
                "id": "task-no-time",
                "status": "pending",
                "description": "No timestamp task",
            }
        ]

        result = scheduler._build_task_summary(tasks)
        assert result is not None
        assert "[task-no-" in result
        assert "pending" in result
        assert "unknown age" in result

    def test_invalid_timestamp_format_graceful(self, scheduler):
        """Tasks with invalid timestamp format handle gracefully."""
        tasks = [
            {
                "id": "task-bad-time",
                "status": "pending",
                "description": "Bad timestamp",
                "created_at": "not-a-timestamp",
            }
        ]

        result = scheduler._build_task_summary(tasks)
        assert result is not None
        assert "unknown age" in result

    def test_short_id_truncation(self, scheduler):
        """Task IDs are truncated to 8 characters."""
        tasks = [
            {
                "id": "very-long-task-id-that-should-be-truncated",
                "status": "pending",
                "description": "Test task",
                "created_at": datetime.now(UTC).isoformat(),
            }
        ]

        result = scheduler._build_task_summary(tasks)
        assert "[very-lon]" in result
        assert "very-long-task-id-that-should-be-truncated" not in result

    def test_missing_description_fallback(self, scheduler):
        """Tasks without description show 'Untitled'."""
        tasks = [
            {
                "id": "task-no-desc",
                "status": "pending",
                "created_at": datetime.now(UTC).isoformat(),
            }
        ]

        result = scheduler._build_task_summary(tasks)
        assert '"Untitled"' in result

    def test_started_at_preferred_over_created_at(self, scheduler):
        """started_at is used for age calculation if available."""
        now = datetime.now(UTC)
        created_at = (now - timedelta(hours=10)).isoformat()
        started_at = (now - timedelta(minutes=5)).isoformat()

        tasks = [
            {
                "id": "task-both",
                "status": "in_progress",
                "description": "Task with both timestamps",
                "created_at": created_at,
                "started_at": started_at,
            }
        ]

        result = scheduler._build_task_summary(tasks)
        # Should use started_at (5m) not created_at (10h)
        assert "5m ago" in result or "4m ago" in result
        assert "10h ago" not in result


class TestShouldSkipHeartbeat:
    """Test the _should_skip_heartbeat method with task summary."""

    def test_returns_four_tuple(self, scheduler, tmp_path):
        """Method returns four-tuple (skip, reason, summary, task_count)."""
        # Create empty HEARTBEAT.md
        (tmp_path / "HEARTBEAT.md").write_text("")

        should_skip, reason, task_summary, task_count = scheduler._should_skip_heartbeat()
        assert isinstance(should_skip, bool)
        assert isinstance(reason, str)
        assert task_summary is None or isinstance(task_summary, str)
        assert isinstance(task_count, int)

    def test_skip_returns_none_summary(self, scheduler, tmp_path):
        """When skipping, task summary is None."""
        # Empty heartbeat and no tasks
        (tmp_path / "HEARTBEAT.md").write_text("")

        should_skip, reason, task_summary, task_count = scheduler._should_skip_heartbeat()
        assert should_skip is True
        assert task_summary is None
        assert task_count == 0

    def test_active_tasks_returns_summary(self, scheduler, tmp_path):
        """When not skipping with active tasks, summary is provided."""
        import yaml

        # Create HEARTBEAT.md with content
        (tmp_path / "HEARTBEAT.md").write_text("# Heartbeat\nSome pending work here")

        # Create TASKS.yaml with active task
        tasks_data = {
            "version": 1,
            "tasks": [
                {
                    "id": "test-task-id",
                    "status": "in_progress",
                    "description": "Test task",
                    "created_at": datetime.now(UTC).isoformat(),
                }
            ],
        }
        with (tmp_path / "TASKS.yaml").open("w") as f:
            yaml.dump(tasks_data, f)

        should_skip, reason, task_summary, task_count = scheduler._should_skip_heartbeat()
        assert should_skip is False
        assert task_summary is not None
        assert "Active Tasks (1):" in task_summary
        assert "[test-tas]" in task_summary
        assert task_count == 1

    def test_no_active_tasks_returns_none_summary(self, scheduler, tmp_path):
        """When not skipping but no active tasks, summary is None."""
        import yaml

        # Create HEARTBEAT.md with content
        (tmp_path / "HEARTBEAT.md").write_text("# Heartbeat\nSome pending work here")

        # Create TASKS.yaml with only completed tasks
        tasks_data = {
            "version": 1,
            "tasks": [
                {
                    "id": "completed-task",
                    "status": "completed",
                    "description": "Done",
                    "created_at": datetime.now(UTC).isoformat(),
                }
            ],
        }
        with (tmp_path / "TASKS.yaml").open("w") as f:
            yaml.dump(tasks_data, f)

        should_skip, reason, task_summary, task_count = scheduler._should_skip_heartbeat()
        assert should_skip is False
        assert task_summary is None
        assert task_count == 0


class TestBuildHeartbeatPrompt:
    """Test the _build_heartbeat_prompt method with task summary."""

    def test_prompt_without_summary(self, scheduler):
        """Prompt without task summary is unchanged."""
        prompt = scheduler._build_heartbeat_prompt()
        assert "[HEARTBEAT CHECK -" in prompt
        assert "<active_tasks>" not in prompt

    def test_prompt_with_summary(self, scheduler):
        """Prompt with task summary includes the summary in XML tags."""
        task_summary = "Active Tasks (2):\n- [task-001] in_progress | \"Task A\" (running 5m ago)"
        prompt = scheduler._build_heartbeat_prompt(task_summary=task_summary)

        assert "[HEARTBEAT CHECK -" in prompt
        assert "<active_tasks>" in prompt
        assert "</active_tasks>" in prompt
        assert "Active Tasks (2):" in prompt
        assert "[task-001]" in prompt

    def test_prompt_with_none_summary(self, scheduler):
        """Prompt with None summary is unchanged."""
        prompt = scheduler._build_heartbeat_prompt(task_summary=None)
        assert "[HEARTBEAT CHECK -" in prompt
        assert "<active_tasks>" not in prompt
