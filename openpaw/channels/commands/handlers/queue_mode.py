"""Queue mode command handler."""

from typing import TYPE_CHECKING

from openpaw.channels.commands.base import CommandDefinition, CommandHandler, CommandResult

# Import directly from module to avoid circular dependency through runtime.__init__
from openpaw.core.queue.lane import QueueMode

if TYPE_CHECKING:
    from openpaw.channels.base import Message
    from openpaw.channels.commands.base import CommandContext


class QueueModeCommand(CommandHandler):
    """Change queue mode for the current session."""

    @property
    def definition(self) -> CommandDefinition:
        """Command metadata."""
        return CommandDefinition(
            name="queue",
            description="Set queue mode (collect, steer, followup, interrupt)",
            args_description="<mode>",
        )

    async def handle(
        self,
        message: "Message",
        args: str,
        context: "CommandContext",
    ) -> CommandResult:
        """Execute the queue mode command.

        Args:
            message: Incoming message.
            args: Mode string (collect, steer, followup, interrupt, default, reset).
            context: Command execution context.

        Returns:
            CommandResult with confirmation or error message.
        """
        mode_str = args.strip().lower()
        mode_map = {
            "collect": QueueMode.COLLECT,
            "steer": QueueMode.STEER,
            "followup": QueueMode.FOLLOWUP,
            "interrupt": QueueMode.INTERRUPT,
            "default": QueueMode.COLLECT,
            "reset": QueueMode.COLLECT,
        }

        mode = mode_map.get(mode_str)
        if mode:
            await context.queue_manager.set_session_mode(message.session_key, mode)
            return CommandResult(
                response=f"Queue mode set to: {mode.value}"
            )
        else:
            return CommandResult(
                response=f"Unknown mode: {mode_str}. Valid modes: collect, steer, followup, interrupt, default"
            )
