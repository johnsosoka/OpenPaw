"""Domain models for session management."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass
class SessionState:
    """Represents a session's current conversation state.

    Attributes:
        conversation_id: Unique conversation identifier (e.g., "conv_2026-02-07T14-30-00").
        started_at: When this conversation began.
        message_count: Number of messages in this conversation.
        last_active_at: Last time a message was sent in this conversation.
    """

    conversation_id: str
    started_at: datetime
    message_count: int = 0
    last_active_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary with ISO 8601 datetime strings.

        Returns:
            Dictionary representation suitable for JSON serialization.
        """
        return {
            "conversation_id": self.conversation_id,
            "started_at": self.started_at.isoformat(),
            "message_count": self.message_count,
            "last_active_at": self.last_active_at.isoformat() if self.last_active_at else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SessionState":
        """Create instance from dictionary with ISO 8601 datetime strings.

        Args:
            data: Dictionary from JSON file.

        Returns:
            SessionState instance with parsed datetimes.
        """
        return cls(
            conversation_id=data["conversation_id"],
            started_at=datetime.fromisoformat(data["started_at"]),
            message_count=data.get("message_count", 0),
            last_active_at=datetime.fromisoformat(data["last_active_at"]) if data.get("last_active_at") else None,
        )
