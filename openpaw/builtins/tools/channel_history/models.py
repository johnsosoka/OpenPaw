"""Pydantic input model for channel history tool."""

from pydantic import BaseModel, Field


class BrowseChannelHistoryInput(BaseModel):
    """Input schema for browse_channel_history."""

    channel: str | None = Field(
        default=None,
        description=(
            "Channel name to query (e.g., 'discord', 'discord-work'). "
            "Required when multiple history-capable channels exist. "
            "Auto-selected when only one exists."
        ),
    )
    limit: int = Field(
        default=50,
        ge=1,
        le=100,
        description="Maximum number of messages to return (1-100).",
    )
    before: str | None = Field(
        default=None,
        description=(
            "Pagination cursor — message ID. Fetches messages sent before this "
            "message. Use the oldest_message_id from a previous call's footer."
        ),
    )
    keyword: str | None = Field(
        default=None,
        description="Case-insensitive substring filter on message content.",
    )
    user: str | None = Field(
        default=None,
        description="Filter by display name (case-insensitive substring match).",
    )
    include_bots: bool = Field(
        default=False,
        description="Include bot messages in results (default: excluded).",
    )
