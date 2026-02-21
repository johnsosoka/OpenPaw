"""Domain models for sub-agent management."""

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class SubAgentStatus(StrEnum):
    """Status values for sub-agent lifecycle.

    Lifecycle flow:
        pending -> running -> completed
        pending -> running -> failed
        any -> cancelled
        running (stale) -> timed_out
    """

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


@dataclass
class SubAgentRequest:
    """Represents a sub-agent spawn request.

    Attributes:
        id: Unique identifier (UUID or tool-generated).
        task: The prompt/instruction for the sub-agent.
        label: Human-readable label for the request.
        status: Current request status (pending, running, etc.).
        session_key: Session for result delivery routing (channel:id).
        created_at: When the request was created.
        started_at: When the sub-agent began execution.
        completed_at: When the sub-agent finished.
        timeout_minutes: Maximum runtime before timeout.
        notify: Whether to notify session on completion.
    """

    id: str
    task: str
    label: str
    status: SubAgentStatus
    session_key: str
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    completed_at: datetime | None = None
    timeout_minutes: int = 30
    notify: bool = True
    allowed_tools: list[str] | None = None
    denied_tools: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary with ISO 8601 datetime strings.

        Returns:
            Dictionary representation suitable for YAML serialization.
        """
        data = asdict(self)

        # Convert enum to string
        data["status"] = self.status.value

        # Convert datetimes to ISO 8601 strings
        data["created_at"] = self.created_at.isoformat()
        if self.started_at:
            data["started_at"] = self.started_at.isoformat()
        if self.completed_at:
            data["completed_at"] = self.completed_at.isoformat()

        # Omit allowed_tools and denied_tools if None
        if self.allowed_tools is None:
            data.pop("allowed_tools", None)
        if self.denied_tools is None:
            data.pop("denied_tools", None)

        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SubAgentRequest":
        """Create instance from dictionary with ISO 8601 datetime strings.

        Args:
            data: Dictionary from YAML file.

        Returns:
            SubAgentRequest instance with parsed enums and datetimes.
        """
        # Parse enum
        status = SubAgentStatus(data["status"])

        # Parse datetimes
        created_at = datetime.fromisoformat(data["created_at"])
        started_at = datetime.fromisoformat(data["started_at"]) if data.get("started_at") else None
        completed_at = datetime.fromisoformat(data["completed_at"]) if data.get("completed_at") else None

        return cls(
            id=data["id"],
            task=data["task"],
            label=data["label"],
            status=status,
            session_key=data["session_key"],
            created_at=created_at,
            started_at=started_at,
            completed_at=completed_at,
            timeout_minutes=data.get("timeout_minutes", 30),
            notify=data.get("notify", True),
            allowed_tools=data.get("allowed_tools"),
            denied_tools=data.get("denied_tools"),
        )


@dataclass
class SubAgentResult:
    """Represents the result of a sub-agent execution.

    Attributes:
        request_id: ID of the corresponding SubAgentRequest.
        output: The sub-agent's response text.
        token_count: Total tokens used during execution.
        duration_ms: Execution time in milliseconds.
        error: Error message if execution failed.
    """

    request_id: str
    output: str
    token_count: int = 0
    duration_ms: float = 0.0
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary.

        Returns:
            Dictionary representation suitable for YAML serialization.
        """
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SubAgentResult":
        """Create instance from dictionary.

        Args:
            data: Dictionary from YAML file.

        Returns:
            SubAgentResult instance.
        """
        return cls(
            request_id=data["request_id"],
            output=data["output"],
            token_count=data.get("token_count", 0),
            duration_ms=data.get("duration_ms", 0.0),
            error=data.get("error"),
        )
