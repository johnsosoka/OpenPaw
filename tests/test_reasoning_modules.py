"""Tests for the reasoning modules: DirectPlanner, LightReflection, FullReflection (ADR-102)."""

from pathlib import Path
from typing import cast

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage

from openpaw.agent.harness.modules.base import (
    ModuleKind,
    ReasoningContext,
    ToolSummary,
    WorkspaceInfo,
)
from openpaw.agent.harness.modules.direct import DirectPlanner, _PlanSchema
from openpaw.agent.harness.modules.reflection import (
    FullReflection,
    LightReflection,
    _RemainingStepsSchema,
    _VerdictSchema,
)
from openpaw.model.plan import IdeationResult, Plan, PlanStep, StepStatus
from openpaw.model.status_event import StatusEvent


class CaptureEmitter:
    """In-memory StatusEmitter for assertions."""

    def __init__(self) -> None:
        self.events: list[StatusEvent] = []

    async def emit(self, event: StatusEvent) -> None:
        self.events.append(event)


class FakeStructuredModel:
    """Fake chat model: with_structured_output(...).ainvoke returns canned outputs in order.

    An output that is an Exception instance is raised instead of returned.
    """

    def __init__(self, *outputs: object) -> None:
        self._outputs = list(outputs)
        self.prompts: list[str] = []
        self.schemas: list[type] = []

    def with_structured_output(self, schema: type) -> "FakeStructuredModel":
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
    return cast(BaseChatModel, FakeStructuredModel(*outputs))


def make_ctx(model: BaseChatModel, **overrides: object) -> ReasoningContext:
    defaults: dict[str, object] = {
        "task": "Ship the quarterly report",
        "conversation_digest": "User asked for the quarterly report by Friday.",
        "tools_summary": [ToolSummary(name="web_search", description="Search the web")],
        "model": model,
        "emit": CaptureEmitter(),
        "workspace": WorkspaceInfo(name="testws", timezone="UTC", workspace_path=Path("/tmp/ws")),
    }
    defaults.update(overrides)
    return ReasoningContext(**defaults)  # type: ignore[arg-type]


def two_step_plan() -> Plan:
    return Plan(
        objective="Ship the quarterly report",
        steps=(
            PlanStep(id="1", description="Gather data", status=StepStatus.DONE),
            PlanStep(id="2", description="Write report"),
        ),
    )


# ---------------------------------------------------------------------------
# DirectPlanner
# ---------------------------------------------------------------------------


async def test_direct_planner_happy_path():
    model = fake_model(_PlanSchema(steps=["Gather data", "Write report"]))
    ctx = make_ctx(model)

    artifact = await DirectPlanner().run(ctx)

    assert artifact.kind == ModuleKind.PLANNING
    assert artifact.plan is not None
    assert artifact.plan.objective == ctx.task
    assert [s.id for s in artifact.plan.steps] == ["1", "2"]
    assert [s.description for s in artifact.plan.steps] == ["Gather data", "Write report"]
    assert all(s.status == StepStatus.PENDING for s in artifact.plan.steps)
    assert artifact.verdict is None and artifact.ideation is None
    assert "Gather data" in artifact.raw

    fake = cast(FakeStructuredModel, model)
    assert fake.call_count == 1
    prompt = fake.prompts[0]
    assert ctx.task in prompt
    assert ctx.conversation_digest in prompt
    assert "- web_search: Search the web" in prompt
    assert "Creative directions" not in prompt


async def test_direct_planner_includes_ideation_block():
    model = fake_model(_PlanSchema(steps=["Do it"]))
    ideation = IdeationResult(ideas=("idea",), recommended_directions=("Lean into visuals", "Keep it short"))
    ctx = make_ctx(model, ideation=ideation)

    await DirectPlanner().run(ctx)

    prompt = cast(FakeStructuredModel, model).prompts[0]
    assert "Creative directions to consider:" in prompt
    assert "- Lean into visuals" in prompt
    assert "- Keep it short" in prompt


async def test_direct_planner_empty_steps_raises():
    model = fake_model(_PlanSchema(steps=[]))
    with pytest.raises(ValueError, match="empty plan"):
        await DirectPlanner().run(make_ctx(model))


# ---------------------------------------------------------------------------
# LightReflection
# ---------------------------------------------------------------------------


async def test_light_reflection_advance_verdict():
    schema = _VerdictSchema(action="advance", step_succeeded=True, notes="looks good")
    model = fake_model(schema)
    ctx = make_ctx(model, plan=two_step_plan(), current_step_id="2", last_step_result="report written")

    artifact = await LightReflection().run(ctx)

    assert artifact.kind == ModuleKind.REFLECTION
    assert artifact.plan is None
    assert artifact.verdict is not None
    assert artifact.verdict.action == "advance"
    assert artifact.verdict.step_succeeded is True
    assert artifact.verdict.notes == "looks good"

    prompt = cast(FakeStructuredModel, model).prompts[0]
    assert "[x] 1. Gather data" in prompt  # checklist included
    assert "report written" in prompt
    assert "Step 2" in prompt


async def test_light_reflection_coerces_revise_plan_to_advance():
    schema = _VerdictSchema(action="revise_plan", step_succeeded=False, notes="plan is stale")
    model = fake_model(schema)
    ctx = make_ctx(model, plan=two_step_plan(), current_step_id="2", last_step_result="failed")

    artifact = await LightReflection().run(ctx)

    assert artifact.verdict is not None
    assert artifact.verdict.action == "advance"  # light never rewrites the plan
    assert artifact.plan is None
    assert "never rewrites the plan" in artifact.verdict.notes
    assert "plan is stale" in artifact.verdict.notes
    assert artifact.verdict.step_succeeded is False
    assert cast(FakeStructuredModel, model).call_count == 1


async def test_light_reflection_passes_insert_step_through():
    schema = _VerdictSchema(action="insert_step", step_succeeded=False, insert_description="Retry with auth")
    model = fake_model(schema)
    ctx = make_ctx(model, plan=two_step_plan(), current_step_id="2", last_step_result="401 error")

    artifact = await LightReflection().run(ctx)

    assert artifact.verdict is not None
    assert artifact.verdict.action == "insert_step"
    assert artifact.verdict.insert_description == "Retry with auth"


async def test_light_reflection_requires_plan_and_step():
    with pytest.raises(ValueError, match="require ctx.plan"):
        await LightReflection().run(make_ctx(fake_model()))


# ---------------------------------------------------------------------------
# FullReflection
# ---------------------------------------------------------------------------


async def test_full_reflection_advance_is_single_call():
    schema = _VerdictSchema(action="advance", step_succeeded=True, notes="fine")
    model = fake_model(schema)
    ctx = make_ctx(model, plan=two_step_plan(), current_step_id="2", last_step_result="done")

    artifact = await FullReflection().run(ctx)

    assert artifact.verdict is not None
    assert artifact.verdict.action == "advance"
    assert artifact.plan is None
    assert cast(FakeStructuredModel, model).call_count == 1


async def test_full_reflection_revise_path_returns_remaining_steps_plan():
    plan = Plan(
        objective="Ship the quarterly report",
        steps=(
            PlanStep(id="1", description="Gather data", status=StepStatus.DONE),
            PlanStep(id="2", description="Write report", status=StepStatus.DONE),
            PlanStep(id="3", description="Email draft"),
            PlanStep(id="4", description="Publish"),
        ),
    )
    verdict = _VerdictSchema(action="revise_plan", step_succeeded=True, notes="remaining steps stale")
    rewrite = _RemainingStepsSchema(steps=["Review with legal", "Publish to portal"])
    model = fake_model(verdict, rewrite)
    ctx = make_ctx(model, plan=plan, current_step_id="2", last_step_result="report needs legal review")

    artifact = await FullReflection().run(ctx)

    fake = cast(FakeStructuredModel, model)
    assert fake.call_count == 2
    assert fake.schemas == [_VerdictSchema, _RemainingStepsSchema]
    assert "[x] 2. Write report" in fake.prompts[1]  # checklist in rewrite prompt too

    assert artifact.verdict is not None and artifact.verdict.action == "revise_plan"
    assert artifact.plan is not None
    assert artifact.plan.objective == plan.objective
    # Only the new remaining steps, ids continuing after the executed ordinals.
    assert [s.id for s in artifact.plan.steps] == ["3", "4"]
    assert [s.description for s in artifact.plan.steps] == ["Review with legal", "Publish to portal"]

    # The reflect node applies the tail via with_remaining_replaced.
    applied = plan.with_remaining_replaced(artifact.plan.steps)
    assert [s.description for s in applied.steps] == [
        "Gather data",
        "Write report",
        "Review with legal",
        "Publish to portal",
    ]


async def test_full_reflection_id_continuation_counts_current_step():
    # Current step not yet flipped from PENDING by the graph — ids must still
    # continue past it.
    plan = Plan(
        objective="obj",
        steps=(
            PlanStep(id="1", description="a", status=StepStatus.DONE),
            PlanStep(id="2", description="b"),  # current, still PENDING
            PlanStep(id="3", description="c"),
        ),
    )
    model = fake_model(
        _VerdictSchema(action="revise_plan", step_succeeded=True),
        _RemainingStepsSchema(steps=["new"]),
    )
    ctx = make_ctx(model, plan=plan, current_step_id="2", last_step_result="ran")

    artifact = await FullReflection().run(ctx)

    assert artifact.plan is not None
    assert [s.id for s in artifact.plan.steps] == ["3"]


async def test_full_reflection_empty_rewrite_coerces_to_advance():
    model = fake_model(
        _VerdictSchema(action="revise_plan", step_succeeded=True, notes="hm"),
        _RemainingStepsSchema(steps=[]),
    )
    ctx = make_ctx(model, plan=two_step_plan(), current_step_id="2", last_step_result="done")

    artifact = await FullReflection().run(ctx)

    assert artifact.plan is None
    assert artifact.verdict is not None
    assert artifact.verdict.action == "advance"
    assert "no steps" in artifact.verdict.notes


class TestModuleEntrypointContract:
    """Every module declares the ReasoningModule interface explicitly and is
    constructible through the uniform build() entrypoint (John's review)."""

    def test_all_registry_entries_subclass_the_interface(self):
        from openpaw.agent.harness.modules.base import ReasoningModule
        from openpaw.agent.harness.modules.registry import MODULE_REGISTRY

        for name, cls in MODULE_REGISTRY.items():
            assert issubclass(cls, ReasoningModule), name

    def test_run_is_abstract(self):
        from openpaw.agent.harness.modules.base import ModuleKind, ReasoningModule

        class Incomplete(ReasoningModule):
            name = "incomplete"
            kind = ModuleKind.PLANNING
            tagline = "missing run()"

        with pytest.raises(TypeError):
            Incomplete()  # type: ignore[abstract]

    def test_uniform_build_constructs_every_module(self, tmp_path):
        from openpaw.agent.harness.modules.base import WorkspaceInfo
        from openpaw.agent.harness.modules.registry import MODULE_REGISTRY

        info = WorkspaceInfo(name="t", timezone="UTC", workspace_path=tmp_path)
        for name, cls in MODULE_REGISTRY.items():
            instance = cls.build(info)
            assert instance.name == name

    def test_self_discover_build_wires_workspace_cache(self, tmp_path):
        from openpaw.agent.harness.modules.base import WorkspaceInfo
        from openpaw.agent.harness.modules.self_discover import SelfDiscoverPlanner

        info = WorkspaceInfo(name="t", timezone="UTC", workspace_path=tmp_path)
        planner = SelfDiscoverPlanner.build(info)
        planner._cache.put("k", {"structure_text": "x"})
        assert (tmp_path / "data" / "reasoning_structures.json").exists()
