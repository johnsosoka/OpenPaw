"""New conversation command handler."""

import logging
from typing import TYPE_CHECKING

from openpaw.channels.commands.base import CommandDefinition, CommandHandler, CommandResult

if TYPE_CHECKING:
    from openpaw.channels.base import Message
    from openpaw.channels.commands.base import CommandContext

logger = logging.getLogger(__name__)


class NewCommand(CommandHandler):
    """Start a fresh conversation."""

    @property
    def definition(self) -> CommandDefinition:
        """Command metadata."""
        return CommandDefinition(
            name="new",
            description="Start a fresh conversation",
            bypass_queue=True,
        )

    async def handle(
        self,
        message: "Message",
        args: str,
        context: "CommandContext",
    ) -> CommandResult:
        """Execute the new command.

        Args:
            message: Incoming message.
            args: Command arguments (unused).
            context: Command execution context.

        Returns:
            CommandResult with confirmation and new thread ID.
        """
        # Get current thread ID before rotation
        old_thread_id = context.session_manager.get_thread_id(message.session_key)
        old_state = context.session_manager.get_state(message.session_key)
        old_conv_id = old_state.conversation_id if old_state else "unknown"

        # Archive current conversation (if archiver available and checkpointer exists)
        archived = False
        if context.conversation_archiver and context.checkpointer:
            try:
                archive = await context.conversation_archiver.archive(
                    checkpointer=context.checkpointer,
                    thread_id=old_thread_id,
                    session_key=message.session_key,
                    conversation_id=old_conv_id,
                    tags=["manual"],
                )
                if archive:
                    archived = True
                    logger.info(f"Archived conversation {old_conv_id} ({archive.message_count} messages)")
            except Exception as e:
                logger.warning(f"Failed to archive conversation {old_conv_id}: {e}")

        # Close browser session if active (conversation context changing)
        if context.browser_builtin:
            try:
                await context.browser_builtin.cleanup()
                logger.debug("Closed browser session on conversation rotation")
            except Exception as e:
                logger.warning(f"Failed to close browser on /new: {e}")

        # Rotate to new conversation
        context.session_manager.new_conversation(message.session_key)
        new_thread_id = context.session_manager.get_thread_id(message.session_key)

        # Build response
        if archived:
            response = f"New conversation started. Previous conversation ({old_conv_id}) archived."
        else:
            response = "New conversation started."

        return CommandResult(
            response=response,
            new_thread_id=new_thread_id,
        )
