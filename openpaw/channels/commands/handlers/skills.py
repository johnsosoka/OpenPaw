"""Skills listing and staged-skill approval command handler (ADR-105 §7)."""

from typing import TYPE_CHECKING

from langchain_core.messages import HumanMessage
from langchain_core.messages.utils import count_tokens_approximately

from openpaw.channels.commands.base import CommandDefinition, CommandHandler, CommandResult
from openpaw.model.skill import SkillInfo, SkillStatus
from openpaw.stores.skill import SkillRejectedError

if TYPE_CHECKING:
    from openpaw.channels.base import Message
    from openpaw.channels.commands.base import CommandContext

_USAGE = "Usage: /skills [approve <name> | reject <name>]"


class SkillsCommand(CommandHandler):
    """List workspace skills and approve/reject staged ones."""

    @property
    def definition(self) -> CommandDefinition:
        return CommandDefinition(
            name="skills",
            description="List skills; approve or reject staged skills",
            args_description="[approve|reject <name>]",
        )

    async def handle(
        self,
        message: "Message",
        args: str,
        context: "CommandContext",
    ) -> CommandResult:
        if context.skill_store is None:
            return CommandResult(response="Skill management is not available.")

        parts = args.strip().split()
        if not parts:
            return await self._list(context)

        action = parts[0].lower()
        if action not in ("approve", "reject"):
            return CommandResult(response=f"Unknown action: '{action}'. {_USAGE}")
        if len(parts) != 2:
            return CommandResult(response=f"Missing skill name. {_USAGE}")

        name = parts[1]
        try:
            if action == "approve":
                skill = await context.skill_store.approve(name)
                return CommandResult(
                    response=(
                        f"Skill '{skill.name}' approved (v{skill.version}) — "
                        "now active and hot-reloaded."
                    )
                )
            skill = await context.skill_store.reject(name)
            return CommandResult(
                response=(
                    f"Skill '{skill.name}' rejected — marked deprecated "
                    "(kept on disk, not loaded)."
                )
            )
        except SkillRejectedError as e:
            reasons = "; ".join(err.reason for err in e.errors)
            return CommandResult(response=f"Cannot {action} '{name}': {reasons}")

    async def _list(self, context: "CommandContext") -> CommandResult:
        """Render all skills split into active/staged/deprecated sections."""
        skills: list[SkillInfo] = await context.skill_store.list_skills()
        if not skills:
            return CommandResult(response="No workspace skills found.")

        sections: list[str] = []
        for status, header in (
            (SkillStatus.ACTIVE, "Active"),
            (SkillStatus.STAGED, "Staged (awaiting /skills approve)"),
            (SkillStatus.DEPRECATED, "Deprecated"),
        ):
            group = [s for s in skills if s.status is status]
            if not group:
                continue
            lines = [f"{header}:"]
            lines.extend(_format_skill_line(s) for s in group)
            sections.append("\n".join(lines))

        return CommandResult(response="\n\n".join(sections))


def _format_skill_line(skill: SkillInfo) -> str:
    """One list line: name, version, created_by, approx token size."""
    tokens = count_tokens_approximately([HumanMessage(skill.content)])
    return f"- {skill.name} (v{skill.version}, {skill.created_by.value}, ~{tokens} tokens)"
