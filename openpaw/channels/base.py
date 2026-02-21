"""Base channel adapter interface."""

from abc import ABC, abstractmethod
from typing import Any

from openpaw.model.message import Message


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

    async def register_commands(self, commands: list[Any]) -> None:
        """Register available commands with the channel platform.

        Override in implementations that support native command registration
        (e.g., Telegram BotFather hints, Discord slash commands).

        Default implementation is a no-op.
        """
        pass

    def build_session_key(self, *parts: str | int) -> str:
        """Build a session key from parts.

        Args:
            *parts: Components to join into a session key.

        Returns:
            Session key string like 'channel:part1:part2'.
        """
        return f"{self.name}:" + ":".join(str(p) for p in parts)

    async def send_file(
        self,
        session_key: str,
        file_data: bytes,
        filename: str,
        mime_type: str | None = None,
        caption: str | None = None,
    ) -> None:
        """Send a file to a channel session.

        Args:
            session_key: Target session (e.g., "telegram:123456").
            file_data: Raw file bytes.
            filename: Display filename for the file.
            mime_type: Optional MIME type hint.
            caption: Optional caption/message to accompany the file.

        Raises:
            NotImplementedError: If the channel doesn't support file sending.
        """
        raise NotImplementedError(
            f"Channel '{type(self).__name__}' does not support file sending"
        )

    async def send_approval_request(
        self,
        session_key: str,
        approval_id: str,
        tool_name: str,
        tool_args: dict[str, Any],
        show_args: bool = True,
    ) -> None:
        """Send an approval request to the user with approve/deny options.

        Override in channel implementations that support interactive approval
        (e.g., Telegram inline keyboards).

        Default sends a text message with instructions.

        Args:
            session_key: Target session identifier.
            approval_id: Unique ID for this approval request.
            tool_name: Name of the tool requiring approval.
            tool_args: Arguments passed to the tool.
            show_args: Whether to display tool arguments to user.
        """
        # Format approval message
        message = f"🔒 Approval Required: {tool_name}\n"
        if show_args and tool_args:
            # Truncate long args
            args_str = str(tool_args)
            if len(args_str) > 500:
                args_str = args_str[:500] + "..."
            message += f"Arguments: {args_str}\n"
        message += f"\nApproval ID: {approval_id}\n"
        message += "Reply /approve or /deny to this request."

        await self.send_message(session_key, message)
