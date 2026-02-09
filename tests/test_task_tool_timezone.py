"""Tests for task tool timezone display."""

from datetime import UTC

import pytest

from openpaw.builtins.tools.task import TaskToolBuiltin
from openpaw.stores.task import Task, TaskStatus, TaskStore


@pytest.fixture
def task_store(tmp_path):
    """Create a temporary task store."""
    return TaskStore(tmp_path)


@pytest.fixture
def task_tool_utc(task_store):
    """Create task tool with UTC timezone (default)."""
    config = {
        "task_store": task_store,
        "timezone": "UTC",
    }
    return TaskToolBuiltin(config)


@pytest.fixture
def task_tool_denver(task_store):
    """Create task tool with America/Denver timezone."""
    config = {
        "task_store": task_store,
        "timezone": "America/Denver",
    }
    return TaskToolBuiltin(config)


def test_task_note_timestamp_utc(task_tool_utc, task_store):
    """Test task note timestamps display in UTC."""
    # Create a task
    task = Task(
        id="task1",
        type="test",
        description="Test task",
        status=TaskStatus.PENDING,
    )
    task_store.create(task)

    # Get the update tool
    tools = task_tool_utc.get_langchain_tool()
    update_tool = next(t for t in tools if t.name == "update_task")

    # Update with notes
    result = update_tool.invoke({
        "task_id": "task1",
        "notes": "Progress update"
    })

    # Verify response
    assert "Updated task task1" in result

    # Read task and verify note timestamp format
    updated_task = task_store.get("task1")
    assert updated_task is not None
    assert "Progress update" in updated_task.notes
    # Should have UTC timestamp
    assert "UTC]" in updated_task.notes


def test_task_note_timestamp_denver(task_tool_denver, task_store):
    """Test task note timestamps display in America/Denver timezone."""
    # Create a task
    task = Task(
        id="task1",
        type="test",
        description="Test task",
        status=TaskStatus.PENDING,
    )
    task_store.create(task)

    # Get the update tool
    tools = task_tool_denver.get_langchain_tool()
    update_tool = next(t for t in tools if t.name == "update_task")

    # Update with notes
    result = update_tool.invoke({
        "task_id": "task1",
        "notes": "Progress update"
    })

    # Verify response
    assert "Updated task task1" in result

    # Read task and verify note timestamp format
    updated_task = task_store.get("task1")
    assert updated_task is not None
    assert "Progress update" in updated_task.notes
    # Should have MST/MDT timestamp (not UTC)
    assert ("MST]" in updated_task.notes or "MDT]" in updated_task.notes)
    assert "UTC]" not in updated_task.notes


def test_task_internal_timestamps_remain_utc(task_tool_denver, task_store):
    """Test task internal timestamps (created_at, started_at, completed_at) remain UTC."""
    # Create a task
    task = Task(
        id="task1",
        type="test",
        description="Test task",
        status=TaskStatus.PENDING,
    )
    task_store.create(task)

    # Get the update tool
    tools = task_tool_denver.get_langchain_tool()
    update_tool = next(t for t in tools if t.name == "update_task")

    # Update to in_progress
    update_tool.invoke({
        "task_id": "task1",
        "status": "in_progress",
    })

    # Update to completed
    update_tool.invoke({
        "task_id": "task1",
        "status": "completed",
        "result_summary": "Done",
    })

    # Read task
    updated_task = task_store.get("task1")
    assert updated_task is not None

    # Verify internal timestamps are UTC
    assert updated_task.created_at.tzinfo is not None
    assert updated_task.started_at is not None
    assert updated_task.started_at.tzinfo is not None
    assert updated_task.completed_at is not None
    assert updated_task.completed_at.tzinfo is not None

    # All should be in UTC (datetime.timezone.utc or equivalent)
    assert updated_task.created_at.tzinfo == UTC
    assert updated_task.started_at.tzinfo == UTC
    assert updated_task.completed_at.tzinfo == UTC


def test_multiple_notes_preserve_timezone(task_tool_denver, task_store):
    """Test multiple note updates preserve timezone format."""
    # Create a task
    task = Task(
        id="task1",
        type="test",
        description="Test task",
        status=TaskStatus.PENDING,
    )
    task_store.create(task)

    # Get the update tool
    tools = task_tool_denver.get_langchain_tool()
    update_tool = next(t for t in tools if t.name == "update_task")

    # Add first note
    update_tool.invoke({
        "task_id": "task1",
        "notes": "First update"
    })

    # Add second note
    update_tool.invoke({
        "task_id": "task1",
        "notes": "Second update"
    })

    # Read task
    updated_task = task_store.get("task1")
    assert updated_task is not None

    # Verify both notes have timezone timestamps
    notes_lines = updated_task.notes.split("\n")
    assert len(notes_lines) == 2
    assert "First update" in notes_lines[0]
    assert "Second update" in notes_lines[1]
    # Both should have MST/MDT timestamps
    for line in notes_lines:
        assert ("MST]" in line or "MDT]" in line)
        assert "UTC]" not in line


def test_default_timezone_is_utc(task_store):
    """Test that default timezone is UTC when not specified."""
    config = {
        "task_store": task_store,
        # No timezone specified
    }
    task_tool = TaskToolBuiltin(config)

    # Should default to UTC
    assert task_tool._timezone == "UTC"
