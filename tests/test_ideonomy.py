"""Tests for the IdeonomyModule creative reasoning module (ADR-102 §3)."""

from pathlib import Path
from typing import cast

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage

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
from openpaw.model.status_event import StatusEvent, StatusEventKind

NAMING_TASK = (
    "What should we name this concept? Find a metaphor or analogy "
    "that captures its meaning and essence."
)


class CaptureEmitter:
    """In-memory StatusEmitter for assertions."""

    def __init__(self) -> None:
        self.events: list[StatusEvent] = []

    async def emit(self, event: StatusEvent) -> None:
        self.events.append(event)


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
        emit=CaptureEmitter(),
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
# Status events (Tier 1 progress + Tier 2 insight snapshots, ADR-106)
# ---------------------------------------------------------------------------


async def test_module_emits_phase_and_insight_events():
    model = fake_model(
        lens("Light bends", "lens one thoughts"),
        lens("Cycles turn", "lens two thoughts"),
        lens("Forms echo", "lens three thoughts"),
        synthesis(),
    )
    ctx = make_ctx(model)

    await IdeonomyModule().run(ctx)

    events = cast(CaptureEmitter, ctx.emit).events
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

    await IdeonomyModule().run(ctx)

    insights = [
        e for e in cast(CaptureEmitter, ctx.emit).events
        if e.kind is StatusEventKind.MODULE_INSIGHT
    ]
    # 3 lens phases attempted, but the failed one emits no insight
    assert [e.payload["headline"] for e in insights] == ["One", "Three"]
    # synthesis phase reports the count of SUCCESSFUL lenses
    synth = [
        e for e in cast(CaptureEmitter, ctx.emit).events
        if e.kind is StatusEventKind.MODULE_PHASE and e.payload["phase"] == "synthesis"
    ]
    assert synth[0].payload["total"] == 2
