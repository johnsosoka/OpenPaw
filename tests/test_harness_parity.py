"""Feature-parity test matrix for the AgentHarness seam (PRD-002 §5, CONCERNS C4).

Every caller-visible behavior of the harness surface is asserted under BOTH
topologies via one parameterized fixture:

- react   -> AgentRunner (the existing loop, unchanged)
- planner -> PlannerHarness wrapping the same AgentRunner as its executor

Callers under test: the run() contract MessageProcessor depends on
(final text, timeout notification, ApprovalRequiredError/InterruptSignalError
propagation, last_metrics/last_tools_used), checkpoint maintenance
(resolve_orphaned_tool_calls, get_context_info), the rebuild/update surface
(commands, MCP post-start wiring), and the CommandContext type contract.

Fixture strategy mirrors the existing planner tests (tests/test_planner_graph
fakes are reused, not reinvented): the outer graph of either harness is
swapped for a scripted stand-in. For react that is ``runner._agent`` (the
compiled create_agent graph — ``make_fake_react``'s node is named "model", so
AgentRunner's update parsing sees the exact production shape); for planner it
is ``harness._graph`` built with fake node models.

Intended (documented) differences — asserted around, not away:
- kind: react vs planner (identity, not behavior).
- run() recursion_limit VALUE differs (planner takes a max with the plan-step
  budget); parity is asserted on presence and configurable propagation.
- planner emits status events and clears/records plan state on
  interrupt/approval — extra behavior on top of the identical error contract,
  already covered in tests/test_planner_harness.py.
"""

import asyncio
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from openpaw.agent.harness import AgentHarness, HarnessKind
from openpaw.agent.harness.modules.direct import _PlanSchema
from openpaw.agent.harness.planner import PlannerHarness, TriageDecision
from openpaw.agent.middleware.approval import ApprovalRequiredError
from openpaw.agent.middleware.queue_aware import InterruptSignalError
from openpaw.agent.runner import AgentRunner
from openpaw.channels.commands.base import CommandContext
from openpaw.channels.commands.handlers.model import ModelCommand
from openpaw.core.config.models import HarnessConfig
from openpaw.core.prompts.system_events import (
    TIMEOUT_NOTIFICATION_GENERIC,
    TIMEOUT_NOTIFICATION_TEMPLATE,
)
from openpaw.model.message import Message
from openpaw.runtime.queue.lane import QueueMode
from openpaw.workspace.message_processor import MessageProcessor
from tests.test_planner_graph import _ReactState, advance, build, make_fake_react, plan_decision
from tests.test_planner_harness import make_node_resolver, make_workspace

THREAD_ID = "telegram:1:conv1"

# ---------------------------------------------------------------------------
# Parity fixture machinery
# ---------------------------------------------------------------------------


class ScriptedStream:
    """Outer-graph stand-in: yields scripted updates, then optionally hangs or raises.

    Records astream invocations (input + config) and aupdate_state calls so
    tests can assert the caller-side contract without any real model.
    """

    def __init__(
        self,
        updates: list[dict[str, Any]] | None = None,
        error: Exception | None = None,
        hang_seconds: float = 0.0,
    ) -> None:
        self.updates = updates or []
        self.error = error
        self.hang_seconds = hang_seconds
        self.invocations: list[tuple[Any, dict[str, Any] | None]] = []
        self.state_updates: list[tuple[dict[str, Any], str | None]] = []

    def astream(self, input: Any, config: dict[str, Any] | None = None, **_: Any) -> AsyncIterator[dict[str, Any]]:
        self.invocations.append((input, config))

        async def gen() -> AsyncIterator[dict[str, Any]]:
            for update in self.updates:
                yield update
            if self.hang_seconds:
                await asyncio.sleep(self.hang_seconds)
            if self.error is not None:
                raise self.error

        return gen()

    async def aupdate_state(self, config: dict[str, Any], values: dict[str, Any], as_node: str | None = None) -> None:
        self.state_updates.append((values, as_node))


@dataclass
class ParityCase:
    """One harness kind plus the hooks the parity tests need to script it."""

    kind: HarnessKind
    harness: Any  # AgentRunner | PlannerHarness — both satisfy AgentHarness

    def install(self, graph: Any) -> None:
        """Swap the outer graph (react: compiled create_agent; planner: StateGraph)."""
        if self.kind is HarnessKind.REACT:
            self.harness._agent = graph
        else:
            self.harness._graph = graph

    def script_simple_turn(self, replies: list[str]) -> list[str]:
        """Install a working fake graph for a plain conversational turn.

        Returns the list that records the prompts the fake model receives.
        On planner, triage is scripted to route "react" so a simple message
        follows the same path a react harness takes (PRD-002 H2.1 parity).
        """
        calls: list[str] = []
        if self.kind is HarnessKind.REACT:
            self.harness._agent = make_fake_react(replies, calls)
        else:
            self.harness._graph = build(
                triage=[TriageDecision(route="react", objective="simple turn", reason="parity")],
                react=make_fake_react(replies, calls),
                run_context=self.harness._run_context,
            )
        return calls

    @property
    def graph(self) -> Any:
        """The real compiled graph (checkpoint-maintenance tests)."""
        return self.harness.agent_graph

    @property
    def seed_as_node(self) -> str:
        """The node that owns ``messages`` — where seeded state must come from."""
        return "model" if self.kind is HarnessKind.REACT else "react"


def make_case(
    kind: HarnessKind,
    tmp_path: Path,
    *,
    checkpointer: Any | None = "default",
    extra_model_kwargs: dict[str, Any] | None = None,
) -> ParityCase:
    """Build a harness of the requested kind over a real workspace on tmp_path."""
    workspace = make_workspace(tmp_path)
    saver = MemorySaver() if checkpointer == "default" else checkpointer
    inner = AgentRunner(
        workspace=workspace,
        model="openai:gpt-4o-mini",
        api_key="test",
        checkpointer=saver,
        extra_model_kwargs=extra_model_kwargs,
    )
    if kind is HarnessKind.REACT:
        return ParityCase(kind, inner)
    return ParityCase(
        kind,
        PlannerHarness(
            workspace=workspace,
            inner=inner,
            harness_config=HarnessConfig(type="planner"),
            node_resolver=make_node_resolver(),
        ),
    )


@pytest.fixture(params=[HarnessKind.REACT, HarnessKind.PLANNER], ids=["react", "planner"])
def case(request: pytest.FixtureRequest, tmp_path: Path) -> ParityCase:
    return make_case(request.param, tmp_path)


# ---------------------------------------------------------------------------
# 1. run() contract
# ---------------------------------------------------------------------------


async def test_run_returns_final_text(case: ParityCase) -> None:
    calls = case.script_simple_turn(["hi there"])

    response = await case.harness.run("hello", thread_id=THREAD_ID)

    assert response == "hi there"
    assert calls == ["hello"]
    assert case.harness.last_metrics is not None  # metrics always populated after a run
    assert case.harness.last_tools_used == []


async def test_run_with_no_ai_output_returns_empty_string(case: ParityCase) -> None:
    """The empty-response edge MessageProcessor turns into its fallback message."""
    case.install(ScriptedStream())

    assert await case.harness.run("hello", thread_id=THREAD_ID) == ""


async def test_run_passes_thread_session_and_recursion_config(case: ParityCase) -> None:
    stub = ScriptedStream()
    case.install(stub)

    await case.harness.run("ping", session_id="sess-1", thread_id=THREAD_ID)

    ((input_payload, config),) = stub.invocations
    assert input_payload == {"messages": [{"role": "user", "content": "ping"}]}
    assert config is not None
    assert config["configurable"]["thread_id"] == THREAD_ID
    assert config["configurable"]["session_id"] == "sess-1"
    # Values intentionally differ (planner budgets plan steps); presence is the contract.
    assert config["recursion_limit"] > 0
    assert len(config["callbacks"]) == 1  # usage-metadata callback wired per run


# ---------------------------------------------------------------------------
# 2. Timeout — notification text, not an exception; partial metrics recorded.
#    Setting timeout_seconds post-construction is the mutability contract
#    (SubAgentRunner overrides it per request).
# ---------------------------------------------------------------------------


async def test_timeout_returns_generic_notification(case: ParityCase) -> None:
    case.install(ScriptedStream(hang_seconds=5.0))
    case.harness.timeout_seconds = 0.05

    response = await case.harness.run("slow task", thread_id=THREAD_ID)

    assert response == TIMEOUT_NOTIFICATION_GENERIC.format(timeout=0)
    assert case.harness.last_metrics is not None
    assert case.harness.last_metrics.is_partial is True


async def test_timeout_with_tool_in_flight_names_the_tool(case: ParityCase) -> None:
    tool_call_update = {
        "model": {"messages": [AIMessage(content="", tool_calls=[{"name": "shell", "args": {}, "id": "t1"}])]}
    }
    case.install(ScriptedStream(updates=[tool_call_update], hang_seconds=5.0))
    case.harness.timeout_seconds = 0.05

    response = await case.harness.run("slow tool", thread_id=THREAD_ID)

    assert response == TIMEOUT_NOTIFICATION_TEMPLATE.format(timeout=0, tool_name="shell")
    assert case.harness.last_metrics is not None
    assert case.harness.last_metrics.is_partial is True
    assert "shell" in case.harness.last_tools_used


# ---------------------------------------------------------------------------
# 3./4. Approval + interrupt error contracts — the exact exception object with
# intact attributes must reach the caller (MessageProcessor's except clauses
# read approval_id/tool_name/tool_args/tool_call_id and pending_messages).
# Planner-side extras (resume marker, plan clearing) are pinned in
# tests/test_planner_harness.py; identical error surface is pinned here.
# ---------------------------------------------------------------------------


async def test_approval_error_reaches_caller_with_attributes(case: ParityCase) -> None:
    error = ApprovalRequiredError("appr-1", "shell", {"cmd": "ls"}, "tc-1")
    case.install(ScriptedStream(error=error))

    with pytest.raises(ApprovalRequiredError) as exc_info:
        await case.harness.run("risky", thread_id=THREAD_ID)

    assert exc_info.value is error  # unwrapped — same object, not a re-raise copy
    assert (exc_info.value.approval_id, exc_info.value.tool_name) == ("appr-1", "shell")
    assert exc_info.value.tool_args == {"cmd": "ls"}
    assert exc_info.value.tool_call_id == "tc-1"


async def test_interrupt_error_reaches_caller_with_pending_messages(case: ParityCase) -> None:
    error = InterruptSignalError([("telegram", "stop!")])
    case.install(ScriptedStream(error=error))

    with pytest.raises(InterruptSignalError) as exc_info:
        await case.harness.run("long task", thread_id=THREAD_ID)

    assert exc_info.value is error
    assert exc_info.value.pending_messages == [("telegram", "stop!")]


# ---------------------------------------------------------------------------
# 5. Orphaned tool-call recovery — real graphs, real MemorySaver.
# ---------------------------------------------------------------------------


async def test_resolve_orphaned_tool_calls_injects_and_is_idempotent(case: ParityCase) -> None:
    config = {"configurable": {"thread_id": THREAD_ID}}
    orphan = AIMessage(content="", tool_calls=[{"name": "shell", "args": {}, "id": "tc-9"}])
    await case.graph.aupdate_state(config, {"messages": [HumanMessage("run it"), orphan]}, as_node=case.seed_as_node)

    await case.harness.resolve_orphaned_tool_calls(THREAD_ID, responses={"tc-9": "Tool 'shell' was approved."})

    state = await case.graph.aget_state(config)
    tool_msgs = [m for m in state.values["messages"] if isinstance(m, ToolMessage)]
    assert len(tool_msgs) == 1
    assert tool_msgs[0].tool_call_id == "tc-9"
    assert "approved" in str(tool_msgs[0].content)

    # Idempotent: a second pass finds nothing dangling.
    await case.harness.resolve_orphaned_tool_calls(THREAD_ID)
    state = await case.graph.aget_state(config)
    assert len([m for m in state.values["messages"] if isinstance(m, ToolMessage)]) == 1


async def test_resolve_orphaned_tool_calls_noop_on_clean_state(case: ParityCase) -> None:
    # Empty thread: no error, no writes.
    await case.harness.resolve_orphaned_tool_calls(THREAD_ID)

    # Populated thread without dangling tool calls: untouched.
    config = {"configurable": {"thread_id": THREAD_ID}}
    await case.graph.aupdate_state(
        config, {"messages": [HumanMessage("hi"), AIMessage(content="done")]}, as_node=case.seed_as_node
    )
    await case.harness.resolve_orphaned_tool_calls(THREAD_ID)

    state = await case.graph.aget_state(config)
    assert len(state.values["messages"]) == 2
    assert not any(isinstance(m, ToolMessage) for m in state.values["messages"])


# ---------------------------------------------------------------------------
# 6. get_context_info — same dict shape for the auto-compact pre-run check.
# ---------------------------------------------------------------------------


async def test_get_context_info_empty_thread_returns_zeros(case: ParityCase) -> None:
    info = await case.harness.get_context_info("telegram:1:conv-empty")

    assert info == {
        "max_input_tokens": 0,
        "approximate_tokens": 0,
        "utilization": 0.0,
        "message_count": 0,
    }


async def test_get_context_info_populated_thread(case: ParityCase) -> None:
    config = {"configurable": {"thread_id": THREAD_ID}}
    await case.graph.aupdate_state(
        config,
        {"messages": [HumanMessage("tell me about parity"), AIMessage(content="parity is preserved")]},
        as_node=case.seed_as_node,
    )

    info = await case.harness.get_context_info(THREAD_ID)

    assert set(info) == {"max_input_tokens", "approximate_tokens", "utilization", "message_count"}
    assert info["message_count"] == 2
    assert info["approximate_tokens"] > 0
    assert info["max_input_tokens"] > 0
    assert info["utilization"] == pytest.approx(info["approximate_tokens"] / info["max_input_tokens"])


async def test_get_context_info_identical_across_kinds(tmp_path: Path) -> None:
    """Same model, same messages -> byte-identical report from both kinds."""
    messages = [HumanMessage("tell me about parity"), AIMessage(content="parity is preserved")]
    infos = {}
    for kind in (HarnessKind.REACT, HarnessKind.PLANNER):
        subdir = tmp_path / kind.value
        subdir.mkdir()
        one = make_case(kind, subdir)
        config = {"configurable": {"thread_id": THREAD_ID}}
        await one.graph.aupdate_state(config, {"messages": messages}, as_node=one.seed_as_node)
        infos[kind] = await one.harness.get_context_info(THREAD_ID)

    assert infos[HarnessKind.REACT] == infos[HarnessKind.PLANNER]


# ---------------------------------------------------------------------------
# 7. Rebuild / update surface (commands and MCP post-start wiring)
# ---------------------------------------------------------------------------


def test_rebuild_agent_recompiles_the_graph(case: ParityCase) -> None:
    before = case.graph

    case.harness.rebuild_agent()

    assert case.graph is not before


def test_update_tools_replaces_set_and_recompiles(case: ParityCase) -> None:
    @tool
    def extra_tool(query: str) -> str:
        """Does an extra thing. With detail."""
        return query

    before = case.graph
    case.harness.update_tools([extra_tool])

    assert [t.name for t in case.harness.additional_tools] == ["extra_tool"]
    assert case.graph is not before


def test_update_model_updates_model_id_and_recompiles(case: ParityCase) -> None:
    # On planner this touches the execution engine only (node models pinned
    # untouched in test_planner_harness); the caller-visible contract is the same.
    before = case.graph

    case.harness.update_model("openai:gpt-4.1", temperature=0.2)

    assert case.harness.model_id == "openai:gpt-4.1"
    assert case.graph is not before


def test_update_checkpointer_swaps_and_recompiles(case: ParityCase) -> None:
    before = case.graph
    saver = MemorySaver()

    case.harness.update_checkpointer(saver)

    assert case.harness.checkpointer is saver
    assert case.graph is not before


# ---------------------------------------------------------------------------
# 8. Protocol attribute surface
# ---------------------------------------------------------------------------


def test_protocol_surface(case: ParityCase) -> None:
    harness = case.harness
    assert isinstance(harness, AgentHarness)
    assert harness.kind is case.kind
    assert harness.last_metrics is None  # None before first run
    assert harness.last_tools_used == []
    assert harness.max_output_tokens is None  # uncapped by default
    assert isinstance(harness.additional_tools, list)
    assert isinstance(harness.timeout_seconds, float)
    assert isinstance(harness.model_id, str) and harness.model_id
    assert harness.checkpointer is not None


@pytest.mark.parametrize("kind", [HarnessKind.REACT, HarnessKind.PLANNER], ids=["react", "planner"])
def test_max_output_tokens_reflects_configured_cap(kind: HarnessKind, tmp_path: Path) -> None:
    capped = make_case(kind, tmp_path, extra_model_kwargs={"max_tokens": 512})
    assert capped.harness.max_output_tokens == 512


# ---------------------------------------------------------------------------
# 9. MessageProcessor integration smoke — the real caller over each kind.
#
# Collaborators are mocked exactly as tests/workspace/test_message_processor_*
# do; the harness and its graph path are real. The full steer/approval loops
# are covered per-kind elsewhere (test_steer_interrupt, test_approval_gates,
# test_planner_harness); this pins the happy-path seam: run -> metrics ->
# token log -> channel delivery.
# ---------------------------------------------------------------------------


def _make_message_processor(harness: Any, token_logger: MagicMock) -> MessageProcessor:
    queue_manager = MagicMock()
    queue_manager.get_session_mode = AsyncMock(return_value=QueueMode.COLLECT)
    queue_manager.peek_pending = AsyncMock(return_value=False)

    session_manager = MagicMock()
    session_manager.get_thread_id = MagicMock(return_value=THREAD_ID)

    builtin_loader = MagicMock()
    builtin_loader.get_tool_instance = MagicMock(return_value=None)

    queue_middleware = MagicMock()
    queue_middleware.was_steered = False
    queue_middleware.pending_steer_message = None

    return MessageProcessor(
        agent_runner=harness,
        session_manager=session_manager,
        queue_manager=queue_manager,
        builtin_loader=builtin_loader,
        queue_middleware=queue_middleware,
        approval_middleware=MagicMock(),
        approval_manager=None,
        workspace_name="parity",
        token_logger=token_logger,
        logger=logging.getLogger("parity-test"),
    )


async def test_message_processor_processes_batch_end_to_end(case: ParityCase) -> None:
    calls = case.script_simple_turn(["hi there"])
    token_logger = MagicMock()
    processor = _make_message_processor(case.harness, token_logger)
    channel = MagicMock()
    channel.send_message = AsyncMock()
    message = Message(id="m1", channel="telegram", session_key="telegram:1", user_id="42", content="hello")

    await processor.process_messages("telegram:1", [message], channel)

    assert calls == ["hello"]  # batch content reached the agent
    channel.send_message.assert_awaited_once_with("telegram:1", "hi there")
    token_logger.log.assert_called_once()
    assert token_logger.log.call_args.kwargs["metrics"] is case.harness.last_metrics


async def test_message_processor_sends_fallback_on_empty_response(case: ParityCase) -> None:
    case.install(ScriptedStream())  # run() returns ""
    processor = _make_message_processor(case.harness, MagicMock())
    channel = MagicMock()
    channel.send_message = AsyncMock()
    message = Message(id="m1", channel="telegram", session_key="telegram:1", user_id="42", content="hello")

    await processor.process_messages("telegram:1", [message], channel)

    channel.send_message.assert_awaited_once()
    assert "empty" in channel.send_message.await_args.args[1]


# ---------------------------------------------------------------------------
# 10. Commands surface — CommandContext holds AgentHarness; /model works on both.
# ---------------------------------------------------------------------------


def _make_command_context(harness: Any) -> CommandContext:
    return CommandContext(
        channel=MagicMock(),
        session_manager=MagicMock(),
        checkpointer=MagicMock(),
        agent_runner=harness,
        workspace_name="parity",
        workspace_path=Path("/tmp/parity"),
        queue_manager=MagicMock(),
    )


def test_command_context_accepts_either_harness(case: ParityCase) -> None:
    context = _make_command_context(case.harness)
    assert isinstance(context.agent_runner, AgentHarness)


async def test_model_command_reports_current_model(case: ParityCase) -> None:
    result = await ModelCommand().handle(MagicMock(), "", _make_command_context(case.harness))
    assert result.response == f"Model: {case.harness.model_id}"


# ---------------------------------------------------------------------------
# Plan-path variants (planner-only by design — react has no plan steps).
# These assert the react-visible contract holds when the failure happens
# INSIDE a plan step rather than on the direct route.
# ---------------------------------------------------------------------------


def _make_react_graph_from(node: Any) -> Any:
    builder = StateGraph(_ReactState)
    builder.add_node("model", node)
    builder.add_edge(START, "model")
    builder.add_edge("model", END)
    return builder.compile()


async def test_planner_timeout_mid_plan_step_returns_notification(tmp_path: Path) -> None:
    one = make_case(HarnessKind.PLANNER, tmp_path)

    async def hang(state: dict[str, Any]) -> dict[str, Any]:
        await asyncio.sleep(60)
        return {"messages": []}

    one.harness._graph = build(
        triage=[plan_decision()],
        planning=[_PlanSchema(steps=["one"])],
        react=_make_react_graph_from(hang),
        run_context=one.harness._run_context,
    )
    one.harness.timeout_seconds = 0.1

    response = await one.harness.run("do it", thread_id=THREAD_ID)

    assert response == TIMEOUT_NOTIFICATION_GENERIC.format(timeout=0)
    assert one.harness.last_metrics is not None
    assert one.harness.last_metrics.is_partial is True


async def test_planner_approval_mid_plan_step_propagates_and_marks_resume(tmp_path: Path) -> None:
    one = make_case(HarnessKind.PLANNER, tmp_path)
    error = ApprovalRequiredError("appr-1", "shell", {"cmd": "ls"}, "tc-1")

    def raise_approval(state: dict[str, Any]) -> dict[str, Any]:
        raise error

    one.harness._graph = build(
        triage=[plan_decision()],
        planning=[_PlanSchema(steps=["one"])],
        reflection=[advance()],
        react=_make_react_graph_from(raise_approval),
        run_context=one.harness._run_context,
        checkpointer=MemorySaver(),
    )

    with pytest.raises(ApprovalRequiredError) as exc_info:
        await one.harness.run("do it", thread_id=THREAD_ID)

    assert exc_info.value is error  # identical error contract to the react path
    state = await one.harness._graph.aget_state({"configurable": {"thread_id": THREAD_ID}})
    assert state.values.get("resume_step_id") == "1"  # approval resumes the STEP (H4.4)
