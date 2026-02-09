"""Command routing system."""

from typing import TYPE_CHECKING

from openpaw.channels.commands.base import CommandDefinition, CommandHandler, CommandResult

if TYPE_CHECKING:
    from openpaw.channels.base import Message
    from openpaw.channels.commands.base import CommandContext


class CommandRouter:
    """Routes commands to registered handlers."""

    def __init__(self) -> None:
        self._handlers: dict[str, CommandHandler] = {}

    def register(self, handler: CommandHandler) -> None:
        """Register a command handler.

        Args:
            handler: Command handler to register.
        """
        self._handlers[handler.definition.name] = handler

    def get_handler(self, command_name: str) -> CommandHandler | None:
        """Get handler for a command name.

        Args:
            command_name: Name of the command.

        Returns:
            Command handler if found, None otherwise.
        """
        return self._handlers.get(command_name)

    def list_commands(self, include_hidden: bool = False) -> list[CommandDefinition]:
        """List all registered commands.

        Args:
            include_hidden: Whether to include hidden commands.

        Returns:
            List of command definitions.
        """
        return [
            h.definition
            for h in self._handlers.values()
            if include_hidden or not h.definition.hidden
        ]

    async def route(
        self, message: "Message", context: "CommandContext"
    ) -> CommandResult | None:
        """Route a command message to its handler.

        Args:
            message: Incoming message.
            context: Command execution context.

        Returns:
            CommandResult if handled, None if unknown command (pass to agent).
        """
        if not message.is_command:
            return None

        command_name, args = message.parse_command()

        # Strip bot mention suffix: /queue@MyBotName -> queue
        if "@" in command_name:
            command_name = command_name.split("@")[0]

        handler = self.get_handler(command_name)
        if handler is None:
            return None  # Unknown command -> pass to agent

        return await handler.handle(message, args, context)
