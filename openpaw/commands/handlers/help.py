"""Help command handler."""

from typing import TYPE_CHECKING

from openpaw.commands.base import CommandDefinition, CommandHandler, CommandResult

if TYPE_CHECKING:
    from openpaw.channels.base import Message
    from openpaw.commands.base import CommandContext


class HelpCommand(CommandHandler):
    """Display available commands."""

    @property
    def definition(self) -> CommandDefinition:
        """Command metadata."""
        return CommandDefinition(
            name="help",
            description="Show available commands",
        )

    async def handle(
        self,
        message: "Message",
        args: str,
        context: "CommandContext",
    ) -> CommandResult:
        """Execute the help command.

        Args:
            message: Incoming message.
            args: Command arguments (unused).
            context: Command execution context.

        Returns:
            CommandResult with formatted help text.
        """
        commands = []
        if context.command_router:
            commands = context.command_router.list_commands()

        if not commands:
            return CommandResult(response="No commands available.")

        lines = ["Available commands:\n"]
        for cmd in commands:
            args_hint = f" {cmd.args_description}" if cmd.args_description else ""
            lines.append(f"/{cmd.name}{args_hint} - {cmd.description}")

        return CommandResult(response="\n".join(lines))
