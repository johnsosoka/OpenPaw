"""Shared channel context for builtin tools that need to send messages/files."""

import contextvars
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from openpaw.channels.base import ChannelAdapter

logger = logging.getLogger(__name__)

# Context variables for the current channel session
_channel_var: contextvars.ContextVar[Any] = contextvars.ContextVar("_channel", default=None)
_session_key_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("_session_key", default=None)


def set_channel_context(channel: "ChannelAdapter", session_key: str) -> None:
    """Set the channel context for the current async task.

    Args:
        channel: The channel instance to send messages through.
        session_key: The session key for routing (e.g., 'telegram:123456').
    """
    _channel_var.set(channel)
    _session_key_var.set(session_key)
    logger.debug(f"Channel context set: session_key={session_key}")


def clear_channel_context() -> None:
    """Clear the channel context."""
    _channel_var.set(None)
    _session_key_var.set(None)
    logger.debug("Channel context cleared")


def get_channel_context() -> tuple[Any, str | None]:
    """Get the current channel and session key.

    Returns:
        Tuple of (channel, session_key). Both may be None if context not set.
    """
    return _channel_var.get(), _session_key_var.get()
