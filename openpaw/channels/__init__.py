"""Channel adapters for different messaging platforms."""

from openpaw.channels.base import ChannelAdapter
from openpaw.channels.telegram import TelegramChannel
from openpaw.model.message import Message, MessageDirection

__all__ = [
    "ChannelAdapter",
    "Message",
    "MessageDirection",
    "TelegramChannel",
    # commands subpackage is available at openpaw.channels.commands
]
