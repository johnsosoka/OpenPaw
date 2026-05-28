"""Lifecycle notifier for OpenPaw."""

import logging

from openpaw.channels.base import ChannelAdapter


async def _notify_lifecycle_impl(
    channels: dict[str, ChannelAdapter],
    workspace_name: str,
    logger: logging.Logger,
    event: str,
    detail: str | None = None,
) -> None:
    """Send a lifecycle notification to all channels.

    Args:
        channels: Dictionary of channel adapters.
        workspace_name: Name of the workspace.
        logger: Logger instance.
        event: Event name (startup, shutdown, auto_compact).
        detail: Optional detail message.
    """
    message = f"[{workspace_name}] {event}"
    if detail:
        message += f": {detail}"

    for channel in channels.values():
        try:
            # Send to first allowed user in each channel
            allowed_users = getattr(channel, "_allowed_users", [])
            if allowed_users:
                session_key = f"{channel.name}:{allowed_users[0]}"
                await channel.send_message(session_key, message)
        except Exception as e:
            logger.debug(f"Failed to send lifecycle notification via {channel}: {e}")


class LifecycleNotifier:
    """Sends lifecycle notifications to all channels."""

    def __init__(
        self,
        workspace_name: str,
        channels: dict[str, ChannelAdapter],
        logger: logging.Logger,
    ):
        self._workspace_name = workspace_name
        self._channels = channels
        self._logger = logger

    async def notify(self, event: str, detail: str | None = None) -> None:
        """Send a lifecycle notification to all channels.

        Args:
            event: Event name (startup, shutdown, auto_compact).
            detail: Optional detail message.
        """
        await _notify_lifecycle_impl(
            self._channels,
            self._workspace_name,
            self._logger,
            event,
            detail,
        )
