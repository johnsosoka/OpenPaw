"""Content combining logic for message batches."""

from typing import Any

from openpaw.core.utils import resolve_user_name
from openpaw.model.message import Message


class ContentCombiner:
    """Combines message batches into single strings with optional user name prefixes.

    Pure logic — no I/O, no side effects, no framework dependencies beyond
    Message and resolve_user_name.
    """

    def __init__(self, user_aliases: dict[int, str] | None = None) -> None:
        """Initialize with optional user aliases.

        Args:
            user_aliases: Mapping of user IDs to display names.
        """
        self._user_aliases = user_aliases or {}

    def resolve_user_name(
        self, user_id: str, metadata: dict[str, Any] | None = None
    ) -> str | None:
        """Resolve display name for a user ID.

        Args:
            user_id: The user identifier.
            metadata: Optional metadata dict with ``first_name`` or ``username``.

        Returns:
            Display name if available, otherwise None.
        """
        return resolve_user_name(user_id, metadata or {}, self._user_aliases)

    def build_combined_content(self, messages: list[Message]) -> str:
        """Build combined content from messages with optional user name prefixes.

        Args:
            messages: List of messages to combine.

        Returns:
            Combined message content with optional [Name] prefixes.
        """
        lines: list[str] = []
        for msg in messages:
            name = self.resolve_user_name(msg.user_id, msg.metadata)
            if name:
                lines.append(f"[{name}]: {msg.content}")
            else:
                lines.append(msg.content)
        return "\n".join(lines)

    def build_combined_content_from_tuples(
        self, tuples: list[tuple[str, Message | str]]
    ) -> str:
        """Build combined content from (channel_name, msg) tuples.

        Args:
            tuples: List of (channel_name, msg) tuples where msg is Message or str.

        Returns:
            Combined message content with optional [Name] prefixes.
        """
        lines: list[str] = []
        for _channel_name, msg in tuples:
            if isinstance(msg, Message):
                name = self.resolve_user_name(msg.user_id, msg.metadata)
                if name:
                    lines.append(f"[{name}]: {msg.content}")
                else:
                    lines.append(msg.content)
            else:
                # Raw string
                lines.append(str(msg))
        return "\n".join(lines)
