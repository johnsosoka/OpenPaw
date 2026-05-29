"""Channel history browsing builtin tool.

Re-exports public symbols for backward compatibility.
"""

import logging
from typing import Any

from openpaw.builtins.base import (
    BaseBuiltinTool,
    BuiltinMetadata,
    BuiltinPrerequisite,
    BuiltinType,
)
from openpaw.channels.base import ChannelAdapter

from .browser import _create_browse_tool
from .formatter import (
    _MESSAGE_TRUNCATION,
    _build_filter_qualifier,
    _format_history_output,
    _format_timestamp,
)
from .models import BrowseChannelHistoryInput
from .resolver import _resolve_adapter, _resolve_channel_id

logger = logging.getLogger(__name__)

__all__ = [
    "ChannelHistoryToolBuiltin",
    "BrowseChannelHistoryInput",
    "_resolve_adapter",
    "_resolve_channel_id",
    "_format_history_output",
    "_format_timestamp",
    "_build_filter_qualifier",
    "_create_browse_tool",
    "_MESSAGE_TRUNCATION",
]


class ChannelHistoryToolBuiltin(BaseBuiltinTool):
    """On-demand channel history browser for history-capable adapters.

    Enables agents to browse message history beyond the initial context
    window, paginate through older messages, and filter by keyword or user.

    Capabilities:
    - Paginate through channel history (newest to oldest)
    - Filter by keyword (case-insensitive substring)
    - Filter by user (case-insensitive display name substring)
    - Exclude bot messages (default on)
    - Auto-select the channel when only one supports history

    Config options:
        max_messages_per_request: Hard cap on messages returned (default: 100)
        content_truncation: Per-message content char limit (default: 500)

    Wired at startup via set_channels(). If no channel supports history
    browsing, the tool is removed from the agent by WorkspaceRunner.
    """

    metadata = BuiltinMetadata(
        name="channel_history",
        display_name="Channel History Browser",
        description="Browse and search message history from history-capable channel adapters",
        builtin_type=BuiltinType.TOOL,
        group="communication",
        prerequisites=BuiltinPrerequisite(),  # Runtime gating, not API-key gating
    )

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        """Initialize the channel history tool.

        Args:
            config: Optional configuration dict containing:
                - max_messages_per_request: Hard cap on messages (default: 100)
                - content_truncation: Per-message char limit (default: 500)
        """
        super().__init__(config)

        self.max_messages_per_request: int = self.config.get(
            "max_messages_per_request", 100
        )
        self.content_truncation: int = self.config.get(
            "content_truncation", _MESSAGE_TRUNCATION
        )

        # Channel adapters — set via set_channels() at workspace startup
        self._channels: dict[str, ChannelAdapter] | None = None

        logger.debug("ChannelHistoryToolBuiltin initialized")

    def set_channels(self, channels: dict[str, "ChannelAdapter"]) -> None:
        """Set the history-capable channel adapter references.

        Called by WorkspaceRunner after channels are set up. Only channels
        with supports_history_browsing == True should be passed.

        Args:
            channels: Dict mapping channel name -> ChannelAdapter for
                history-capable channels only.
        """
        self._channels = channels
        logger.info(
            "ChannelHistoryTool connected to %d channel(s): %s",
            len(channels),
            list(channels.keys()),
        )

    def get_langchain_tool(self) -> Any:
        """Return the browse_channel_history tool as a list."""
        return [_create_browse_tool(self)]
