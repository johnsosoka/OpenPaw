"""Manage skill builtin — the agent's paved path for writing skills (PRD-001 F1.3).

Wraps SkillStore.create/update/deprecate so a single tool call validates the
skill, writes it atomically, emits lifecycle events, and triggers hot-reload.
Direct sandbox writes into agent/skills/ remain possible but skip all of that.
"""

import asyncio
import logging
from typing import Any, Literal

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from openpaw.builtins.base import (
    BaseBuiltinTool,
    BuiltinMetadata,
    BuiltinPrerequisite,
    BuiltinType,
)
from openpaw.model.skill import SkillCreatedBy, SkillInfo, SkillStatus
from openpaw.stores.skill import APPROVAL_IMMEDIATE, SkillRejectedError, SkillStore

logger = logging.getLogger(__name__)

_NO_CONTEXT_ERROR = (
    "[Error: manage_skill not available in this context (no skill store configured)]"
)


class ManageSkillInput(BaseModel):
    """Input schema for the manage_skill tool."""

    operation: Literal["create", "update", "deprecate"] = Field(
        description="Lifecycle operation: create a new skill, update an "
        "existing one, or deprecate one."
    )
    name: str = Field(
        description="Skill name — lowercase letters, digits, and hyphens "
        "(e.g. 'telegram-digest-format'). Also the directory name."
    )
    description: str | None = Field(
        default=None,
        description="Short one-line description of what the skill covers. "
        "Required for create; optional for update (keeps existing if omitted).",
    )
    content: str | None = Field(
        default=None,
        description="Skill body markdown (no frontmatter — the framework "
        "stamps it). Required for create and update.",
    )
    source: str | None = Field(
        default=None,
        description="Optional provenance reference, e.g. the conversation or "
        "session this lesson came from.",
    )


class ManageSkillTool(BaseBuiltinTool):
    """Tool for agents to create, update, and deprecate their own skills.

    All writes go through the SkillStore validation gates (schema, token
    budget, content lint, approval policy). Gate failures are returned to
    the agent verbatim so it can fix the skill and retry.

    The SkillStore is injected at wiring time via set_skill_store() (closure
    pattern, like CronTool.set_scheduler()). Without it, the tool returns a
    clean error.
    """

    metadata = BuiltinMetadata(
        name="manage_skill",
        display_name="Manage Skill",
        description="Create, update, or deprecate agent skills with validation and hot-reload",
        builtin_type=BuiltinType.TOOL,
        group="learning",
        prerequisites=BuiltinPrerequisite(),
    )

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(config)
        self._store: SkillStore | None = None
        self._approval: str = APPROVAL_IMMEDIATE

    def set_skill_store(
        self, store: SkillStore, approval: str = APPROVAL_IMMEDIATE
    ) -> None:
        """Inject the SkillStore and the workspace's approval policy.

        Called by WorkspaceRunner at wiring time.

        Args:
            store: The workspace's SkillStore instance.
            approval: "immediate" (writes go active + hot-reload) or
                "staged" (writes await /skills approve).
        """
        self._store = store
        self._approval = approval

    def get_langchain_tool(self) -> Any:
        """Return the manage_skill tool as a LangChain StructuredTool."""

        async def manage_skill_async(
            operation: str,
            name: str,
            description: str | None = None,
            content: str | None = None,
            source: str | None = None,
        ) -> str:
            """Create, update, or deprecate a skill via the SkillStore."""
            store = self._store
            if store is None:
                return _NO_CONTEXT_ERROR

            try:
                if operation == "create":
                    if content is None or description is None:
                        return (
                            "[Error: 'create' requires both 'description' and 'content']"
                        )
                    skill = await store.create(
                        name=name,
                        description=description,
                        content=content,
                        created_by=SkillCreatedBy.AGENT,
                        source=source or "",
                        approval=self._approval,
                    )
                    return _format_success("created", skill)

                if operation == "update":
                    if content is None:
                        return "[Error: 'update' requires 'content']"
                    skill = await store.update(
                        name=name,
                        content=content,
                        created_by=SkillCreatedBy.AGENT,
                        source=source or "",
                        approval=self._approval,
                        description=description,
                    )
                    return _format_success("updated", skill)

                # operation == "deprecate" (Literal schema guarantees the set)
                skill = await store.deprecate(name)
                return (
                    f"Skill '{skill.name}' deprecated (v{skill.version}). "
                    "It is no longer loaded but remains on disk."
                )

            except SkillRejectedError as e:
                lines = ["Skill rejected by validation gates:"]
                lines.extend(f"- [{err.gate}] {err.reason}" for err in e.errors)
                lines.append("Fix the issues and retry.")
                return "\n".join(lines)
            except Exception as e:
                logger.error(f"manage_skill {operation} failed: {e}", exc_info=True)
                return f"[Error: Failed to {operation} skill: {e}]"

        def manage_skill_sync(
            operation: str,
            name: str,
            description: str | None = None,
            content: str | None = None,
            source: str | None = None,
        ) -> str:
            """Sync wrapper for LangChain compatibility (delegates to async)."""
            try:
                loop = asyncio.get_running_loop()
                future = asyncio.run_coroutine_threadsafe(
                    manage_skill_async(operation, name, description, content, source),
                    loop,
                )
                return future.result(timeout=60.0)
            except RuntimeError:
                return asyncio.run(
                    manage_skill_async(operation, name, description, content, source)
                )

        return StructuredTool.from_function(
            func=manage_skill_sync,
            coroutine=manage_skill_async,
            name="manage_skill",
            description=(
                "Create, update, or deprecate one of your skills. This is the "
                "preferred way to persist a learned procedure, preference, or "
                "recipe: it validates the skill (naming, token budget, content "
                "safety), writes it atomically, and hot-reloads your prompt so "
                "the skill takes effect immediately (or stages it for human "
                "approval, per workspace policy). Read the skill-authoring "
                "guide before writing a new skill."
            ),
            args_schema=ManageSkillInput,
        )


def _format_success(verb: str, skill: SkillInfo) -> str:
    """Format a success message for a create/update result."""
    if skill.status is SkillStatus.STAGED:
        return (
            f"Skill '{skill.name}' {verb} as STAGED (v{skill.version}). "
            "It will take effect after human approval via /skills approve "
            f"{skill.name}."
        )
    return (
        f"Skill '{skill.name}' {verb} (v{skill.version}, active). "
        "Hot-reload triggered — the skill is now in your prompt."
    )
