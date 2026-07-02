"""IdeonomyModule — structured creative ideation through ideonomic lenses (ADR-102 §3).

Ideonomy is Patrick Gunkel's "science of ideas" (https://ideonomy.mit.edu).
Division data and selection mechanics are ported, with attribution, from the
MIT-licensed https://github.com/Morpheis/ideonomy-engine. Lens selection is
deterministic and costs no tokens; the module spends one LLM call per
selected lens plus one synthesis call (default 3 lenses = 4 calls).
"""

import json
import logging

from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

from openpaw.agent.harness.modules.base import (
    ModuleKind,
    ReasoningArtifact,
    ReasoningContext,
    ReasoningModule,
)
from openpaw.agent.harness.modules.ideonomy.divisions import Division
from openpaw.agent.harness.modules.ideonomy.selector import select_lenses
from openpaw.model.plan import IdeationResult

logger = logging.getLogger(__name__)


class _SynthesisSchema(BaseModel):
    """Structured output schema for the cross-lens synthesis call."""

    ideas: list[str] = Field(description="Concrete ideas surfaced across the lens explorations")
    evaluations: list[str] = Field(description="Strengths and risks of the leading ideas")
    recommended_directions: list[str] = Field(description="The most promising directions to pursue")


class IdeonomyModule(ReasoningModule):
    """Deterministic lens selection, then one LLM pass per lens plus one synthesis call."""

    name = "ideonomy"
    kind = ModuleKind.CREATIVE
    tagline = "Divergent ideation through ideonomic lenses; strongest for open-ended or creative tasks"

    def __init__(self, lens_count: int = 3) -> None:
        self._lens_count = lens_count

    async def run(self, ctx: ReasoningContext) -> ReasoningArtifact:
        """Think through the task lens by lens, then synthesize an IdeationResult.

        Failed lens calls are skipped with a warning; the module proceeds as
        long as at least one lens succeeds.

        Raises:
            ValueError: If every lens call fails, or the synthesis call
                returns no structured output or no ideas — the ideate node
                owns fallback handling.
        """
        lenses = select_lenses(ctx.task, self._lens_count)
        lens_outputs: list[tuple[str, str]] = []
        for lens in lenses:
            try:
                response = await ctx.model.ainvoke([HumanMessage(_lens_prompt(lens, ctx.task))])
                lens_outputs.append((lens.theme, str(response.content)))
            except Exception:
                logger.warning("Ideonomy lens %s failed; skipping", lens.theme, exc_info=True)
        if not lens_outputs:
            raise ValueError("IdeonomyModule: all lens calls failed")

        blocks = "\n\n".join(f"## {theme}\n{output}" for theme, output in lens_outputs)
        prompt = (
            f"Task: {ctx.task}\n\n"
            f"Lens explorations:\n\n{blocks}\n\n"
            "Synthesize these explorations: extract the concrete ideas, evaluate "
            "the leading ones, and recommend the most promising directions."
        )
        result = await ctx.model.with_structured_output(_SynthesisSchema).ainvoke([HumanMessage(prompt)])
        if not isinstance(result, _SynthesisSchema):
            raise ValueError(f"IdeonomyModule expected structured synthesis output, got {type(result).__name__}")
        if not result.ideas:
            raise ValueError("IdeonomyModule synthesis produced no ideas")

        ideation = IdeationResult(
            ideas=tuple(result.ideas),
            evaluations=tuple(result.evaluations),
            recommended_directions=tuple(result.recommended_directions),
        )
        raw = json.dumps({"lenses": dict(lens_outputs), "synthesis": result.model_dump()})
        return ReasoningArtifact(kind=self.kind, ideation=ideation, raw=raw)


def _lens_prompt(lens: Division, task: str) -> str:
    """Build the per-lens exploration prompt."""
    questions = "\n".join(f"- {q}" for q in lens.guiding_questions)
    return (
        f"Think through this task using the {lens.theme} lens.\n\n"
        f"Core question: {lens.core_question}\n\n"
        f"Guiding questions:\n{questions}\n\n"
        f"Task: {task}\n\n"
        "Answer the guiding questions against the task, then note the most "
        "promising ideas this lens surfaces."
    )
