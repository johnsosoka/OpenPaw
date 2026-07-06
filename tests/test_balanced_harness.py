"""Tests for BalancedHarness (ADR-111): protocol conformance, factory
dispatch, middleware assembly, timeout override, config validation, and the
learning-loop harness-independence invariant (DESIGN §5)."""

import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import MemorySaver
from pydantic import ValidationError

from openpaw.agent.harness import AgentHarness, HarnessKind
from openpaw.agent.harness.balanced import BalancedHarness, build_balanced_middleware
from openpaw.agent.harness.ultra import UltraHarness
from openpaw.agent.middleware.plan_event_bridge import PlanEventBridge
from openpaw.agent.middleware.todo_list import Todo, TodoListMiddleware
from openpaw.agent.runner import AgentRunner
from openpaw.core.config.models import HarnessConfig, WorkspaceConfig
from openpaw.core.workspace import AgentWorkspace
from openpaw.model.status_event import StatusEventKind
from openpaw.workspace.agent_factory import AgentFactory


def make_workspace(tmp_path: Path, config: WorkspaceConfig | None = None) -> AgentWorkspace:
    (tmp_path / "AGENT.md").write_text("# Agent")
    return AgentWorkspace(
        name="balanced-test",
        path=tmp_path,
        agent_md="# Agent",
        user_md="# User",
        soul_md="# Soul",
        heartbeat_md="# Heartbeat",
        skills_path=tmp_path / "agent" / "skills",
        tools_path=tmp_path / "tools",
        config=config,
    )


def make_factory(
    workspace: AgentWorkspace, builtin_tools: list[Any] | None = None
) -> AgentFactory:
    return AgentFactory(
        workspace=workspace,
        model="openai:gpt-4o-mini",
        api_key="test",
        max_turns=10,
        temperature=0.7,
        region=None,
        timeout_seconds=30.0,
        builtin_tools=builtin_tools or [],
        workspace_tools=[],
        enabled_builtin_names=[],
        extra_model_kwargs={},
        middleware=[],
        logger=logging.getLogger("test"),
    )


def balanced_config(harness: dict[str, Any] | None = None) -> WorkspaceConfig:
    return WorkspaceConfig.model_validate({"harness": harness or {"type": "balanced"}})


# ---------------------------------------------------------------------------
# Factory dispatch
# ---------------------------------------------------------------------------


def test_factory_dispatches_balanced(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path, config=balanced_config())
    saver = MemorySaver()

    harness = make_factory(workspace).create_harness(checkpointer=saver)

    assert isinstance(harness, BalancedHarness)
    assert harness.kind == HarnessKind.BALANCED
    assert isinstance(harness, AgentHarness)
    assert harness.checkpointer is saver


def test_factory_react_path_unchanged(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path, config=WorkspaceConfig())
    harness = make_factory(workspace).create_harness()
    assert type(harness) is AgentRunner  # not the subclass
    assert harness.kind == HarnessKind.REACT
    assert harness._middleware == []  # no balanced additions leak into react


def test_factory_ultra_path_unchanged(tmp_path: Path) -> None:
    workspace = make_workspace(
        tmp_path, config=WorkspaceConfig.model_validate({"harness": {"type": "ultra"}})
    )
    harness = make_factory(workspace).create_harness()
    assert isinstance(harness, UltraHarness)


# ---------------------------------------------------------------------------
# Middleware assembly
# ---------------------------------------------------------------------------


def test_balanced_stack_has_bridge_before_todo_middleware(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path, config=balanced_config())
    harness = make_factory(workspace).create_harness()
    assert isinstance(harness, BalancedHarness)

    types = [type(m) for m in harness._middleware]
    assert types.index(PlanEventBridge) < types.index(TodoListMiddleware)


def test_plan_visibility_false_drops_the_bridge(tmp_path: Path) -> None:
    workspace = make_workspace(
        tmp_path,
        config=balanced_config({"type": "balanced", "plan": {"visibility": False}}),
    )
    harness = make_factory(workspace).create_harness()
    assert isinstance(harness, BalancedHarness)

    types = [type(m) for m in harness._middleware]
    assert PlanEventBridge not in types
    assert TodoListMiddleware in types  # the todo tool stays regardless


def test_build_balanced_middleware_order() -> None:
    extras = build_balanced_middleware(emitter=None, workspace_name="ws")
    assert [type(m) for m in extras] == [PlanEventBridge, TodoListMiddleware]
    assert [type(m) for m in build_balanced_middleware(None, "ws", plan_visibility=False)] == [
        TodoListMiddleware
    ]


def test_workspace_middleware_precedes_balanced_additions(tmp_path: Path) -> None:
    """Existing middleware (status/queue/approval) keeps its position."""
    from langchain.agents.middleware.types import AgentMiddleware

    class SentinelMiddleware(AgentMiddleware):
        pass

    sentinel = SentinelMiddleware()
    workspace = make_workspace(tmp_path, config=balanced_config())
    factory = make_factory(workspace)
    factory._middleware = [sentinel]

    harness = factory.create_harness()
    assert isinstance(harness, BalancedHarness)
    assert harness._middleware[0] is sentinel
    assert isinstance(harness._middleware[-1], TodoListMiddleware)


# ---------------------------------------------------------------------------
# Timeout override (harness.execution.timeout_seconds, DESIGN §6)
# ---------------------------------------------------------------------------


def test_execution_timeout_override_applies(tmp_path: Path) -> None:
    workspace = make_workspace(
        tmp_path,
        config=balanced_config(
            {"type": "balanced", "execution": {"timeout_seconds": 900}}
        ),
    )
    harness = make_factory(workspace).create_harness()
    assert harness.timeout_seconds == 900


def test_timeout_defaults_to_workspace_timeout(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path, config=balanced_config())
    harness = make_factory(workspace).create_harness()
    assert harness.timeout_seconds == 30.0


# ---------------------------------------------------------------------------
# Turn budget (harness.execution.max_turns, DESIGN §6)
# ---------------------------------------------------------------------------


def test_execution_max_turns_applies_to_balanced(tmp_path: Path) -> None:
    workspace = make_workspace(
        tmp_path,
        config=balanced_config({"type": "balanced", "execution": {"max_turns": 4}}),
    )
    harness = make_factory(workspace).create_harness()
    assert harness.max_turns == 4


def test_execution_max_turns_defaults_to_workspace_max_turns(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path, config=balanced_config())
    harness = make_factory(workspace).create_harness()
    assert harness.max_turns == 10  # factory default from make_factory


def test_execution_max_turns_applies_to_ultra_inner_runner(tmp_path: Path) -> None:
    workspace = make_workspace(
        tmp_path,
        config=WorkspaceConfig.model_validate(
            {"harness": {"type": "ultra", "execution": {"max_turns": 6}}}
        ),
    )
    harness = make_factory(workspace).create_harness()
    assert isinstance(harness, UltraHarness)
    assert harness._inner.max_turns == 6


def test_execution_max_turns_validation() -> None:
    from openpaw.core.config.models.harness import ExecutionConfig

    assert ExecutionConfig().max_turns is None
    assert ExecutionConfig.model_validate({"max_turns": 1}).max_turns == 1
    with pytest.raises(ValidationError):
        ExecutionConfig.model_validate({"max_turns": 0})


# ---------------------------------------------------------------------------
# Verdict timeout clamp (F8: verdict budget vs write_todos tool timeout)
# ---------------------------------------------------------------------------


def test_verdict_timeout_defaults_to_30s(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path, config=balanced_config())
    assert make_factory(workspace)._verdict_timeout() == 30.0


def test_verdict_timeout_clamps_under_small_tool_timeout(tmp_path: Path) -> None:
    workspace = make_workspace(
        tmp_path,
        config=WorkspaceConfig.model_validate(
            {
                "harness": {"type": "balanced"},
                "tool_timeouts": {"default_seconds": 20},
            }
        ),
    )
    assert make_factory(workspace)._verdict_timeout() == 10.0


def test_verdict_timeout_honors_write_todos_override(tmp_path: Path) -> None:
    workspace = make_workspace(
        tmp_path,
        config=WorkspaceConfig.model_validate(
            {
                "harness": {"type": "balanced"},
                "tool_timeouts": {
                    "default_seconds": 120,
                    "overrides": {"write_todos": 30},
                },
            }
        ),
    )
    assert make_factory(workspace)._verdict_timeout() == 15.0


def test_clamped_verdict_timeout_reaches_the_reflector(tmp_path: Path) -> None:
    workspace = make_workspace(
        tmp_path,
        config=WorkspaceConfig.model_validate(
            {
                "harness": {"type": "balanced", "reflection": {"mode": "checkpoint"}},
                "tool_timeouts": {"default_seconds": 20},
            }
        ),
    )
    harness = make_factory(workspace).create_harness()
    assert isinstance(harness, BalancedHarness)
    assert harness._plan_bridge is not None
    reflector = harness._plan_bridge.reflector
    assert reflector is not None
    assert reflector._verdict_timeout == 10.0


# ---------------------------------------------------------------------------
# Run-time behavior: bridge arming, todo state seam
# ---------------------------------------------------------------------------


async def test_run_arms_bridge_with_session_identity(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path, config=balanced_config())
    harness = make_factory(workspace).create_harness()
    assert isinstance(harness, BalancedHarness)

    with patch.object(AgentRunner, "run", new=AsyncMock(return_value="done")) as inner_run:
        result = await harness.run("hi", thread_id="telegram:123:conv1")

    assert result == "done"
    inner_run.assert_awaited_once()
    bridge = harness._plan_bridge
    assert bridge is not None
    assert bridge._run_ids.get("telegram:123", "") != ""


async def test_run_without_bridge_still_runs(tmp_path: Path) -> None:
    workspace = make_workspace(
        tmp_path,
        config=balanced_config({"type": "balanced", "plan": {"visibility": False}}),
    )
    harness = make_factory(workspace).create_harness()
    assert isinstance(harness, BalancedHarness)

    with patch.object(AgentRunner, "run", new=AsyncMock(return_value="done")):
        assert await harness.run("hi", session_id="s1") == "done"


async def test_get_todos_reads_checkpointed_state(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path, config=balanced_config())
    harness = make_factory(workspace).create_harness(checkpointer=MemorySaver())
    assert isinstance(harness, BalancedHarness)

    todos: list[Todo] = [{"content": "A", "status": "in_progress"}]
    fake_state = SimpleNamespace(values={"todos": todos})
    harness._agent = SimpleNamespace(aget_state=AsyncMock(return_value=fake_state))

    assert await harness.get_todos("telegram:1:conv1") == todos


async def test_get_todos_empty_for_unknown_thread(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path, config=balanced_config())
    harness = make_factory(workspace).create_harness(checkpointer=MemorySaver())
    assert isinstance(harness, BalancedHarness)
    assert await harness.get_todos("telegram:1:conv-nope") == []


async def test_get_todos_stateless_is_empty(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path, config=balanced_config())
    harness = make_factory(workspace).create_harness(checkpointer=None)
    assert isinstance(harness, BalancedHarness)
    assert await harness.get_todos("telegram:1:conv1") == []


def test_write_todos_tool_reaches_the_agent(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path, config=balanced_config())
    harness = make_factory(workspace).create_harness()
    assert isinstance(harness, BalancedHarness)

    todo_mw = next(m for m in harness._middleware if isinstance(m, TodoListMiddleware))
    assert [t.name for t in todo_mw.tools] == ["write_todos"]
    # And the compiled graph accepted the middleware stack without error.
    assert harness.agent_graph is not None


def test_rebuild_preserves_balanced_middleware(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path, config=balanced_config())
    harness = make_factory(workspace).create_harness()
    assert isinstance(harness, BalancedHarness)

    harness.rebuild_agent()

    types = [type(m) for m in harness._middleware]
    assert PlanEventBridge in types
    assert TodoListMiddleware in types


# ---------------------------------------------------------------------------
# Integration: write_todos through the real compiled graph
# ---------------------------------------------------------------------------


class ToolCallingFakeModel(GenericFakeChatModel):
    """Fake model that accepts tool binding and replays scripted turns."""

    def bind_tools(self, tools: Any, **kwargs: Any) -> Any:
        return self


async def test_todos_checkpoint_per_thread_and_bridge_emits(tmp_path: Path) -> None:
    """End to end: a scripted write_todos turn runs through the compiled
    balanced graph, todos land in per-thread checkpointed state, and the
    bridge emits plan.* events stamped with the run identity."""
    todos: list[Todo] = [
        {"content": "Research", "status": "in_progress"},
        {"content": "Build", "status": "pending"},
    ]
    model = ToolCallingFakeModel(
        messages=iter(
            [
                AIMessage(
                    content="",
                    tool_calls=[{"name": "write_todos", "args": {"todos": todos}, "id": "c1"}],
                ),
                AIMessage(content="done"),
            ]
        )
    )

    class CaptureEmitter:
        def __init__(self) -> None:
            self.events: list[Any] = []

        async def emit(self, event: Any) -> None:
            self.events.append(event)

    emitter = CaptureEmitter()
    workspace = make_workspace(tmp_path, config=balanced_config())
    factory = make_factory(workspace)
    factory.set_status_emitter(emitter)

    with patch.object(AgentRunner, "_create_model", return_value=model):
        harness = factory.create_harness(checkpointer=MemorySaver())
        assert isinstance(harness, BalancedHarness)
        result = await harness.run("plan and build", thread_id="telegram:1:conv1")

    assert result == "done"
    # Todos checkpointed on THIS thread, absent on others.
    assert await harness.get_todos("telegram:1:conv1") == todos
    assert await harness.get_todos("telegram:1:conv2") == []
    # Bridge emitted the checklist events with run identity stamped, preceded
    # by the module-agnostic planning intent (two-tier UX: route line, then
    # the checklist).
    kinds = [e.kind for e in emitter.events]
    assert StatusEventKind.PLAN_CREATED in kinds
    assert StatusEventKind.PLAN_STEP_STARTED in kinds
    intent = next(
        e
        for e in emitter.events
        if e.kind is StatusEventKind.NODE_ENTERED and e.payload == {"route": "plan"}
    )
    assert kinds.index(StatusEventKind.NODE_ENTERED) < kinds.index(
        StatusEventKind.PLAN_CREATED
    )
    assert intent.node is None
    assert all(e.session_key == "telegram:1" for e in emitter.events)
    assert all(e.workspace == "balanced-test" for e in emitter.events)


class _NoOpEditChannel:
    """Fake channel that mirrors Telegram: an edit to identical text fails.

    Telegram raises BadRequest "message is not modified" on a no-op edit and
    the adapter returns False — the condition that turned a redundant
    identical checklist render into a duplicate message.
    """

    def __init__(self) -> None:
        self.sends: list[str] = []
        self.edits: list[str] = []
        self._n = 0
        self._by_id: dict[str, str] = {}

    async def send_message(self, session_key: str, content: str) -> Any:
        self._n += 1
        self.sends.append(content)
        self._by_id[str(self._n)] = content
        return SimpleNamespace(id=str(self._n))

    async def edit_message(self, session_key: str, message_id: str, content: str) -> bool:
        if self._by_id.get(message_id) == content:
            return False  # "message is not modified"
        self._by_id[message_id] = content
        self.edits.append(content)
        return True

    async def delete_message(self, session_key: str, message_id: str) -> bool:
        return True

    async def send_typing(self, session_key: str) -> None:
        return None


async def test_balanced_plan_checklist_renders_once_end_to_end(tmp_path: Path) -> None:
    """Regression (duplicate checklist): a real balanced run whose first
    write_todos marks step 1 in_progress emits plan.created + a redundant
    step_started for that same step. Driven through the REAL bus -> real
    PlanChannelSink -> real StatusUpdateMiddleware -> PlanStatusRenderer, with
    a Telegram-like channel (no-op edit returns False), exactly ONE checklist
    message must reach the channel — not two."""
    from openpaw.agent.middleware.status_update import StatusUpdateMiddleware
    from openpaw.core.config.models import StatusUpdatesConfig
    from openpaw.runtime.status_bus import PlanChannelSink, StatusBus

    todos: list[Todo] = [
        {"content": "Create notes/ folder", "status": "in_progress"},
        {"content": "Write a.md", "status": "pending"},
        {"content": "Write b.md", "status": "pending"},
    ]
    model = ToolCallingFakeModel(
        messages=iter(
            [
                AIMessage(
                    content="",
                    tool_calls=[{"name": "write_todos", "args": {"todos": todos}, "id": "c1"}],
                ),
                AIMessage(content="done"),
            ]
        )
    )

    # Wire status plumbing exactly as init_agent does: one bus, one middleware,
    # one PlanChannelSink.
    bus = StatusBus("balanced-test")
    mw = StatusUpdateMiddleware(
        StatusUpdatesConfig(enabled=True, min_interval_seconds=0),
        emitter=bus,
        workspace="balanced-test",
    )
    bus.add_sink(PlanChannelSink(mw))

    workspace = make_workspace(tmp_path, config=balanced_config())
    factory = AgentFactory(
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
        middleware=[mw],
        logger=logging.getLogger("test"),
    )
    factory.set_status_emitter(bus)

    channel = _NoOpEditChannel()
    mw.set_context(channel, "telegram:1")

    with patch.object(AgentRunner, "_create_model", return_value=model):
        harness = factory.create_harness(checkpointer=MemorySaver())
        await harness.run("plan and build", thread_id="telegram:1:conv1")

    checklists = [s for s in channel.sends if "Plan" in s]
    assert len(checklists) == 1, channel.sends


async def test_balanced_plan_final_tick_survives_two_turns_end_to_end(
    tmp_path: Path,
) -> None:
    """Regression (multi-turn checklist): a balanced plan spanning two user
    turns must tick its final step. Turn 1 leaves the last step in_progress;
    the run ends and the next turn re-arms (reset -> set_context, as
    MessageProcessor does). Turn 2's write_todos flips the last step to
    completed — a bare plan.step_completed (the todo list persists in the
    checkpointer, so no plan.created). The SAME checklist must edit to the
    final [x], with no duplicate message. Driven through the real bus ->
    PlanChannelSink -> StatusUpdateMiddleware -> PlanStatusRenderer."""
    from openpaw.agent.middleware.status_update import StatusUpdateMiddleware
    from openpaw.core.config.models import StatusUpdatesConfig
    from openpaw.runtime.status_bus import PlanChannelSink, StatusBus

    turn1: list[Todo] = [
        {"content": "Draft outline", "status": "completed"},
        {"content": "Write section", "status": "completed"},
        {"content": "Final review", "status": "in_progress"},
    ]
    turn2 = [{**t, "status": "completed"} if t["content"] == "Final review" else t for t in turn1]
    model = ToolCallingFakeModel(
        messages=iter(
            [
                AIMessage(
                    content="",
                    tool_calls=[{"name": "write_todos", "args": {"todos": turn1}, "id": "c1"}],
                ),
                AIMessage(content="turn 1 done"),
                AIMessage(
                    content="",
                    tool_calls=[{"name": "write_todos", "args": {"todos": turn2}, "id": "c2"}],
                ),
                AIMessage(content="turn 2 done"),
            ]
        )
    )

    bus = StatusBus("balanced-test")
    mw = StatusUpdateMiddleware(
        StatusUpdatesConfig(enabled=True, min_interval_seconds=0),
        emitter=bus,
        workspace="balanced-test",
    )
    bus.add_sink(PlanChannelSink(mw))

    workspace = make_workspace(tmp_path, config=balanced_config())
    factory = AgentFactory(
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
        middleware=[mw],
        logger=logging.getLogger("test"),
    )
    factory.set_status_emitter(bus)

    channel = _NoOpEditChannel()

    with patch.object(AgentRunner, "_create_model", return_value=model):
        harness = factory.create_harness(checkpointer=MemorySaver())

        # Turn 1: same thread; leaves "Final review" in_progress.
        mw.set_context(channel, "telegram:1")
        await harness.run("start the doc", thread_id="telegram:1:conv1")
        mw.reset()

        # Turn 2: continue on the SAME thread; ticks the final step.
        mw.set_context(channel, "telegram:1")
        await harness.run("finish it", thread_id="telegram:1:conv1")

    checklists = [s for s in channel.sends if "Plan" in s]
    assert len(checklists) == 1, channel.sends  # no duplicate across turns
    assert any("[x] 3. Final review" in e for e in channel.edits), channel.edits


# ---------------------------------------------------------------------------
# Config validation
# ---------------------------------------------------------------------------


def test_harness_config_accepts_balanced() -> None:
    config = HarnessConfig.model_validate({"type": "balanced"})
    assert config.type == "balanced"
    assert config.plan.visibility is True  # default


def test_harness_config_plan_visibility_toggle() -> None:
    config = HarnessConfig.model_validate(
        {"type": "balanced", "plan": {"visibility": False}}
    )
    assert config.plan.visibility is False


def test_harness_config_rejects_unknown_type() -> None:
    with pytest.raises(ValidationError):
        HarnessConfig.model_validate({"type": "planner"})  # renamed to ultra


def test_harness_config_rejects_plan_typos() -> None:
    with pytest.raises(ValidationError):
        HarnessConfig.model_validate({"type": "balanced", "plan": {"visibilty": True}})


def test_harness_config_ideation_defaults() -> None:
    config = HarnessConfig.model_validate({"type": "balanced"})
    assert config.ideation.lens_tool is True
    assert config.ideation.lens_count == 3


def test_harness_config_ideation_group_validates() -> None:
    config = HarnessConfig.model_validate(
        {"type": "balanced", "ideation": {"lens_tool": False, "lens_count": 5}}
    )
    assert config.ideation.lens_tool is False
    assert config.ideation.lens_count == 5


def test_harness_config_ideation_rejects_bad_values() -> None:
    with pytest.raises(ValidationError):
        HarnessConfig.model_validate({"type": "balanced", "ideation": {"lens_count": 0}})
    with pytest.raises(ValidationError):
        HarnessConfig.model_validate({"type": "balanced", "ideation": {"lens_count": 8}})
    with pytest.raises(ValidationError):
        HarnessConfig.model_validate({"type": "balanced", "ideation": {"lens_tools": True}})


# ---------------------------------------------------------------------------
# Lens tool registration (DESIGN §4/§10.3: balanced-only, config-gated)
# ---------------------------------------------------------------------------


def _tool_names(harness: Any) -> list[str]:
    return [getattr(t, "name", "") for t in (harness.additional_tools or [])]


def test_lens_tool_registered_by_default_on_balanced(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path, config=balanced_config())
    harness = make_factory(workspace).create_harness()
    assert "explore_lenses" in _tool_names(harness)


def test_lens_tool_disabled_by_config(tmp_path: Path) -> None:
    workspace = make_workspace(
        tmp_path,
        config=balanced_config({"type": "balanced", "ideation": {"lens_tool": False}}),
    )
    harness = make_factory(workspace).create_harness()
    assert "explore_lenses" not in _tool_names(harness)


def test_lens_tool_absent_on_react_even_when_configured(tmp_path: Path) -> None:
    workspace = make_workspace(
        tmp_path,
        config=WorkspaceConfig.model_validate(
            {"harness": {"type": "react", "ideation": {"lens_tool": True}}}
        ),
    )
    harness = make_factory(workspace).create_harness()
    assert "explore_lenses" not in _tool_names(harness)


def test_recitation_line_present_when_lens_tool_enabled(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path, config=balanced_config())
    harness = make_factory(workspace).create_harness()
    todo_mw = next(m for m in harness._middleware if isinstance(m, TodoListMiddleware))
    assert "explore_lenses" in todo_mw._guidance


def test_recitation_line_absent_when_lens_tool_disabled(tmp_path: Path) -> None:
    workspace = make_workspace(
        tmp_path,
        config=balanced_config({"type": "balanced", "ideation": {"lens_tool": False}}),
    )
    harness = make_factory(workspace).create_harness()
    todo_mw = next(m for m in harness._middleware if isinstance(m, TodoListMiddleware))
    assert "explore_lenses" not in todo_mw._guidance


# ---------------------------------------------------------------------------
# Checkpoint reflection wiring (DESIGN §3/§10.2)
# ---------------------------------------------------------------------------


def test_organic_mode_wires_no_reflector(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path, config=balanced_config())
    harness = make_factory(workspace).create_harness()
    assert isinstance(harness, BalancedHarness)
    assert harness._plan_bridge is not None
    assert harness._plan_bridge.reflector is None


def test_checkpoint_mode_wires_reflector_with_runner_model_fallback(tmp_path: Path) -> None:
    workspace = make_workspace(
        tmp_path,
        config=balanced_config(
            {"type": "balanced", "reflection": {"mode": "checkpoint", "every": 2}}
        ),
    )
    harness = make_factory(workspace).create_harness()
    assert isinstance(harness, BalancedHarness)
    bridge = harness._plan_bridge
    assert bridge is not None
    reflector = bridge.reflector
    assert reflector is not None
    assert reflector._every == 2
    # No explicit model pointer -> the runner's model instance is the fallback.
    assert reflector._model_factory is None
    assert reflector._default_model_provider is not None
    assert reflector._resolve_model() is harness._model_instance


def test_checkpoint_with_visibility_off_keeps_bridge_without_emitter(tmp_path: Path) -> None:
    """The bridge is reflection's counting seam: visibility off suppresses
    status events (no emitter) but the checkpoint nudge path stays alive."""
    workspace = make_workspace(
        tmp_path,
        config=balanced_config(
            {
                "type": "balanced",
                "plan": {"visibility": False},
                "reflection": {"mode": "checkpoint"},
            }
        ),
    )
    harness = make_factory(workspace).create_harness()
    assert isinstance(harness, BalancedHarness)
    bridge = harness._plan_bridge
    assert bridge is not None
    assert bridge._emitter is None
    assert bridge.reflector is not None


# ---------------------------------------------------------------------------
# Learning-loop conformance (DESIGN §5 hard invariant)
# ---------------------------------------------------------------------------


@tool
def manage_skill(action: str) -> str:
    """Manage agent skills (stand-in for the real builtin)."""
    return action


@pytest.mark.parametrize("harness_type", ["react", "balanced", "ultra"])
def test_skill_tooling_is_harness_independent(tmp_path: Path, harness_type: str) -> None:
    """manage_skill availability rides the builtin toolbelt, not the topology.

    The learning loop wires at workspace level (WorkspaceRunner filters
    manage_skill on learning.enabled BEFORE the factory is built); every
    harness type must expose whatever builtins survive that filter.
    """
    workspace = make_workspace(
        tmp_path,
        config=WorkspaceConfig.model_validate(
            {"harness": {"type": harness_type}, "learning": {"enabled": True}}
        ),
    )
    harness = make_factory(workspace, builtin_tools=[manage_skill]).create_harness()

    tool_names = [getattr(t, "name", "") for t in harness.additional_tools]
    assert "manage_skill" in tool_names
