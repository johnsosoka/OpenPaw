"""Tests for the IdeonomyModule creative reasoning module (ADR-102 §3, ADR-109 §3)."""

import asyncio
from pathlib import Path
from typing import TypedDict, cast

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from openpaw.agent.harness.modules.base import (
    ModuleKind,
    ReasoningContext,
    ToolSummary,
    WorkspaceInfo,
)
from openpaw.agent.harness.modules.ideonomy import IdeonomyModule, select_lenses
from openpaw.agent.harness.modules.ideonomy.divisions import DIVISIONS, Division
from openpaw.agent.harness.modules.ideonomy.module import _LensSchema, _SynthesisSchema
from openpaw.agent.harness.modules.ideonomy.selector import score_division
from openpaw.model.status_event import StatusEventKind
from tests.test_reasoning_modules import run_streamed

NAMING_TASK = (
    "What should we name this concept? Find a metaphor or analogy "
    "that captures its meaning and essence."
)


def lens(headline: str, exploration: str) -> _LensSchema:
    return _LensSchema(headline=headline, exploration=exploration)


class FakeModel:
    """Fake chat model returning canned outputs in order.

    Lens calls and the synthesis call are both structured; they share one
    output queue. An output that is an Exception is raised.
    """

    def __init__(self, *outputs: object) -> None:
        self._outputs = list(outputs)
        self.prompts: list[str] = []
        self.schemas: list[type] = []

    def with_structured_output(self, schema: type) -> "FakeModel":
        self.schemas.append(schema)
        return self

    async def ainvoke(self, messages: list[BaseMessage]) -> object:
        self.prompts.append(str(messages[0].content))
        output = self._outputs.pop(0)
        if isinstance(output, Exception):
            raise output
        return output

    @property
    def call_count(self) -> int:
        return len(self.prompts)


def fake_model(*outputs: object) -> BaseChatModel:
    return cast(BaseChatModel, FakeModel(*outputs))


def make_ctx(model: BaseChatModel, task: str = NAMING_TASK) -> ReasoningContext:
    return ReasoningContext(
        task=task,
        conversation_digest="User asked for naming help.",
        tools_summary=[ToolSummary(name="web_search", description="Search the web")],
        model=model,
        workspace=WorkspaceInfo(name="testws", timezone="UTC", workspace_path=Path("/tmp/ws")),
    )


def by_theme(theme: str) -> Division:
    return next(d for d in DIVISIONS if d.theme == theme)


def synthesis() -> _SynthesisSchema:
    return _SynthesisSchema(
        ideas=["Call it Prism"],
        evaluations=["Prism is evocative but common"],
        recommended_directions=["Lean into the light metaphor"],
    )


# ---------------------------------------------------------------------------
# Selector
# ---------------------------------------------------------------------------


def test_selector_is_deterministic():
    assert select_lenses(NAMING_TASK) == select_lenses(NAMING_TASK)


def test_selector_scores_relevant_divisions_higher():
    concepts = by_theme("CONCEPTS")
    analogies = by_theme("ANALOGIES")
    cycles = by_theme("CYCLES")

    assert score_division(concepts, NAMING_TASK) > score_division(cycles, NAMING_TASK)
    assert score_division(analogies, NAMING_TASK) > score_division(cycles, NAMING_TASK)

    themes = [d.theme for d in select_lenses(NAMING_TASK)]
    assert "CONCEPTS" in themes
    assert "ANALOGIES" in themes
    assert "CYCLES" not in themes


def test_selector_respects_count():
    assert len(select_lenses(NAMING_TASK)) == 3  # default
    assert len(select_lenses(NAMING_TASK, count=5)) == 5
    assert len(select_lenses(NAMING_TASK, count=100)) == len(DIVISIONS)


def test_selector_ties_break_alphabetically():
    # No keyword can match — all scores are 0, order falls back to theme.
    themes = [d.theme for d in select_lenses("zzz qqq xxx")]
    assert themes == ["ALTERNATIVES", "ANALOGIES", "ANALYSES"]


def test_division_data_shape():
    assert len(DIVISIONS) == 28
    for d in DIVISIONS:
        assert d.keywords and d.core_question and d.guiding_questions
        assert all(k == k.lower() for k in d.keywords)  # scorer assumes lowercase


# ---------------------------------------------------------------------------
# IdeonomyModule
# ---------------------------------------------------------------------------


async def test_module_happy_path():
    model = fake_model(
        lens("Light bends", "lens one thoughts"),
        lens("Cycles turn", "lens two thoughts"),
        lens("Forms echo", "lens three thoughts"),
        synthesis(),
    )
    ctx = make_ctx(model)

    artifact = await IdeonomyModule().run(ctx)

    fake = cast(FakeModel, model)
    assert fake.call_count == 4  # 3 lens calls + 1 synthesis
    assert fake.schemas == [_LensSchema, _LensSchema, _LensSchema, _SynthesisSchema]

    expected_themes = [d.theme for d in select_lenses(ctx.task)]
    for prompt, theme in zip(fake.prompts[:3], expected_themes):
        assert f"the {theme} lens" in prompt
        assert ctx.task in prompt
    synthesis_prompt = fake.prompts[3]
    assert "lens one thoughts" in synthesis_prompt
    assert ctx.task in synthesis_prompt

    assert artifact.kind == ModuleKind.CREATIVE
    assert artifact.ideation is not None
    assert artifact.ideation.ideas == ("Call it Prism",)
    assert artifact.ideation.evaluations == ("Prism is evocative but common",)
    assert artifact.ideation.recommended_directions == ("Lean into the light metaphor",)
    assert artifact.plan is None and artifact.verdict is None
    assert "lens two thoughts" in artifact.raw
    assert "Call it Prism" in artifact.raw


async def test_module_lens_count_configurable():
    model = fake_model(lens("Only", "only lens"), synthesis())

    artifact = await IdeonomyModule(lens_count=1).run(make_ctx(model))

    assert cast(FakeModel, model).call_count == 2  # 1 lens + 1 synthesis
    assert artifact.ideation is not None


async def test_module_skips_failed_lens():
    model = fake_model(
        lens("One", "lens one thoughts"),
        RuntimeError("provider hiccup"),
        lens("Three", "lens three thoughts"),
        synthesis(),
    )

    artifact = await IdeonomyModule().run(make_ctx(model))

    assert cast(FakeModel, model).call_count == 4
    assert artifact.ideation is not None
    assert "lens one thoughts" in artifact.raw
    assert "lens three thoughts" in artifact.raw


async def test_module_all_lenses_failed_raises():
    model = fake_model(RuntimeError("a"), RuntimeError("b"), RuntimeError("c"))
    with pytest.raises(ValueError, match="all lens calls failed"):
        await IdeonomyModule().run(make_ctx(model))
    assert cast(FakeModel, model).call_count == 3  # no synthesis attempted


async def test_module_empty_synthesis_ideas_raises():
    model = fake_model(
        lens("a", "t1"),
        lens("b", "t2"),
        lens("c", "t3"),
        _SynthesisSchema(ideas=[], evaluations=[], recommended_directions=[]),
    )
    with pytest.raises(ValueError, match="no ideas"):
        await IdeonomyModule().run(make_ctx(model))


async def test_module_unstructured_synthesis_raises():
    model = fake_model(
        lens("a", "t1"), lens("b", "t2"), lens("c", "t3"), AIMessage("not structured")
    )
    with pytest.raises(ValueError, match="structured synthesis output"):
        await IdeonomyModule().run(make_ctx(model))


# ---------------------------------------------------------------------------
# Subgraph fan-out (ADR-109 §3)
# ---------------------------------------------------------------------------


async def test_fan_out_delivers_every_lens_output_to_synthesis():
    model = fake_model(
        *(lens(f"Headline {i}", f"exploration {i}") for i in range(1, 6)),
        synthesis(),
    )

    artifact = await IdeonomyModule(lens_count=5).run(make_ctx(model))

    fake = cast(FakeModel, model)
    assert fake.call_count == 6  # 5 explore_lens Sends + 1 synthesis
    assert fake.schemas == [_LensSchema] * 5 + [_SynthesisSchema]
    synthesis_prompt = fake.prompts[-1]
    for i in range(1, 6):
        assert f"exploration {i}" in synthesis_prompt
    assert artifact.ideation is not None


class OverlapProbe(FakeModel):
    """FakeModel that yields once per call and records peak in-flight calls.

    The single ``sleep(0)`` lets sibling Send tasks enter before this call
    finishes — a sequential for-loop can never overlap, so ``peak >= 2`` is
    concurrency evidence without timing flakiness.
    """

    def __init__(self, *outputs: object) -> None:
        super().__init__(*outputs)
        self.in_flight = 0
        self.peak = 0

    async def ainvoke(self, messages: list[BaseMessage]) -> object:
        self.in_flight += 1
        self.peak = max(self.peak, self.in_flight)
        await asyncio.sleep(0)
        try:
            return await super().ainvoke(messages)
        finally:
            self.in_flight -= 1


async def test_lens_calls_run_concurrently():
    probe = OverlapProbe(lens("a", "t1"), lens("b", "t2"), lens("c", "t3"), synthesis())

    artifact = await IdeonomyModule().run(make_ctx(cast(BaseChatModel, probe)))

    assert probe.peak >= 2
    assert artifact.ideation is not None
    # All three explorations survive the parallel reduce into synthesis.
    synthesis_prompt = probe.prompts[-1]
    assert all(f"t{i}" in synthesis_prompt for i in (1, 2, 3))


async def test_module_subgraph_run_is_unpersisted():
    """The nested module run must not checkpoint under a parent's saver (ADR-109 §1)."""
    saver = MemorySaver()
    model = fake_model(lens("a", "t1"), lens("b", "t2"), lens("c", "t3"), synthesis())
    ctx = make_ctx(model)

    class _S(TypedDict, total=False):
        done: bool

    async def node(state: _S) -> _S:
        await IdeonomyModule().run(ctx)
        return {"done": True}

    builder: StateGraph[_S, None, _S, _S] = StateGraph(_S)
    builder.add_node("mod", node)
    builder.add_edge(START, "mod")
    builder.add_edge("mod", END)
    graph = builder.compile(checkpointer=saver)
    await graph.ainvoke({}, config={"configurable": {"thread_id": "t"}})

    checkpoints = list(saver.list(None))
    assert checkpoints  # the parent run itself checkpoints...
    # ...but nothing under a namespaced checkpoint_ns (the module subgraph).
    assert all(c.config["configurable"]["checkpoint_ns"] == "" for c in checkpoints)


# ---------------------------------------------------------------------------
# Status events (Tier 1 progress + Tier 2 insight snapshots, ADR-106).
# Events ride the custom stream (ADR-110), so the module runs inside a
# minimal streamed parent graph here.
# ---------------------------------------------------------------------------


async def test_module_emits_phase_and_insight_events():
    model = fake_model(
        lens("Light bends", "lens one thoughts"),
        lens("Cycles turn", "lens two thoughts"),
        lens("Forms echo", "lens three thoughts"),
        synthesis(),
    )
    ctx = make_ctx(model)

    _, events = await run_streamed(lambda: IdeonomyModule().run(ctx))

    kinds = [str(e.kind) for e in events]
    # lenses_selected, then per lens: phase(lens) + insight, then synthesis.
    assert kinds == [
        "module.phase",   # lenses_selected
        "module.phase",   # lens 1
        "module.insight",
        "module.phase",   # lens 2
        "module.insight",
        "module.phase",   # lens 3
        "module.insight",
        "module.phase",   # synthesis
    ]

    selected = events[0]
    assert selected.payload["phase"] == "lenses_selected"
    assert selected.payload["total"] == 3
    assert selected.node == "creative"
    assert selected.payload["module"] == "ideonomy"

    lens_phase = events[1]
    assert lens_phase.payload["phase"] == "lens"
    assert lens_phase.payload["index"] == 1

    insights = [e for e in events if e.kind is StatusEventKind.MODULE_INSIGHT]
    assert [e.payload["headline"] for e in insights] == [
        "Light bends",
        "Cycles turn",
        "Forms echo",
    ]
    # insight labels are the selected lens themes, in order
    assert [e.payload["label"] for e in insights] == [
        d.theme for d in select_lenses(ctx.task)
    ]


async def test_module_no_insight_for_failed_lens():
    model = fake_model(
        lens("One", "lens one thoughts"),
        RuntimeError("provider hiccup"),
        lens("Three", "lens three thoughts"),
        synthesis(),
    )
    ctx = make_ctx(model)

    _, events = await run_streamed(lambda: IdeonomyModule().run(ctx))

    insights = [e for e in events if e.kind is StatusEventKind.MODULE_INSIGHT]
    # 3 lens phases attempted, but the failed one emits no insight
    assert [e.payload["headline"] for e in insights] == ["One", "Three"]
    # synthesis phase reports the count of SUCCESSFUL lenses
    synth = [
        e for e in events
        if e.kind is StatusEventKind.MODULE_PHASE and e.payload["phase"] == "synthesis"
    ]
    assert synth[0].payload["total"] == 2
