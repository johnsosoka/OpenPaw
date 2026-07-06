"""Reflection modules — step-outcome evaluation (ADR-102 §2/§3).

``LightReflection``: one structured verdict per step. Light never rewrites
the plan: a ``revise_plan`` action from the model is coerced to ``advance``
(the model's notes are preserved, prefixed with the coercion reason) so the
plan-loop contract stays simple — ``artifact.plan`` is always None for light.

``FullReflection``: verdict call as in light; on ``revise_plan`` a second
structured call rewrites the remaining steps. ``artifact.plan`` then holds
ONLY the new remaining steps — a Plan with the same objective whose step ids
continue from the highest executed ordinal — and the reflect node applies it
to the live plan via :meth:`openpaw.model.plan.Plan.with_remaining_replaced`.
"""

import json
import logging
import re

from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

from openpaw.agent.harness.modules.base import (
    ModuleKind,
    ReasoningArtifact,
    ReasoningContext,
    ReasoningModule,
    ReflectAction,
    ReflectionVerdict,
)
from openpaw.model.plan import Plan, PlanStep, StepStatus

logger = logging.getLogger(__name__)

_LIGHT_COERCION_NOTE = "revise_plan requested; light reflection never rewrites the plan — advancing"
_EMPTY_REVISION_NOTE = "revise_plan returned no steps; advancing"


class _VerdictSchema(BaseModel):
    """Structured output schema for step-outcome evaluation."""

    action: ReflectAction = Field(description="What the plan loop should do next")
    step_succeeded: bool = Field(description="Whether the step achieved its intent")
    insert_description: str = Field(default="", description="New-step description when action is insert_step")
    notes: str = Field(default="", description="Brief evaluation notes")


class _RemainingStepsSchema(BaseModel):
    """Structured output schema for rewriting the remaining plan steps."""

    steps: list[str] = Field(description="Rewritten remaining steps, in order")


def _require_reflection_inputs(ctx: ReasoningContext) -> tuple[Plan, str]:
    """Return (plan, current_step_id), failing fast on a miswired context."""
    if ctx.plan is None or ctx.current_step_id is None:
        raise ValueError("reflection modules require ctx.plan and ctx.current_step_id")
    return ctx.plan, ctx.current_step_id


def _verdict_prompt(ctx: ReasoningContext, plan: Plan, step_id: str) -> str:
    return (
        f"Objective: {ctx.task}\n\n"
        f"Current plan:\n{plan.render_checklist()}\n\n"
        f"Step {step_id} output:\n{ctx.last_step_result}\n\n"
        "Did the step achieve its intent? Choose an action: advance to the "
        "next step, revise_plan if the remaining steps no longer fit, "
        "insert_step to add one corrective step, or abort_to_user if the "
        "objective cannot proceed without the user."
    )


async def _call_verdict(ctx: ReasoningContext, plan: Plan, step_id: str) -> _VerdictSchema:
    """One structured verdict call, shared by both reflection depths."""
    result = await ctx.model.with_structured_output(_VerdictSchema).ainvoke(
        [HumanMessage(_verdict_prompt(ctx, plan, step_id))]
    )
    if not isinstance(result, _VerdictSchema):
        raise ValueError(f"reflection expected structured verdict output, got {type(result).__name__}")
    return result


def _next_ordinal(plan: Plan, current_step_id: str) -> int:
    """First free ordinal after the executed steps.

    Executed = any non-PENDING step, plus the current step (it has just run
    regardless of when the graph flips its status). Letter-suffixed insertion
    ids ("2A") count under their numeric prefix.
    """
    highest = 0
    for step in plan.steps:
        if step.status == StepStatus.PENDING and step.id != current_step_id:
            continue
        match = re.match(r"\d+", step.id)
        if match:
            highest = max(highest, int(match.group()))
    return highest + 1


class LightReflection(ReasoningModule):
    """One structured verdict per step; never rewrites the plan.

    The 0.5.0 default (``harness.reflection.module: light``). A model verdict
    of ``revise_plan`` is coerced to ``advance`` with the notes preserved —
    revision authority belongs to :class:`FullReflection`.
    """

    name = "light"
    kind = ModuleKind.REFLECTION
    tagline = "Single structured outcome check per step; fast, cheap, catches obvious failures"

    async def run(self, ctx: ReasoningContext) -> ReasoningArtifact:
        """Evaluate the just-executed step against its intent (one call)."""
        plan, step_id = _require_reflection_inputs(ctx)
        schema = await _call_verdict(ctx, plan, step_id)

        action: ReflectAction = schema.action
        notes = schema.notes
        if action == "revise_plan":
            action = "advance"
            notes = f"[{_LIGHT_COERCION_NOTE}] {schema.notes}".strip()

        verdict = ReflectionVerdict(
            action=action,
            step_succeeded=schema.step_succeeded,
            notes=notes,
            insert_description=schema.insert_description,
        )
        return ReasoningArtifact(kind=self.kind, verdict=verdict, raw=json.dumps(schema.model_dump()))


class FullReflection(ReasoningModule):
    """Verdict plus authority to rewrite the remaining plan.

    On ``revise_plan`` a second structured call produces the rewritten
    remaining steps; ``artifact.plan`` carries only that new tail (same
    objective, ids continuing from the highest executed ordinal). The reflect
    node applies it via ``Plan.with_remaining_replaced``.
    """

    name = "full"
    kind = ModuleKind.REFLECTION
    tagline = "Deep outcome evaluation that may rewrite the remaining plan; best for long or fragile plans"

    async def run(self, ctx: ReasoningContext) -> ReasoningArtifact:
        """Evaluate the step; on revise_plan, rewrite the remaining steps."""
        plan, step_id = _require_reflection_inputs(ctx)
        schema = await _call_verdict(ctx, plan, step_id)
        verdict = ReflectionVerdict(
            action=schema.action,
            step_succeeded=schema.step_succeeded,
            notes=schema.notes,
            insert_description=schema.insert_description,
        )
        if schema.action != "revise_plan":
            return ReasoningArtifact(kind=self.kind, verdict=verdict, raw=json.dumps(schema.model_dump()))

        revised = await self._rewrite_remaining(ctx, plan, step_id)
        raw = json.dumps({"verdict": schema.model_dump(), "revised_steps": revised.steps})
        if not revised.steps:
            # Defensive: a revision that deletes every remaining step is not
            # a plan rewrite — treat it as advance rather than emptying the tail.
            logger.warning("FullReflection revise_plan returned no steps; coercing to advance")
            verdict = ReflectionVerdict(
                action="advance",
                step_succeeded=schema.step_succeeded,
                notes=f"[{_EMPTY_REVISION_NOTE}] {schema.notes}".strip(),
                insert_description=schema.insert_description,
            )
            return ReasoningArtifact(kind=self.kind, verdict=verdict, raw=raw)

        start = _next_ordinal(plan, step_id)
        tail = tuple(
            PlanStep(id=str(start + offset), description=description)
            for offset, description in enumerate(revised.steps)
        )
        new_remaining = Plan(objective=plan.objective, steps=tail)
        return ReasoningArtifact(kind=self.kind, plan=new_remaining, verdict=verdict, raw=raw)

    async def _rewrite_remaining(
        self, ctx: ReasoningContext, plan: Plan, step_id: str
    ) -> _RemainingStepsSchema:
        """Second structured call: produce the new remaining steps only."""
        prompt = (
            f"Objective: {ctx.task}\n\n"
            f"Current plan:\n{plan.render_checklist()}\n\n"
            f"Step {step_id} output:\n{ctx.last_step_result}\n\n"
            "The remaining (unexecuted) steps no longer fit. Rewrite them: "
            "produce the new ordered list of remaining steps only — do not "
            "repeat steps that have already executed."
        )
        result = await ctx.model.with_structured_output(_RemainingStepsSchema).ainvoke([HumanMessage(prompt)])
        if not isinstance(result, _RemainingStepsSchema):
            raise ValueError(f"reflection expected structured remaining-steps output, got {type(result).__name__}")
        return result
