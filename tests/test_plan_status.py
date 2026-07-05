"""Tests for plan checklist rendering (T2.7): PlanStatusRenderer,
StatusUpdateMiddleware.handle_plan_event, and PlanChannelSink."""

from typing import Any

import pytest

from openpaw.agent.middleware.status_update import StatusUpdateMiddleware
from openpaw.core.config.models import StatusUpdatesConfig
from openpaw.model.status_event import StatusEvent, StatusEventKind
from openpaw.runtime.status_bus import PlanChannelSink, StatusBus

SESSION = "telegram:123456"


class MockMessage:
    """Mock message returned by send_message."""

    def __init__(self, id: str, session_key: str, content: str):
        self.id = id
        self.session_key = session_key
        self.content = content


class MockChannel:
    """Mock channel adapter (mirrors test_status_update_middleware)."""

    def __init__(self) -> None:
        self.sent_messages: list[tuple[str, str]] = []
        self.edited_messages: list[tuple[str, str, str]] = []
        self.deleted_messages: list[tuple[str, str]] = []
        self._message_counter: int = 0

    async def send_message(self, session_key: str, content: str) -> Any:
        self._message_counter += 1
        self.sent_messages.append((session_key, content))
        return MockMessage(str(self._message_counter), session_key, content)

    async def edit_message(self, session_key: str, message_id: str, content: str) -> bool:
        self.edited_messages.append((session_key, message_id, content))
        return True

    async def delete_message(self, session_key: str, message_id: str) -> bool:
        self.deleted_messages.append((session_key, message_id))
        return True


def _make_config(enabled: bool = True) -> StatusUpdatesConfig:
    return StatusUpdatesConfig(
        enabled=enabled,
        agent_start=False,
        min_interval_seconds=0,
        use_emojis=False,
        typing_indicator=False,
    )


def _make_middleware(
    channel: MockChannel | None = None,
    config: StatusUpdatesConfig | None = None,
) -> StatusUpdateMiddleware:
    mw = StatusUpdateMiddleware(config or _make_config())
    if channel is not None:
        mw.set_context(channel, SESSION)
    return mw


def _event(
    kind: StatusEventKind,
    payload: dict[str, Any] | None = None,
    session_key: str | None = SESSION,
    node: str | None = None,
) -> StatusEvent:
    return StatusEvent(
        kind=kind,
        workspace="ws",
        session_key=session_key,
        run_id="run-1",
        node=node,
        payload=payload or {},
    )


def _plan_payload(revision: int = 0, second_status: str = "pending") -> dict[str, Any]:
    return {
        "plan": {
            "objective": "Do the thing",
            "revision": revision,
            "steps": [
                {"id": "1", "description": "First step", "status": "pending"},
                {"id": "2", "description": "Second step", "status": second_status},
            ],
        }
    }


# ---------------------------------------------------------------------------
# Plan message flow
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_plan_created_sends_checklist_message():
    channel = MockChannel()
    mw = _make_middleware(channel)

    await mw.handle_plan_event(_event(StatusEventKind.PLAN_CREATED, _plan_payload()))

    assert len(channel.sent_messages) == 1
    session_key, text = channel.sent_messages[0]
    assert session_key == SESSION
    assert "Plan: Do the thing" in text
    assert "[ ] 1. First step" in text
    assert "[ ] 2. Second step" in text
    assert "(rev" not in text  # revision 0 has no suffix


@pytest.mark.asyncio
async def test_step_started_edits_plan_message_and_sends_phase_line():
    channel = MockChannel()
    mw = _make_middleware(channel)
    await mw.handle_plan_event(_event(StatusEventKind.PLAN_CREATED, _plan_payload()))
    plan_msg_id = "1"

    await mw.handle_plan_event(
        _event(
            StatusEventKind.PLAN_STEP_STARTED,
            {"step_id": "1", "description": "First step"},
        )
    )

    # Checklist edited in place on the SAME message
    assert len(channel.edited_messages) == 1
    _, edited_id, text = channel.edited_messages[0]
    assert edited_id == plan_msg_id
    assert "[~] 1. First step" in text
    # Phase line goes to a DISTINCT tool-status message
    assert len(channel.sent_messages) == 2
    assert channel.sent_messages[1][1] == "Step 1/2: First step..."


@pytest.mark.asyncio
async def test_step_completed_marks_step_done():
    channel = MockChannel()
    mw = _make_middleware(channel)
    await mw.handle_plan_event(_event(StatusEventKind.PLAN_CREATED, _plan_payload()))

    await mw.handle_plan_event(
        _event(StatusEventKind.PLAN_STEP_COMPLETED, {"step_id": "1", "description": "First step"})
    )

    _, _, text = channel.edited_messages[-1]
    assert "[x] 1. First step" in text
    assert "[ ] 2. Second step" in text


@pytest.mark.asyncio
async def test_plan_revised_rerenders_with_rev_suffix():
    channel = MockChannel()
    mw = _make_middleware(channel)
    await mw.handle_plan_event(_event(StatusEventKind.PLAN_CREATED, _plan_payload()))
    await mw.handle_plan_event(
        _event(StatusEventKind.PLAN_STEP_STARTED, {"step_id": "1", "description": "First step"})
    )

    await mw.handle_plan_event(
        _event(StatusEventKind.PLAN_REVISED, _plan_payload(revision=2, second_status="failed"))
    )

    _, edited_id, text = channel.edited_messages[-1]
    assert edited_id == "1"  # still the same plan message
    assert "(rev 2)" in text
    # Full payload is authoritative: overlay cleared, statuses from payload
    assert "[ ] 1. First step" in text
    assert "[✗] 2. Second step" in text  # first-class failure mark (ADR-111 §10.1)


@pytest.mark.asyncio
async def test_plan_message_survives_run_completion():
    channel = MockChannel()
    mw = _make_middleware(channel)
    await mw.handle_plan_event(_event(StatusEventKind.PLAN_CREATED, _plan_payload()))
    # Give the run a tool-status message too
    await mw.send_forced_status("Running tool: shell...")
    status_msg_id = "2"

    await mw.delete_status()
    mw.reset()

    # Only the tool-status line is deleted; the plan checklist stays
    assert channel.deleted_messages == [(SESSION, status_msg_id)]
    # After reset, further plan events no longer edit the old message
    await mw.handle_plan_event(
        _event(StatusEventKind.PLAN_STEP_COMPLETED, {"step_id": "1", "description": "First step"})
    )
    assert len(channel.edited_messages) == 0


# ---------------------------------------------------------------------------
# React route and node phases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_react_route_produces_zero_messages():
    channel = MockChannel()
    mw = _make_middleware(channel)

    await mw.handle_plan_event(
        _event(
            StatusEventKind.NODE_ENTERED,
            {"route": "react", "reason": "simple"},
            node="triage",
        )
    )

    assert channel.sent_messages == []
    assert channel.edited_messages == []


@pytest.mark.asyncio
async def test_node_entered_renders_phase_lines():
    channel = MockChannel()
    mw = _make_middleware(channel)

    await mw.handle_plan_event(_event(StatusEventKind.NODE_ENTERED, {}, node="plan"))
    await mw.handle_plan_event(_event(StatusEventKind.NODE_ENTERED, {}, node="synthesize"))

    # First phase line sends the status message; second edits it in place
    assert channel.sent_messages[0][1] == "Planning..."
    assert channel.edited_messages[-1][2] == "Putting it all together..."


@pytest.mark.asyncio
async def test_triage_entry_renders_thinking():
    channel = MockChannel()
    mw = _make_middleware(channel)

    await mw.handle_plan_event(_event(StatusEventKind.NODE_ENTERED, {}, node="triage"))

    assert channel.sent_messages[0][1] == "Thinking..."


@pytest.mark.asyncio
async def test_triage_decision_announces_route():
    channel = MockChannel()
    mw = _make_middleware(channel)

    await mw.handle_plan_event(
        _event(StatusEventKind.NODE_ENTERED, {"route": "plan", "reason": "multi-step"}, node="triage")
    )
    await mw.handle_plan_event(
        _event(StatusEventKind.NODE_ENTERED, {"route": "ideate", "reason": "creative"}, node="triage")
    )
    await mw.handle_plan_event(
        _event(
            StatusEventKind.NODE_ENTERED,
            {"route": "plan", "resume_step_id": "2"},
            node="triage",
        )
    )

    assert channel.sent_messages[0][1] == "I need to form a plan for this..."
    assert channel.edited_messages[0][2] == "I need to think about this creatively..."
    assert channel.edited_messages[1][2] == "Resuming the plan..."


@pytest.mark.asyncio
async def test_nodeless_route_renders_shared_route_line():
    """Balanced's tool-time intent carries a route with node=None; it renders
    the same _ROUTE_LINES text as ultra's triage route. A resume_step_id on a
    node=None event is NOT the triage resume path — it still renders the route
    line (only node=='triage' gets 'Resuming the plan...')."""
    channel = MockChannel()
    mw = _make_middleware(channel)

    await mw.handle_plan_event(_event(StatusEventKind.NODE_ENTERED, {"route": "plan"}))
    await mw.handle_plan_event(_event(StatusEventKind.NODE_ENTERED, {"route": "ideate"}))

    assert channel.sent_messages[0][1] == "I need to form a plan for this..."
    assert channel.edited_messages[0][2] == "I need to think about this creatively..."


@pytest.mark.asyncio
async def test_module_selected_announces_creative_and_planning_only():
    channel = MockChannel()
    mw = _make_middleware(channel)

    await mw.handle_plan_event(
        _event(StatusEventKind.MODULE_SELECTED, {"kind": "creative", "module": "ideonomy", "reason": ""})
    )
    await mw.handle_plan_event(
        _event(
            StatusEventKind.MODULE_SELECTED,
            {"kind": "planning", "module": "self_discover", "reason": ""},
        )
    )
    # Reflection modules resolve every step — must stay silent
    await mw.handle_plan_event(
        _event(StatusEventKind.MODULE_SELECTED, {"kind": "reflection", "module": "light", "reason": ""})
    )

    assert channel.sent_messages[0][1] == "Ideating with the ideonomy module..."
    assert channel.edited_messages[-1][2] == "Using the self_discover module to shape the plan..."
    assert len(channel.edited_messages) == 1  # reflection rendered nothing


@pytest.mark.asyncio
async def test_reflection_verdict_narrates_deviations_only():
    channel = MockChannel()
    mw = _make_middleware(channel)

    # Clean advance: silent (the checklist tick tells the story)
    await mw.handle_plan_event(
        _event(
            StatusEventKind.REFLECTION_VERDICT,
            {"verdict": "advance", "reason": "ok", "step_succeeded": True},
        )
    )
    assert channel.sent_messages == []

    await mw.handle_plan_event(
        _event(
            StatusEventKind.REFLECTION_VERDICT,
            {"verdict": "advance", "reason": "flaky", "step_succeeded": False},
        )
    )
    await mw.handle_plan_event(
        _event(
            StatusEventKind.REFLECTION_VERDICT,
            {"verdict": "insert_step", "reason": "missing dep", "step_succeeded": False},
        )
    )
    await mw.handle_plan_event(
        _event(
            StatusEventKind.REFLECTION_VERDICT,
            {"verdict": "revise_plan", "reason": "wrong approach", "step_succeeded": False},
        )
    )

    assert channel.sent_messages[0][1] == "That step didn't go as planned — pressing on..."
    assert channel.edited_messages[0][2] == "Hit a snag — adding a recovery step..."
    assert (
        channel.edited_messages[1][2]
        == "This isn't working — going back to the drawing board..."
    )


@pytest.mark.asyncio
async def test_module_phase_lines_render():
    channel = MockChannel()
    mw = _make_middleware(channel)

    await mw.handle_plan_event(
        _event(
            StatusEventKind.MODULE_PHASE,
            {"phase": "lenses_selected", "total": 3, "detail": "Causation · Function · Form"},
        )
    )
    await mw.handle_plan_event(
        _event(
            StatusEventKind.MODULE_PHASE,
            {"phase": "lens", "index": 2, "total": 3, "detail": "Function"},
        )
    )
    await mw.handle_plan_event(
        _event(StatusEventKind.MODULE_PHASE, {"phase": "synthesis", "total": 3})
    )

    lines = [channel.sent_messages[0][1]] + [e[2] for e in channel.edited_messages]
    assert lines == [
        "Exploring through 3 lenses: Causation · Function · Form",
        "Lens 2/3: Function...",
        "Weaving 3 explorations together...",
    ]


@pytest.mark.asyncio
async def test_self_discover_phase_lines_render():
    channel = MockChannel()
    mw = _make_middleware(channel)

    for phase in ("discovering", "select", "adapt", "implement", "solving"):
        await mw.handle_plan_event(
            _event(StatusEventKind.MODULE_PHASE, {"phase": phase})
        )

    lines = [channel.sent_messages[0][1]] + [e[2] for e in channel.edited_messages]
    assert lines == [
        "New kind of task — working out how to reason about it...",
        "Selecting reasoning modules...",
        "Adapting them to the task...",
        "Composing a reasoning structure...",
        "Building the plan from the structure...",
    ]


@pytest.mark.asyncio
async def test_module_insight_line_renders_label_and_headline():
    channel = MockChannel()
    mw = _make_middleware(channel)

    await mw.handle_plan_event(
        _event(
            StatusEventKind.MODULE_INSIGHT,
            {"label": "Function", "headline": "reframe it as a nervous system, not a controller"},
        )
    )

    assert channel.sent_messages[0][1] == (
        "Function — reframe it as a nervous system, not a controller"
    )


@pytest.mark.asyncio
async def test_module_insight_uses_bulb_emoji_when_enabled():
    channel = MockChannel()
    config = StatusUpdatesConfig(
        enabled=True, agent_start=False, min_interval_seconds=0,
        use_emojis=True, typing_indicator=False,
    )
    mw = _make_middleware(channel, config=config)

    await mw.handle_plan_event(
        _event(StatusEventKind.MODULE_INSIGHT, {"label": "Form", "headline": "echo the shape"})
    )
    await mw.handle_plan_event(
        _event(StatusEventKind.MODULE_PHASE, {"phase": "synthesis", "total": 2})
    )

    assert channel.sent_messages[0][1].startswith("💡 ")
    assert channel.edited_messages[-1][2].startswith("📋 ")


@pytest.mark.asyncio
async def test_module_insight_empty_headline_renders_nothing():
    channel = MockChannel()
    mw = _make_middleware(channel)

    await mw.handle_plan_event(
        _event(StatusEventKind.MODULE_INSIGHT, {"label": "Function", "headline": "  "})
    )

    assert channel.sent_messages == []


@pytest.mark.asyncio
async def test_harness_narration_suppresses_starting_work():
    """Once a harness event has rendered, the inner react run's generic
    'Starting work...' must not stomp the phase narration."""
    channel = MockChannel()
    config = StatusUpdatesConfig(
        enabled=True,
        agent_start=True,
        min_interval_seconds=0,
        use_emojis=False,
        typing_indicator=False,
    )
    mw = _make_middleware(channel, config=config)

    await mw.handle_plan_event(_event(StatusEventKind.NODE_ENTERED, {}, node="triage"))
    await mw.abefore_agent({}, None)

    texts = [t for _, t in channel.sent_messages] + [t for _, _, t in channel.edited_messages]
    assert texts == ["Thinking..."]

    # A fresh run (set_context) re-enables the generic label for react paths
    mw.set_context(channel, SESSION)
    await mw.abefore_agent({}, None)
    assert channel.sent_messages[-1][1] == "Starting work..."


# ---------------------------------------------------------------------------
# Guards: session mismatch, disabled, no context
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_session_mismatch_is_ignored():
    channel = MockChannel()
    mw = _make_middleware(channel)

    await mw.handle_plan_event(
        _event(StatusEventKind.PLAN_CREATED, _plan_payload(), session_key="telegram:999")
    )

    assert channel.sent_messages == []


@pytest.mark.asyncio
async def test_disabled_config_renders_nothing():
    channel = MockChannel()
    mw = _make_middleware(channel, config=_make_config(enabled=False))

    await mw.handle_plan_event(_event(StatusEventKind.PLAN_CREATED, _plan_payload()))

    assert channel.sent_messages == []


@pytest.mark.asyncio
async def test_no_armed_context_is_ignored():
    mw = _make_middleware(channel=None)

    # Must not raise without a channel/session
    await mw.handle_plan_event(_event(StatusEventKind.PLAN_CREATED, _plan_payload()))


@pytest.mark.asyncio
async def test_channel_failures_are_swallowed():
    class ExplodingChannel(MockChannel):
        async def send_message(self, session_key: str, content: str) -> Any:
            raise RuntimeError("boom")

    mw = _make_middleware(ExplodingChannel())

    # Never breaks the run
    await mw.handle_plan_event(_event(StatusEventKind.PLAN_CREATED, _plan_payload()))


# ---------------------------------------------------------------------------
# PlanChannelSink
# ---------------------------------------------------------------------------


class RecordingMiddleware:
    """Fake middleware capturing forwarded events."""

    def __init__(self) -> None:
        self.events: list[StatusEvent] = []

    async def handle_plan_event(self, event: StatusEvent) -> None:
        self.events.append(event)


@pytest.mark.asyncio
async def test_sink_forwards_plan_kinds_and_filters_the_rest():
    mw = RecordingMiddleware()
    sink = PlanChannelSink(mw)  # type: ignore[arg-type]

    await sink.handle(_event(StatusEventKind.PLAN_CREATED, _plan_payload()))
    await sink.handle(_event(StatusEventKind.NODE_ENTERED, {}, node="plan"))
    await sink.handle(_event(StatusEventKind.TOOL_STARTED, {"tool": "shell"}))
    await sink.handle(_event(StatusEventKind.RUN_STARTED))

    assert [e.kind for e in mw.events] == [
        StatusEventKind.PLAN_CREATED,
        StatusEventKind.NODE_ENTERED,
    ]


@pytest.mark.asyncio
async def test_events_during_graph_run_use_armed_context():
    """Events emitted mid-run (same asyncio task chain) hit the armed context.

    Simulates the ultra graph emitting through the bus while
    MessageProcessor's set_context is in effect for the run.
    """
    channel = MockChannel()
    mw = _make_middleware(channel)
    bus = StatusBus("ws")
    bus.add_sink(PlanChannelSink(mw))

    async def fake_plan_node() -> None:
        await bus.emit(_event(StatusEventKind.PLAN_CREATED, _plan_payload()))

    async def fake_graph_run() -> None:
        await fake_plan_node()

    await fake_graph_run()

    assert len(channel.sent_messages) == 1
    assert channel.sent_messages[0][0] == SESSION
    assert "Plan: Do the thing" in channel.sent_messages[0][1]


# ---------------------------------------------------------------------------
# Duplicate-checklist regression (balanced harness: plan.created shows the
# first step already in_progress, then a redundant step_started renders the
# same text; a no-op edit must NOT spawn a second checklist message)
# ---------------------------------------------------------------------------


class NoOpEditChannel(MockChannel):
    """MockChannel that mirrors Telegram: an edit to identical text fails.

    Telegram raises BadRequest "message is not modified" on a no-op edit, and
    the adapter returns False. This is what turned an identical re-render into
    a duplicate message via the send-new fallback.
    """

    def __init__(self) -> None:
        super().__init__()
        self._by_id: dict[str, str] = {}

    async def send_message(self, session_key: str, content: str):  # type: ignore[override]
        msg = await super().send_message(session_key, content)
        self._by_id[msg.id] = content
        return msg

    async def edit_message(self, session_key: str, message_id: str, content: str) -> bool:  # type: ignore[override]
        if self._by_id.get(message_id) == content:
            return False  # "message is not modified"
        self._by_id[message_id] = content
        self.edited_messages.append((session_key, message_id, content))
        return True


def _plan_step1_in_progress() -> dict[str, Any]:
    """plan.created payload where step 1 is already in_progress (balanced)."""
    return {
        "plan": {
            "objective": "",
            "revision": 0,
            "steps": [
                {"id": "1", "description": "First step", "status": "in_progress"},
                {"id": "2", "description": "Second step", "status": "pending"},
            ],
        }
    }


@pytest.mark.asyncio
async def test_redundant_step_started_does_not_duplicate_checklist():
    """Root-cause pin: plan.created (step 1 in_progress) + step_started for the
    same step is a byte-identical re-render; on a Telegram-like channel the
    no-op edit must be skipped, never fall through to a second message."""
    channel = NoOpEditChannel()
    mw = _make_middleware(channel)

    await mw.handle_plan_event(_event(StatusEventKind.PLAN_CREATED, _plan_step1_in_progress()))
    await mw.handle_plan_event(
        _event(StatusEventKind.PLAN_STEP_STARTED, {"step_id": "1", "description": "First step"})
    )

    checklists = [c for _, c in channel.sent_messages if "Plan" in c]
    assert len(checklists) == 1  # exactly one checklist message, not two
    # The identical render was skipped entirely (no channel edit attempted).
    assert channel.edited_messages == []


@pytest.mark.asyncio
async def test_changed_render_still_edits_the_single_message():
    """The skip only fires on identical text — a real status change still edits
    the ONE checklist in place (no regression to live updates)."""
    channel = NoOpEditChannel()
    mw = _make_middleware(channel)

    await mw.handle_plan_event(_event(StatusEventKind.PLAN_CREATED, _plan_step1_in_progress()))
    await mw.handle_plan_event(
        _event(StatusEventKind.PLAN_STEP_COMPLETED, {"step_id": "1", "description": "First step"})
    )

    checklists = [c for _, c in channel.sent_messages if "Plan" in c]
    assert len(checklists) == 1
    assert len(channel.edited_messages) == 1
    assert "[x] 1. First step" in channel.edited_messages[-1][2]


@pytest.mark.asyncio
async def test_redelivered_plan_created_is_idempotent_same_run():
    """Defense-in-depth: a re-delivered plan.created for the same run + same
    plan must edit in place, never null message_id and spawn a second message."""
    channel = NoOpEditChannel()
    mw = _make_middleware(channel)

    await mw.handle_plan_event(_event(StatusEventKind.PLAN_CREATED, _plan_step1_in_progress()))
    # Same run_id ("run-1"), same plan payload — a duplicate delivery.
    await mw.handle_plan_event(_event(StatusEventKind.PLAN_CREATED, _plan_step1_in_progress()))

    checklists = [c for _, c in channel.sent_messages if "Plan" in c]
    assert len(checklists) == 1  # not two


@pytest.mark.asyncio
async def test_new_run_plan_created_starts_fresh_message():
    """Ultra parity: each run legitimately starts a NEW plan message. After a
    reset (per-run set_context), a plan.created sends a fresh checklist."""
    channel = NoOpEditChannel()
    mw = _make_middleware(channel)

    await mw.handle_plan_event(_event(StatusEventKind.PLAN_CREATED, _plan_step1_in_progress()))
    mw.set_context(channel, SESSION)  # MessageProcessor re-arms per run (resets renderer)
    await mw.handle_plan_event(
        _event(StatusEventKind.PLAN_CREATED, _plan_step1_in_progress(), session_key=SESSION)
    )

    checklists = [c for _, c in channel.sent_messages if "Plan" in c]
    assert len(checklists) == 2  # a fresh message per run, as ultra expects
