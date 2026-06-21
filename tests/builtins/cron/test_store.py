"""Tests for DynamicCronStore and factory functions."""

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import patch

import pytest

from openpaw.stores.cron import (
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
        assert store.storage_file == workspace / "data" / "dynamic_crons.json"

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
        """Test removing a task by full ID returns the resolved UUID."""
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

        full_id = store.remove_task("removable")

        assert full_id == "removable"
        assert len(store.list_tasks()) == 0

    def test_remove_nonexistent_task(self, tmp_path: Any) -> None:
        """Test removing a task that doesn't exist returns None."""
        store = DynamicCronStore(tmp_path)

        result = store.remove_task("nonexistent-id")

        assert result is None

    def test_remove_task_by_prefix(self, tmp_path: Any) -> None:
        """Test removing a task using its 8-character ID prefix."""
        store = DynamicCronStore(tmp_path)

        # Use a well-known UUID so the prefix is deterministic
        known_uuid = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
        task = DynamicCronTask(
            id=known_uuid,
            task_type="once",
            prompt="Remove via prefix",
            created_at=datetime.now(UTC),
            run_at=datetime.now(UTC) + timedelta(hours=1),
        )
        store.add_task(task)
        assert len(store.list_tasks()) == 1

        # Remove using the 8-character prefix shown by list_scheduled()
        full_id = store.remove_task(known_uuid[:8])

        assert full_id == known_uuid
        assert len(store.list_tasks()) == 0

    def test_get_task_by_prefix(self, tmp_path: Any) -> None:
        """Test retrieving a task using its 8-character ID prefix."""
        store = DynamicCronStore(tmp_path)

        known_uuid = "b2c3d4e5-f6a7-8901-bcde-f12345678901"
        task = DynamicCronTask(
            id=known_uuid,
            task_type="interval",
            prompt="Find via prefix",
            created_at=datetime.now(UTC),
            interval_seconds=300,
            next_run=datetime.now(UTC) + timedelta(minutes=5),
        )
        store.add_task(task)

        retrieved = store.get_task(known_uuid[:8])

        assert retrieved is not None
        assert retrieved.id == known_uuid
        assert retrieved.prompt == "Find via prefix"

    def test_remove_task_ambiguous_prefix(self, tmp_path: Any) -> None:
        """Test that an ambiguous prefix raises ValueError."""
        store = DynamicCronStore(tmp_path)

        # Two UUIDs that share the same first 8 characters
        shared_prefix = "ffffffff"
        task1 = DynamicCronTask(
            id=f"{shared_prefix}-0000-0000-0000-000000000001",
            task_type="once",
            prompt="First task",
            created_at=datetime.now(UTC),
            run_at=datetime.now(UTC) + timedelta(hours=1),
        )
        task2 = DynamicCronTask(
            id=f"{shared_prefix}-0000-0000-0000-000000000002",
            task_type="once",
            prompt="Second task",
            created_at=datetime.now(UTC),
            run_at=datetime.now(UTC) + timedelta(hours=2),
        )
        store.add_task(task1)
        store.add_task(task2)

        with pytest.raises(ValueError, match="Ambiguous task ID prefix"):
            store.remove_task(shared_prefix)

    def test_get_task_ambiguous_prefix(self, tmp_path: Any) -> None:
        """Test that get_task with ambiguous prefix raises ValueError."""
        store = DynamicCronStore(tmp_path)

        shared_prefix = "eeeeeeee"
        task1 = DynamicCronTask(
            id=f"{shared_prefix}-0000-0000-0000-000000000001",
            task_type="once",
            prompt="First task",
            created_at=datetime.now(UTC),
            run_at=datetime.now(UTC) + timedelta(hours=1),
        )
        task2 = DynamicCronTask(
            id=f"{shared_prefix}-0000-0000-0000-000000000002",
            task_type="once",
            prompt="Second task",
            created_at=datetime.now(UTC),
            run_at=datetime.now(UTC) + timedelta(hours=2),
        )
        store.add_task(task1)
        store.add_task(task2)

        with pytest.raises(ValueError, match="Ambiguous task ID prefix"):
            store.get_task(shared_prefix)

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

    @patch("openpaw.stores.cron.datetime")
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

    @patch("openpaw.stores.cron.datetime")
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
