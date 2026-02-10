"""Channel adapters for different messaging platforms."""

from openpaw.channels.base import ChannelAdapter, Message, MessageDirection
from openpaw.channels.telegram import TelegramChannel

# Gracefully handle slack-bolt not being installed
try:
    from openpaw.channels.slack import SlackChannel

    __all__ = [
        "ChannelAdapter",
        "Message",
        "MessageDirection",
        "TelegramChannel",
        "SlackChannel",
        # commands subpackage is available at openpaw.channels.commands
    ]
except ImportError:
    __all__ = [
        "ChannelAdapter",
        "Message",
        "MessageDirection",
        "TelegramChannel",
        # commands subpackage is available at openpaw.channels.commands
    ]
