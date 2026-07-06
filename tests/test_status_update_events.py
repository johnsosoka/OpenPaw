"""Event-stream assertions for StatusUpdateMiddleware (ADR-106 Phase A).

Verifies the middleware emits StatusEvents alongside its unchanged channel
rendering. Fixtures mirror tests/test_status_update_middleware.py.
"""

from typing import Any
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from openpaw.agent.middleware.queue_aware import InterruptSignalError
from openpaw.agent.middleware.status_update import StatusUpdateMiddleware
from openpaw.core.config.models import StatusUpdatesConfig
from openpaw.core.prompts.system_events import STEER_SKIP_MESSAGE
from openpaw.model.status_event import StatusEvent, StatusEventKind
from openpaw.runtime.status_bus import StatusBus


class MockMessage:
    def __init__(self, id: str, session_key: str, content: str):
        self.id = id
        self.session_key = session_key
        self.content = content


class MockChannel:
    def __init__(self) -> None:
        self.sent_messages: list[tuple[str, str]] = []
        self.edited_messages: list[tuple[str, str, str]] = []
        self._message_counter: int = 0

    async def send_message(self, session_key: str, content: str) -> Any:
        self._message_counter += 1
        self.sent_messages.append((session_key, content))
        return MockMessage(str(self._message_counter), session_key, content)

    async def edit_message(self, session_key: str, message_id: str, content: str) -> bool:
        self.edited_messages.append((session_key, message_id, content))
        return True

    async def delete_message(self, session_key: str, message_id: str) -> bool:
        return True


class ListSink:
    """In-memory sink capturing emitted events."""

    def __init__(self) -> None:
        self.events: list[StatusEvent] = []

    async def handle(self, event: StatusEvent) -> None:
        self.events.append(event)

    @property
    def kinds(self) -> list[StatusEventKind]:
        return [e.kind for e in self.events]


def _make_config(**overrides: Any) -> StatusUpdatesConfig:
    defaults: dict[str, Any] = {
        "enabled": True,
        "agent_start": True,
        "tool_calls_detected": True,
        "tool_start": True,
        "tool_complete": True,
        "subagent_spawned": True,
        "steer_redirected": True,
        "run_interrupted": True,
        "min_interval_seconds": 0,
        "use_emojis": False,
    }
    defaults.update(overrides)
    return StatusUpdatesConfig(**defaults)


def _make_middleware(
    config: StatusUpdatesConfig | None = None,
) -> tuple[StatusUpdateMiddleware, ListSink, MockChannel]:
    sink = ListSink()
    bus = StatusBus("testws")
    bus.add_sink(sink)
    mw = StatusUpdateMiddleware(
        config or _make_config(), emitter=bus, workspace="testws"
    )
    channel = MockChannel()
    mw.set_context(channel, "telegram:123456")
    return mw, sink, channel


def _make_tool_request(tool_name: str, args: dict[str, Any] | None = None) -> Any:
    req = MagicMock()
    req.tool_call = {"name": tool_name, "id": f"call_{tool_name}", "args": args or {}}
    return req


async def _ok_handler(request: Any) -> Any:
    return MagicMock()


# ---------------------------------------------------------------------------
# Kind sequence for a simulated run
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_simulated_run_emits_expected_kind_sequence():
    mw, sink, channel = _make_middleware()

    await mw.abefore_agent({}, None)
    state = {"messages": [AIMessage(content="", tool_calls=[
        {"name": "read_file", "id": "c1", "args": {"file_path": "notes.md"}},
    ])]}
    await mw.aafter_model(state, None)
    await mw.awrap_tool_call(
        _make_tool_request("read_file", {"file_path": "notes.md"}), _ok_handler
    )

    assert sink.kinds == [
        StatusEventKind.RUN_STARTED,
        StatusEventKind.TOOL_SELECTED,
        StatusEventKind.TOOL_STARTED,
        StatusEventKind.TOOL_COMPLETED,
    ]
    # Rendering unchanged: channel still received status messages
    assert len(channel.sent_messages) == 1
    assert channel.sent_messages[0][1] == "Starting work..."


@pytest.mark.asyncio
async def test_events_share_run_id_and_context():
    mw, sink, _channel = _make_middleware()

    await mw.abefore_agent({}, None)
    await mw.awrap_tool_call(_make_tool_request("read_file"), _ok_handler)

    run_ids = {e.run_id for e in sink.events}
    assert len(run_ids) == 1
    for event in sink.events:
        assert event.workspace == "testws"
        assert event.session_key == "telegram:123456"


@pytest.mark.asyncio
async def test_set_context_generates_fresh_run_id_per_run():
    mw, sink, channel = _make_middleware()

    await mw.abefore_agent({}, None)
    mw.reset()
    mw.set_context(channel, "telegram:123456")
    await mw.abefore_agent({}, None)

    assert sink.kinds == [StatusEventKind.RUN_STARTED, StatusEventKind.RUN_STARTED]
    assert sink.events[0].run_id != sink.events[1].run_id


@pytest.mark.asyncio
async def test_run_started_payload():
    mw, sink, _channel = _make_middleware()

    await mw.abefore_agent({}, None)

    assert sink.events[0].payload == {"run_count": 1, "is_system_batch": False}


@pytest.mark.asyncio
async def test_tool_events_carry_name_and_detail():
    mw, sink, _channel = _make_middleware()

    await mw.awrap_tool_call(
        _make_tool_request("read_file", {"file_path": "notes.md"}), _ok_handler
    )

    started, completed = sink.events
    assert started.kind == StatusEventKind.TOOL_STARTED
    assert started.payload == {"tool": "read_file", "detail": "notes.md"}
    assert completed.kind == StatusEventKind.TOOL_COMPLETED
    assert completed.payload == {"tool": "read_file", "detail": "notes.md"}


@pytest.mark.asyncio
async def test_tool_selected_payload_lists_tools():
    mw, sink, _channel = _make_middleware()
    state = {"messages": [AIMessage(content="", tool_calls=[
        {"name": "read_file", "id": "c1", "args": {}},
        {"name": "write_file", "id": "c2", "args": {}},
    ])]}

    await mw.aafter_model(state, None)

    assert sink.kinds == [StatusEventKind.TOOL_SELECTED]
    assert sink.events[0].payload == {"tools": ["read_file", "write_file"]}


# ---------------------------------------------------------------------------
# Events fire even when the render sub-flag is off (telemetry != rendering)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tool_events_fire_when_render_flags_disabled():
    mw, sink, channel = _make_middleware(
        _make_config(tool_start=False, tool_complete=False, tool_calls_detected=False)
    )
    state = {"messages": [AIMessage(content="", tool_calls=[
        {"name": "read_file", "id": "c1", "args": {}},
    ])]}

    await mw.aafter_model(state, None)
    await mw.awrap_tool_call(_make_tool_request("read_file"), _ok_handler)

    assert sink.kinds == [
        StatusEventKind.TOOL_SELECTED,
        StatusEventKind.TOOL_STARTED,
        StatusEventKind.TOOL_COMPLETED,
    ]
    # No rendering occurred
    assert channel.sent_messages == []
    assert channel.edited_messages == []


@pytest.mark.asyncio
async def test_no_events_when_middleware_disabled():
    mw, sink, _channel = _make_middleware(_make_config(enabled=False))
    state = {"messages": [AIMessage(content="", tool_calls=[
        {"name": "read_file", "id": "c1", "args": {}},
    ])]}

    await mw.abefore_agent({}, None)
    await mw.aafter_model(state, None)
    await mw.awrap_tool_call(_make_tool_request("read_file"), _ok_handler)

    assert sink.events == []


@pytest.mark.asyncio
async def test_no_emitter_is_safe():
    """Middleware without an emitter (default) behaves exactly as before."""
    mw = StatusUpdateMiddleware(_make_config())
    channel = MockChannel()
    mw.set_context(channel, "telegram:123456")

    await mw.abefore_agent({}, None)
    await mw.awrap_tool_call(_make_tool_request("read_file"), _ok_handler)

    assert len(channel.sent_messages) == 1


# ---------------------------------------------------------------------------
# Steer / interrupt
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_interrupt_emits_run_interrupted():
    mw, sink, _channel = _make_middleware()

    async def handler(request: Any) -> Any:
        raise InterruptSignalError([("telegram", "test")])

    with pytest.raises(InterruptSignalError):
        await mw.awrap_tool_call(_make_tool_request("read_file"), handler)

    assert sink.kinds == [
        StatusEventKind.TOOL_STARTED,
        StatusEventKind.RUN_INTERRUPTED,
    ]
    assert sink.events[1].payload == {"tool": "read_file"}


@pytest.mark.asyncio
async def test_steer_emits_run_steered_once():
    mw, sink, _channel = _make_middleware()

    async def handler(request: Any) -> Any:
        return ToolMessage(content=STEER_SKIP_MESSAGE, tool_call_id="c1")

    await mw.awrap_tool_call(_make_tool_request("tool_a"), handler)
    await mw.awrap_tool_call(_make_tool_request("tool_b"), handler)

    steered = [e for e in sink.events if e.kind == StatusEventKind.RUN_STEERED]
    assert len(steered) == 1
    assert steered[0].payload == {"tool": "tool_a"}


# ---------------------------------------------------------------------------
# Sub-agent lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_subagent_lifecycle_emits_dispatched_tool_completed():
    mw, sink, _channel = _make_middleware()

    await mw.create_subagent_status("req-1", "researcher")
    await mw.update_subagent_status("req-1", "Running tool: brave_search...")
    await mw.finalize_subagent_status("req-1", "completed")

    assert sink.kinds == [
        StatusEventKind.SUBAGENT_DISPATCHED,
        StatusEventKind.SUBAGENT_TOOL,
        StatusEventKind.SUBAGENT_COMPLETED,
    ]
    assert sink.events[0].payload == {"subagent_id": "req-1", "label": "researcher"}
    assert sink.events[1].payload == {
        "subagent_id": "req-1",
        "status": "Running tool: brave_search...",
    }
    assert sink.events[2].payload == {"subagent_id": "req-1", "outcome": "completed"}


@pytest.mark.asyncio
async def test_failing_emitter_never_breaks_rendering():
    class ExplodingEmitter:
        async def emit(self, event: StatusEvent) -> None:
            raise RuntimeError("emitter exploded")

    mw = StatusUpdateMiddleware(
        _make_config(), emitter=ExplodingEmitter(), workspace="testws"
    )
    channel = MockChannel()
    mw.set_context(channel, "telegram:123456")

    await mw.abefore_agent({}, None)
    await mw.awrap_tool_call(_make_tool_request("read_file"), _ok_handler)

    # Rendering proceeded despite the emitter failing on every emit
    assert len(channel.sent_messages) == 1
