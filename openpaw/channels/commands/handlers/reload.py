"""Skills reload command handler."""

from typing import TYPE_CHECKING

from openpaw.channels.commands.base import CommandDefinition, CommandHandler, CommandResult

if TYPE_CHECKING:
    from openpaw.channels.base import Message
    from openpaw.channels.commands.base import CommandContext

_VALID_TARGETS = ("", "skills")


class ReloadCommand(CommandHandler):
    """Reload workspace skills from disk without restarting."""

    @property
    def definition(self) -> CommandDefinition:
        return CommandDefinition(
            name="reload",
            description="Reload skills from disk",
            args_description="[skills]",
        )

    async def handle(
        self,
        message: "Message",
        args: str,
        context: "CommandContext",
    ) -> CommandResult:
        target = args.strip().lower()
        if target not in _VALID_TARGETS:
            return CommandResult(
                response=f"Unknown reload target: '{target}'. Usage: /reload [skills]"
            )

        if context.skill_reloader is None:
            return CommandResult(response="Skill reload is not available.")

        workspace_count, framework_count, errors = context.skill_reloader()
        total = workspace_count + framework_count

        lines = [
            f"Skills reloaded: {total} skill{'s' if total != 1 else ''} loaded "
            f"({workspace_count} workspace, {framework_count} framework)."
        ]
        lines.extend(f"Warning: {error}" for error in errors)

        return CommandResult(response="\n".join(lines))
