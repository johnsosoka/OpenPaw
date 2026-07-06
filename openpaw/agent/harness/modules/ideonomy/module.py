"""IdeonomyModule — structured creative ideation through ideonomic lenses (ADR-102 §3, ADR-109 §3).

Ideonomy is Patrick Gunkel's "science of ideas" (https://ideonomy.mit.edu).
Division data and selection mechanics are ported, with attribution, from the
MIT-licensed https://github.com/Morpheis/ideonomy-engine. Lens selection is
deterministic and costs no tokens; the module spends one LLM call per
selected lens plus one synthesis call (default 3 lenses = 4 calls). The
lens calls fan out via ``Send`` and run concurrently, so wall-clock is
roughly two sequential calls regardless of lens count.
"""

import json
import logging
import operator
from collections.abc import Sequence
from typing import Annotated, cast

from langchain_core.messages import HumanMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Send
from pydantic import BaseModel, Field
from typing_extensions import TypedDict

from openpaw.agent.harness.modules.base import (
    ModuleKind,
    ReasoningArtifact,
    ReasoningContext,
    ReasoningModule,
    render_context_block,
    unpersisted_nested_config,
)
from openpaw.agent.harness.modules.ideonomy.divisions import Division
from openpaw.agent.harness.modules.ideonomy.selector import select_lenses
from openpaw.model.plan import IdeationResult
from openpaw.model.status_event import StatusEventKind

logger = logging.getLogger(__name__)


class _LensSchema(BaseModel):
    """Structured output for one lens exploration (headline drives the snapshot)."""

    headline: str = Field(description="One-sentence takeaway this lens surfaces about the task")
    exploration: str = Field(
        description="Answers to the guiding questions and the concrete ideas this lens surfaces"
    )


class _SynthesisSchema(BaseModel):
    """Structured output schema for the cross-lens synthesis call."""

    ideas: list[str] = Field(description="Concrete ideas surfaced across the lens explorations")
    evaluations: list[str] = Field(description="Strengths and risks of the leading ideas")
    recommended_directions: list[str] = Field(description="The most promising directions to pursue")


class IdeonomyState(TypedDict, total=False):
    """Subgraph state (ADR-109 §3) — JSON-safe values only, never live models.

    ``lens_outputs`` carries an ``operator.add`` reducer so the concurrent
    ``explore_lens`` branches can each append their result; a failed lens
    appends nothing and the reducer tolerates it.
    """

    task: str
    context_brief: str
    lenses: list[dict[str, object]]
    lens_outputs: Annotated[list[dict[str, str]], operator.add]
    ideas: list[str]
    evaluations: list[str]
    recommended_directions: list[str]


class _LensPayload(TypedDict):
    """Per-lens ``Send`` payload — one ``explore_lens`` invocation's input."""

    theme: str
    core_question: str
    guiding_questions: list[str]
    index: int
    total: int
    task: str
    context_brief: str


class IdeonomyModule(ReasoningModule):
    """Deterministic lens selection, concurrent per-lens LLM calls, one synthesis call."""

    name = "ideonomy"
    kind = ModuleKind.CREATIVE
    tagline = "Divergent ideation through ideonomic lenses; strongest for open-ended or creative tasks"

    def __init__(self, lens_count: int = 3) -> None:
        self._lens_count = lens_count
        # Live model/workspace stay off graph state (ADR-109 serializer rule);
        # run() binds the per-invocation context on the instance instead.
        self._ctx: ReasoningContext | None = None
        self._graph = self._build_graph()

    async def run(self, ctx: ReasoningContext) -> ReasoningArtifact:
        """Explore the task lens by lens (concurrently), then synthesize an IdeationResult.

        Invokes the compiled subgraph unpersisted (``CONFIG_KEY_CHECKPOINTER``
        — nested runs would otherwise inherit the parent checkpointer). Stage
        nodes emit ``module.phase``/``module.insight`` on the custom stream
        (ADR-110) so the user sees lens-by-lens progress and a one-line
        snapshot from each lens. Failed lens calls are skipped with a warning;
        the module proceeds as long as at least one lens succeeds.

        Raises:
            ValueError: If every lens call fails, or the synthesis call
                returns no structured output or no ideas — the ideate node
                owns fallback handling.
        """
        self._ctx = ctx
        result = cast(
            IdeonomyState,
            await self._graph.ainvoke(
                IdeonomyState(task=ctx.task, context_brief=ctx.context_brief),
                config=unpersisted_nested_config(),
            ),
        )
        synthesis = {
            "ideas": result["ideas"],
            "evaluations": result["evaluations"],
            "recommended_directions": result["recommended_directions"],
        }
        ideation = IdeationResult(
            ideas=tuple(result["ideas"]),
            evaluations=tuple(result["evaluations"]),
            recommended_directions=tuple(result["recommended_directions"]),
        )
        raw = json.dumps(
            {
                "lenses": {o["theme"]: o["exploration"] for o in result["lens_outputs"]},
                "synthesis": synthesis,
            }
        )
        return ReasoningArtifact(kind=self.kind, ideation=ideation, raw=raw)

    # -- subgraph assembly --------------------------------------------------

    def _build_graph(
        self,
    ) -> CompiledStateGraph[IdeonomyState, None, IdeonomyState, IdeonomyState]:
        """Compile the fan-out topology once per instance (ADR-109 §1, §3)."""
        builder: StateGraph[IdeonomyState, None, IdeonomyState, IdeonomyState] = (
            StateGraph(IdeonomyState)
        )
        builder.add_node("select_lenses", self._select_lenses)
        builder.add_node("explore_lens", self._explore_lens, input_schema=_LensPayload)
        builder.add_node("synthesize", self._synthesize)
        builder.add_edge(START, "select_lenses")
        builder.add_conditional_edges("select_lenses", _fan_out, ["explore_lens"])
        builder.add_edge("explore_lens", "synthesize")
        builder.add_edge("synthesize", END)
        return builder.compile(name="ideonomy")

    def _require_ctx(self) -> ReasoningContext:
        """The per-run context bound by ``run()`` — nodes never run without it."""
        if self._ctx is None:
            raise RuntimeError("IdeonomyModule node executed outside run()")
        return self._ctx

    # -- nodes ---------------------------------------------------------------

    async def _select_lenses(self, state: IdeonomyState) -> IdeonomyState:
        """Deterministic, zero-token lens selection; ``_fan_out`` sends each lens on."""
        lenses = select_lenses(state["task"], self._lens_count)
        self._emit(
            self._require_ctx(),
            StatusEventKind.MODULE_PHASE,
            {
                "phase": "lenses_selected",
                "total": len(lenses),
                "detail": " · ".join(lens.theme for lens in lenses),
            },
        )
        return {"lenses": [_lens_fields(lens) for lens in lenses]}

    async def _explore_lens(self, state: _LensPayload) -> IdeonomyState:
        """Explore the task through one lens; a failed call contributes nothing.

        Sibling lenses run concurrently (Send fan-out), so phase/insight
        events may interleave and arrive out of lens order — payloads carry
        index/label, which is all the renderers key on.
        """
        ctx = self._require_ctx()
        theme = state["theme"]
        self._emit(
            ctx,
            StatusEventKind.MODULE_PHASE,
            {"phase": "lens", "index": state["index"], "total": state["total"], "detail": theme},
        )
        prompt = _lens_prompt(
            theme,
            state["core_question"],
            state["guiding_questions"],
            state["task"],
            state["context_brief"],
        )
        try:
            exploration = await ctx.model.with_structured_output(_LensSchema).ainvoke(
                [HumanMessage(prompt)]
            )
            if not isinstance(exploration, _LensSchema):
                raise TypeError(f"lens returned {type(exploration).__name__}")
        except Exception:
            logger.warning("Ideonomy lens %s failed; skipping", theme, exc_info=True)
            return {"lens_outputs": []}
        self._emit(
            ctx,
            StatusEventKind.MODULE_INSIGHT,
            {"label": theme, "headline": exploration.headline},
        )
        return {"lens_outputs": [{"theme": theme, "exploration": exploration.exploration}]}

    async def _synthesize(self, state: IdeonomyState) -> IdeonomyState:
        """Cross-lens synthesis; raises when every lens failed (posture unchanged)."""
        ctx = self._require_ctx()
        lens_outputs = state.get("lens_outputs", [])
        if not lens_outputs:
            raise ValueError("IdeonomyModule: all lens calls failed")
        self._emit(
            ctx, StatusEventKind.MODULE_PHASE, {"phase": "synthesis", "total": len(lens_outputs)}
        )
        blocks = "\n\n".join(f"## {o['theme']}\n{o['exploration']}" for o in lens_outputs)
        prompt = (
            f"Task: {state['task']}\n\n"
            f"{render_context_block(state.get('context_brief', ''))}"
            f"Lens explorations:\n\n{blocks}\n\n"
            "Synthesize these explorations: extract the concrete ideas, evaluate "
            "the leading ones, and recommend the most promising directions."
        )
        result = await ctx.model.with_structured_output(_SynthesisSchema).ainvoke([HumanMessage(prompt)])
        if not isinstance(result, _SynthesisSchema):
            raise ValueError(f"IdeonomyModule expected structured synthesis output, got {type(result).__name__}")
        if not result.ideas:
            raise ValueError("IdeonomyModule synthesis produced no ideas")
        return {
            "ideas": result.ideas,
            "evaluations": result.evaluations,
            "recommended_directions": result.recommended_directions,
        }


def _fan_out(state: IdeonomyState) -> list[Send]:
    """One ``explore_lens`` Send per selected lens — the concurrent fan-out (ADR-109 §3)."""
    lenses = state["lenses"]
    total = len(lenses)
    return [
        Send(
            "explore_lens",
            {
                **lens,
                "index": index,
                "total": total,
                "task": state["task"],
                "context_brief": state.get("context_brief", ""),
            },
        )
        for index, lens in enumerate(lenses, start=1)
    ]


def _lens_fields(lens: Division) -> dict[str, object]:
    """The JSON-safe slice of a Division that ``explore_lens`` needs."""
    return {
        "theme": lens.theme,
        "core_question": lens.core_question,
        "guiding_questions": list(lens.guiding_questions),
    }


def _lens_prompt(
    theme: str,
    core_question: str,
    guiding_questions: Sequence[str],
    task: str,
    context_brief: str,
) -> str:
    """Build the per-lens exploration prompt."""
    questions = "\n".join(f"- {q}" for q in guiding_questions)
    return (
        f"Think through this task using the {theme} lens.\n\n"
        f"Core question: {core_question}\n\n"
        f"Guiding questions:\n{questions}\n\n"
        f"Task: {task}\n\n"
        f"{render_context_block(context_brief)}"
        "Answer the guiding questions against the task and note the most "
        "promising ideas this lens surfaces (the exploration), and distill a "
        "single-sentence takeaway (the headline)."
    )
