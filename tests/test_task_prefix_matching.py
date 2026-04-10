"""Tests for task ID prefix matching and full-UUID display in list_tasks."""

import uuid
from pathlib import Path

import pytest

from openpaw.builtins.tools.task import TaskToolBuiltin
from openpaw.model.task import Task, TaskStatus
from openpaw.stores.task import TaskStore


@pytest.fixture
def task_store(tmp_path: Path) -> TaskStore:
    """Create a TaskStore instance backed by a temporary directory."""
    return TaskStore(tmp_path)


@pytest.fixture
def builtin(task_store: TaskStore) -> TaskToolBuiltin:
    """Create a TaskToolBuiltin wired to the shared task store."""
    return TaskToolBuiltin(
        {"task_store": task_store, "workspace_path": task_store.workspace_path}
    )


def _make_task(status: TaskStatus = TaskStatus.PENDING) -> Task:
    """Return a minimal Task with a fresh UUID."""
    return Task(
        id=str(uuid.uuid4()),
        type="test",
        description="A test task",
        status=status,
    )


# ---------------------------------------------------------------------------
# TaskStore._resolve_task_id — unit tests
# ---------------------------------------------------------------------------


def test_get_task_exact_match(task_store: TaskStore) -> None:
    """Full UUID lookup returns the correct task."""
    task = _make_task()
    task_store.create(task)

    result = task_store.get(task.id)

    assert result is not None
    assert result.id == task.id


def test_get_task_prefix_match(task_store: TaskStore) -> None:
    """An 8-character prefix uniquely resolves to the correct task."""
    task = _make_task()
    task_store.create(task)

    prefix = task.id[:8]
    result = task_store.get(prefix)

    assert result is not None
    assert result.id == task.id


def test_get_task_ambiguous_prefix(task_store: TaskStore) -> None:
    """A prefix matching multiple tasks returns None (no guessing)."""
    shared_prefix = "aaaaaaaa"

    task_a = Task(
        id=f"{shared_prefix}-0000-0000-0000-000000000001",
        type="test",
        description="Task A",
        status=TaskStatus.PENDING,
    )
    task_b = Task(
        id=f"{shared_prefix}-0000-0000-0000-000000000002",
        type="test",
        description="Task B",
        status=TaskStatus.PENDING,
    )
    task_store.create(task_a)
    task_store.create(task_b)

    result = task_store.get(shared_prefix)

    assert result is None


def test_get_task_no_match(task_store: TaskStore) -> None:
    """A completely unknown ID returns None."""
    result = task_store.get("nonexistent-id-that-does-not-exist")

    assert result is None


# ---------------------------------------------------------------------------
# TaskStore.update() — prefix support
# ---------------------------------------------------------------------------


def test_update_task_prefix_match(task_store: TaskStore) -> None:
    """update() resolves an 8-character prefix and applies the change."""
    task = _make_task(status=TaskStatus.PENDING)
    task_store.create(task)

    prefix = task.id[:8]
    success = task_store.update(prefix, status=TaskStatus.IN_PROGRESS)

    assert success is True

    updated = task_store.get(task.id)
    assert updated is not None
    assert updated.status == TaskStatus.IN_PROGRESS


# ---------------------------------------------------------------------------
# TaskStore.delete() — prefix support
# ---------------------------------------------------------------------------


def test_delete_task_prefix_match(task_store: TaskStore) -> None:
    """delete() resolves an 8-character prefix and removes the task."""
    task = _make_task(status=TaskStatus.COMPLETED)
    task_store.create(task)

    prefix = task.id[:8]
    success = task_store.delete(prefix)

    assert success is True
    assert task_store.get(task.id) is None


# ---------------------------------------------------------------------------
# list_tasks tool output — full UUID display
# ---------------------------------------------------------------------------


def test_list_tasks_shows_full_uuid(builtin: TaskToolBuiltin) -> None:
    """list_tasks output contains the full UUID, not a truncated 8-char prefix."""
    task = _make_task()
    builtin.store.create(task)

    tools = builtin.get_langchain_tool()
    list_tool = next(t for t in tools if t.name == "list_tasks")

    output = list_tool.invoke({})

    assert task.id in output
    # The old truncated form should NOT appear as the only ID token
    truncated = task.id[:8]
    assert f"[{truncated}]" not in output
    assert f"[{task.id}]" in output
