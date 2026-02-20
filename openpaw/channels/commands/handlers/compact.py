"""Compact conversation command handler."""

import logging
from typing import TYPE_CHECKING

from openpaw.channels.commands.base import CommandDefinition, CommandHandler, CommandResult
from openpaw.prompts.commands import COMPACTED_TEMPLATE, SUMMARIZE_PROMPT

if TYPE_CHECKING:
    from openpaw.channels.base import Message
    from openpaw.channels.commands.base import CommandContext

logger = logging.getLogger(__name__)


class CompactCommand(CommandHandler):
    """Compact the current conversation by summarizing, archiving, and starting fresh."""

    @property
    def definition(self) -> CommandDefinition:
        """Command metadata.

        Returns:
            CommandDefinition for the compact command.
        """
        return CommandDefinition(
            name="compact",
            description="Summarize and archive conversation, start fresh with context",
            bypass_queue=True,
        )

    async def handle(
        self,
        message: "Message",
        args: str,
        context: "CommandContext",
    ) -> CommandResult:
        """Execute the compact command.

        Args:
            message: Incoming message.
            args: Command arguments (unused).
            context: Command execution context.

        Returns:
            CommandResult with confirmation and new thread ID.
        """
        if not context.checkpointer:
            return CommandResult(response="Cannot compact: no checkpointer available.")

        # Get current thread info
        old_thread_id = context.session_manager.get_thread_id(message.session_key)
        old_state = context.session_manager.get_state(message.session_key)
        old_conv_id = old_state.conversation_id if old_state else "unknown"

        # Step 1: Generate summary using the agent
        summary = None
        try:
            summary = await context.agent_runner.run(
                message=SUMMARIZE_PROMPT,
                thread_id=old_thread_id,
            )
            if summary:
                summary = summary.strip()
            logger.info(f"Generated summary for {old_conv_id}: {len(summary or '')} chars")
        except Exception as e:
            logger.warning(f"Failed to generate summary for {old_conv_id}: {e}")

        # Step 2: Archive the conversation (with summary if available)
        message_count = 0
        if context.conversation_archiver:
            try:
                archive = await context.conversation_archiver.archive(
                    checkpointer=context.checkpointer,
                    thread_id=old_thread_id,
                    session_key=message.session_key,
                    conversation_id=old_conv_id,
                    summary=summary,
                    tags=["compact"],
                )
                if archive:
                    message_count = archive.message_count
                    logger.info(f"Archived conversation {old_conv_id} ({message_count} messages)")
            except Exception as e:
                logger.warning(f"Failed to archive conversation {old_conv_id}: {e}")

        # Step 3: Close browser session if active (conversation context changing)
        if context.browser_builtin:
            try:
                await context.browser_builtin.cleanup()
                logger.debug("Closed browser session on conversation compaction")
            except Exception as e:
                logger.warning(f"Failed to close browser on /compact: {e}")

        # Step 4: Rotate to new conversation
        context.session_manager.new_conversation(message.session_key)
        new_thread_id = context.session_manager.get_thread_id(message.session_key)

        # Step 5: Inject summary into new thread as first message
        if summary:
            try:
                injection_prompt = COMPACTED_TEMPLATE.format(summary=summary)
                await context.agent_runner.run(
                    message=injection_prompt,
                    thread_id=new_thread_id,
                )
                logger.info(f"Injected summary into new conversation for {message.session_key}")
            except Exception as e:
                logger.warning(f"Failed to inject summary into new thread: {e}")

        # Build response
        parts = ["Conversation compacted."]
        if message_count > 0:
            parts.append(f"{message_count} messages archived.")
        if summary:
            parts.append("Summary preserved as context.")
        else:
            parts.append("Could not generate summary.")

        return CommandResult(
            response=" ".join(parts),
            new_thread_id=new_thread_id,
        )
