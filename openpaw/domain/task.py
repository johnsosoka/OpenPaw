"""Domain models for task management."""

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class TaskStatus(StrEnum):
    """Status values for task lifecycle.

    Lifecycle flow:
        pending -> in_progress -> completed
        pending -> in_progress -> failed
        any -> cancelled
    """

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    AWAITING_CHECK = "awaiting_check"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskPriority(StrEnum):
    """Priority levels for task execution."""

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class TaskType(StrEnum):
    """Common task type categories.

    Agents can use these standard types or define custom types as strings.
    """

    RESEARCH = "research"
    DEPLOYMENT = "deployment"
    BATCH = "batch"
    MONITORING = "monitoring"
    CUSTOM = "custom"


@dataclass
class Task:
    """Represents a long-running task tracked by an agent.

    Tasks are persisted to TASKS.yaml and survive restarts. Agents use
    this to monitor asynchronous operations during heartbeat checks.

    Attributes:
        id: Unique identifier (UUID or tool-generated).
        type: Task category (research, deployment, batch, etc.).
        status: Current task status (pending, in_progress, etc.).
        priority: Task priority level.
        created_at: When the task was created.
        started_at: When the task began execution.
        completed_at: When the task finished (success or failure).
        expected_duration_minutes: Estimated runtime for user transparency.
        deadline: Optional deadline for task completion.
        last_checked_at: Last heartbeat check timestamp.
        check_count: Number of times agent has checked this task.
        check_interval_minutes: Override heartbeat interval for this task.
        description: Human-readable task description.
        notes: Multi-line notes tracking task progress.
        metadata: Tool-specific data (arbitrary key-value pairs).
        result_summary: Brief outcome description when complete.
        result_path: Path to output file (relative to workspace).
        error_message: Error details if task failed.
    """

    id: str
    type: str
    status: TaskStatus
    description: str

    # Priority and timing
    priority: TaskPriority = TaskPriority.NORMAL
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    completed_at: datetime | None = None
    expected_duration_minutes: int | None = None
    deadline: datetime | None = None

    # Monitoring
    last_checked_at: datetime | None = None
    check_count: int = 0
    check_interval_minutes: int | None = None

    # Content
    notes: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    # Results
    result_summary: str | None = None
    result_path: str | None = None
    error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary with ISO 8601 datetime strings.

        Returns:
            Dictionary representation suitable for YAML serialization.
        """
        data = asdict(self)

        # Convert enums to strings
        data["status"] = self.status.value
        data["priority"] = self.priority.value

        # Convert datetimes to ISO 8601 strings
        data["created_at"] = self.created_at.isoformat()
        if self.started_at:
            data["started_at"] = self.started_at.isoformat()
        if self.completed_at:
            data["completed_at"] = self.completed_at.isoformat()
        if self.deadline:
            data["deadline"] = self.deadline.isoformat()
        if self.last_checked_at:
            data["last_checked_at"] = self.last_checked_at.isoformat()

        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Task":
        """Create instance from dictionary with ISO 8601 datetime strings.

        Args:
            data: Dictionary from YAML file.

        Returns:
            Task instance with parsed enums and datetimes.
        """
        # Parse enums
        status = TaskStatus(data["status"])
        priority = TaskPriority(data.get("priority", "normal"))

        # Parse datetimes
        created_at = datetime.fromisoformat(data["created_at"])
        started_at = datetime.fromisoformat(data["started_at"]) if data.get("started_at") else None
        completed_at = datetime.fromisoformat(data["completed_at"]) if data.get("completed_at") else None
        deadline = datetime.fromisoformat(data["deadline"]) if data.get("deadline") else None
        last_checked_at = datetime.fromisoformat(data["last_checked_at"]) if data.get("last_checked_at") else None

        return cls(
            id=data["id"],
            type=data["type"],
            status=status,
            description=data["description"],
            priority=priority,
            created_at=created_at,
            started_at=started_at,
            completed_at=completed_at,
            expected_duration_minutes=data.get("expected_duration_minutes"),
            deadline=deadline,
            last_checked_at=last_checked_at,
            check_count=data.get("check_count", 0),
            check_interval_minutes=data.get("check_interval_minutes"),
            notes=data.get("notes"),
            metadata=data.get("metadata", {}),
            result_summary=data.get("result_summary"),
            result_path=data.get("result_path"),
            error_message=data.get("error_message"),
        )
