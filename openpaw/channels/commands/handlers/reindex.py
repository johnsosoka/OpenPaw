"""Reindex command handler."""

from typing import TYPE_CHECKING

from openpaw.channels.commands.base import CommandDefinition, CommandHandler, CommandResult

if TYPE_CHECKING:
    from openpaw.channels.base import Message
    from openpaw.channels.commands.base import CommandContext


class ReindexCommand(CommandHandler):
    """Trigger workspace file re-indexing."""

    @property
    def definition(self) -> CommandDefinition:
        """Command metadata."""
        return CommandDefinition(
            name="reindex",
            description="Re-index workspace files for search",
        )

    async def handle(
        self,
        message: "Message",
        args: str,
        context: "CommandContext",
    ) -> CommandResult:
        """Execute the reindex command.

        Triggers a forced re-index of all workspace files, bypassing hash-based
        change detection. Reports file and chunk counts on completion.

        Args:
            message: Incoming message.
            args: Unused (no arguments for this command).
            context: Command execution context.

        Returns:
            CommandResult with indexing summary or an unavailability notice.
        """
        file_indexer = getattr(context, "file_indexer", None)
        if not file_indexer:
            return CommandResult(
                response="File indexing is not enabled for this workspace."
            )

        result = await file_indexer.index_workspace(force=True)
        return CommandResult(
            response=(
                f"Re-indexed workspace files: "
                f"{result.files_indexed} files, "
                f"{result.chunks_created} chunks "
                f"({result.duration_ms:.0f}ms)"
            ),
        )
