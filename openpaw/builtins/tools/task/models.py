"""Task tool input schemas."""
from typing import Any

from pydantic import BaseModel, Field


class CreateTaskInput(BaseModel):
    """Input schema for creating a task."""

    description: str = Field(description="Human-readable task description")
    type: str = Field(
        description=(
            "Task category. Common types: 'research', 'deployment', 'batch', "
            "'monitoring', 'custom'. Use standard types when applicable."
        )
    )
    priority: str = Field(
        default="normal",
        description="Priority level: 'low', 'normal', 'high', 'urgent'. Default: 'normal'",
    )
    expected_duration_minutes: int | None = Field(
        default=None,
        description="Estimated runtime in minutes (optional but recommended for transparency)",
    )
    metadata: dict[str, Any] | None = Field(
        default=None,
        description="Tool-specific data as key-value pairs (optional)",
    )


class UpdateTaskInput(BaseModel):
    """Input schema for updating a task."""

    task_id: str = Field(description="Unique task identifier (from list_tasks or create_task)")
    status: str | None = Field(
        default=None,
        description=(
            "New status: 'pending', 'in_progress', 'awaiting_check', 'completed', "
            "'failed', 'cancelled'. Only update when status changes."
        ),
    )
    notes: str | None = Field(
        default=None,
        description="Add progress notes or observations (appended to existing notes)",
    )
    result_summary: str | None = Field(
        default=None,
        description="Brief outcome description (set when completing task)",
    )
    result_path: str | None = Field(
        default=None,
        description="Path to output file relative to workspace (set when completing task)",
    )
    error_message: str | None = Field(
        default=None,
        description="Error details (set when marking task as failed)",
    )


class ListTasksInput(BaseModel):
    """Input schema for listing tasks."""

    status: str | None = Field(
        default=None,
        description=(
            "Filter by status: 'pending', 'in_progress', 'awaiting_check', "
            "'completed', 'failed', 'cancelled'. Omit to list all tasks."
        ),
    )
    type: str | None = Field(
        default=None,
        description="Filter by task type (e.g., 'research', 'deployment'). Omit to list all types.",
    )


class GetTaskInput(BaseModel):
    """Input schema for getting task details."""

    task_id: str = Field(description="Unique task identifier to retrieve")
