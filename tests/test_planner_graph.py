"""Tests for the planner harness graph (ADR-101): routing, plan loop, events.

All model calls use fakes; the react subgraph is a tiny real compiled
StateGraph injected via build_planner_graph's react_graph parameter.
"""

from pathlib import Path
from typing import Annotated, Any, TypedDict, cast

import aiosqlite
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from openpaw.agent.harness.modules.base import ModuleKind, ReasoningContext, ReasoningModule, WorkspaceInfo
from openpaw.agent.harness.modules.direct import DirectPlanner, _PlanSchema
from openpaw.agent.harness.modules.reflection import FullReflection, LightReflection, _VerdictSchema
from openpaw.agent.harness.planner.graph import (
    PlannerNodeModels,
    TriageDecision,
    build_planner_graph,
)
from openpaw.agent.harness.planner.prompts import FALLBACK_STEP_DESCRIPTION
from openpaw.agent.harness.planner.state import (
    PlannerRunContext,
    PlannerState,
    plan_from_state,
    plan_to_state,
)
from openpaw.core.config.models import HarnessConfig
from openpaw.model.plan import Plan, PlanStep, StepStatus
from openpaw.model.status_event import StatusEvent

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class CaptureEmitter:
    """In-memory StatusEmitter for event assertions."""

    def __init__(self) -> None:
        self.events: list[StatusEvent] = []

    async def emit(self, event: StatusEvent) -> None:
        self.events.append(event)

    def kinds(self) -> list[str]:
        return [str(e.kind) for e in self.events]


class FakeModel:
    """Fake chat model for both structured and plain calls.

    Outputs are returned in order; an Exception instance is raised instead.
    A fake constructed with no outputs fails loudly if invoked at all.
    """

    def __init__(self, *outputs: object) -> None:
        self._outputs = list(outputs)
        self.prompts: list[str] = []

    def with_structured_output(self, schema: type) -> "FakeModel":
        return self

    async def ainvoke(self, messages: list[Any]) -> object:
        self.prompts.append("\n".join(str(m.content) for m in messages))
        if not self._outputs:
            raise AssertionError("FakeModel invoked with no queued outputs")
        output = self._outputs.pop(0)
        if isinstance(output, Exception):
            raise output
        return output

    @property
    def call_count(self) -> int:
        return len(self.prompts)


def fake(*outputs: object) -> BaseChatModel:
    return cast(BaseChatModel, FakeModel(*outputs))


class _ReactState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]


def make_fake_react(replies: list[str], calls: list[str], checkpointer: Any | None = None) -> Any:
    """A real compiled one-node graph standing in for the create_agent graph."""
    counter = {"i": 0}

    def model_node(state: _ReactState) -> dict[str, Any]:
        calls.append(str(state["messages"][-1].content))
        i = min(counter["i"], len(replies) - 1)
        counter["i"] += 1
        return {"messages": [AIMessage(content=replies[i])]}

    builder = StateGraph(_ReactState)
    builder.add_node("model", model_node)
    builder.add_edge(START, "model")
    builder.add_edge("model", END)
    return builder.compile(checkpointer=checkpointer)


class FailingModule:
    """A planning module that always blows up (fallback-chain tests)."""

    name = "direct"
    kind = ModuleKind.PLANNING
    tagline = "always fails"

    async def run(self, ctx: ReasoningContext) -> Any:
        raise RuntimeError("module exploded")


def default_candidates() -> dict[ModuleKind, dict[str, ReasoningModule]]:
    return {
        ModuleKind.PLANNING: {"direct": DirectPlanner()},
        ModuleKind.CREATIVE: {},
        ModuleKind.REFLECTION: {"light": LightReflection(), "full": FullReflection()},
    }


def build(
    *,
    triage: list[object] | None = None,
    planning: list[object] | None = None,
    reflection: list[object] | None = None,
    synthesize: list[object] | None = None,
    react: Any = None,
    harness_config: HarnessConfig | None = None,
    candidates: dict[ModuleKind, dict[str, ReasoningModule]] | None = None,
    emitter: CaptureEmitter | None = None,
    checkpointer: Any | None = None,
    run_context: PlannerRunContext | None = None,
) -> Any:
    """Assemble a planner graph with fake models everywhere."""
    node_models = PlannerNodeModels(
        triage=fake(*(triage or [])),
        planning=fake(*(planning or [])),
        creative=fake(),
        reflection=fake(*(reflection or [])),
        selector=fake(),
        synthesize=fake(*(synthesize or [AIMessage(content="final answer")])),
    )
    return build_planner_graph(
        react_graph=react if react is not None else make_fake_react(["react reply"], []),
        node_models=node_models,
        harness_config=harness_config or HarnessConfig(type="planner"),
        candidates=candidates or default_candidates(),
        emitter=emitter or CaptureEmitter(),
        workspace_info=WorkspaceInfo(name="testws", timezone="UTC", workspace_path=Path("/tmp/ws")),
        tools_summary=[],
        run_context=run_context or PlannerRunContext(),
        checkpointer=checkpointer,
        inner_recursion_limit=20,
    )


def plan_decision(objective: str = "do the thing") -> TriageDecision:
    return TriageDecision(route="plan", objective=objective, reason="multi-step")


def advance(succeeded: bool = True) -> _VerdictSchema:
    return _VerdictSchema(action="advance", step_succeeded=succeeded)


# ---------------------------------------------------------------------------
# State serialization
# ---------------------------------------------------------------------------


async def test_planner_state_round_trips_through_sqlite_checkpointer(tmp_path: Path) -> None:
    """Plan state survives a real AsyncSqliteSaver checkpoint round-trip."""
    plan = Plan(
        objective="obj",
        steps=(
            PlanStep(id="1", description="a", status=StepStatus.DONE, result_summary="did a"),
            PlanStep(id="2", description="b"),
        ),
        revision=1,
    )

    def seed(state: PlannerState) -> dict[str, Any]:
        return {
            "messages": [AIMessage(content="ok")],
            "plan": plan_to_state(plan),
            "current_step_id": "2",
            "step_results": ["did a"],
        }

    builder = StateGraph(PlannerState)
    builder.add_node("seed", seed)
    builder.add_edge(START, "seed")
    builder.add_edge("seed", END)

    conn = await aiosqlite.connect(str(tmp_path / "ckpt.db"))
    try:
        saver = AsyncSqliteSaver(conn)
        await saver.setup()
        graph = builder.compile(checkpointer=saver)
        config = {"configurable": {"thread_id": "t1"}}
        await graph.ainvoke({"messages": [HumanMessage("hi")]}, config=config)

        state = await graph.aget_state(config)
        restored = plan_from_state(cast(PlannerState, state.values))
        assert restored == plan
        assert isinstance(restored.steps, tuple)  # tuple survives (payload form)
        assert restored.steps[0].status is StepStatus.DONE
        assert restored.steps[0].result_summary == "did a"
        assert state.values["step_results"] == ["did a"]
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# Triage routing
# ---------------------------------------------------------------------------


async def test_triage_react_route_runs_react_node() -> None:
    calls: list[str] = []
    react = make_fake_react(["hi there"], calls)
    graph = build(
        triage=[TriageDecision(route="react", objective="greet", reason="simple")],
        react=react,
    )
    result = await graph.ainvoke({"messages": [HumanMessage("hello")]})
    assert result["messages"][-1].content == "hi there"
    assert calls == ["hello"]  # shared messages key — the original batch


async def test_triage_failure_falls_back_to_react() -> None:
    calls: list[str] = []
    graph = build(triage=[RuntimeError("triage model down")], react=make_fake_react(["fallback reply"], calls))
    result = await graph.ainvoke({"messages": [HumanMessage("hello")]})
    assert result["messages"][-1].content == "fallback reply"
    assert result["route"] == "react"


async def test_system_batch_routes_react_without_llm_call() -> None:
    calls: list[str] = []
    emitter = CaptureEmitter()
    graph = build(react=make_fake_react(["noted"], calls), emitter=emitter)
    result = await graph.ainvoke({"messages": [HumanMessage("[SYSTEM] cron result: ok")]})
    assert result["messages"][-1].content == "noted"
    assert result["route"] == "react"
    # The short-circuit (not the fail-open fallback) handled it — no LLM call.
    triage_events = [e for e in emitter.events if e.node == "triage"]
    assert triage_events[0].payload["reason"] == "system batch"


# ---------------------------------------------------------------------------
# Plan loop
# ---------------------------------------------------------------------------


async def test_two_step_plan_executes_and_synthesizes() -> None:
    calls: list[str] = []
    emitter = CaptureEmitter()
    graph = build(
        triage=[plan_decision()],
        planning=[_PlanSchema(steps=["step one", "step two"])],
        reflection=[advance(), advance()],
        synthesize=[AIMessage(content="all done")],
        react=make_fake_react(["did step one", "did step two"], calls),
        emitter=emitter,
    )
    result = await graph.ainvoke({"messages": [HumanMessage("do it")]})

    assert result["messages"][-1].content == "all done"
    assert result["step_results"] == ["did step one", "did step two"]
    assert len(calls) == 2
    assert "Execute step 1: step one" in calls[0]
    assert "Execute step 2: step two" in calls[1]

    final_plan = plan_from_state(cast(PlannerState, result))
    assert final_plan is not None
    assert all(s.status is StepStatus.DONE for s in final_plan.steps)
    assert final_plan.steps[0].result_summary == "did step one"

    # Event sequence for the happy path (H7.2 vocabulary).
    plan_kinds = [k for k in emitter.kinds() if k not in ("module.selected", "node.completed")]
    assert plan_kinds == [
        "node.entered",  # triage entry ("Thinking...")
        "node.entered",  # triage decision (route announcement)
        "node.entered",  # plan
        "plan.created",
        "plan.step_started",
        "plan.step_completed",
        "node.entered",  # reflect
        "reflection.verdict",
        "plan.step_started",
        "plan.step_completed",
        "node.entered",  # reflect
        "reflection.verdict",
        "node.entered",  # synthesize
    ]
    # Triage entry has no route; the decision event carries it (renderer keys
    # "Thinking..." vs the routing announcement off this distinction).
    triage_events = [e for e in emitter.events if e.node == "triage"]
    assert "route" not in triage_events[0].payload
    assert triage_events[1].payload["route"] == "plan"
    # Verdict payload carries step_succeeded for the failed-advance narration.
    verdicts = [e for e in emitter.events if str(e.kind) == "reflection.verdict"]
    assert all(e.payload["step_succeeded"] is True for e in verdicts)
    # module.selected rides the custom stream (ADR-110) and never reaches the
    # injected emitter under ainvoke — end-to-end coverage lives in
    # tests/test_harness_parity.py and tests/test_module_selector.py.
    assert "module.selected" not in emitter.kinds()


async def test_reflection_insert_step_executes_inserted_step() -> None:
    calls: list[str] = []
    graph = build(
        triage=[plan_decision()],
        planning=[_PlanSchema(steps=["step one", "step two"])],
        reflection=[
            _VerdictSchema(action="insert_step", step_succeeded=False, insert_description="fix auth"),
            advance(),
            advance(),
        ],
        react=make_fake_react(["r1", "r1a", "r2"], calls),
    )
    result = await graph.ainvoke({"messages": [HumanMessage("do it")]})

    assert len(calls) == 3
    assert "Execute step 1A: fix auth" in calls[1]
    final_plan = plan_from_state(cast(PlannerState, result))
    assert final_plan is not None
    assert [s.id for s in final_plan.steps] == ["1", "1A", "2"]
    assert final_plan.steps[0].status is StepStatus.FAILED  # step_succeeded=False
    assert final_plan.revision == 1


async def test_reflection_abort_to_user_short_circuits_to_synthesize() -> None:
    calls: list[str] = []
    graph = build(
        triage=[plan_decision()],
        planning=[_PlanSchema(steps=["step one", "step two"])],
        reflection=[_VerdictSchema(action="abort_to_user", step_succeeded=False, notes="need credentials")],
        synthesize=[AIMessage(content="stopped: need credentials")],
        react=make_fake_react(["r1"], calls),
    )
    result = await graph.ainvoke({"messages": [HumanMessage("do it")]})

    assert len(calls) == 1  # step two never executed
    assert result["abort_reason"] == "need credentials"
    assert result["messages"][-1].content == "stopped: need credentials"


async def test_max_steps_budget_caps_the_loop() -> None:
    calls: list[str] = []
    config = HarnessConfig.model_validate({"type": "planner", "execution": {"max_steps": 1}})
    graph = build(
        triage=[plan_decision()],
        planning=[_PlanSchema(steps=["one", "two", "three"])],
        reflection=[advance()],
        react=make_fake_react(["r1"], calls),
        harness_config=config,
    )
    result = await graph.ainvoke({"messages": [HumanMessage("do it")]})
    assert len(calls) == 1
    assert result["messages"][-1].content == "final answer"


async def test_reflection_off_omits_reflect_node_and_still_loops() -> None:
    calls: list[str] = []
    reflection_model = FakeModel()  # would raise if invoked
    config = HarnessConfig.model_validate({"type": "planner", "reflection": {"module": "off"}})
    graph = build_planner_graph(
        react_graph=make_fake_react(["r1", "r2"], calls),
        node_models=PlannerNodeModels(
            triage=fake(plan_decision()),
            planning=fake(_PlanSchema(steps=["one", "two"])),
            creative=fake(),
            reflection=cast(BaseChatModel, reflection_model),
            selector=fake(),
            synthesize=fake(AIMessage(content="done")),
        ),
        harness_config=config,
        candidates=default_candidates(),
        emitter=CaptureEmitter(),
        workspace_info=WorkspaceInfo(name="testws", timezone="UTC", workspace_path=Path("/tmp/ws")),
        tools_summary=[],
        run_context=PlannerRunContext(),
        checkpointer=None,
        inner_recursion_limit=20,
    )
    assert "reflect" not in graph.nodes
    result = await graph.ainvoke({"messages": [HumanMessage("do it")]})
    assert len(calls) == 2
    assert reflection_model.call_count == 0
    final_plan = plan_from_state(cast(PlannerState, result))
    assert final_plan is not None
    assert all(s.status is StepStatus.DONE for s in final_plan.steps)


# ---------------------------------------------------------------------------
# Resume marker (approval re-run path)
# ---------------------------------------------------------------------------


async def test_resume_marker_routes_triage_directly_to_execute_step() -> None:
    calls: list[str] = []
    triage_model = FakeModel()  # must NOT be called on the resume path
    saver = MemorySaver()
    graph = build_planner_graph(
        react_graph=make_fake_react(["resumed step done"], calls),
        node_models=PlannerNodeModels(
            triage=cast(BaseChatModel, triage_model),
            planning=fake(),
            creative=fake(),
            reflection=fake(advance()),
            selector=fake(),
            synthesize=fake(AIMessage(content="wrapped up")),
        ),
        harness_config=HarnessConfig(type="planner"),
        candidates=default_candidates(),
        emitter=CaptureEmitter(),
        workspace_info=WorkspaceInfo(name="testws", timezone="UTC", workspace_path=Path("/tmp/ws")),
        tools_summary=[],
        run_context=PlannerRunContext(),
        checkpointer=saver,
        inner_recursion_limit=20,
    )
    config = {"configurable": {"thread_id": "telegram:1:conv1"}}
    paused_plan = Plan(
        objective="obj",
        steps=(
            PlanStep(id="1", description="a", status=StepStatus.DONE),
            PlanStep(id="2", description="b"),
        ),
    )
    await graph.aupdate_state(
        config,
        {
            "plan": plan_to_state(paused_plan),
            "objective": "obj",
            "resume_step_id": "2",
            "step_results": ["did a"],
        },
        as_node="plan",
    )

    result = await graph.ainvoke({"messages": [HumanMessage("approved, go ahead")]}, config=config)

    assert triage_model.call_count == 0  # resume path skips the triage LLM
    assert len(calls) == 1
    assert "Execute step 2: b" in calls[0]
    assert result["resume_step_id"] is None  # execute_step cleared the marker
    assert result["messages"][-1].content == "wrapped up"


# ---------------------------------------------------------------------------
# Fallback chain
# ---------------------------------------------------------------------------


async def test_module_failure_falls_back_to_direct_then_synthetic_plan() -> None:
    calls: list[str] = []
    candidates = default_candidates()
    candidates[ModuleKind.PLANNING] = {"direct": cast(ReasoningModule, FailingModule())}
    graph = build(
        triage=[plan_decision()],
        # DirectPlanner fallback consumes this and fails too -> synthetic plan.
        planning=[RuntimeError("planning model down")],
        reflection=[advance()],
        react=make_fake_react(["done directly"], calls),
        candidates=candidates,
    )
    result = await graph.ainvoke({"messages": [HumanMessage("do it")]})

    final_plan = plan_from_state(cast(PlannerState, result))
    assert final_plan is not None
    assert [s.description for s in final_plan.steps] == [FALLBACK_STEP_DESCRIPTION]
    assert len(calls) == 1
    assert FALLBACK_STEP_DESCRIPTION in calls[0]


async def test_module_failure_recovers_via_direct_planner() -> None:
    calls: list[str] = []
    candidates = default_candidates()
    candidates[ModuleKind.PLANNING] = {"direct": cast(ReasoningModule, FailingModule())}
    graph = build(
        triage=[plan_decision()],
        planning=[_PlanSchema(steps=["recovered step"])],  # DirectPlanner fallback succeeds
        reflection=[advance()],
        react=make_fake_react(["ok"], calls),
        candidates=candidates,
    )
    result = await graph.ainvoke({"messages": [HumanMessage("do it")]})
    final_plan = plan_from_state(cast(PlannerState, result))
    assert final_plan is not None
    assert [s.description for s in final_plan.steps] == ["recovered step"]


# ---------------------------------------------------------------------------
# Step-scoped inner runs are unpersisted
# ---------------------------------------------------------------------------


async def test_execute_step_inner_run_is_unpersisted() -> None:
    """The step invocation disables checkpointing on the shared react graph."""
    calls: list[str] = []
    inner_saver = MemorySaver()
    react = make_fake_react(["r1"], calls, checkpointer=inner_saver)
    graph = build(
        triage=[plan_decision()],
        planning=[_PlanSchema(steps=["one"])],
        reflection=[advance()],
        react=react,
    )
    await graph.ainvoke({"messages": [HumanMessage("do it")]})
    assert len(calls) == 1
    assert list(inner_saver.list(None)) == []  # no checkpoints written by the step run
