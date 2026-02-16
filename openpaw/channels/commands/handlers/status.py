"""Status command handler."""

from typing import TYPE_CHECKING

from openpaw.agent.metrics import TokenUsageReader
from openpaw.channels.commands.base import CommandDefinition, CommandHandler, CommandResult

if TYPE_CHECKING:
    from openpaw.channels.base import Message
    from openpaw.channels.commands.base import CommandContext


class StatusCommand(CommandHandler):
    """Display workspace status information."""

    @property
    def definition(self) -> CommandDefinition:
        """Command metadata."""
        return CommandDefinition(
            name="status",
            description="Show workspace status",
        )

    async def handle(
        self,
        message: "Message",
        args: str,
        context: "CommandContext",
    ) -> CommandResult:
        """Execute the status command.

        Args:
            message: Incoming message.
            args: Command arguments (unused).
            context: Command execution context.

        Returns:
            CommandResult with formatted status information.
        """
        lines = [f"Workspace: {context.workspace_name}"]
        lines.append(f"Model: {context.agent_runner.model_id}")

        # Session info
        state = context.session_manager.get_state(message.session_key)
        if state:
            lines.append(f"Conversation: {state.conversation_id}")
            lines.append(f"Messages: {state.message_count}")

        # Task info (if available)
        if context.task_store:
            try:
                tasks = context.task_store.list()
                if tasks:
                    pending = sum(1 for t in tasks if t.status == "pending")
                    in_progress = sum(1 for t in tasks if t.status == "in_progress")
                    completed = sum(1 for t in tasks if t.status == "completed")
                    lines.append(f"Tasks: {pending} pending, {in_progress} in progress, {completed} completed")
            except Exception:
                # Task system might not be available, skip
                pass

        # Token usage info
        try:
            reader = TokenUsageReader(context.workspace_path)
            today = reader.tokens_today(timezone_str=context.workspace_timezone)
            session = reader.tokens_for_session(
                message.session_key,
                timezone_str=context.workspace_timezone
            )

            if today.total_tokens > 0:
                lines.append(
                    f"Tokens today: {today.total_tokens:,} "
                    f"(in: {today.input_tokens:,}, out: {today.output_tokens:,})"
                )
            if session.total_tokens > 0:
                lines.append(f"Tokens this session: {session.total_tokens:,}")
        except Exception:
            # Token tracking might not be available, skip
            pass

        return CommandResult(response="\n".join(lines))
