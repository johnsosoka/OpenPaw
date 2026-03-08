"""Domain models for channel history and events."""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class ChannelHistoryEntry:
    """A single message from channel history (for on-demand context injection).

    Returned by channel adapters that implement fetch_channel_history().
    Used to build the XML context block prepended to triggered messages.

    Attributes:
        timestamp: When the message was sent (UTC).
        user_id: Platform-specific user identifier.
        display_name: Human-readable name for the message author.
        content: Text content of the message.
        is_bot: True if the message was sent by a bot.
        attachments_summary: Short description of attachments, if any
            (e.g., "[image]", "[file: report.pdf]"). None when no attachments.
    """

    timestamp: datetime
    user_id: str
    display_name: str
    content: str
    is_bot: bool = False
    attachments_summary: str | None = None


@dataclass
class ChannelEvent:
    """Raw channel event for persistent logging (pre-filter, pre-conversion).

    Emitted by channel adapters for every visible message, regardless of
    allowlist or activation filters. Only the bot's own messages are excluded.
    Used by ChannelLogger to write persistent JSONL logs.

    Attributes:
        timestamp: When the message was sent (UTC).
        channel_name: Adapter channel name (e.g., "discord", "discord-work").
        channel_id: Platform-specific channel identifier.
        channel_label: Human-readable channel name (e.g., "general").
        server_name: Guild or server name. None for DMs.
        server_id: Guild or server platform identifier. None for DMs.
        user_id: Platform-specific user identifier.
        display_name: Human-readable name for the message author.
        content: Text content of the message.
        attachment_names: Filenames of any attachments (no binary data).
        message_id: Platform-specific message identifier.
    """

    timestamp: datetime
    channel_name: str
    channel_id: str
    channel_label: str
    server_name: str | None
    server_id: str | None
    user_id: str
    display_name: str
    content: str
    attachment_names: list[str] = field(default_factory=list)
    message_id: str = ""
