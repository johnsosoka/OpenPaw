"""Channel and session resolution for channel history browsing."""

import logging

from openpaw.builtins.tools._channel_context import get_current_session_key
from openpaw.channels.base import ChannelAdapter

logger = logging.getLogger(__name__)


def _resolve_adapter(
    channels: dict[str, "ChannelAdapter"],
    channel_name: str | None,
) -> tuple["ChannelAdapter | None", str | None]:
    """Resolve which adapter to use.

    Args:
        channels: Available history-capable channels.
        channel_name: Requested channel name, or None for auto-selection.

    Returns:
        Tuple of (adapter, error_string). One of the two will be None.
    """
    if channel_name is not None:
        adapter = channels.get(channel_name)
        if adapter is None:
            available = ", ".join(sorted(channels.keys()))
            return None, (
                f"[Error: Channel '{channel_name}' not found or does not support "
                f"history browsing. Available: {available}]"
            )
        return adapter, None

    # Auto-selection: only works when exactly one history-capable channel exists
    if len(channels) == 1:
        return next(iter(channels.values())), None

    available = ", ".join(sorted(channels.keys()))
    return None, (
        f"[Error: Multiple history-capable channels available. "
        f"Specify channel= with one of: {available}]"
    )


def _resolve_channel_id(adapter: "ChannelAdapter") -> tuple[str, str | None]:
    """Resolve the platform channel ID from context or return an error.

    Uses the current session key from _channel_context contextvars to extract
    the channel ID. Fails gracefully when running outside a user session (e.g.,
    from a cron job without a channel context).

    Args:
        adapter: The selected channel adapter.

    Returns:
        Tuple of (channel_id, error_string). One will be None.
    """
    session_key = get_current_session_key()
    if not session_key:
        return "", (
            "[Error: No active session context. "
            "Cannot determine which channel to browse. "
            "This tool must be called from within a channel session.]"
        )

    # Session key format: "{channel_name}:{channel_id}"
    # channel_name can contain colons (e.g., "discord-work"), but channel_id
    # is always the last segment.
    parts = session_key.rsplit(":", 1)
    if len(parts) != 2 or not parts[1]:
        return "", (
            f"[Error: Unable to extract channel ID from session key '{session_key}'. "
            f"Provide the channel_id explicitly or ensure you are in a guild channel.]"
        )

    channel_id = parts[1]

    # Detect DMs: Discord DM session keys use the user ID as channel_id,
    # but we can't tell without platform context. We surface an informative
    # message if the fetch returns empty (handled in the caller).
    return channel_id, None
