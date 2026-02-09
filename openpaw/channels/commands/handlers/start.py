"""Start command handler."""

from typing import TYPE_CHECKING

from openpaw.channels.commands.base import CommandDefinition, CommandHandler, CommandResult

if TYPE_CHECKING:
    from openpaw.channels.base import Message
    from openpaw.channels.commands.base import CommandContext


class StartCommand(CommandHandler):
    """Initialize the bot with a welcome message."""

    @property
    def definition(self) -> CommandDefinition:
        """Command metadata."""
        return CommandDefinition(
            name="start",
            description="Initialize the bot",
            hidden=True,
        )

    async def handle(
        self,
        message: "Message",
        args: str,
        context: "CommandContext",
    ) -> CommandResult:
        """Execute the start command.

        Args:
            message: Incoming message.
            args: Command arguments (unused).
            context: Command execution context.

        Returns:
            CommandResult with welcome message.
        """
        return CommandResult(
            response=f"OpenPaw agent '{context.workspace_name}' ready. Send /help for commands."
        )
