"""Base channel adapter interface."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class MessageDirection(Enum):
    """Direction of a message."""

    INBOUND = "inbound"
    OUTBOUND = "outbound"


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
    timestamp: datetime = field(default_factory=datetime.now)
    reply_to_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

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


class ChannelAdapter(ABC):
    """Abstract base class for channel adapters.

    Channel adapters handle:
    - Protocol adaptation (platform-specific API to common Message format)
    - Access control (allowlists, pairing flows)
    - Message sending/receiving
    """

    name: str = "base"

    @abstractmethod
    async def start(self) -> None:
        """Start the channel adapter (connect, authenticate, etc.)."""
        ...

    @abstractmethod
    async def stop(self) -> None:
        """Stop the channel adapter gracefully."""
        ...

    @abstractmethod
    async def send_message(self, session_key: str, content: str, **kwargs: Any) -> Message:
        """Send a message to a session.

        Args:
            session_key: The session to send to.
            content: Message content.
            **kwargs: Channel-specific options.

        Returns:
            The sent Message object.
        """
        ...

    @abstractmethod
    def on_message(self, callback: Any) -> None:
        """Register a callback for incoming messages.

        Args:
            callback: Async function taking a Message and returning None.
        """
        ...

    def build_session_key(self, *parts: str | int) -> str:
        """Build a session key from parts.

        Args:
            *parts: Components to join into a session key.

        Returns:
            Session key string like 'channel:part1:part2'.
        """
        return f"{self.name}:" + ":".join(str(p) for p in parts)
