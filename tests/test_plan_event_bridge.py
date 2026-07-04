"""Tests for PlanEventBridge (balanced harness, DESIGN §2.1).

Three layers:
- compute_plan_events diff semantics (created / started / completed /
  failed / revised, reorder tolerance, no spurious step_completed);
- the middleware wrapper (interception, arming, best-effort emission);
- payload parity — bridge-emitted events fed through the REAL
  PlanStatusRenderer must draw the checklist, the ✗ failure mark, and the
  failure note phase line.
"""

import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

from langchain_core.messages import ToolMessage
from langgraph.types import Command

from openpaw.agent.harness.checkpoint_reflection import CheckpointReflector
from openpaw.agent.middleware.plan_event_bridge import (
    PlanEventBridge,
    compute_plan_events,
    serialize_plan,
)
from openpaw.agent.middleware.plan_status import PlanStatusRenderer
from openpaw.agent.middleware.todo_list import Todo
from openpaw.model.status_event import StatusEvent, StatusEventKind

WORKSPACE = "ws"
SESSION = "telegram:123456"


class CaptureEmitter:
    """In-memory StatusEmitter for event assertions."""

    def __init__(self) -> None:
        self.events: list[StatusEvent] = []

    async def emit(self, event: StatusEvent) -> None:
        self.events.append(event)

    def kinds(self) -> list[StatusEventKind]:
        return [e.kind for e in self.events]


def todo(content: str, status: str = "pending", note: str = "") -> Todo:
    item: Todo = {"content": content, "status": status}  # type: ignore[typeddict-item]
    if note:
        item["note"] = note
    return item


def kinds_of(events: list[tuple[StatusEventKind, dict[str, Any]]]) -> list[StatusEventKind]:
    return [kind for kind, _ in events]


# ---------------------------------------------------------------------------
# Diff semantics: created
# ---------------------------------------------------------------------------


def test_first_write_emits_created_with_positional_ids() -> None:
    new = [todo("Research", "in_progress"), todo("Build"), todo("Test")]

    events, revision = compute_plan_events([], new, revision=5)

    assert revision == 0  # created resets the revision counter
    assert kinds_of(events) == [
        StatusEventKind.PLAN_CREATED,
        StatusEventKind.PLAN_STEP_STARTED,  # first item written in_progress
    ]
    plan = events[0][1]["plan"]
    assert plan["revision"] == 0
    assert [s["id"] for s in plan["steps"]] == ["1", "2", "3"]
    assert plan["steps"][0]["status"] == "in_progress"
    assert events[1][1] == {"step_id": "1", "description": "Research"}


def test_empty_new_list_emits_nothing() -> None:
    events, revision = compute_plan_events([todo("A", "completed")], [], revision=2)
    assert events == []
    assert revision == 2


def test_empty_to_empty_emits_nothing() -> None:
    assert compute_plan_events([], [], revision=0) == ([], 0)


# ---------------------------------------------------------------------------
# Diff semantics: pure status flips
# ---------------------------------------------------------------------------


def test_status_flip_to_in_progress_emits_step_started() -> None:
    prev = [todo("A", "completed"), todo("B")]
    new = [todo("A", "completed"), todo("B", "in_progress")]

    events, revision = compute_plan_events(prev, new, revision=0)

    assert events == [
        (StatusEventKind.PLAN_STEP_STARTED, {"step_id": "2", "description": "B"})
    ]
    assert revision == 0


def test_status_flip_to_completed_emits_step_completed() -> None:
    prev = [todo("A", "in_progress"), todo("B")]
    new = [todo("A", "completed"), todo("B", "in_progress")]

    events, _ = compute_plan_events(prev, new, revision=0)

    assert kinds_of(events) == [
        StatusEventKind.PLAN_STEP_COMPLETED,
        StatusEventKind.PLAN_STEP_STARTED,
    ]
    assert events[0][1] == {"step_id": "1", "description": "A"}
    assert "failed" not in events[0][1]


def test_status_flip_to_failed_carries_failure_payload() -> None:
    prev = [todo("Deploy", "in_progress")]
    new = [todo("Deploy", "failed", note="no SSH access")]

    events, _ = compute_plan_events(prev, new, revision=0)

    assert events == [
        (
            StatusEventKind.PLAN_STEP_COMPLETED,
            {"step_id": "1", "description": "Deploy", "failed": True, "note": "no SSH access"},
        )
    ]


def test_status_regression_falls_back_to_revised() -> None:
    """completed -> pending is not a forward transition: authoritative revise."""
    prev = [todo("A", "completed"), todo("B", "in_progress")]
    new = [todo("A"), todo("B", "in_progress")]

    events, revision = compute_plan_events(prev, new, revision=0)

    assert kinds_of(events) == [StatusEventKind.PLAN_REVISED]
    assert revision == 1
    assert events[0][1]["plan"]["revision"] == 1


def test_unchanged_list_emits_nothing() -> None:
    prev = [todo("A", "in_progress"), todo("B")]
    events, revision = compute_plan_events(prev, list(prev), revision=3)
    assert events == []
    assert revision == 3


# ---------------------------------------------------------------------------
# Diff semantics: content changes and reorders
# ---------------------------------------------------------------------------


def test_content_change_emits_revised() -> None:
    prev = [todo("A", "completed"), todo("B", "in_progress")]
    new = [todo("A", "completed"), todo("B", "in_progress"), todo("C")]

    events, revision = compute_plan_events(prev, new, revision=0)

    assert kinds_of(events) == [StatusEventKind.PLAN_REVISED]
    assert revision == 1
    steps = events[0][1]["plan"]["steps"]
    assert [s["description"] for s in steps] == ["A", "B", "C"]
    assert steps[0]["status"] == "done"  # completed maps to plan vocabulary


def test_reorder_emits_revised_without_spurious_step_events() -> None:
    prev = [todo("A", "in_progress"), todo("B"), todo("C")]
    new = [todo("B"), todo("C"), todo("A", "in_progress")]

    events, _ = compute_plan_events(prev, new, revision=0)

    # A reorder repositions ids, so a full revision is correct; what would
    # be WRONG is a spurious completion (or a re-started A).
    assert kinds_of(events) == [StatusEventKind.PLAN_REVISED]


def test_rewrite_with_newly_started_step_emits_revised_plus_started() -> None:
    """The failure playbook: rewrite remaining todos AND start the next one."""
    prev = [todo("A", "completed"), todo("B", "in_progress"), todo("C")]
    new = [todo("A", "completed"), todo("B", "failed", note="flaky dep"), todo("Fix dep", "in_progress")]

    events, _ = compute_plan_events(prev, new, revision=0)

    assert kinds_of(events) == [
        StatusEventKind.PLAN_REVISED,
        StatusEventKind.PLAN_STEP_STARTED,
        StatusEventKind.PLAN_STEP_COMPLETED,
    ]
    started = events[1][1]
    assert started == {"step_id": "3", "description": "Fix dep"}
    failed = events[2][1]
    assert failed["failed"] is True
    assert failed["note"] == "flaky dep"
    assert failed["step_id"] == "2"  # id in the NEW plan


def test_content_change_never_emits_plain_step_completed() -> None:
    """Spurious plan.revised is acceptable; spurious step_completed is not."""
    prev = [todo("A", "in_progress"), todo("B")]
    new = [todo("A reworded", "completed"), todo("B", "in_progress")]

    events, _ = compute_plan_events(prev, new, revision=0)

    completed = [p for k, p in events if k is StatusEventKind.PLAN_STEP_COMPLETED]
    assert completed == []  # the revised payload carries the completion


def test_serialize_plan_includes_notes() -> None:
    plan = serialize_plan([todo("Deploy", "failed", note="no SSH")], revision=1)
    assert plan["steps"][0]["note"] == "no SSH"
    assert plan["objective"] == ""


# ---------------------------------------------------------------------------
# Middleware wrapper
# ---------------------------------------------------------------------------


def make_runtime(thread_id: str | None) -> Any:
    configurable = {"thread_id": thread_id} if thread_id else {}
    return SimpleNamespace(config={"configurable": configurable})


def make_request(
    name: str = "write_todos",
    todos: list[Todo] | None = None,
    state_todos: list[Todo] | None = None,
    thread_id: str | None = f"{SESSION}:conv-1",
) -> Any:
    return SimpleNamespace(
        tool_call={"name": name, "args": {"todos": todos or []}, "id": "call-1"},
        state={"todos": state_todos or []},
        runtime=make_runtime(thread_id),
    )


def todo_command(todos: list[Todo] | None = None) -> Command[Any]:
    """The shape a successful write_todos handler returns."""
    return Command(
        update={
            "todos": todos or [],
            "messages": [ToolMessage("Updated todo list", tool_call_id="call-1")],
        }
    )


async def test_bridge_ignores_other_tools() -> None:
    emitter = CaptureEmitter()
    bridge = PlanEventBridge(emitter=emitter, workspace=WORKSPACE)
    handler = AsyncMock(return_value="result")

    result = await bridge.awrap_tool_call(make_request(name="read_file"), handler)

    assert result == "result"
    assert emitter.events == []


async def test_bridge_emits_stamped_events() -> None:
    emitter = CaptureEmitter()
    bridge = PlanEventBridge(emitter=emitter, workspace=WORKSPACE)
    bridge.arm(session_key=SESSION, run_id="run-42")
    command = todo_command()
    handler = AsyncMock(return_value=command)

    request = make_request(todos=[todo("Research", "in_progress"), todo("Build")])
    result = await bridge.awrap_tool_call(request, handler)

    assert result is command
    handler.assert_awaited_once_with(request)
    assert emitter.kinds() == [
        StatusEventKind.PLAN_CREATED,
        StatusEventKind.PLAN_STEP_STARTED,
    ]
    for event in emitter.events:
        assert event.workspace == WORKSPACE
        assert event.session_key == SESSION
        assert event.run_id == "run-42"


async def test_bridge_diffs_against_checkpointed_state() -> None:
    emitter = CaptureEmitter()
    bridge = PlanEventBridge(emitter=emitter, workspace=WORKSPACE)
    bridge.arm(session_key=SESSION, run_id="run-1")
    handler = AsyncMock(return_value=todo_command())

    prev = [todo("A", "in_progress"), todo("B")]
    new = [todo("A", "completed"), todo("B", "in_progress")]
    await bridge.awrap_tool_call(make_request(todos=new, state_todos=prev), handler)

    assert emitter.kinds() == [
        StatusEventKind.PLAN_STEP_COMPLETED,
        StatusEventKind.PLAN_STEP_STARTED,
    ]


async def test_bridge_without_emitter_is_passthrough() -> None:
    bridge = PlanEventBridge(emitter=None, workspace=WORKSPACE)
    command = todo_command()
    handler = AsyncMock(return_value=command)
    assert await bridge.awrap_tool_call(make_request(todos=[todo("A")]), handler) is command


async def test_emitter_failure_never_breaks_the_tool_call() -> None:
    class ExplodingEmitter:
        async def emit(self, event: StatusEvent) -> None:
            raise RuntimeError("bus down")

    bridge = PlanEventBridge(emitter=ExplodingEmitter(), workspace=WORKSPACE)
    command = todo_command()
    handler = AsyncMock(return_value=command)

    assert await bridge.awrap_tool_call(make_request(todos=[todo("A")]), handler) is command


async def test_error_tool_message_emits_no_events_and_skips_reflection() -> None:
    """A failed write_todos (validation-error ToolMessage) leaves state
    unchanged: no plan events, and the reflector cadence must not advance."""

    class SpyModel:
        def __init__(self) -> None:
            self.calls = 0

        def with_structured_output(self, schema: Any) -> "SpyModel":
            self.calls += 1
            return self

    model = SpyModel()
    reflector = CheckpointReflector(every=1, model_factory=lambda: model)  # type: ignore[arg-type, return-value]
    emitter = CaptureEmitter()
    bridge = PlanEventBridge(emitter=emitter, workspace=WORKSPACE, reflector=reflector)
    bridge.arm(session_key=SESSION, run_id="run-1")

    error = ToolMessage("validation failed", tool_call_id="call-1", status="error")
    handler = AsyncMock(return_value=error)
    prev = [todo("A", "in_progress")]
    new = [todo("A", "completed")]  # a would-be completion flip

    result = await bridge.awrap_tool_call(
        make_request(todos=new, state_todos=prev), handler
    )

    assert result is error
    assert emitter.events == []
    assert model.calls == 0
    assert reflector._completed_since_verdict == {}


async def test_non_command_result_emits_no_events() -> None:
    """A timeout-style plain ToolMessage (status success) is also not a
    state-updating Command: no events may fire from the args."""
    emitter = CaptureEmitter()
    bridge = PlanEventBridge(emitter=emitter, workspace=WORKSPACE)
    timeout_stub = ToolMessage("[Tool 'write_todos' timed out]", tool_call_id="call-1")
    handler = AsyncMock(return_value=timeout_stub)

    result = await bridge.awrap_tool_call(
        make_request(todos=[todo("A", "in_progress")]), handler
    )

    assert result is timeout_stub
    assert emitter.events == []


async def test_concurrent_sessions_keep_their_own_identity() -> None:
    """F2 regression: arming session B mid-A-run must not re-stamp A's
    events — identity is derived per call from the thread config."""
    emitter = CaptureEmitter()
    bridge = PlanEventBridge(emitter=emitter, workspace=WORKSPACE)
    session_a, session_b = "telegram:111", "telegram:222"
    gate = asyncio.Event()

    async def slow_handler(request: Any) -> Command[Any]:
        await gate.wait()
        return todo_command()

    async def fast_handler(request: Any) -> Command[Any]:
        return todo_command()

    bridge.arm(session_key=session_a, run_id="run-A")
    task_a = asyncio.create_task(
        bridge.awrap_tool_call(
            make_request(todos=[todo("A1", "in_progress")], thread_id=f"{session_a}:conv"),
            slow_handler,
        )
    )
    await asyncio.sleep(0)  # A is inside its handler, parked on the gate

    # B arms and completes an entire write while A's call is in flight.
    bridge.arm(session_key=session_b, run_id="run-B")
    await bridge.awrap_tool_call(
        make_request(todos=[todo("B1", "in_progress")], thread_id=f"{session_b}:conv"),
        fast_handler,
    )
    gate.set()
    await task_a

    a_events = [e for e in emitter.events if e.session_key == session_a]
    b_events = [e for e in emitter.events if e.session_key == session_b]
    assert a_events and b_events
    assert len(a_events) + len(b_events) == len(emitter.events)
    assert all(e.run_id == "run-A" for e in a_events)
    assert all(e.run_id == "run-B" for e in b_events)


async def test_revision_counters_are_per_session() -> None:
    """A content revision in one session must not bump another's counter."""
    emitter = CaptureEmitter()
    bridge = PlanEventBridge(emitter=emitter, workspace=WORKSPACE)
    handler = AsyncMock(return_value=todo_command())

    async def write(session: str, prev: list[Todo], new: list[Todo]) -> None:
        await bridge.awrap_tool_call(
            make_request(todos=new, state_todos=prev, thread_id=f"{session}:conv"),
            handler,
        )

    # Session A: create, then a content change -> rev 1.
    await write("telegram:111", [], [todo("A", "in_progress")])
    await write("telegram:111", [todo("A", "in_progress")], [todo("A2", "in_progress")])
    # Session B: create, then a content change -> ITS rev 1 (not 2).
    await write("telegram:222", [], [todo("B", "in_progress")])
    await write("telegram:222", [todo("B", "in_progress")], [todo("B2", "in_progress")])

    revisions = [
        e.payload["plan"]["revision"]
        for e in emitter.events
        if e.kind is StatusEventKind.PLAN_REVISED
    ]
    assert revisions == [1, 1]


async def test_explore_lenses_call_emits_lenses_selected_phase() -> None:
    """DESIGN §4: intercepting explore_lenses emits the existing ideonomy
    module.phase payload so the renderer announces the lens exploration."""
    from openpaw.agent.harness.modules.ideonomy.selector import select_lenses

    emitter = CaptureEmitter()
    bridge = PlanEventBridge(emitter=emitter, workspace=WORKSPACE, lens_count=3)
    bridge.arm(session_key=SESSION, run_id="run-7")
    handler = AsyncMock(return_value="lens scaffold")

    topic = "brainstorm a product name"
    request = SimpleNamespace(
        tool_call={"name": "explore_lenses", "args": {"topic": topic}, "id": "c1"},
        state={},
        runtime=make_runtime(f"{SESSION}:conv-1"),
    )
    result = await bridge.awrap_tool_call(request, handler)

    assert result == "lens scaffold"
    handler.assert_awaited_once_with(request)
    assert emitter.kinds() == [StatusEventKind.MODULE_PHASE]
    event = emitter.events[0]
    expected_themes = " · ".join(lens.theme for lens in select_lenses(topic, 3))
    assert event.payload == {
        "kind": "creative",
        "module": "ideonomy",
        "phase": "lenses_selected",
        "total": 3,
        "detail": expected_themes,
    }
    assert event.session_key == SESSION
    assert event.run_id == "run-7"
    assert event.workspace == WORKSPACE


async def test_explore_lenses_emission_failure_never_breaks_the_tool_call() -> None:
    class ExplodingEmitter:
        async def emit(self, event: StatusEvent) -> None:
            raise RuntimeError("bus down")

    bridge = PlanEventBridge(emitter=ExplodingEmitter(), workspace=WORKSPACE)
    handler = AsyncMock(return_value="scaffold")
    request = SimpleNamespace(
        tool_call={"name": "explore_lenses", "args": {"topic": "t"}, "id": "c1"},
        state={},
        runtime=make_runtime(f"{SESSION}:conv-1"),
    )
    assert await bridge.awrap_tool_call(request, handler) == "scaffold"


async def test_malformed_args_never_break_the_tool_call() -> None:
    emitter = CaptureEmitter()
    bridge = PlanEventBridge(emitter=emitter, workspace=WORKSPACE)
    command = todo_command()
    handler = AsyncMock(return_value=command)
    request = SimpleNamespace(
        tool_call={"name": "write_todos", "args": {"todos": "not-a-list"}, "id": "c1"},
        state={},
        runtime=make_runtime(f"{SESSION}:conv-1"),
    )

    assert await bridge.awrap_tool_call(request, handler) is command
    assert emitter.events == []


async def test_request_without_runtime_is_fail_open() -> None:
    """Unit stubs / out-of-graph calls carry no runtime: events still emit,
    just with blank identity."""
    emitter = CaptureEmitter()
    bridge = PlanEventBridge(emitter=emitter, workspace=WORKSPACE)
    handler = AsyncMock(return_value=todo_command())

    await bridge.awrap_tool_call(
        make_request(todos=[todo("A", "in_progress")], thread_id=None), handler
    )

    assert emitter.kinds() == [
        StatusEventKind.PLAN_CREATED,
        StatusEventKind.PLAN_STEP_STARTED,
    ]
    assert all(e.session_key is None for e in emitter.events)


# ---------------------------------------------------------------------------
# Payload parity with the real renderer
# ---------------------------------------------------------------------------


class MockMessage:
    def __init__(self, id: str) -> None:
        self.id = id


class MockChannel:
    def __init__(self) -> None:
        self.sent: list[str] = []
        self.edited: list[str] = []
        self._counter = 0

    async def send_message(self, session_key: str, content: str) -> MockMessage:
        self._counter += 1
        self.sent.append(content)
        return MockMessage(str(self._counter))

    async def edit_message(self, session_key: str, message_id: str, content: str) -> bool:
        self.edited.append(content)
        return True


def _stamp(kind: StatusEventKind, payload: dict[str, Any]) -> StatusEvent:
    return StatusEvent(
        kind=kind, workspace=WORKSPACE, session_key=SESSION, run_id="r1", payload=payload
    )


async def test_bridge_events_drive_the_real_renderer() -> None:
    """End-to-end payload parity: diff output -> PlanStatusRenderer."""
    renderer = PlanStatusRenderer(use_emojis=False)
    channel = MockChannel()

    created, revision = compute_plan_events(
        [], [todo("Research", "in_progress"), todo("Deploy")], revision=0
    )
    for kind, payload in created:
        await renderer.handle(_stamp(kind, payload), channel, SESSION)

    # Objective-less header, no dangling colon; live in_progress mark.
    checklist = channel.sent[0]
    assert checklist.splitlines()[0] == "Plan"
    assert "[~] 1. Research" in checklist
    assert "[ ] 2. Deploy" in checklist

    # Fail the deploy step: ✗ mark + note surfaced as the phase line.
    flips, revision = compute_plan_events(
        [todo("Research", "in_progress"), todo("Deploy")],
        [todo("Research", "completed"), todo("Deploy", "failed", note="no SSH access")],
        revision=revision,
    )
    phase_lines = [
        await renderer.handle(_stamp(kind, payload), channel, SESSION)
        for kind, payload in flips
    ]

    final = channel.edited[-1]
    assert "[x] 1. Research" in final
    assert "[✗] 2. Deploy" in final
    assert "no SSH access" in phase_lines


async def test_revised_payload_redraws_checklist_authoritatively() -> None:
    renderer = PlanStatusRenderer(use_emojis=False)
    channel = MockChannel()

    created, revision = compute_plan_events([], [todo("A", "in_progress")], revision=0)
    for kind, payload in created:
        await renderer.handle(_stamp(kind, payload), channel, SESSION)

    revised, _ = compute_plan_events(
        [todo("A", "in_progress")],
        [todo("A", "failed", note="dead end"), todo("New approach", "in_progress")],
        revision=revision,
    )
    for kind, payload in revised:
        await renderer.handle(_stamp(kind, payload), channel, SESSION)

    final = channel.edited[-1]
    assert "(rev 1)" in final
    assert "[✗] 1. A" in final
    assert "[~] 2. New approach" in final
