"""SelfDiscoverPlanner — SELECT / ADAPT / IMPLEMENT with cached structures (ADR-102 §3, ADR-109).

Faithful adaptation of Self-Discover (Zhou et al. 2024, arXiv:2402.03620),
implemented as a compiled LangGraph subgraph (ADR-109 §2)::

    load_cache --hit-->  solve
    load_cache --miss--> select -> adapt -> implement -> store_cache -> solve

Stage 1 (discovery, cached per task type): three structured-output meta-prompt
calls — SELECT indices into the 39 numbered seed modules, ADAPT them to the
task, IMPLEMENT an ordered reasoning structure. Stage 2 (solve): one
structured-output call follows the structure to synthesize a Plan.

Discovery prompts are deliberately task-only — no tools_summary, no digest —
so cached structures stay valid across toolsets and transfer between models
(the paper's transferability finding; ADR-103 lets discovery run on a stronger
model than solve). The solve call gets the tools context, like DirectPlanner.

The prompt wording stays faithful to the paper; constraining each stage's
output shape via ``with_structured_output`` is a deliberate reliability
deviation (ADR-109 §2). The subgraph runs unpersisted — reasoning pipelines
are ephemeral, nothing inside can pause (ADR-109 §1).
"""

import json
import logging
from typing import TypedDict, TypeVar, cast

from langchain_core.messages import HumanMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel, Field

from openpaw.agent.harness.modules.base import (
    ModuleKind,
    ReasoningArtifact,
    ReasoningContext,
    ReasoningModule,
    WorkspaceInfo,
    unpersisted_nested_config,
)
from openpaw.agent.harness.modules.direct import _PlanSchema
from openpaw.agent.harness.modules.self_discover.cache import StructureCache
from openpaw.agent.harness.modules.self_discover.seed_modules import SEED_REASONING_MODULES
from openpaw.model.plan import Plan, PlanStep
from openpaw.model.status_event import StatusEventKind

logger = logging.getLogger(__name__)

# Meta-prompts verbatim from the paper (see research/external-references.md §1);
# each gains a trailing output-format sentence for the structured schema
# (presentation, not semantics — ADR-109 §2 fidelity note).
_SELECT_PROMPT = (
    "Given the task: {task}, which of the following reasoning modules are relevant? "
    "Do not elaborate on why.\n\n{modules}\n\n"
    "Respond with the numbers of the relevant modules."
)
_ADAPT_PROMPT = (
    "Without working out the full solution, adapt the following reasoning modules to be "
    "specific to our task:\n{selected}\n\nOur task:\n{task}"
)
_IMPLEMENT_PROMPT = (
    "Without working out the full solution, create an actionable reasoning structure for the "
    "task using these adapted reasoning modules:\n{adapted}\n\nTask Description:\n{task}\n\n"
    "Respond with an ordered list of reasoning steps, each with a short name and an instruction."
)
_SOLVE_INSTRUCTION = (
    "Follow the step-by-step reasoning plan in JSON to correctly solve the task. Fill in the "
    "values following the keys by reasoning specifically about the task given. Do not simply "
    "rephrase the keys."
)

# When SELECT yields no usable indices: the paper's broadly-applicable core
# modules — simplification (4), critical thinking (10), core-issue
# identification (16), step-by-step (38).
_DEFAULT_SELECTED_INDICES: tuple[int, ...] = (4, 10, 16, 38)


class _SelectSchema(BaseModel):
    """SELECT: which seed reasoning modules apply."""

    selected_indices: list[int] = Field(
        description="1-based indices into the numbered reasoning module list"
    )


class _AdaptSchema(BaseModel):
    """ADAPT: the selected modules, rephrased for this task."""

    adapted_modules: list[str] = Field(
        description="Each selected reasoning module, rephrased to be specific to the task"
    )


class _StructureStep(BaseModel):
    """One step of the operationalized reasoning structure."""

    name: str = Field(description="Short reasoning step name")
    instruction: str = Field(description="What to reason about in this step")


class _ImplementSchema(BaseModel):
    """IMPLEMENT: the operationalized reasoning structure."""

    steps: list[_StructureStep] = Field(description="Ordered reasoning steps")


class SelfDiscoverState(TypedDict, total=False):
    """Subgraph state — JSON-safe values only (serializer rule, ADR-109 §1)."""

    task: str
    cache_hit: bool
    selected_modules: list[str]
    adapted_modules: list[str]
    structure: dict[str, object]
    plan_steps: list[str]


_SchemaT = TypeVar("_SchemaT", bound=BaseModel)


class SelfDiscoverPlanner(ReasoningModule):
    """Discover (or reuse) a task-type reasoning structure, then plan with it.

    Cache miss: 3 discovery calls + 1 solve call. Cache hit: 1 solve call.
    The live model and cache stay on the instance; graph state carries only
    JSON-safe data (ADR-109 §1).
    """

    name = "self_discover"
    kind = ModuleKind.PLANNING
    tagline = (
        "Composes a task-specific reasoning structure before planning; "
        "best for novel, hard, multi-step tasks"
    )

    def __init__(self, cache: StructureCache) -> None:
        self._cache = cache
        self._ctx: ReasoningContext | None = None
        self._graph = self._build_graph()

    @classmethod
    def build(cls, workspace: WorkspaceInfo) -> "SelfDiscoverPlanner":
        """Assemble with a workspace-local structure cache (ADR-102 §3)."""
        return cls(StructureCache(workspace.workspace_path))

    async def run(self, ctx: ReasoningContext) -> ReasoningArtifact:
        """Produce a Plan by following a discovered reasoning structure.

        Invokes the compiled subgraph unpersisted (``CONFIG_KEY_CHECKPOINTER``
        — nested runs would otherwise inherit the parent checkpointer). Stage
        nodes emit ``module.phase``/``module.insight`` on the custom stream
        (ADR-110) so the user sees the cache-hit-vs-discover decision, the
        SELECT/ADAPT/IMPLEMENT stages, and a snapshot of the structure.

        Raises:
            ValueError: If any stage returns unusable structured output or the
                solve call yields an empty step list — the plan node owns
                fallback handling, same as DirectPlanner.
        """
        self._ctx = ctx
        result = cast(
            SelfDiscoverState,
            await self._graph.ainvoke(
                SelfDiscoverState(task=ctx.task), config=unpersisted_nested_config()
            ),
        )
        structure = result["structure"]
        plan = Plan(
            objective=ctx.task,
            steps=tuple(
                PlanStep(id=str(i), description=step)
                for i, step in enumerate(result["plan_steps"], start=1)
            ),
        )
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

    # -- subgraph assembly --------------------------------------------------

    def _build_graph(
        self,
    ) -> CompiledStateGraph[SelfDiscoverState, None, SelfDiscoverState, SelfDiscoverState]:
        """Compile the discovery/solve topology once per instance (ADR-109 §1)."""
        builder: StateGraph[SelfDiscoverState, None, SelfDiscoverState, SelfDiscoverState] = (
            StateGraph(SelfDiscoverState)
        )
        builder.add_node("load_cache", self._load_cache)
        builder.add_node("select", self._select)
        builder.add_node("adapt", self._adapt)
        builder.add_node("implement", self._implement)
        builder.add_node("store_cache", self._store_cache)
        builder.add_node("solve", self._solve)
        builder.add_edge(START, "load_cache")
        builder.add_conditional_edges("load_cache", _route_after_cache, ["select", "solve"])
        builder.add_edge("select", "adapt")
        builder.add_edge("adapt", "implement")
        builder.add_edge("implement", "store_cache")
        builder.add_edge("store_cache", "solve")
        builder.add_edge("solve", END)
        return builder.compile(name="self_discover")

    def _require_ctx(self) -> ReasoningContext:
        """The per-run context bound by ``run()`` — nodes never run without it."""
        if self._ctx is None:
            raise RuntimeError("SelfDiscoverPlanner node executed outside run()")
        return self._ctx

    # -- nodes ---------------------------------------------------------------

    async def _load_cache(self, state: SelfDiscoverState) -> SelfDiscoverState:
        """Cache probe: a hit routes straight to solve, a miss starts discovery."""
        ctx = self._require_ctx()
        structure = self._cache.get(self._cache.key_for(state["task"]))
        if structure is None:
            self._emit(ctx, StatusEventKind.MODULE_PHASE, {"phase": "discovering"})
            return {"cache_hit": False}
        self._emit(ctx, StatusEventKind.MODULE_PHASE, {"phase": "structure_reused"})
        return {"cache_hit": True, "structure": structure}

    async def _select(self, state: SelfDiscoverState) -> SelfDiscoverState:
        """SELECT: structured indices into the numbered seed module list."""
        ctx = self._require_ctx()
        self._emit(ctx, StatusEventKind.MODULE_PHASE, {"phase": "select"})
        result = await self._structured(
            ctx,
            _SelectSchema,
            _SELECT_PROMPT.format(task=state["task"], modules="\n".join(SEED_REASONING_MODULES)),
        )
        return {"selected_modules": _resolve_selection(result.selected_indices)}

    async def _adapt(self, state: SelfDiscoverState) -> SelfDiscoverState:
        """ADAPT: rephrase the selected modules for this task."""
        ctx = self._require_ctx()
        self._emit(ctx, StatusEventKind.MODULE_PHASE, {"phase": "adapt"})
        result = await self._structured(
            ctx,
            _AdaptSchema,
            _ADAPT_PROMPT.format(selected="\n".join(state["selected_modules"]), task=state["task"]),
        )
        return {"adapted_modules": result.adapted_modules}

    async def _implement(self, state: SelfDiscoverState) -> SelfDiscoverState:
        """IMPLEMENT: operationalize into an ordered reasoning structure."""
        ctx = self._require_ctx()
        self._emit(ctx, StatusEventKind.MODULE_PHASE, {"phase": "implement"})
        result = await self._structured(
            ctx,
            _ImplementSchema,
            _IMPLEMENT_PROMPT.format(adapted="\n".join(state["adapted_modules"]), task=state["task"]),
        )
        if not result.steps:
            raise ValueError("SelfDiscoverPlanner IMPLEMENT produced no reasoning steps")
        # Insertion-ordered {name: instruction} — the cache entry shape is
        # unchanged from the freeform-JSON era, so old entries stay valid.
        structure: dict[str, object] = {step.name: step.instruction for step in result.steps}
        return {"structure": structure}

    async def _store_cache(self, state: SelfDiscoverState) -> SelfDiscoverState:
        """Persist the discovered structure for future task-type repeats."""
        self._cache.put(self._cache.key_for(state["task"]), state["structure"])
        return {}

    async def _solve(self, state: SelfDiscoverState) -> SelfDiscoverState:
        """Stage 2: one structured-output call following the structure."""
        ctx = self._require_ctx()
        structure = state["structure"]
        self._emit_structure_insight(ctx, structure)
        self._emit(ctx, StatusEventKind.MODULE_PHASE, {"phase": "solving"})
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
        result = await self._structured(ctx, _PlanSchema, prompt)
        if not result.steps:
            raise ValueError("SelfDiscoverPlanner produced an empty plan")
        return {"plan_steps": list(result.steps)}

    # -- helpers ---------------------------------------------------------------

    async def _structured(
        self, ctx: ReasoningContext, schema: type[_SchemaT], prompt: str
    ) -> _SchemaT:
        """One structured-output call; raises if the model ignores the schema."""
        result = await ctx.model.with_structured_output(schema).ainvoke([HumanMessage(prompt)])
        if not isinstance(result, schema):
            raise ValueError(
                f"SelfDiscoverPlanner expected {schema.__name__}, got {type(result).__name__}"
            )
        return result

    def _emit_structure_insight(self, ctx: ReasoningContext, structure: dict[str, object]) -> None:
        """Snapshot the structure's step names (skip legacy text-fallback entries)."""
        labels = [k for k in structure if k != "structure_text"]
        if not labels:
            return
        self._emit(
            ctx,
            StatusEventKind.MODULE_INSIGHT,
            {"label": "Reasoning structure", "headline": " · ".join(labels)},
        )


def _route_after_cache(state: SelfDiscoverState) -> str:
    """Conditional edge: hit skips discovery entirely."""
    return "solve" if state.get("cache_hit") else "select"


def _resolve_selection(indices: list[int]) -> list[str]:
    """Map SELECT indices to seed module texts, dropping out-of-range picks.

    An empty (or entirely invalid) selection falls back to the core default
    set rather than failing discovery (ADR-109 §2).
    """
    valid: list[int] = []
    dropped: list[int] = []
    for index in indices:
        (valid if 1 <= index <= len(SEED_REASONING_MODULES) else dropped).append(index)
    if dropped:
        logger.warning("SELECT returned out-of-range module indices, dropped: %s", dropped)
    if not valid:
        logger.warning(
            "SELECT returned no valid module indices; falling back to core set %s",
            _DEFAULT_SELECTED_INDICES,
        )
        valid = list(_DEFAULT_SELECTED_INDICES)
    return [SEED_REASONING_MODULES[index - 1] for index in valid]
