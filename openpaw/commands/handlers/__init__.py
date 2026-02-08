"""Command handlers for OpenPaw framework."""

from openpaw.commands.base import CommandHandler
from openpaw.commands.handlers.compact import CompactCommand
from openpaw.commands.handlers.help import HelpCommand
from openpaw.commands.handlers.new import NewCommand
from openpaw.commands.handlers.queue_mode import QueueModeCommand
from openpaw.commands.handlers.start import StartCommand
from openpaw.commands.handlers.status import StatusCommand


def get_framework_commands() -> list[CommandHandler]:
    """Return all framework command handlers for registration.

    Returns:
        List of command handler instances.
    """
    return [
        StartCommand(),
        NewCommand(),
        CompactCommand(),
        HelpCommand(),
        QueueModeCommand(),
        StatusCommand(),
    ]


__all__ = [
    "CompactCommand",
    "get_framework_commands",
    "HelpCommand",
    "NewCommand",
    "QueueModeCommand",
    "StartCommand",
    "StatusCommand",
]
