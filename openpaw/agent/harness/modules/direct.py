"""DirectPlanner — single-call plan synthesis (ADR-102 §3).

The baseline planning module (``harness.planning.module: direct``) and the
fallback when richer modules fail. One structured-output call: task -> Plan.
"""

import json

from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

from openpaw.agent.harness.modules.base import ModuleKind, ReasoningArtifact, ReasoningContext
from openpaw.model.plan import Plan, PlanStep


class _PlanSchema(BaseModel):
    """Structured output schema for single-call plan synthesis."""

    steps: list[str] = Field(description="Ordered, concrete steps to accomplish the task")


class DirectPlanner:
    """One structured-output LLM call: task -> Plan."""

    name = "direct"
    kind = ModuleKind.PLANNING
    tagline = "Fast single-call plan synthesis; reliable baseline for routine multi-step tasks"

    async def run(self, ctx: ReasoningContext) -> ReasoningArtifact:
        """Synthesize a plan in one call against the per-node planning model.

        Raises:
            ValueError: If the model returns no structured output or an empty
                step list — the plan node owns fallback handling.
        """
        tool_lines = "\n".join(f"- {t.name}: {t.description}" for t in ctx.tools_summary)
        ideation_block = ""
        if ctx.ideation is not None and ctx.ideation.recommended_directions:
            directions = "\n".join(f"- {d}" for d in ctx.ideation.recommended_directions)
            ideation_block = f"\n\nCreative directions to consider:\n{directions}"
        prompt = (
            f"Task: {ctx.task}\n\n"
            f"Recent context:\n{ctx.conversation_digest}\n\n"
            f"Available tools:\n{tool_lines}"
            f"{ideation_block}\n\n"
            "Produce a short, concrete, ordered plan. Each step must be "
            "independently executable and verifiable."
        )
        result = await ctx.model.with_structured_output(_PlanSchema).ainvoke([HumanMessage(prompt)])
        if not isinstance(result, _PlanSchema):
            raise ValueError(f"DirectPlanner expected structured plan output, got {type(result).__name__}")
        if not result.steps:
            raise ValueError("DirectPlanner produced an empty plan")

        plan = Plan(
            objective=ctx.task,
            steps=tuple(PlanStep(id=str(i), description=step) for i, step in enumerate(result.steps, start=1)),
        )
        return ReasoningArtifact(kind=self.kind, plan=plan, raw=json.dumps(result.model_dump()))
