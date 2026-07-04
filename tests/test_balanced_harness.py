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
    assert bridge._session_key == "telegram:123"
    assert bridge._run_id != ""


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
    # Bridge emitted the checklist events with run identity stamped.
    kinds = [e.kind for e in emitter.events]
    assert StatusEventKind.PLAN_CREATED in kinds
    assert StatusEventKind.PLAN_STEP_STARTED in kinds
    assert all(e.session_key == "telegram:1" for e in emitter.events)
    assert all(e.workspace == "balanced-test" for e in emitter.events)


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


def test_harness_config_rejects_unknown_groups() -> None:
    # reflection/ideation groups arrive with the next phase — a premature
    # `ideation:` key must fail fast rather than silently no-op.
    with pytest.raises(ValidationError):
        HarnessConfig.model_validate({"type": "balanced", "ideation": {"lens_tool": True}})


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
