"""Channel adapters for different messaging platforms."""

from openpaw.channels.base import ChannelAdapter
from openpaw.channels.stdio import StdioChannel
from openpaw.channels.telegram import TelegramChannel
from openpaw.model.message import Message, MessageDirection

__all__ = [
    "ChannelAdapter",
    "Message",
    "MessageDirection",
    "StdioChannel",
    "TelegramChannel",
    # commands subpackage is available at openpaw.channels.commands
]
