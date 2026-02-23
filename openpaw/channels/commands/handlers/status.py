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

        # Model override indicator
        try:
            factory = context.agent_factory
            if factory and hasattr(factory, 'active_model') and hasattr(factory, 'configured_model'):
                if factory.active_model != factory.configured_model:
                    lines.append(f"Configured: {factory.configured_model} (overridden)")
        except (AttributeError, TypeError):
            # Agent factory might not support model tracking, skip
            pass

        # Context utilization
        try:
            state = context.session_manager.get_state(message.session_key)
            if state and state.conversation_id:
                thread_id = f"{message.session_key}:{state.conversation_id}"
                context_info = await context.agent_runner.get_context_info(thread_id)

                max_tokens = context_info.get("max_input_tokens", 200000)
                approx_tokens = context_info.get("approximate_tokens", 0)
                utilization = context_info.get("utilization", 0.0)

                lines.append(
                    f"Context: {utilization:.0%} (~{approx_tokens:,} / {max_tokens:,} tokens)"
                )
        except (AttributeError, TypeError):
            # Context info might not be available, skip
            pass

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

                    # Show in-progress task detail (max 3)
                    in_progress_tasks = [t for t in tasks if t.status == "in_progress"]
                    for task in in_progress_tasks[:3]:
                        lines.append(f"  - {task.description}")
            except (AttributeError, TypeError):
                # Task system might not be available, skip
                pass

        # Active subagents
        try:
            if context.subagent_store:
                active_subagents = context.subagent_store.list_active()
                if active_subagents:
                    labels = [req.label for req in active_subagents[:5]]
                    label_str = ", ".join(labels)
                    lines.append(f"Subagents: {len(active_subagents)} active ({label_str})")
        except (AttributeError, TypeError):
            # Subagent store might not be available, skip
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
        except (AttributeError, TypeError):
            # Token tracking might not be available, skip
            pass

        return CommandResult(response="\n".join(lines))
