"""Harness introspection command handler (/harness, CONCERNS C9).

Prints the harness type and the resolved node→model table so a run's
reasoning configuration is reproducible from the channel.
"""

from typing import TYPE_CHECKING

from openpaw.channels.commands.base import CommandDefinition, CommandHandler, CommandResult

if TYPE_CHECKING:
    from openpaw.channels.base import Message
    from openpaw.channels.commands.base import CommandContext


class HarnessCommand(CommandHandler):
    """Show harness type and per-node model resolution."""

    @property
    def definition(self) -> CommandDefinition:
        return CommandDefinition(
            name="harness",
            description="Show harness type and node models",
        )

    async def handle(
        self,
        message: "Message",
        args: str,
        context: "CommandContext",
    ) -> CommandResult:
        if context.harness_info is None:
            return CommandResult(response="Harness info is not available.")
        return CommandResult(response=context.harness_info())
