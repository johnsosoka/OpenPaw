"""Tests for UltraHarness (protocol conformance, parity contracts) and
AgentFactory harness dispatch."""

import asyncio
import logging
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from langgraph.checkpoint.memory import MemorySaver

from openpaw.agent.harness import AgentHarness, HarnessKind
from openpaw.agent.harness.ultra import UltraHarness
from openpaw.agent.middleware.approval import ApprovalRequiredError
from openpaw.agent.middleware.queue_aware import InterruptSignalError
from openpaw.agent.runner import AgentRunner
from openpaw.core.config.models import ExecutionConfig, HarnessConfig, WorkspaceConfig
from openpaw.core.prompts.system_events import TIMEOUT_NOTIFICATION_GENERIC
from openpaw.core.workspace import AgentWorkspace
from openpaw.workspace.agent_factory import AgentFactory
from openpaw.workspace.model_resolver import ModelResolver
from openpaw.workspace.node_model_resolver import NodeModelResolver

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def make_workspace(tmp_path: Path, config: WorkspaceConfig | None = None) -> AgentWorkspace:
    (tmp_path / "AGENT.md").write_text("# Agent")
    return AgentWorkspace(
        name="ultra-test",
        path=tmp_path,
        agent_md="# Agent",
        user_md="# User",
        soul_md="# Soul",
        heartbeat_md="# Heartbeat",
        skills_path=tmp_path / "agent" / "skills",
        tools_path=tmp_path / "tools",
        config=config,
    )


def make_node_resolver() -> NodeModelResolver:
    return NodeModelResolver(
        resolver=ModelResolver(
            provider_catalog={},
            configured_model="openai:gpt-4o-mini",
            api_key="test",
            region=None,
            extra_model_kwargs={},
        ),
        workspace_model="openai:gpt-4o-mini",
        workspace_api_key="test",
        workspace_temperature=0.7,
        workspace_region=None,
        workspace_extra_kwargs={},
    )


@pytest.fixture
def harness(tmp_path: Path) -> UltraHarness:
    workspace = make_workspace(tmp_path)
    inner = AgentRunner(
        workspace=workspace,
        model="openai:gpt-4o-mini",
        api_key="test",
        checkpointer=MemorySaver(),
    )
    return UltraHarness(
        workspace=workspace,
        inner=inner,
        harness_config=HarnessConfig(type="ultra"),
        node_resolver=make_node_resolver(),
    )


class StubGraph:
    """Stub outer graph: astream raises a scripted error; records state updates."""

    def __init__(self, error: Exception | None = None, delay: float = 0.0, on_start: Any = None) -> None:
        self.error = error
        self.delay = delay
        self.on_start = on_start
        self.state_updates: list[tuple[dict[str, Any], str | None]] = []

    def astream(self, *_args: Any, **_kwargs: Any) -> AsyncIterator[Any]:
        async def gen() -> AsyncIterator[Any]:
            if self.on_start:
                self.on_start()
            if self.delay:
                await asyncio.sleep(self.delay)
            if self.error:
                raise self.error
            yield ((), "updates", {})  # root-namespace 3-tuple (subgraphs=True shape)

        return gen()

    async def aupdate_state(self, config: dict[str, Any], values: dict[str, Any], as_node: str | None = None) -> None:
        self.state_updates.append((values, as_node))


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


def test_ultra_harness_satisfies_protocol(harness: UltraHarness) -> None:
    assert isinstance(harness, AgentHarness)
    assert harness.kind == HarnessKind.ULTRA
    assert harness.model_id == "openai:gpt-4o-mini"
    assert harness.last_metrics is None
    assert harness.last_tools_used == []
    assert harness.checkpointer is not None  # shared with the inner runner


def test_zero_config_ultra_builds(tmp_path: Path) -> None:
    """H6.2: bare harness: {type: ultra} builds with all nodes inheriting."""
    workspace = make_workspace(tmp_path)
    inner = AgentRunner(workspace=workspace, model="openai:gpt-4o-mini", api_key="test")
    harness = UltraHarness(
        workspace=workspace,
        inner=inner,
        harness_config=HarnessConfig(type="ultra"),
        node_resolver=make_node_resolver(),
    )
    assert {"triage", "react", "plan", "execute_step", "reflect", "synthesize"} <= set(harness.agent_graph.nodes)


def test_timeout_seconds_default_inherits_inner(harness: UltraHarness) -> None:
    assert harness.timeout_seconds == harness._inner.timeout_seconds


def test_timeout_seconds_override_takes_precedence(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    inner = AgentRunner(workspace=workspace, model="openai:gpt-4o-mini", api_key="test")
    harness = UltraHarness(
        workspace=workspace,
        inner=inner,
        harness_config=HarnessConfig(type="ultra", execution=ExecutionConfig(timeout_seconds=900)),
        node_resolver=make_node_resolver(),
    )
    assert harness.timeout_seconds == 900
    assert inner.timeout_seconds != 900


@pytest.mark.parametrize("bad_timeout", [0, -5])
def test_execution_timeout_seconds_rejects_non_positive(bad_timeout: float) -> None:
    with pytest.raises(ValueError):
        ExecutionConfig(timeout_seconds=bad_timeout)


def test_update_model_applies_to_execution_only(harness: UltraHarness) -> None:
    """ADR-103 §4: runtime /model override never touches node models."""
    node_models_before = harness._node_models

    harness.update_model("openai:gpt-4.1", temperature=0.2)

    assert harness.model_id == "openai:gpt-4.1"
    assert harness._inner.temperature == 0.2
    assert harness._node_models is node_models_before  # untouched instances


def test_update_checkpointer_recompiles_with_shared_instance(harness: UltraHarness) -> None:
    graph_before = harness.agent_graph
    saver = MemorySaver()

    harness.update_checkpointer(saver)

    assert harness.checkpointer is saver
    assert harness._inner.checkpointer is saver
    assert harness.agent_graph is not graph_before  # recompiled


def test_update_tools_delegates_and_recompiles(harness: UltraHarness) -> None:
    from langchain_core.tools import tool

    @tool
    def extra_tool(query: str) -> str:
        """Does an extra thing. With detail."""
        return query

    graph_before = harness.agent_graph
    harness.update_tools([extra_tool])

    assert [t.name for t in harness.additional_tools] == ["extra_tool"]
    assert harness.agent_graph is not graph_before


# ---------------------------------------------------------------------------
# Approval / interrupt / timeout contracts
# ---------------------------------------------------------------------------


async def test_approval_during_plan_step_records_resume_marker(harness: UltraHarness) -> None:
    error = ApprovalRequiredError("appr-1", "shell", {"cmd": "ls"}, "tc-1")
    stub = StubGraph(error=error, on_start=lambda: setattr(harness._run_context, "executing_step_id", "2"))
    harness._graph = stub

    with pytest.raises(ApprovalRequiredError):
        await harness.run("do risky thing", thread_id="telegram:1:conv1")

    assert stub.state_updates == [({"resume_step_id": "2"}, "plan")]


async def test_approval_on_react_route_records_nothing(harness: UltraHarness) -> None:
    """No plan step executing -> no marker (react-route approvals resume as today)."""
    stub = StubGraph(error=ApprovalRequiredError("appr-1", "shell", {}, "tc-1"))
    harness._graph = stub

    with pytest.raises(ApprovalRequiredError):
        await harness.run("do risky thing", thread_id="telegram:1:conv1")

    assert stub.state_updates == []


async def test_interrupt_clears_plan_state(harness: UltraHarness) -> None:
    stub = StubGraph(error=InterruptSignalError([("telegram", "stop!")]))
    harness._graph = stub

    with pytest.raises(InterruptSignalError):
        await harness.run("long task", thread_id="telegram:1:conv1")

    assert len(stub.state_updates) == 1
    values, as_node = stub.state_updates[0]
    assert values["plan"] is None
    assert values["current_step_id"] is None
    assert values["resume_step_id"] is None
    assert as_node == "plan"


async def test_stateless_harness_skips_state_maintenance(tmp_path: Path) -> None:
    """No checkpointer -> approval/interrupt contracts are no-ops, error still propagates."""
    workspace = make_workspace(tmp_path)
    inner = AgentRunner(workspace=workspace, model="openai:gpt-4o-mini", api_key="test", checkpointer=None)
    harness = UltraHarness(
        workspace=workspace,
        inner=inner,
        harness_config=HarnessConfig(type="ultra"),
        node_resolver=make_node_resolver(),
    )
    stub = StubGraph(error=InterruptSignalError([]))
    harness._graph = stub

    with pytest.raises(InterruptSignalError):
        await harness.run("task")

    assert stub.state_updates == []


async def test_timeout_returns_notification_with_partial_metrics(harness: UltraHarness) -> None:
    harness._graph = StubGraph(delay=5.0)
    harness.timeout_seconds = 0.05

    response = await harness.run("slow task", thread_id="telegram:1:conv1")

    assert response == TIMEOUT_NOTIFICATION_GENERIC.format(timeout=0)
    assert harness.last_metrics is not None
    assert harness.last_metrics.is_partial is True


# ---------------------------------------------------------------------------
# run() end-to-end over a fake ultra graph (real astream/updates parsing)
# ---------------------------------------------------------------------------


async def test_run_plan_flow_returns_synthesis(harness: UltraHarness) -> None:
    from langchain_core.messages import AIMessage

    from openpaw.agent.harness.modules.direct import _PlanSchema
    from tests.test_ultra_graph import advance, build, make_fake_react, plan_decision

    calls: list[str] = []
    harness._graph = build(
        triage=[plan_decision()],
        planning=[_PlanSchema(steps=["one"])],
        reflection=[advance()],
        synthesize=[AIMessage(content="synth done")],
        react=make_fake_react(["step done"], calls),
        run_context=harness._run_context,
    )

    response = await harness.run("do it", thread_id="telegram:1:conv1")

    assert response == "synth done"
    assert len(calls) == 1
    assert harness.last_metrics is not None  # metrics extracted (zero-usage fakes)


async def test_run_react_flow_returns_react_reply(harness: UltraHarness) -> None:
    from openpaw.agent.harness.ultra import TriageDecision
    from tests.test_ultra_graph import build, make_fake_react

    harness._graph = build(
        triage=[TriageDecision(route="react", objective="greet", reason="simple")],
        react=make_fake_react(["react says hi"], []),
        run_context=harness._run_context,
    )

    response = await harness.run("hello", thread_id="telegram:1:conv1")

    assert response == "react says hi"


# ---------------------------------------------------------------------------
# Orphaned tool-call recovery (outer graph state)
# ---------------------------------------------------------------------------


async def test_resolve_orphaned_tool_calls_repairs_react_route(harness: UltraHarness) -> None:
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

    thread_id = "telegram:1:conv1"
    config = {"configurable": {"thread_id": thread_id}}
    orphan = AIMessage(content="", tool_calls=[{"name": "shell", "args": {}, "id": "tc-9"}])
    await harness.agent_graph.aupdate_state(
        config, {"messages": [HumanMessage("run it"), orphan]}, as_node="react"
    )

    await harness.resolve_orphaned_tool_calls(thread_id, responses={"tc-9": "Tool 'shell' was approved."})

    state = await harness.agent_graph.aget_state(config)
    tool_msgs = [m for m in state.values["messages"] if isinstance(m, ToolMessage)]
    assert len(tool_msgs) == 1
    assert tool_msgs[0].tool_call_id == "tc-9"
    assert "approved" in str(tool_msgs[0].content)

    # Idempotent: nothing dangling on a second pass.
    await harness.resolve_orphaned_tool_calls(thread_id)
    state = await harness.agent_graph.aget_state(config)
    assert len([m for m in state.values["messages"] if isinstance(m, ToolMessage)]) == 1


async def test_resolve_orphaned_tool_calls_noop_without_orphans(harness: UltraHarness) -> None:
    """Typical execute_step approval case: inner run unpersisted -> no-op."""
    await harness.resolve_orphaned_tool_calls("telegram:1:conv1")  # empty thread, no error


# ---------------------------------------------------------------------------
# Context info
# ---------------------------------------------------------------------------


async def test_get_context_info_empty_thread(harness: UltraHarness) -> None:
    info = await harness.get_context_info("telegram:1:conv-empty")
    assert info == {
        "max_input_tokens": 0,
        "approximate_tokens": 0,
        "utilization": 0.0,
        "message_count": 0,
    }


# ---------------------------------------------------------------------------
# Factory dispatch
# ---------------------------------------------------------------------------


def make_factory(workspace: AgentWorkspace) -> AgentFactory:
    return AgentFactory(
        workspace=workspace,
        model="openai:gpt-4o-mini",
        api_key="test",
        max_turns=10,
        temperature=0.7,
        region=None,
        timeout_seconds=30.0,
        builtin_tools=[],
        workspace_tools=[],
        enabled_builtin_names=[],
        extra_model_kwargs={},
        middleware=[],
        logger=logging.getLogger("test"),
    )


def test_factory_dispatches_react_by_default(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path, config=WorkspaceConfig())
    harness = make_factory(workspace).create_harness()
    assert isinstance(harness, AgentRunner)
    assert harness.kind == HarnessKind.REACT


def test_factory_dispatches_react_without_config(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path, config=None)
    harness = make_factory(workspace).create_harness()
    assert isinstance(harness, AgentRunner)


def test_factory_dispatches_ultra(tmp_path: Path) -> None:
    workspace = make_workspace(
        tmp_path, config=WorkspaceConfig.model_validate({"harness": {"type": "ultra"}})
    )
    saver = MemorySaver()
    harness = make_factory(workspace).create_harness(checkpointer=saver)
    assert isinstance(harness, UltraHarness)
    assert harness.kind == HarnessKind.ULTRA
    assert harness.checkpointer is saver  # outer and inner share the instance
    assert isinstance(harness, AgentHarness)
