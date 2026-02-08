"""Channel factory for creating channel adapters from configuration."""

import logging
from typing import Any

from openpaw.channels.base import ChannelAdapter

logger = logging.getLogger(__name__)


def create_channel(
    channel_type: str,
    config: dict[str, Any],
    workspace_name: str,
) -> ChannelAdapter:
    """Create a channel adapter from type string and config.

    Args:
        channel_type: Channel type identifier (e.g., "telegram").
        config: Channel configuration dict (token, allowed_users, etc.).
        workspace_name: Workspace name for error messages.

    Returns:
        Configured ChannelAdapter instance.

    Raises:
        ValueError: If channel_type is unsupported.
    """
    if channel_type == "telegram":
        from openpaw.channels.telegram import TelegramChannel

        return TelegramChannel(
            token=config.get("token"),
            allowed_users=config.get("allowed_users", []),
            allowed_groups=config.get("allowed_groups", []),
            allow_all=config.get("allow_all", False),
            workspace_name=workspace_name,
        )
    raise ValueError(f"Unsupported channel type: {channel_type}")
