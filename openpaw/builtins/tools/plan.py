"""Session-scoped planning tool for multi-step work externalization."""

import logging
from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from openpaw.builtins.base import (
    BaseBuiltinTool,
    BuiltinMetadata,
    BuiltinPrerequisite,
    BuiltinType,
)

logger = logging.getLogger(__name__)


class PlanStep(BaseModel):
    """A single step in a plan."""

    step: str = Field(description="Description of what this step accomplishes")
    status: str = Field(
        default="pending",
        description="Step status: 'pending', 'in_progress', or 'completed'",
    )


class WritePlanInput(BaseModel):
    """Input schema for writing a plan."""

    steps: list[PlanStep] = Field(description="Ordered list of plan steps with status")


class PlanToolBuiltin(BaseBuiltinTool):
    """Session-scoped planning tool for multi-step work.

    Forces the model to externalize its plan before executing, preventing
    premature stopping after partial work. Plans are ephemeral (not persisted
    to disk) — use task_tracker for durable cross-session work tracking.

    Inspired by DeepAgent SDK's write_todos pattern: a lightweight planning
    tool that forces the model to think through all steps before starting.
    """

    metadata = BuiltinMetadata(
        name="plan",
        display_name="Planning",
        description="Session-scoped task planning for multi-step work",
        builtin_type=BuiltinType.TOOL,
        group="automation",
        prerequisites=BuiltinPrerequisite(),  # No API keys needed
    )

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(config)
        self._plan: list[dict[str, str]] = []

    def get_langchain_tool(self) -> list[StructuredTool]:
        return [
            self._create_write_plan_tool(),
            self._create_read_plan_tool(),
        ]

    def reset(self) -> None:
        """Clear the current plan. Called on /new and /compact."""
        self._plan = []

    def _create_write_plan_tool(self) -> StructuredTool:
        def write_plan(steps: list[PlanStep]) -> str:
            """Write or update your current work plan.

            Use this BEFORE starting multi-step work to externalize your approach.
            Each step should be a concrete action you intend to take. Update the
            plan as you complete steps (set status to 'completed') or discover
            new steps are needed.

            When to plan:
            - Tasks requiring 3 or more sequential steps
            - Complex debugging or troubleshooting
            - Multi-file changes or refactoring
            - Any work where you might lose track of progress

            When NOT to plan:
            - Simple questions or lookups
            - Single-step actions
            - Casual conversation

            Args:
                steps: Ordered list of plan steps. Each step has:
                    - step: Description of the action
                    - status: 'pending', 'in_progress', or 'completed'

            Returns:
                Confirmation with plan summary.
            """
            valid_statuses = {"pending", "in_progress", "completed"}
            normalized = []
            for s in steps:
                # s is a PlanStep Pydantic object, not a dict
                status = s.status
                if status not in valid_statuses:
                    return f"[Error: Invalid status '{status}'. Valid: pending, in_progress, completed]"
                normalized.append({"step": s.step, "status": status})

            self._plan = normalized

            # Format summary
            total = len(normalized)
            completed = sum(1 for s in normalized if s["status"] == "completed")
            in_progress = sum(1 for s in normalized if s["status"] == "in_progress")
            pending = total - completed - in_progress

            lines = [f"Plan updated ({completed}/{total} completed):"]
            for i, s in enumerate(normalized, 1):
                icon = {
                    "completed": "[x]",
                    "in_progress": "[>]",
                    "pending": "[ ]",
                }[s["status"]]
                lines.append(f"  {icon} {i}. {s['step']}")

            if pending > 0:
                lines.append(f"\n{pending} step(s) remaining.")

            return "\n".join(lines)

        return StructuredTool.from_function(
            func=write_plan,
            name="write_plan",
            description=(
                "Write or update your work plan for the current task. "
                "Use this before starting multi-step work to organize your approach. "
                "Update step statuses as you progress. Plans are session-scoped "
                "and reset on new conversations."
            ),
            args_schema=WritePlanInput,
        )

    def _create_read_plan_tool(self) -> StructuredTool:
        def read_plan() -> str:
            """Read the current work plan.

            Returns the current plan with step statuses. Useful after
            conversation compaction to recall what you were working on.

            Returns:
                Current plan or message indicating no plan exists.
            """
            if not self._plan:
                return "No active plan. Use write_plan to create one."

            total = len(self._plan)
            completed = sum(1 for s in self._plan if s["status"] == "completed")

            lines = [f"Current plan ({completed}/{total} completed):"]
            for i, s in enumerate(self._plan, 1):
                icon = {
                    "completed": "[x]",
                    "in_progress": "[>]",
                    "pending": "[ ]",
                }[s["status"]]
                lines.append(f"  {icon} {i}. {s['step']}")

            return "\n".join(lines)

        return StructuredTool.from_function(
            func=read_plan,
            name="read_plan",
            description=(
                "Read your current work plan to check progress. "
                "Useful after conversation compaction or to review remaining steps."
            ),
        )
