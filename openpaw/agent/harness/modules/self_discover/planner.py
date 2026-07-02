"""SelfDiscoverPlanner — SELECT / ADAPT / IMPLEMENT with cached structures (ADR-102 §3).

Faithful adaptation of Self-Discover (Zhou et al. 2024, arXiv:2402.03620).
Stage 1 (discovery, cached per task type): three sequential meta-prompt calls
— SELECT over the 39 seed modules, ADAPT to the task, IMPLEMENT into a JSON
reasoning structure. Stage 2 (solve): one structured-output call follows the
structure to synthesize a Plan.

Discovery prompts are deliberately task-only — no tools_summary — so cached
structures stay valid across toolsets and transfer between models (the
paper's transferability finding; ADR-103 lets discovery run on a stronger
model than solve). The solve call gets the tools context, like DirectPlanner.
"""

import json

from langchain_core.messages import BaseMessage, HumanMessage

from openpaw.agent.harness.modules.base import ModuleKind, ReasoningArtifact, ReasoningContext
from openpaw.agent.harness.modules.direct import _PlanSchema
from openpaw.agent.harness.modules.self_discover.cache import StructureCache
from openpaw.agent.harness.modules.self_discover.seed_modules import SEED_REASONING_MODULES
from openpaw.model.plan import Plan, PlanStep

# Meta-prompts verbatim from the paper (see research/external-references.md §1);
# IMPLEMENT gains a trailing output-format line so the structure parses as JSON.
_SELECT_PROMPT = (
    "Given the task: {task}, which of the following reasoning modules are relevant? "
    "Do not elaborate on why.\n\n{modules}"
)
_ADAPT_PROMPT = (
    "Without working out the full solution, adapt the following reasoning modules to be "
    "specific to our task:\n{selected}\n\nOur task:\n{task}"
)
_IMPLEMENT_PROMPT = (
    "Without working out the full solution, create an actionable reasoning structure for the "
    "task using these adapted reasoning modules:\n{adapted}\n\nTask Description:\n{task}\n\n"
    "Respond with only a JSON object mapping reasoning step names to instructions."
)
_SOLVE_INSTRUCTION = (
    "Follow the step-by-step reasoning plan in JSON to correctly solve the task. Fill in the "
    "values following the keys by reasoning specifically about the task given. Do not simply "
    "rephrase the keys."
)


def _text(message: BaseMessage) -> str:
    """Extract plain text from a chat model response."""
    content = message.content
    return content if isinstance(content, str) else str(content)


def _parse_structure(raw: str) -> dict[str, object]:
    """Parse IMPLEMENT output as a JSON object; non-JSON degrades to text.

    A ``{"structure_text": raw}`` fallback keeps the pipeline moving — the
    solve prompt works with either form (the instance-level follow-up paper
    found rigid JSON is optional anyway).
    """
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`").removeprefix("json").strip()
    try:
        parsed: object = json.loads(text)
    except json.JSONDecodeError:
        return {"structure_text": raw}
    if isinstance(parsed, dict):
        return {str(k): v for k, v in parsed.items()}
    return {"structure_text": raw}


class SelfDiscoverPlanner:
    """Discover (or reuse) a task-type reasoning structure, then plan with it.

    Cache miss: 3 discovery calls + 1 solve call. Cache hit: 1 solve call.
    """

    name = "self_discover"
    kind = ModuleKind.PLANNING
    tagline = (
        "Composes a task-specific reasoning structure before planning; "
        "best for novel, hard, multi-step tasks"
    )

    def __init__(self, cache: StructureCache) -> None:
        self._cache = cache

    async def run(self, ctx: ReasoningContext) -> ReasoningArtifact:
        """Produce a Plan by following a discovered reasoning structure.

        Raises:
            ValueError: If the solve call returns no structured output or an
                empty step list — the plan node owns fallback handling, same
                as DirectPlanner.
        """
        key = self._cache.key_for(ctx.task)
        structure = self._cache.get(key)
        if structure is None:
            structure = await self._discover(ctx)
            self._cache.put(key, structure)

        plan = await self._solve(ctx, structure)
        return ReasoningArtifact(
            kind=self.kind,
            plan=plan,
            reasoning_structure=structure,
            raw=json.dumps(
                {
                    "reasoning_structure": structure,
                    "steps": [s.description for s in plan.steps],
                }
            ),
        )

    async def _discover(self, ctx: ReasoningContext) -> dict[str, object]:
        """Stage 1: SELECT -> ADAPT -> IMPLEMENT (3 sequential calls, task-only)."""
        modules_text = "\n".join(SEED_REASONING_MODULES)
        selected = await ctx.model.ainvoke(
            [HumanMessage(_SELECT_PROMPT.format(task=ctx.task, modules=modules_text))]
        )
        adapted = await ctx.model.ainvoke(
            [HumanMessage(_ADAPT_PROMPT.format(selected=_text(selected), task=ctx.task))]
        )
        implemented = await ctx.model.ainvoke(
            [HumanMessage(_IMPLEMENT_PROMPT.format(adapted=_text(adapted), task=ctx.task))]
        )
        return _parse_structure(_text(implemented))

    async def _solve(self, ctx: ReasoningContext, structure: dict[str, object]) -> Plan:
        """Stage 2: one structured-output call following the structure."""
        tool_lines = "\n".join(f"- {t.name}: {t.description}" for t in ctx.tools_summary)
        prompt = (
            f"{_SOLVE_INSTRUCTION}\n\n"
            f"Reasoning structure:\n{json.dumps(structure, indent=2)}\n\n"
            f"Task: {ctx.task}\n\n"
            f"Recent context:\n{ctx.conversation_digest}\n\n"
            f"Available tools:\n{tool_lines}\n\n"
            "Then produce a short, concrete, ordered plan. Each step must be "
            "independently executable and verifiable."
        )
        result = await ctx.model.with_structured_output(_PlanSchema).ainvoke([HumanMessage(prompt)])
        if not isinstance(result, _PlanSchema):
            raise ValueError(
                f"SelfDiscoverPlanner expected structured plan output, got {type(result).__name__}"
            )
        if not result.steps:
            raise ValueError("SelfDiscoverPlanner produced an empty plan")
        return Plan(
            objective=ctx.task,
            steps=tuple(
                PlanStep(id=str(i), description=step)
                for i, step in enumerate(result.steps, start=1)
            ),
        )
