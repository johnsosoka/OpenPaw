"""Tests for tool equipping (ADR-104, PRD-002 H5): catalog, floor, equip node,
step-executor subsetting, and the request_tools recovery loop.

Graph-level tests reuse the fakes from test_ultra_graph; the step executor
is a recording fake so factory calls (the subset contract) are observable.
"""

import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from openpaw.agent.harness.modules.base import ModuleKind, ReasoningModule, WorkspaceInfo
from openpaw.agent.harness.modules.direct import _PlanSchema
from openpaw.agent.harness.ultra.equipment import (
    REQUEST_TOOLS_NAME,
    EquipDecision,
    EquipmentContext,
    ToolCatalogEntry,
    build_tool_catalog,
    create_request_tools_tool,
    detect_tool_request,
    resolve_equip_floor,
)
from openpaw.agent.harness.ultra.graph import UltraNodeModels, build_ultra_graph
from openpaw.agent.harness.ultra.state import UltraRunContext, UltraState, plan_from_state
from openpaw.core.config.models import HarnessConfig
from openpaw.model.plan import StepStatus
from tests.test_ultra_graph import (
    CaptureEmitter,
    FakeModel,
    advance,
    default_candidates,
    fake,
    make_fake_react,
    plan_decision,
)

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


def fake_tool(name: str, description: str = "") -> Any:
    return SimpleNamespace(name=name, description=description)


class FakeExecutor:
    """Stands in for a step-scoped compiled agent graph."""

    def __init__(self, results: list[list[Any]]) -> None:
        self._results = results
        self.prompts: list[str] = []

    async def ainvoke(self, payload: dict[str, Any], config: Any = None) -> dict[str, Any]:
        self.prompts.append(str(payload["messages"][-1].content))
        i = min(len(self.prompts) - 1, len(self._results) - 1)
        return {"messages": list(self._results[i])}


class RecordingFactory:
    """step_executor_factory fake: records the equipped-name lists it saw."""

    def __init__(self, executor: Any) -> None:
        self.executor = executor
        self.calls: list[list[str] | None] = []

    def __call__(self, tool_names: list[str] | None) -> Any:
        self.calls.append(tool_names)
        return self.executor


def request_tools_message(needed: str) -> AIMessage:
    return AIMessage(
        content="I need more tools",
        tool_calls=[{"name": REQUEST_TOOLS_NAME, "args": {"tools_needed": needed}, "id": "tc1"}],
    )


def make_equipment(
    *equip_outputs: object,
    catalog_names: tuple[str, ...] = ("alpha", "beta", "gamma"),
    floor: frozenset[str] = frozenset(),
    max_tools: int = 25,
) -> EquipmentContext:
    return EquipmentContext(
        catalog=[
            ToolCatalogEntry(name=n, description=f"{n} does things", group=None, source="workspace")
            for n in catalog_names
        ],
        floor=floor,
        model=fake(*equip_outputs),
        max_tools=max_tools,
    )


def build_graph(
    *,
    triage: list[object] | None = None,
    planning: list[object] | None = None,
    reflection: list[object] | None = None,
    synthesize: list[object] | None = None,
    react: Any = None,
    emitter: CaptureEmitter | None = None,
    equipment: EquipmentContext | None = None,
    step_executor_factory: Any = None,
    candidates: dict[ModuleKind, dict[str, ReasoningModule]] | None = None,
) -> Any:
    node_models = UltraNodeModels(
        triage=fake(*(triage or [])),
        planning=fake(*(planning or [])),
        creative=fake(),
        reflection=fake(*(reflection or [])),
        selector=fake(),
        synthesize=fake(*(synthesize or [AIMessage(content="final answer")])),
    )
    return build_ultra_graph(
        react_graph=react if react is not None else make_fake_react(["react reply"], []),
        node_models=node_models,
        harness_config=HarnessConfig(type="ultra"),
        candidates=candidates or default_candidates(),
        emitter=emitter or CaptureEmitter(),
        workspace_info=WorkspaceInfo(name="testws", timezone="UTC", workspace_path=Path("/tmp/ws")),
        tools_summary=[],
        run_context=UltraRunContext(),
        checkpointer=None,
        inner_recursion_limit=20,
        equipment=equipment,
        step_executor_factory=step_executor_factory,
    )


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------


def test_catalog_takes_first_sentence_and_attributes_group_and_source() -> None:
    tools = [
        fake_tool("send_message", "Send a message to the user. Supports markdown.\nMore detail."),
        fake_tool("my_custom", "Frobnicate the workspace widgets"),
    ]
    catalog = build_tool_catalog(tools)

    by_name = {e.name: e for e in catalog}
    assert by_name["send_message"].description == "Send a message to the user"
    # send_message is registered builtin metadata (group: communication).
    assert by_name["send_message"].group == "communication"
    assert by_name["send_message"].source == "builtin"
    assert by_name["my_custom"].group is None
    assert by_name["my_custom"].source == "workspace"


def test_catalog_lint_warns_on_missing_or_one_word_descriptions(
    caplog: pytest.LogCaptureFixture,
) -> None:
    tools = [
        fake_tool("undocumented", ""),
        fake_tool("terse", "Frobnicates"),
        fake_tool("fine", "Does a clearly described thing"),
    ]
    with caplog.at_level(logging.WARNING, logger="openpaw.agent.harness.ultra.equipment"):
        build_tool_catalog(tools)

    warnings = [r.getMessage() for r in caplog.records]
    assert any("undocumented" in w and "terse" in w for w in warnings)
    assert not any("'fine'" in w for w in warnings)


# ---------------------------------------------------------------------------
# Floor resolution
# ---------------------------------------------------------------------------


def test_floor_expands_groups_and_keeps_structural_entries() -> None:
    tools = [fake_tool("brave_search"), fake_tool("send_message")]
    resolver = {"web": ["brave_search"]}

    floor = resolve_equip_floor(
        ["group:web", "send_message", "group:filesystem"],
        tools,
        group_resolver=lambda g: resolver.get(g, []),
    )

    # group:filesystem resolves to nothing (structural: AgentRunner adds
    # filesystem tools on every build); everything else expands to names.
    assert floor == {"brave_search", "send_message"}


def test_floor_group_resolver_failure_is_nonfatal() -> None:
    def broken(group: str) -> list[str]:
        raise RuntimeError("registry down")

    floor = resolve_equip_floor(["group:web", "send_message"], [], group_resolver=broken)
    assert floor == {"send_message"}


# ---------------------------------------------------------------------------
# request_tools tool + detection
# ---------------------------------------------------------------------------


def test_request_tools_tool_shape_and_detection() -> None:
    tool = create_request_tools_tool()
    assert tool.name == REQUEST_TOOLS_NAME
    assert "Request recorded" in tool.invoke({"tools_needed": "email access"})

    messages = [HumanMessage("do it"), request_tools_message("email access")]
    assert detect_tool_request(messages) == "email access"
    assert detect_tool_request([AIMessage(content="no calls")]) is None


# ---------------------------------------------------------------------------
# Equip node: selection, clamp, unknown-drop, fail-open
# ---------------------------------------------------------------------------


async def test_equip_selects_clamps_drops_unknown_and_unions_floor() -> None:
    emitter = CaptureEmitter()
    executor = FakeExecutor([[AIMessage(content="step done")]])
    factory = RecordingFactory(executor)
    equipment = make_equipment(
        EquipDecision(equip=["alpha", "not_a_tool", "beta", "gamma"], reason="picked"),
        floor=frozenset({"beta", "send_message"}),
        max_tools=2,
    )
    graph = build_graph(
        triage=[plan_decision()],
        planning=[_PlanSchema(steps=["one"])],
        reflection=[advance()],
        emitter=emitter,
        equipment=equipment,
        step_executor_factory=factory,
    )

    result = await graph.ainvoke({"messages": [HumanMessage("do it")]})

    # unknown dropped, clamped to 2 known (alpha, beta), unioned with floor
    # and the always-present request_tools escape hatch.
    expected = sorted({"alpha", "beta", "send_message", REQUEST_TOOLS_NAME})
    assert result["equipped_tools"] == expected
    assert factory.calls == [expected]
    assert result["messages"][-1].content == "final answer"

    equipped_events = [e for e in emitter.events if str(e.kind) == "tools.equipped"]
    assert len(equipped_events) == 1
    payload = equipped_events[0].payload
    assert payload["tools"] == expected
    assert payload["reason"] == "picked"
    assert payload["kept"] == len(expected)
    assert payload["dropped"] == 1  # gamma is the only catalog tool left out


async def test_equip_failure_fails_open_to_full_toolset() -> None:
    emitter = CaptureEmitter()
    executor = FakeExecutor([[AIMessage(content="step done")]])
    factory = RecordingFactory(executor)
    graph = build_graph(
        triage=[plan_decision()],
        planning=[_PlanSchema(steps=["one"])],
        reflection=[advance()],
        emitter=emitter,
        equipment=make_equipment(RuntimeError("equip model down")),
        step_executor_factory=factory,
    )

    result = await graph.ainvoke({"messages": [HumanMessage("do it")]})

    assert result["equipped_tools"] is None  # None = everything
    assert factory.calls == [None]
    assert result["messages"][-1].content == "final answer"
    equipped_events = [e for e in emitter.events if str(e.kind) == "tools.equipped"]
    assert equipped_events[0].payload["tools"] == ["alpha", "beta", "gamma"]
    assert equipped_events[0].payload["dropped"] == 0


# ---------------------------------------------------------------------------
# Disabled: topology and behavior are unchanged
# ---------------------------------------------------------------------------


async def test_disabled_has_no_equip_node_and_factory_receives_none() -> None:
    executor = FakeExecutor([[AIMessage(content="step done")]])
    factory = RecordingFactory(executor)
    graph = build_graph(
        triage=[plan_decision()],
        planning=[_PlanSchema(steps=["one"])],
        reflection=[advance()],
        equipment=None,
        step_executor_factory=factory,
    )
    baseline = build_graph(
        triage=[plan_decision()],
        planning=[_PlanSchema(steps=["one"])],
        reflection=[advance()],
    )

    assert "equip" not in graph.nodes
    assert set(graph.nodes) == set(baseline.nodes)  # identical topology

    result = await graph.ainvoke({"messages": [HumanMessage("do it")]})
    assert factory.calls == [None]  # full toolset requested — zero change
    assert "equipped_tools" not in result or result["equipped_tools"] is None
    assert result["messages"][-1].content == "final answer"


# ---------------------------------------------------------------------------
# Recovery loop (H5.3)
# ---------------------------------------------------------------------------


async def test_request_tools_triggers_one_reequip_then_step_completes() -> None:
    emitter = CaptureEmitter()
    executor = FakeExecutor(
        [
            [request_tools_message("need beta for this")],
            [AIMessage(content="step done with beta")],
        ]
    )
    factory = RecordingFactory(executor)
    equipment = make_equipment(
        EquipDecision(equip=["alpha"], reason="initial"),
        EquipDecision(equip=["alpha", "beta"], reason="re-equip"),
        catalog_names=("alpha", "beta"),
    )
    graph = build_graph(
        triage=[plan_decision()],
        planning=[_PlanSchema(steps=["one"])],
        reflection=[advance()],
        emitter=emitter,
        equipment=equipment,
        step_executor_factory=factory,
    )

    result = await graph.ainvoke({"messages": [HumanMessage("do it")]})

    assert factory.calls == [
        sorted({"alpha", REQUEST_TOOLS_NAME}),
        sorted({"alpha", "beta", REQUEST_TOOLS_NAME}),
    ]
    assert len(executor.prompts) == 2
    assert "Execute step 1" in executor.prompts[0]
    assert executor.prompts[0] == executor.prompts[1]  # same step re-executed

    # The re-equip prompt carried the executor's request.
    equip_model = cast(FakeModel, equipment.model)
    assert "need beta for this" in equip_model.prompts[1]

    assert result["requested_tools"] is None
    assert result["reequipped_steps"] == ["1"]
    assert result["step_results"] == ["step done with beta"]
    final_plan = plan_from_state(cast(UltraState, result))
    assert final_plan is not None
    assert final_plan.steps[0].status is StepStatus.DONE

    equipped_events = [e for e in emitter.events if str(e.kind) == "tools.equipped"]
    assert len(equipped_events) == 2  # initial + re-equip
    # Only ONE step_completed: the requesting attempt did not complete the step.
    assert emitter.kinds().count("plan.step_completed") == 1


async def test_second_request_on_same_step_does_not_reequip_again() -> None:
    executor = FakeExecutor(
        [
            [request_tools_message("need beta")],
            [request_tools_message("need delta too")],  # cap: ignored, step proceeds
        ]
    )
    factory = RecordingFactory(executor)
    equipment = make_equipment(
        EquipDecision(equip=["alpha"], reason="initial"),
        EquipDecision(equip=["alpha", "beta"], reason="re-equip"),
        catalog_names=("alpha", "beta"),
    )
    graph = build_graph(
        triage=[plan_decision()],
        planning=[_PlanSchema(steps=["one"])],
        reflection=[advance()],
        equipment=equipment,
        step_executor_factory=factory,
    )

    result = await graph.ainvoke({"messages": [HumanMessage("do it")]})

    assert len(factory.calls) == 2  # no third equip pass
    assert cast(FakeModel, equipment.model).call_count == 2
    assert result["reequipped_steps"] == ["1"]
    assert result["messages"][-1].content == "final answer"  # run still finishes

# ---------------------------------------------------------------------------
# Harness: step-executor factory (subset build + cache) and factory wiring
# ---------------------------------------------------------------------------


def equipping_config() -> HarnessConfig:
    return HarnessConfig.model_validate(
        {"type": "ultra", "tool_equipping": {"enabled": True, "always_equip": ["send_message"]}}
    )


def test_harness_executor_factory_builds_subset_and_caches(tmp_path: Path) -> None:
    from langchain_core.tools import tool

    from openpaw.agent.harness.ultra import UltraHarness
    from openpaw.agent.runner import AgentRunner
    from tests.test_ultra_harness import make_node_resolver, make_workspace

    @tool
    def alpha_tool() -> str:
        """Alpha does alpha things."""
        return "a"

    @tool
    def beta_tool() -> str:
        """Beta does beta things."""
        return "b"

    workspace = make_workspace(tmp_path)
    inner = AgentRunner(
        workspace=workspace, model="openai:gpt-4o-mini", api_key="test", tools=[alpha_tool, beta_tool]
    )
    built: list[list[str]] = []

    def builder(tools: list[Any]) -> Any:
        built.append([t.name for t in tools])
        return SimpleNamespace(agent_graph=object())

    harness = UltraHarness(
        workspace=workspace,
        inner=inner,
        harness_config=equipping_config(),
        node_resolver=make_node_resolver(),
        step_agent_builder=cast(Any, builder),
    )

    # None = full toolset: the shared inner graph, untouched (zero change).
    assert harness._step_executor_factory(None) is inner.agent_graph
    assert built == []

    g1 = harness._step_executor_factory(["alpha_tool"])
    assert built == [["alpha_tool", REQUEST_TOOLS_NAME]]  # subset + escape hatch

    # Cache: same set (any order) returns the same compiled graph, no rebuild.
    assert harness._step_executor_factory(["alpha_tool"]) is g1
    assert len(built) == 1

    # Recompile (tool update) invalidates the cache.
    harness.update_tools([alpha_tool, beta_tool])
    g2 = harness._step_executor_factory(["alpha_tool"])
    assert g2 is not g1
    assert len(built) == 2


def test_harness_enabled_adds_equip_node_and_disabled_does_not(tmp_path: Path) -> None:
    from openpaw.agent.harness.ultra import UltraHarness
    from openpaw.agent.runner import AgentRunner
    from tests.test_ultra_harness import make_node_resolver, make_workspace

    workspace = make_workspace(tmp_path)

    def harness_for(config: HarnessConfig) -> UltraHarness:
        inner = AgentRunner(workspace=workspace, model="openai:gpt-4o-mini", api_key="test")
        return UltraHarness(
            workspace=workspace,
            inner=inner,
            harness_config=config,
            node_resolver=make_node_resolver(),
        )

    assert "equip" not in harness_for(HarnessConfig(type="ultra")).agent_graph.nodes
    assert "equip" in harness_for(equipping_config()).agent_graph.nodes


def test_agent_factory_tools_override_replaces_toolset(tmp_path: Path) -> None:
    from langchain_core.tools import tool

    from tests.test_ultra_harness import make_factory, make_workspace

    @tool
    def gamma_tool() -> str:
        """Gamma does gamma things."""
        return "g"

    factory = make_factory(make_workspace(tmp_path))
    runner = factory.create_agent(checkpointer=None, tools_override=[gamma_tool])
    assert runner.additional_tools == [gamma_tool]
    assert runner.checkpointer is None
