"""Channel factory for creating channel adapters from configuration."""

import logging
from typing import Any

from openpaw.channels.base import ChannelAdapter

logger = logging.getLogger(__name__)


def create_channel(
    channel_type: str,
    config: dict[str, Any],
    workspace_name: str,
    channel_name: str | None = None,
) -> ChannelAdapter:
    """Create a channel adapter from type string and config.

    Args:
        channel_type: Channel type identifier (e.g., "telegram").
        config: Channel configuration dict (token, allowed_users, etc.).
        workspace_name: Workspace name for error messages.
        channel_name: Optional unique name for this channel instance.
            When set, overrides the adapter's default name (used in session keys).

    Returns:
        Configured ChannelAdapter instance.

    Raises:
        ValueError: If channel_type is unsupported.
    """
    adapter: ChannelAdapter

    if channel_type == "telegram":
        from openpaw.channels.telegram import TelegramChannel

        adapter = TelegramChannel(
            token=config.get("token"),
            allowed_users=config.get("allowed_users", []),
            allowed_groups=config.get("allowed_groups", []),
            allow_all=config.get("allow_all", False),
            mention_required=config.get("mention_required", False),
            triggers=config.get("triggers", []),
            workspace_name=workspace_name,
        )
    elif channel_type == "discord":
        from openpaw.channels.discord import DiscordChannel

        adapter = DiscordChannel(
            token=config.get("token"),
            allowed_users=config.get("allowed_users", []),
            allowed_groups=config.get("allowed_groups", []),
            allow_all=config.get("allow_all", False),
            mention_required=config.get("mention_required", False),
            triggers=config.get("triggers", []),
            workspace_name=workspace_name,
        )
    else:
        raise ValueError(f"Unsupported channel type: {channel_type}")

    # Override adapter name if a custom channel name is provided
    if channel_name:
        adapter.name = channel_name

    return adapter
