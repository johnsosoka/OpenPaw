"""Tests for checkpoint reflection (DESIGN §3, decision §10.2).

Three layers:
- CheckpointReflector trigger math (every N completions, immediate on a
  failed flip) and fail-open verdict calls;
- the PlanEventBridge checkpoint hook (reflection.verdict emission, advisory
  appended to the write_todos ToolMessage on a not-ok verdict);
- config validation for the shared harness.reflection group (balanced
  fields + ultra regression pin).
"""

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.types import Command
from pydantic import ValidationError

from openpaw.agent.harness.checkpoint_reflection import (
    CheckpointOutcome,
    CheckpointReflector,
    _checkpoint_prompt,
    _recent_context,
)
from openpaw.agent.harness.modules.reflection import _VerdictSchema
from openpaw.agent.middleware.plan_event_bridge import PlanEventBridge, _append_advisory
from openpaw.agent.middleware.todo_list import Todo
from openpaw.core.config.models import HarnessConfig, ReflectionNodeConfig
from openpaw.model.status_event import StatusEvent, StatusEventKind


class FakeVerdictModel:
    """Chat-model stand-in whose structured output replays a scripted verdict."""

    def __init__(self, verdict: _VerdictSchema | Exception) -> None:
        self._verdict = verdict
        self.prompts: list[str] = []

    def with_structured_output(self, schema: Any) -> "FakeVerdictModel":
        assert schema is _VerdictSchema
        return self

    async def ainvoke(self, messages: list[Any]) -> Any:
        self.prompts.append(messages[0].content)
        if isinstance(self._verdict, Exception):
            raise self._verdict
        return self._verdict


def reflector_with(
    verdict: _VerdictSchema | Exception, every: int = 1
) -> tuple[CheckpointReflector, FakeVerdictModel]:
    model = FakeVerdictModel(verdict)
    reflector = CheckpointReflector(every=every, model_factory=lambda: model)  # type: ignore[arg-type, return-value]
    return reflector, model


def completed(description: str) -> dict[str, Any]:
    return {"step_id": "1", "description": description}


def failed(description: str, note: str = "boom") -> dict[str, Any]:
    return {"step_id": "1", "description": description, "failed": True, "note": note}


# ---------------------------------------------------------------------------
# Trigger math
# ---------------------------------------------------------------------------


def test_no_flips_never_triggers() -> None:
    reflector = CheckpointReflector(every=1)
    assert reflector.record_flips([]) is None


def test_every_n_completions_triggers_and_resets() -> None:
    reflector = CheckpointReflector(every=3)

    assert reflector.record_flips([completed("A")]) is None
    assert reflector.record_flips([completed("B")]) is None
    trigger = reflector.record_flips([completed("C")])
    assert trigger == completed("C")
    # Counter reset: the cycle starts over.
    assert reflector.record_flips([completed("D")]) is None


def test_failed_flip_triggers_immediately_and_resets_counter() -> None:
    reflector = CheckpointReflector(every=3)
    assert reflector.record_flips([completed("A")]) is None

    trigger = reflector.record_flips([failed("B")])
    assert trigger is not None and trigger.get("failed") is True

    # Failure reset the completion counter.
    assert reflector.record_flips([completed("C")]) is None


def test_batched_completions_count_together() -> None:
    reflector = CheckpointReflector(every=2)
    trigger = reflector.record_flips([completed("A"), completed("B")])
    assert trigger == completed("B")  # reflects against the latest flip


# ---------------------------------------------------------------------------
# Verdict call
# ---------------------------------------------------------------------------


async def test_observe_returns_outcome_from_structured_verdict() -> None:
    reflector, model = reflector_with(
        _VerdictSchema(action="revise_plan", step_succeeded=False, notes="step 2 unresolved")
    )
    todos: list[Todo] = [{"content": "Deploy", "status": "failed", "note": "no SSH"}]

    outcome = await reflector.observe([failed("Deploy", "no SSH")], todos, state={})

    assert outcome == CheckpointOutcome(
        verdict="revise_plan", step_succeeded=False, notes="step 2 unresolved"
    )
    assert not outcome.ok
    prompt = model.prompts[0]
    assert "[✗] Deploy — no SSH" in prompt
    assert "Step just failed: Deploy" in prompt


async def test_ok_outcome_for_advance_with_success() -> None:
    reflector, _ = reflector_with(
        _VerdictSchema(action="advance", step_succeeded=True, notes="fine")
    )
    outcome = await reflector.observe([completed("A")], [], state={})
    assert outcome is not None and outcome.ok


async def test_observe_below_threshold_makes_no_model_call() -> None:
    reflector, model = reflector_with(
        _VerdictSchema(action="advance", step_succeeded=True), every=5
    )
    assert await reflector.observe([completed("A")], [], state={}) is None
    assert model.prompts == []


async def test_verdict_failure_is_fail_open() -> None:
    reflector, _ = reflector_with(RuntimeError("model down"))
    assert await reflector.observe([completed("A")], [], state={}) is None


async def test_missing_model_is_fail_open() -> None:
    reflector = CheckpointReflector(every=1)  # no factory, no default provider
    assert await reflector.observe([completed("A")], [], state={}) is None


async def test_default_model_provider_is_used_when_no_factory() -> None:
    model = FakeVerdictModel(_VerdictSchema(action="advance", step_succeeded=True))
    reflector = CheckpointReflector(every=1)
    reflector.set_default_model_provider(lambda: model)  # type: ignore[arg-type, return-value]

    outcome = await reflector.observe([completed("A")], [], state={})
    assert outcome is not None and model.prompts


async def test_explicit_factory_wins_and_is_cached() -> None:
    explicit = FakeVerdictModel(_VerdictSchema(action="advance", step_succeeded=True))
    calls = 0

    def factory() -> Any:
        nonlocal calls
        calls += 1
        return explicit

    reflector = CheckpointReflector(every=1, model_factory=factory)
    reflector.set_default_model_provider(lambda: FakeVerdictModel(RuntimeError("wrong model")))  # type: ignore[arg-type, return-value]

    await reflector.observe([completed("A")], [], state={})
    await reflector.observe([completed("B")], [], state={})
    assert calls == 1  # cached after first use
    assert len(explicit.prompts) == 2


# ---------------------------------------------------------------------------
# Prompt inputs
# ---------------------------------------------------------------------------


def test_prompt_carries_checklist_flip_and_context() -> None:
    todos: list[dict[str, Any]] = [
        {"content": "Research", "status": "completed"},
        {"content": "Build", "status": "in_progress"},
    ]
    prompt = _checkpoint_prompt(todos, completed("Research"), context="Human: go")

    assert "[x] Research" in prompt
    assert "[~] Build" in prompt
    assert "Step just completed: Research" in prompt
    assert "Recent context:\nHuman: go" in prompt
    assert "advance" in prompt and "revise_plan" in prompt


def test_recent_context_truncates_and_labels_messages() -> None:
    state = {"messages": [HumanMessage("x" * 1000)]}
    context = _recent_context(state)
    assert context.startswith("HumanMessage: xxx")
    assert len(context) < 500


def test_recent_context_handles_missing_messages() -> None:
    assert _recent_context({}) == "(none)"
    assert _recent_context(None) == "(none)"


# ---------------------------------------------------------------------------
# Bridge checkpoint hook
# ---------------------------------------------------------------------------


class CaptureEmitter:
    def __init__(self) -> None:
        self.events: list[StatusEvent] = []

    async def emit(self, event: StatusEvent) -> None:
        self.events.append(event)

    def kinds(self) -> list[StatusEventKind]:
        return [e.kind for e in self.events]


def write_todos_request(new: list[Todo], prev: list[Todo]) -> Any:
    return SimpleNamespace(
        tool_call={"name": "write_todos", "args": {"todos": new}, "id": "c1"},
        state={"todos": prev},
    )


def tool_command(content: str = "Updated todo list") -> Command[Any]:
    return Command(
        update={"messages": [ToolMessage(content, tool_call_id="c1")]}
    )


async def test_bridge_emits_verdict_and_appends_advisory_on_not_ok() -> None:
    reflector, _ = reflector_with(
        _VerdictSchema(action="revise_plan", step_succeeded=False, notes="step unresolved")
    )
    emitter = CaptureEmitter()
    bridge = PlanEventBridge(emitter=emitter, workspace="ws", reflector=reflector)
    handler = AsyncMock(return_value=tool_command())

    prev: list[Todo] = [{"content": "Deploy", "status": "in_progress"}]
    new: list[Todo] = [{"content": "Deploy", "status": "failed", "note": "no SSH"}]
    result = await bridge.awrap_tool_call(write_todos_request(new, prev), handler)

    assert StatusEventKind.REFLECTION_VERDICT in emitter.kinds()
    verdict_event = next(
        e for e in emitter.events if e.kind is StatusEventKind.REFLECTION_VERDICT
    )
    assert verdict_event.payload == {
        "verdict": "revise_plan",
        "reason": "step unresolved",
        "step_succeeded": False,
    }
    message = result.update["messages"][0]
    assert "[checkpoint reflection — revise_plan] step unresolved" in message.content
    assert "course-correct" in message.content


async def test_bridge_ok_verdict_emits_event_without_advisory() -> None:
    reflector, _ = reflector_with(
        _VerdictSchema(action="advance", step_succeeded=True, notes="fine")
    )
    emitter = CaptureEmitter()
    bridge = PlanEventBridge(emitter=emitter, workspace="ws", reflector=reflector)
    handler = AsyncMock(return_value=tool_command())

    prev: list[Todo] = [{"content": "A", "status": "in_progress"}]
    new: list[Todo] = [{"content": "A", "status": "completed"}]
    result = await bridge.awrap_tool_call(write_todos_request(new, prev), handler)

    assert StatusEventKind.REFLECTION_VERDICT in emitter.kinds()
    assert "checkpoint reflection" not in result.update["messages"][0].content


async def test_bridge_no_reflection_below_threshold() -> None:
    reflector, model = reflector_with(
        _VerdictSchema(action="advance", step_succeeded=True), every=5
    )
    emitter = CaptureEmitter()
    bridge = PlanEventBridge(emitter=emitter, workspace="ws", reflector=reflector)
    handler = AsyncMock(return_value=tool_command())

    prev: list[Todo] = [{"content": "A", "status": "in_progress"}]
    new: list[Todo] = [{"content": "A", "status": "completed"}]
    await bridge.awrap_tool_call(write_todos_request(new, prev), handler)

    assert StatusEventKind.REFLECTION_VERDICT not in emitter.kinds()
    assert model.prompts == []


async def test_bridge_reflection_failure_never_breaks_the_tool_call() -> None:
    reflector, _ = reflector_with(RuntimeError("verdict model down"))
    bridge = PlanEventBridge(emitter=CaptureEmitter(), workspace="ws", reflector=reflector)
    command = tool_command()
    handler = AsyncMock(return_value=command)

    prev: list[Todo] = [{"content": "A", "status": "in_progress"}]
    new: list[Todo] = [{"content": "A", "status": "completed"}]
    result = await bridge.awrap_tool_call(write_todos_request(new, prev), handler)

    assert result is command  # untouched
    assert "checkpoint reflection" not in result.update["messages"][0].content


# ---------------------------------------------------------------------------
# Advisory injection shapes
# ---------------------------------------------------------------------------


def test_append_advisory_to_command_tool_message() -> None:
    result = _append_advisory(tool_command("base"), " advisory")
    assert result.update["messages"][0].content == "base advisory"


def test_append_advisory_to_bare_tool_message() -> None:
    message = ToolMessage("base", tool_call_id="c1")
    assert _append_advisory(message, " advisory").content == "base advisory"


def test_append_advisory_leaves_unknown_shapes_untouched() -> None:
    assert _append_advisory("plain string", " advisory") == "plain string"
    assert _append_advisory(None, " advisory") is None
    empty = Command(update={"todos": []})
    assert _append_advisory(empty, " advisory") is empty


# ---------------------------------------------------------------------------
# Config: shared harness.reflection group
# ---------------------------------------------------------------------------


def test_reflection_defaults_are_organic() -> None:
    config = HarnessConfig.model_validate({"type": "balanced"})
    assert config.reflection.mode == "organic"
    assert config.reflection.every == 3
    assert config.reflection.model is None


def test_reflection_checkpoint_fields_validate() -> None:
    config = HarnessConfig.model_validate(
        {
            "type": "balanced",
            "reflection": {"mode": "checkpoint", "every": 2, "model": "fast"},
        }
    )
    assert config.reflection.mode == "checkpoint"
    assert config.reflection.every == 2
    assert config.reflection.model == "fast"


def test_reflection_rejects_bad_mode_and_every() -> None:
    with pytest.raises(ValidationError):
        ReflectionNodeConfig.model_validate({"mode": "periodic"})
    with pytest.raises(ValidationError):
        ReflectionNodeConfig.model_validate({"mode": "checkpoint", "every": 0})
    with pytest.raises(ValidationError):
        ReflectionNodeConfig.model_validate({"mod": "checkpoint"})  # typo


def test_ultra_reflection_config_unaffected() -> None:
    """Regression pin: ultra's module-based reflection group still validates
    exactly as before, with the balanced fields inert at their defaults."""
    config = HarnessConfig.model_validate(
        {
            "type": "ultra",
            "reflection": {"module": "auto", "allowed": ["light", "full"], "model": "fast"},
        }
    )
    assert config.reflection.module == "auto"
    assert config.reflection.allowed == ["light", "full"]
    assert config.reflection.mode == "organic"  # balanced-only field, inert

    with pytest.raises(ValidationError):
        # `allowed` still requires module: auto
        HarnessConfig.model_validate(
            {"type": "ultra", "reflection": {"module": "light", "allowed": ["full"]}}
        )
