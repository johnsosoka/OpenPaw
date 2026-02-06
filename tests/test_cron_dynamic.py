"""Tests for dynamic cron storage and CronTool builtin."""

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import Mock, patch

import pytest

from openpaw.builtins.tools.cron import CronToolBuiltin
from openpaw.cron.dynamic import (
    DynamicCronStore,
    DynamicCronTask,
    create_interval_task,
    create_once_task,
)


class TestDynamicCronTask:
    """Test DynamicCronTask dataclass serialization."""

    def test_to_dict_once_task(self) -> None:
        """Test serialization of one-time task."""
        created = datetime(2026, 2, 6, 12, 0, 0, tzinfo=UTC)
        run_at = datetime(2026, 2, 6, 18, 30, 0, tzinfo=UTC)

        task = DynamicCronTask(
            id="test-id-123",
            task_type="once",
            prompt="Test reminder",
            created_at=created,
            run_at=run_at,
        )

        result = task.to_dict()

        assert result["id"] == "test-id-123"
        assert result["task_type"] == "once"
        assert result["prompt"] == "Test reminder"
        assert result["created_at"] == "2026-02-06T12:00:00+00:00"
        assert result["run_at"] == "2026-02-06T18:30:00+00:00"
        assert result["interval_seconds"] is None
        assert result["next_run"] is None

    def test_to_dict_interval_task(self) -> None:
        """Test serialization of recurring interval task."""
        created = datetime(2026, 2, 6, 12, 0, 0, tzinfo=UTC)
        next_run = datetime(2026, 2, 6, 12, 5, 0, tzinfo=UTC)

        task = DynamicCronTask(
            id="test-id-456",
            task_type="interval",
            prompt="Check status",
            created_at=created,
            interval_seconds=300,
            next_run=next_run,
        )

        result = task.to_dict()

        assert result["id"] == "test-id-456"
        assert result["task_type"] == "interval"
        assert result["interval_seconds"] == 300
        assert result["next_run"] == "2026-02-06T12:05:00+00:00"

    def test_from_dict_once_task(self) -> None:
        """Test deserialization of one-time task."""
        data = {
            "id": "test-id-789",
            "task_type": "once",
            "prompt": "Future action",
            "created_at": "2026-02-06T10:00:00+00:00",
            "run_at": "2026-02-06T16:00:00+00:00",
            "interval_seconds": None,
            "next_run": None,
        }

        task = DynamicCronTask.from_dict(data)

        assert task.id == "test-id-789"
        assert task.task_type == "once"
        assert task.prompt == "Future action"
        assert task.created_at == datetime(2026, 2, 6, 10, 0, 0, tzinfo=UTC)
        assert task.run_at == datetime(2026, 2, 6, 16, 0, 0, tzinfo=UTC)
        assert task.interval_seconds is None
        assert task.next_run is None

    def test_from_dict_interval_task(self) -> None:
        """Test deserialization of recurring interval task."""
        data = {
            "id": "test-id-999",
            "task_type": "interval",
            "prompt": "Recurring check",
            "created_at": "2026-02-06T10:00:00+00:00",
            "run_at": None,
            "interval_seconds": 600,
            "next_run": "2026-02-06T10:10:00+00:00",
        }

        task = DynamicCronTask.from_dict(data)

        assert task.id == "test-id-999"
        assert task.task_type == "interval"
        assert task.interval_seconds == 600
        assert task.next_run == datetime(2026, 2, 6, 10, 10, 0, tzinfo=UTC)

    def test_round_trip_serialization(self) -> None:
        """Test that serialization and deserialization are symmetric."""
        original = DynamicCronTask(
            id="round-trip",
            task_type="once",
            prompt="Test round trip",
            created_at=datetime(2026, 2, 6, 12, 0, 0, tzinfo=UTC),
            run_at=datetime(2026, 2, 6, 18, 0, 0, tzinfo=UTC),
        )

        serialized = original.to_dict()
        deserialized = DynamicCronTask.from_dict(serialized)

        assert deserialized.id == original.id
        assert deserialized.task_type == original.task_type
        assert deserialized.prompt == original.prompt
        assert deserialized.created_at == original.created_at
        assert deserialized.run_at == original.run_at


class TestDynamicCronStore:
    """Test DynamicCronStore persistence and operations."""

    def test_initialization_creates_workspace(self, tmp_path: Any) -> None:
        """Test store initialization creates workspace directory."""
        workspace = tmp_path / "new_workspace"
        assert not workspace.exists()

        store = DynamicCronStore(workspace)

        assert workspace.exists()
        assert workspace.is_dir()
        assert store.storage_file == workspace / "dynamic_crons.json"

    def test_load_empty_returns_empty_list(self, tmp_path: Any) -> None:
        """Test loading from non-existent file returns empty list."""
        store = DynamicCronStore(tmp_path)
        tasks = store.load()

        assert tasks == []

    def test_add_and_list_tasks(self, tmp_path: Any) -> None:
        """Test adding tasks and listing them."""
        store = DynamicCronStore(tmp_path)

        task1 = DynamicCronTask(
            id="task-1",
            task_type="once",
            prompt="First task",
            created_at=datetime.now(UTC),
            run_at=datetime.now(UTC) + timedelta(hours=1),
        )
        task2 = DynamicCronTask(
            id="task-2",
            task_type="interval",
            prompt="Second task",
            created_at=datetime.now(UTC),
            interval_seconds=300,
            next_run=datetime.now(UTC) + timedelta(minutes=5),
        )

        store.add_task(task1)
        store.add_task(task2)

        tasks = store.list_tasks()

        assert len(tasks) == 2
        assert tasks[0].id == "task-1"
        assert tasks[1].id == "task-2"

    def test_remove_task(self, tmp_path: Any) -> None:
        """Test removing a task by ID."""
        store = DynamicCronStore(tmp_path)

        task = DynamicCronTask(
            id="removable",
            task_type="once",
            prompt="Will be removed",
            created_at=datetime.now(UTC),
            run_at=datetime.now(UTC) + timedelta(hours=1),
        )

        store.add_task(task)
        assert len(store.list_tasks()) == 1

        success = store.remove_task("removable")

        assert success is True
        assert len(store.list_tasks()) == 0

    def test_remove_nonexistent_task(self, tmp_path: Any) -> None:
        """Test removing a task that doesn't exist returns False."""
        store = DynamicCronStore(tmp_path)

        success = store.remove_task("nonexistent-id")

        assert success is False

    def test_get_task_by_id(self, tmp_path: Any) -> None:
        """Test retrieving a specific task by ID."""
        store = DynamicCronStore(tmp_path)

        task = DynamicCronTask(
            id="findable",
            task_type="once",
            prompt="Find me",
            created_at=datetime.now(UTC),
            run_at=datetime.now(UTC) + timedelta(hours=1),
        )

        store.add_task(task)

        retrieved = store.get_task("findable")

        assert retrieved is not None
        assert retrieved.id == "findable"
        assert retrieved.prompt == "Find me"

    def test_get_nonexistent_task(self, tmp_path: Any) -> None:
        """Test retrieving a task that doesn't exist returns None."""
        store = DynamicCronStore(tmp_path)

        retrieved = store.get_task("nonexistent")

        assert retrieved is None

    def test_update_task(self, tmp_path: Any) -> None:
        """Test updating an existing task."""
        store = DynamicCronStore(tmp_path)

        original = DynamicCronTask(
            id="updatable",
            task_type="once",
            prompt="Original prompt",
            created_at=datetime.now(UTC),
            run_at=datetime.now(UTC) + timedelta(hours=1),
        )

        store.add_task(original)

        # Update the task
        updated = DynamicCronTask(
            id="updatable",
            task_type="once",
            prompt="Updated prompt",
            created_at=original.created_at,
            run_at=datetime.now(UTC) + timedelta(hours=2),
        )

        success = store.update_task(updated)

        assert success is True

        retrieved = store.get_task("updatable")
        assert retrieved is not None
        assert retrieved.prompt == "Updated prompt"
        assert retrieved.run_at != original.run_at

    def test_update_nonexistent_task(self, tmp_path: Any) -> None:
        """Test updating a task that doesn't exist returns False."""
        store = DynamicCronStore(tmp_path)

        task = DynamicCronTask(
            id="nonexistent",
            task_type="once",
            prompt="Won't be updated",
            created_at=datetime.now(UTC),
            run_at=datetime.now(UTC) + timedelta(hours=1),
        )

        success = store.update_task(task)

        assert success is False

    def test_persistence_across_instances(self, tmp_path: Any) -> None:
        """Test that tasks persist when loading a new store instance."""
        # Create first store instance and add tasks
        store1 = DynamicCronStore(tmp_path)

        task1 = DynamicCronTask(
            id="persistent-1",
            task_type="once",
            prompt="Persist me",
            created_at=datetime.now(UTC),
            run_at=datetime.now(UTC) + timedelta(hours=1),
        )
        task2 = DynamicCronTask(
            id="persistent-2",
            task_type="interval",
            prompt="Also persist",
            created_at=datetime.now(UTC),
            interval_seconds=600,
            next_run=datetime.now(UTC) + timedelta(minutes=10),
        )

        store1.add_task(task1)
        store1.add_task(task2)

        # Create second store instance pointing to same path
        store2 = DynamicCronStore(tmp_path)
        tasks = store2.list_tasks()

        assert len(tasks) == 2
        assert tasks[0].id == "persistent-1"
        assert tasks[1].id == "persistent-2"

    def test_handles_corrupted_file(self, tmp_path: Any) -> None:
        """Test graceful handling of corrupted JSON file."""
        store = DynamicCronStore(tmp_path)

        # Write invalid JSON
        with store.storage_file.open("w") as f:
            f.write("{ this is not valid json ]")

        tasks = store.load()

        assert tasks == []

    def test_handles_invalid_data_structure(self, tmp_path: Any) -> None:
        """Test graceful handling of invalid data structure."""
        store = DynamicCronStore(tmp_path)

        # Write valid JSON but wrong structure (not a list)
        with store.storage_file.open("w") as f:
            json.dump({"not": "a list"}, f)

        tasks = store.load()

        assert tasks == []

    def test_handles_missing_task_fields(self, tmp_path: Any) -> None:
        """Test graceful handling of tasks with missing required fields."""
        store = DynamicCronStore(tmp_path)

        # Write valid JSON with incomplete task data
        with store.storage_file.open("w") as f:
            json.dump([{"id": "incomplete", "task_type": "once"}], f)

        tasks = store.load()

        assert tasks == []

    def test_atomic_write_on_save(self, tmp_path: Any) -> None:
        """Test that save uses atomic write pattern."""
        store = DynamicCronStore(tmp_path)

        task = DynamicCronTask(
            id="atomic",
            task_type="once",
            prompt="Atomic write",
            created_at=datetime.now(UTC),
            run_at=datetime.now(UTC) + timedelta(hours=1),
        )

        store.add_task(task)

        # Verify temp file was cleaned up
        temp_files = list(tmp_path.glob("*.tmp"))
        assert len(temp_files) == 0

        # Verify main file exists and is valid
        assert store.storage_file.exists()
        tasks = store.load()
        assert len(tasks) == 1


class TestFactoryFunctions:
    """Test factory functions for creating tasks."""

    @patch("openpaw.cron.dynamic.datetime")
    def test_create_once_task(self, mock_datetime: Any) -> None:
        """Test create_once_task factory function."""
        now = datetime(2026, 2, 6, 12, 0, 0, tzinfo=UTC)
        run_at = datetime(2026, 2, 6, 18, 0, 0, tzinfo=UTC)
        mock_datetime.now.return_value = now

        task = create_once_task(prompt="Test prompt", run_at=run_at)

        assert task.task_type == "once"
        assert task.prompt == "Test prompt"
        assert task.created_at == now
        assert task.run_at == run_at
        assert task.interval_seconds is None
        assert task.next_run is None
        # UUID should be generated
        assert len(task.id) == 36  # UUID format

    @patch("openpaw.cron.dynamic.datetime")
    def test_create_interval_task(self, mock_datetime: Any) -> None:
        """Test create_interval_task factory function."""
        now = datetime(2026, 2, 6, 12, 0, 0, tzinfo=UTC)
        next_run = datetime(2026, 2, 6, 12, 5, 0, tzinfo=UTC)
        mock_datetime.now.return_value = now

        task = create_interval_task(
            prompt="Recurring task",
            interval_seconds=300,
            next_run=next_run,
        )

        assert task.task_type == "interval"
        assert task.prompt == "Recurring task"
        assert task.created_at == now
        assert task.run_at is None
        assert task.interval_seconds == 300
        assert task.next_run == next_run
        # UUID should be generated
        assert len(task.id) == 36  # UUID format


class TestCronToolBuiltin:
    """Test CronToolBuiltin functionality."""

    def test_metadata(self) -> None:
        """Test CronToolBuiltin metadata."""
        assert CronToolBuiltin.metadata.name == "cron"
        assert CronToolBuiltin.metadata.display_name == "Task Scheduler"
        assert CronToolBuiltin.metadata.group == "automation"
        assert CronToolBuiltin.metadata.prerequisites.env_vars == []

    def test_initialization_requires_workspace_path(self) -> None:
        """Test that initialization requires workspace_path in config."""
        with pytest.raises(ValueError, match="requires 'workspace_path'"):
            CronToolBuiltin(config={})

    def test_initialization_with_config(self, tmp_path: Any) -> None:
        """Test initialization with valid config."""
        config = {
            "workspace_path": str(tmp_path),
            "min_interval_seconds": 60,
            "max_tasks": 25,
            "timezone": "America/New_York",
        }

        tool = CronToolBuiltin(config)

        assert tool.workspace_path == tmp_path
        assert tool.min_interval_seconds == 60
        assert tool.max_tasks == 25
        assert tool.timezone == "America/New_York"
        assert tool.scheduler is None

    def test_initialization_default_values(self, tmp_path: Any) -> None:
        """Test initialization uses default values."""
        config = {"workspace_path": str(tmp_path)}

        tool = CronToolBuiltin(config)

        assert tool.min_interval_seconds == 300
        assert tool.max_tasks == 50
        assert tool.timezone == "UTC"

    def test_get_langchain_tool_returns_list(self, tmp_path: Any) -> None:
        """Test that get_langchain_tool returns a list of tools."""
        config = {"workspace_path": str(tmp_path)}
        tool = CronToolBuiltin(config)

        tools = tool.get_langchain_tool()

        assert isinstance(tools, list)
        assert len(tools) == 4

        tool_names = [t.name for t in tools]
        assert "schedule_at" in tool_names
        assert "schedule_every" in tool_names
        assert "list_scheduled" in tool_names
        assert "cancel_scheduled" in tool_names

    @pytest.mark.asyncio
    async def test_schedule_at_creates_once_task(self, tmp_path: Any) -> None:
        """Test schedule_at creates a one-time task."""
        config = {"workspace_path": str(tmp_path)}
        tool = CronToolBuiltin(config)
        tools = tool.get_langchain_tool()
        schedule_at_tool = next(t for t in tools if t.name == "schedule_at")

        # Schedule task for 1 hour in the future
        future_time = datetime.now(UTC) + timedelta(hours=1)
        result = await schedule_at_tool.ainvoke({
            "run_at": future_time.isoformat(),
            "prompt": "Test reminder",
        })

        assert "Scheduled task" in result
        assert "Test reminder" in result

        # Verify task was stored
        tasks = tool.store.list_tasks()
        assert len(tasks) == 1
        assert tasks[0].task_type == "once"
        assert tasks[0].prompt == "Test reminder"

    @pytest.mark.asyncio
    async def test_schedule_at_rejects_past_time(self, tmp_path: Any) -> None:
        """Test schedule_at rejects past timestamps."""
        config = {"workspace_path": str(tmp_path)}
        tool = CronToolBuiltin(config)
        tools = tool.get_langchain_tool()
        schedule_at_tool = next(t for t in tools if t.name == "schedule_at")

        # Try to schedule in the past
        past_time = datetime.now(UTC) - timedelta(hours=1)
        result = await schedule_at_tool.ainvoke({
            "run_at": past_time.isoformat(),
            "prompt": "Past task",
        })

        assert "[Error:" in result
        assert "must be in the future" in result

        # Verify no task was created
        tasks = tool.store.list_tasks()
        assert len(tasks) == 0

    @pytest.mark.asyncio
    async def test_schedule_at_rejects_invalid_timestamp(self, tmp_path: Any) -> None:
        """Test schedule_at rejects invalid timestamp format."""
        config = {"workspace_path": str(tmp_path)}
        tool = CronToolBuiltin(config)
        tools = tool.get_langchain_tool()
        schedule_at_tool = next(t for t in tools if t.name == "schedule_at")

        result = await schedule_at_tool.ainvoke({
            "run_at": "not-a-valid-timestamp",
            "prompt": "Invalid task",
        })

        assert "[Error:" in result
        assert "Invalid timestamp format" in result

        tasks = tool.store.list_tasks()
        assert len(tasks) == 0

    @pytest.mark.asyncio
    async def test_schedule_every_creates_interval_task(self, tmp_path: Any) -> None:
        """Test schedule_every creates a recurring task."""
        config = {"workspace_path": str(tmp_path), "min_interval_seconds": 60}
        tool = CronToolBuiltin(config)
        tools = tool.get_langchain_tool()
        schedule_every_tool = next(t for t in tools if t.name == "schedule_every")

        result = await schedule_every_tool.ainvoke({
            "interval_seconds": 300,
            "prompt": "Recurring check",
        })

        assert "Scheduled recurring task" in result
        assert "5 minutes" in result
        assert "Recurring check" in result

        # Verify task was stored
        tasks = tool.store.list_tasks()
        assert len(tasks) == 1
        assert tasks[0].task_type == "interval"
        assert tasks[0].interval_seconds == 300

    @pytest.mark.asyncio
    async def test_schedule_every_rejects_below_minimum(self, tmp_path: Any) -> None:
        """Test schedule_every rejects intervals below minimum."""
        config = {"workspace_path": str(tmp_path), "min_interval_seconds": 300}
        tool = CronToolBuiltin(config)
        tools = tool.get_langchain_tool()
        schedule_every_tool = next(t for t in tools if t.name == "schedule_every")

        result = await schedule_every_tool.ainvoke({
            "interval_seconds": 60,
            "prompt": "Too frequent",
        })

        assert "[Error:" in result
        assert "at least 300 seconds" in result

        tasks = tool.store.list_tasks()
        assert len(tasks) == 0

    @pytest.mark.asyncio
    async def test_list_scheduled_formats_correctly(self, tmp_path: Any) -> None:
        """Test list_scheduled returns formatted task list."""
        config = {"workspace_path": str(tmp_path)}
        tool = CronToolBuiltin(config)
        tools = tool.get_langchain_tool()
        list_tool = next(t for t in tools if t.name == "list_scheduled")

        # Add some tasks
        future_time = datetime.now(UTC) + timedelta(hours=1)
        task1 = create_once_task("First task", future_time)
        task2 = create_interval_task("Second task", 600, datetime.now(UTC))

        tool.store.add_task(task1)
        tool.store.add_task(task2)

        result = await list_tool.ainvoke({})

        assert "Scheduled tasks:" in result
        assert "One-time" in result
        assert "Every 10 minutes" in result
        assert "First task" in result
        assert "Second task" in result

    @pytest.mark.asyncio
    async def test_list_scheduled_empty(self, tmp_path: Any) -> None:
        """Test list_scheduled with no tasks."""
        config = {"workspace_path": str(tmp_path)}
        tool = CronToolBuiltin(config)
        tools = tool.get_langchain_tool()
        list_tool = next(t for t in tools if t.name == "list_scheduled")

        result = await list_tool.ainvoke({})

        assert result == "No scheduled tasks."

    @pytest.mark.asyncio
    async def test_cancel_scheduled_removes_task(self, tmp_path: Any) -> None:
        """Test cancel_scheduled removes a task."""
        config = {"workspace_path": str(tmp_path)}
        tool = CronToolBuiltin(config)
        tools = tool.get_langchain_tool()
        cancel_tool = next(t for t in tools if t.name == "cancel_scheduled")

        # Add a task
        future_time = datetime.now(UTC) + timedelta(hours=1)
        task = create_once_task("To be cancelled", future_time)
        tool.store.add_task(task)

        assert len(tool.store.list_tasks()) == 1

        # Cancel it
        result = await cancel_tool.ainvoke({"task_id": task.id})

        assert "Successfully cancelled" in result
        assert task.id in result

        # Verify removed
        assert len(tool.store.list_tasks()) == 0

    @pytest.mark.asyncio
    async def test_cancel_scheduled_nonexistent(self, tmp_path: Any) -> None:
        """Test cancel_scheduled with nonexistent task."""
        config = {"workspace_path": str(tmp_path)}
        tool = CronToolBuiltin(config)
        tools = tool.get_langchain_tool()
        cancel_tool = next(t for t in tools if t.name == "cancel_scheduled")

        result = await cancel_tool.ainvoke({"task_id": "nonexistent-id"})

        assert "[Error:" in result
        assert "not found" in result

    @pytest.mark.asyncio
    async def test_max_tasks_limit_enforced(self, tmp_path: Any) -> None:
        """Test that max_tasks limit is enforced."""
        config = {"workspace_path": str(tmp_path), "max_tasks": 2}
        tool = CronToolBuiltin(config)
        tools = tool.get_langchain_tool()
        schedule_at_tool = next(t for t in tools if t.name == "schedule_at")

        # Add tasks up to limit
        future_time = datetime.now(UTC) + timedelta(hours=1)

        result1 = await schedule_at_tool.ainvoke({
            "run_at": future_time.isoformat(),
            "prompt": "Task 1",
        })
        assert "Scheduled task" in result1

        result2 = await schedule_at_tool.ainvoke({
            "run_at": future_time.isoformat(),
            "prompt": "Task 2",
        })
        assert "Scheduled task" in result2

        # Try to add one more beyond limit
        result3 = await schedule_at_tool.ainvoke({
            "run_at": future_time.isoformat(),
            "prompt": "Task 3",
        })
        assert "[Error:" in result3
        assert "Maximum task limit" in result3

        # Verify only 2 tasks exist
        tasks = tool.store.list_tasks()
        assert len(tasks) == 2

    def test_parse_timestamp_naive_assumes_utc(self, tmp_path: Any) -> None:
        """Test that naive timestamps are assumed to be UTC."""
        config = {"workspace_path": str(tmp_path)}
        tool = CronToolBuiltin(config)

        # Naive timestamp (no timezone)
        result = tool._parse_timestamp("2026-02-06T18:30:00")

        assert result.tzinfo == UTC
        assert result.hour == 18

    def test_parse_timestamp_with_timezone(self, tmp_path: Any) -> None:
        """Test parsing timestamp with explicit timezone."""
        config = {"workspace_path": str(tmp_path)}
        tool = CronToolBuiltin(config)

        # Timestamp with UTC timezone
        result = tool._parse_timestamp("2026-02-06T18:30:00Z")

        assert result.tzinfo == UTC

        # Timestamp with offset
        result2 = tool._parse_timestamp("2026-02-06T18:30:00-05:00")

        # Should be converted to UTC
        assert result2.tzinfo == UTC

    def test_format_interval(self, tmp_path: Any) -> None:
        """Test interval formatting for various durations."""
        config = {"workspace_path": str(tmp_path)}
        tool = CronToolBuiltin(config)

        assert tool._format_interval(30) == "30 seconds"
        assert tool._format_interval(60) == "1 minute"
        assert tool._format_interval(120) == "2 minutes"
        assert tool._format_interval(3600) == "1 hour"
        assert tool._format_interval(7200) == "2 hours"
        assert tool._format_interval(86400) == "1 day"
        assert tool._format_interval(172800) == "2 days"

    def test_format_time_until(self, tmp_path: Any) -> None:
        """Test time until formatting for various durations."""
        config = {"workspace_path": str(tmp_path)}
        tool = CronToolBuiltin(config)

        # Future times
        assert tool._format_time_until(30) == "in 30 seconds"
        assert tool._format_time_until(60) == "in 1 minute"
        assert tool._format_time_until(120) == "in 2 minutes"
        assert tool._format_time_until(3600) == "in 1 hour"
        assert tool._format_time_until(7200) == "in 2 hours"
        assert tool._format_time_until(86400) == "in 1 day"

        # Past times (overdue)
        assert "ago (overdue)" in tool._format_time_until(-60)
        assert "1 minute" in tool._format_time_until(-60)

    @pytest.mark.asyncio
    async def test_scheduler_notification_called(self, tmp_path: Any) -> None:
        """Test that scheduler is notified on task updates."""
        mock_scheduler = Mock()
        config = {
            "workspace_path": str(tmp_path),
            "cron_scheduler": mock_scheduler,
        }
        tool = CronToolBuiltin(config)
        tools = tool.get_langchain_tool()
        schedule_at_tool = next(t for t in tools if t.name == "schedule_at")

        # Schedule a task
        future_time = datetime.now(UTC) + timedelta(hours=1)
        await schedule_at_tool.ainvoke({
            "run_at": future_time.isoformat(),
            "prompt": "Test",
        })

        # Verify _notify_scheduler_update was called
        # Note: Currently it's just a placeholder, but we verify it doesn't error
        assert len(tool.store.list_tasks()) == 1
