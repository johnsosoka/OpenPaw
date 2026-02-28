"""Domain models for messaging."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any


class MessageDirection(Enum):
    """Direction of a message."""

    INBOUND = "inbound"
    OUTBOUND = "outbound"


@dataclass
class Attachment:
    """Represents a message attachment (audio, image, document, etc.).

    Attributes:
        type: Attachment type (audio, image, document, video).
        data: Raw binary data (if downloaded).
        url: Remote URL (if not downloaded).
        filename: Original filename if available.
        mime_type: MIME type of the attachment.
        metadata: Additional type-specific metadata.
        saved_path: Relative path within workspace where file was persisted (set by FilePersistenceProcessor).
    """

    type: str
    data: bytes | None = None
    url: str | None = None
    filename: str | None = None
    mime_type: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    saved_path: str | None = None


@dataclass
class Message:
    """Unified message format across all channels.

    Adapts platform-specific messages to a common structure.
    """

    id: str
    channel: str
    session_key: str
    user_id: str
    content: str
    direction: MessageDirection = MessageDirection.INBOUND
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    reply_to_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    attachments: list[Attachment] = field(default_factory=list)

    @property
    def is_command(self) -> bool:
        """Check if message is a command (starts with /)."""
        return self.content.strip().startswith("/")

    def parse_command(self) -> tuple[str, str]:
        """Parse command and arguments from message.

        Returns:
            Tuple of (command_name, arguments_string).
        """
        if not self.is_command:
            return ("", self.content)

        parts = self.content.strip().split(maxsplit=1)
        command = parts[0][1:]
        args = parts[1] if len(parts) > 1 else ""
        return (command, args)
