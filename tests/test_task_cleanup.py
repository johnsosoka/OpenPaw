"""Tests for task cleanup functionality."""

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from openpaw.model.task import Task, TaskStatus
from openpaw.stores.task import TaskStore


@pytest.fixture
def task_store(tmp_path: Path) -> TaskStore:
    """Create a TaskStore instance for testing."""
    return TaskStore(tmp_path)


@pytest.fixture
def sample_task() -> Task:
    """Create a sample task for testing."""
    return Task(
        id=str(uuid.uuid4()),
        type="test",
        description="Test task",
        status=TaskStatus.PENDING,
    )


def test_cleanup_uses_created_at_fallback(task_store: TaskStore):
    """Test that cleanup falls back to created_at when completed_at is missing."""
    now = datetime.now(UTC)
    old_timestamp = now - timedelta(days=5)
    recent_timestamp = now - timedelta(days=1)

    # Create old completed task WITHOUT completed_at (should be removed)
    old_task = Task(
        id=str(uuid.uuid4()),
        type="test",
        description="Old completed task",
        status=TaskStatus.COMPLETED,
        created_at=old_timestamp,
        completed_at=None,  # Missing completed_at
    )
    task_store.create(old_task)

    # Create recent completed task WITHOUT completed_at (should be kept)
    recent_task = Task(
        id=str(uuid.uuid4()),
        type="test",
        description="Recent completed task",
        status=TaskStatus.COMPLETED,
        created_at=recent_timestamp,
        completed_at=None,  # Missing completed_at
    )
    task_store.create(recent_task)

    # Run cleanup with 3 day threshold
    removed = task_store.cleanup_old_tasks(max_age_days=3, stale_threshold_hours=48)

    # Old task should be removed (uses created_at fallback)
    assert removed == 1
    assert task_store.get(old_task.id) is None
    assert task_store.get(recent_task.id) is not None


def test_cleanup_prefers_completed_at_over_created_at(task_store: TaskStore):
    """Test that cleanup prefers completed_at when available."""
    now = datetime.now(UTC)
    old_created = now - timedelta(days=5)
    recent_completed = now - timedelta(days=1)

    # Create task with old created_at but recent completed_at
    task = Task(
        id=str(uuid.uuid4()),
        type="test",
        description="Task with recent completion",
        status=TaskStatus.COMPLETED,
        created_at=old_created,
        completed_at=recent_completed,
    )
    task_store.create(task)

    # Run cleanup with 3 day threshold
    removed = task_store.cleanup_old_tasks(max_age_days=3, stale_threshold_hours=48)

    # Task should be kept (completed_at is recent)
    assert removed == 0
    assert task_store.get(task.id) is not None


def test_stale_task_detection_in_progress(task_store: TaskStore):
    """Test that stale in_progress tasks are auto-failed."""
    now = datetime.now(UTC)
    stale_timestamp = now - timedelta(hours=50)  # 50 hours ago

    # Create stale in_progress task
    task = Task(
        id=str(uuid.uuid4()),
        type="test",
        description="Stale in_progress task",
        status=TaskStatus.IN_PROGRESS,
        created_at=stale_timestamp,
    )
    task_store.create(task)

    # Run cleanup with 48 hour stale threshold
    removed = task_store.cleanup_old_tasks(max_age_days=3, stale_threshold_hours=48)

    # Task should be auto-failed (not removed, status changed)
    assert removed == 0  # Not removed, just transitioned
    updated_task = task_store.get(task.id)
    assert updated_task is not None
    assert updated_task.status == TaskStatus.FAILED
    assert updated_task.completed_at is not None
    assert "[auto] Marked failed: stale for >48 hours" in updated_task.notes


def test_stale_task_detection_pending(task_store: TaskStore):
    """Test that stale pending tasks are auto-failed."""
    now = datetime.now(UTC)
    stale_timestamp = now - timedelta(hours=72)  # 72 hours ago

    # Create stale pending task
    task = Task(
        id=str(uuid.uuid4()),
        type="test",
        description="Stale pending task",
        status=TaskStatus.PENDING,
        created_at=stale_timestamp,
    )
    task_store.create(task)

    # Run cleanup with 48 hour stale threshold
    removed = task_store.cleanup_old_tasks(max_age_days=3, stale_threshold_hours=48)

    # Task should be auto-failed
    assert removed == 0
    updated_task = task_store.get(task.id)
    assert updated_task is not None
    assert updated_task.status == TaskStatus.FAILED
    assert updated_task.completed_at is not None
    assert "[auto] Marked failed: stale for >48 hours" in updated_task.notes


def test_stale_task_preserves_existing_notes(task_store: TaskStore):
    """Test that stale detection appends to existing notes."""
    now = datetime.now(UTC)
    stale_timestamp = now - timedelta(hours=60)

    # Create stale task with existing notes
    task = Task(
        id=str(uuid.uuid4()),
        type="test",
        description="Stale task with notes",
        status=TaskStatus.IN_PROGRESS,
        created_at=stale_timestamp,
        notes="Existing notes about task progress",
    )
    task_store.create(task)

    # Run cleanup
    task_store.cleanup_old_tasks(max_age_days=3, stale_threshold_hours=48)

    # Notes should contain both old and new
    updated_task = task_store.get(task.id)
    assert updated_task is not None
    assert "Existing notes about task progress" in updated_task.notes
    assert "[auto] Marked failed: stale for >48 hours" in updated_task.notes


def test_stale_then_cleanup(task_store: TaskStore):
    """Test that stale tasks transition to failed with recent completed_at."""
    now = datetime.now(UTC)
    very_old_timestamp = now - timedelta(days=10)

    # Create very old stale task
    task = Task(
        id=str(uuid.uuid4()),
        type="test",
        description="Very old stale task",
        status=TaskStatus.IN_PROGRESS,
        created_at=very_old_timestamp,
    )
    task_store.create(task)

    # First cleanup: auto-fail
    removed = task_store.cleanup_old_tasks(max_age_days=3, stale_threshold_hours=48)
    assert removed == 0  # Not removed, just failed

    # Verify it was failed with recent completed_at
    updated_task = task_store.get(task.id)
    assert updated_task is not None
    assert updated_task.status == TaskStatus.FAILED
    assert updated_task.completed_at is not None

    # The completed_at timestamp is recent (set to now), so task won't be removed yet
    # This is correct behavior - failed tasks stay around for max_age_days after failure
    removed = task_store.cleanup_old_tasks(max_age_days=3, stale_threshold_hours=48)
    assert removed == 0  # Still kept because completed_at is recent
    assert task_store.get(task.id) is not None


def test_recent_active_tasks_not_touched(task_store: TaskStore):
    """Test that recent active tasks are not affected by cleanup."""
    now = datetime.now(UTC)
    recent_timestamp = now - timedelta(hours=24)

    # Create recent active tasks
    pending_task = Task(
        id=str(uuid.uuid4()),
        type="test",
        description="Recent pending",
        status=TaskStatus.PENDING,
        created_at=recent_timestamp,
    )
    in_progress_task = Task(
        id=str(uuid.uuid4()),
        type="test",
        description="Recent in progress",
        status=TaskStatus.IN_PROGRESS,
        created_at=recent_timestamp,
    )
    task_store.create(pending_task)
    task_store.create(in_progress_task)

    # Run cleanup
    removed = task_store.cleanup_old_tasks(max_age_days=3, stale_threshold_hours=48)

    # Both tasks should remain unchanged
    assert removed == 0
    assert task_store.get(pending_task.id).status == TaskStatus.PENDING
    assert task_store.get(in_progress_task.id).status == TaskStatus.IN_PROGRESS


def test_cleanup_default_params(task_store: TaskStore):
    """Test that default cleanup parameters work correctly."""
    now = datetime.now(UTC)

    # Create old completed task (4 days old, beyond default 3-day threshold)
    old_task = Task(
        id=str(uuid.uuid4()),
        type="test",
        description="Old completed",
        status=TaskStatus.COMPLETED,
        created_at=now - timedelta(days=4),
        completed_at=now - timedelta(days=4),
    )
    task_store.create(old_task)

    # Run cleanup with defaults (max_age_days=3)
    removed = task_store.cleanup_old_tasks()

    # Task should be removed
    assert removed == 1
    assert task_store.get(old_task.id) is None


def test_delete_task_tool_happy_path(task_store: TaskStore):
    """Test delete_task tool functionality with completed task."""
    # Create completed task
    task = Task(
        id=str(uuid.uuid4()),
        type="test",
        description="Completed task to delete",
        status=TaskStatus.COMPLETED,
    )
    task_store.create(task)

    # Delete should succeed
    success = task_store.delete(task.id)
    assert success is True
    assert task_store.get(task.id) is None


def test_delete_task_tool_terminal_status_check(task_store: TaskStore):
    """Test that delete_task validates terminal status requirement."""
    from openpaw.builtins.tools.task import TaskToolBuiltin

    # Create builtin with task store
    builtin = TaskToolBuiltin(
        {"task_store": task_store, "workspace_path": task_store.workspace_path}
    )

    # Create active task
    task = Task(
        id=str(uuid.uuid4()),
        type="test",
        description="Active task",
        status=TaskStatus.IN_PROGRESS,
    )
    task_store.create(task)

    # Get the delete tool
    tools = builtin.get_langchain_tool()
    delete_tool = next(t for t in tools if t.name == "delete_task")

    # Try to delete active task (should fail)
    result = delete_tool.invoke({"task_id": task.id})
    assert "Cannot delete active task" in result
    assert "in_progress" in result

    # Task should still exist
    assert task_store.get(task.id) is not None


def test_delete_task_tool_not_found(task_store: TaskStore):
    """Test delete_task with non-existent task."""
    from openpaw.builtins.tools.task import TaskToolBuiltin

    builtin = TaskToolBuiltin(
        {"task_store": task_store, "workspace_path": task_store.workspace_path}
    )

    # Get the delete tool
    tools = builtin.get_langchain_tool()
    delete_tool = next(t for t in tools if t.name == "delete_task")

    # Try to delete non-existent task
    result = delete_tool.invoke({"task_id": "nonexistent-id"})
    assert "Task not found" in result


def test_delete_task_all_terminal_statuses(task_store: TaskStore):
    """Test that all terminal statuses (completed/failed/cancelled) can be deleted."""
    from openpaw.builtins.tools.task import TaskToolBuiltin

    builtin = TaskToolBuiltin(
        {"task_store": task_store, "workspace_path": task_store.workspace_path}
    )
    tools = builtin.get_langchain_tool()
    delete_tool = next(t for t in tools if t.name == "delete_task")

    terminal_statuses = [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED]

    for status in terminal_statuses:
        task = Task(
            id=str(uuid.uuid4()),
            type="test",
            description=f"Task with {status.value} status",
            status=status,
        )
        task_store.create(task)

        # Should be deletable
        result = delete_tool.invoke({"task_id": task.id})
        assert "Task deleted" in result
        assert task_store.get(task.id) is None
