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
    elif channel_type == "slack":
        from openpaw.channels.slack import SlackChannel

        # Validate required tokens
        bot_token = config.get("token")
        app_token = config.get("app_token")
        if not bot_token:
            raise ValueError(f"Workspace '{workspace_name}' missing required channel.token for Slack")
        if not app_token:
            raise ValueError(f"Workspace '{workspace_name}' missing required channel.app_token for Slack")

        return SlackChannel(
            bot_token=bot_token,
            app_token=app_token,
            signing_secret=config.get("signing_secret"),
            allowed_users=config.get("allowed_users", []),
            allowed_channels=config.get("allowed_channels", []),
            allow_all=config.get("allow_all", False),
            workspace_name=workspace_name,
        )
    raise ValueError(f"Unsupported channel type: {channel_type}")
