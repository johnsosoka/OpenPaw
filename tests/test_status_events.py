"""Tests for the status event model, StatusBus, and SessionLogSink (ADR-106)."""

import json
from datetime import UTC
from pathlib import Path

import pytest

from openpaw.model.status_event import StatusEvent, StatusEventKind
from openpaw.runtime.status_bus import NullStatusEmitter, SessionLogSink, StatusBus


class ListSink:
    """In-memory sink capturing events for assertions."""

    def __init__(self) -> None:
        self.events: list[StatusEvent] = []

    async def handle(self, event: StatusEvent) -> None:
        self.events.append(event)


class FailingSink:
    """Sink that always raises, to test error containment."""

    async def handle(self, event: StatusEvent) -> None:
        raise RuntimeError("sink exploded")


def _event(kind: StatusEventKind = StatusEventKind.RUN_STARTED) -> StatusEvent:
    return StatusEvent(
        kind=kind,
        workspace="testws",
        session_key="telegram:123456",
        run_id="run-1",
        payload={"run_count": 1},
    )


# ---------------------------------------------------------------------------
# StatusEvent model
# ---------------------------------------------------------------------------


def test_status_event_is_frozen():
    event = _event()
    with pytest.raises(AttributeError):
        event.kind = StatusEventKind.RUN_COMPLETED  # type: ignore[misc]


def test_status_event_defaults():
    event = StatusEvent(
        kind=StatusEventKind.TOOL_STARTED,
        workspace="testws",
        session_key=None,
        run_id="run-1",
    )
    assert event.node is None
    assert event.payload == {}
    assert event.ts.tzinfo is UTC


def test_status_event_kind_is_str():
    assert StatusEventKind.TOOL_STARTED == "tool.started"
    assert str(StatusEventKind.SUBAGENT_COMPLETED) == "subagent.completed"


# ---------------------------------------------------------------------------
# StatusBus
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bus_fans_out_to_all_sinks_in_order():
    bus = StatusBus("testws")
    sink_a = ListSink()
    sink_b = ListSink()
    bus.add_sink(sink_a)
    bus.add_sink(sink_b)

    event = _event()
    await bus.emit(event)

    assert sink_a.events == [event]
    assert sink_b.events == [event]


@pytest.mark.asyncio
async def test_bus_contains_sink_errors_and_continues():
    bus = StatusBus("testws")
    survivor = ListSink()
    bus.add_sink(FailingSink())
    bus.add_sink(survivor)

    event = _event()
    await bus.emit(event)  # Must not raise

    assert survivor.events == [event]


@pytest.mark.asyncio
async def test_bus_with_no_sinks_is_noop():
    bus = StatusBus("testws")
    await bus.emit(_event())  # Must not raise


@pytest.mark.asyncio
async def test_null_status_emitter_is_noop():
    emitter = NullStatusEmitter()
    await emitter.emit(_event())  # Must not raise


# ---------------------------------------------------------------------------
# SessionLogSink
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_session_log_sink_writes_valid_jsonl(tmp_path: Path):
    sink = SessionLogSink(tmp_path)

    await sink.handle(_event(StatusEventKind.RUN_STARTED))
    await sink.handle(_event(StatusEventKind.TOOL_STARTED))

    assert sink.path == tmp_path / "memory" / "logs" / "events" / "status_events.jsonl"
    lines = sink.path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2

    records = [json.loads(line) for line in lines]
    assert records[0]["kind"] == "run.started"
    assert records[1]["kind"] == "tool.started"
    for record in records:
        assert record["workspace"] == "testws"
        assert record["session_key"] == "telegram:123456"
        assert record["run_id"] == "run-1"
        assert record["node"] is None
        assert record["payload"] == {"run_count": 1}
        assert record["ts"]  # ISO 8601 timestamp present


@pytest.mark.asyncio
async def test_session_log_sink_appends_across_instances(tmp_path: Path):
    """The sink is a rolling append-only file, not per-run."""
    await SessionLogSink(tmp_path).handle(_event())
    await SessionLogSink(tmp_path).handle(_event())

    sink = SessionLogSink(tmp_path)
    assert len(sink.path.read_text(encoding="utf-8").splitlines()) == 2


@pytest.mark.asyncio
async def test_bus_with_session_log_sink_end_to_end(tmp_path: Path):
    bus = StatusBus("testws")
    sink = SessionLogSink(tmp_path)
    bus.add_sink(sink)

    await bus.emit(_event(StatusEventKind.SUBAGENT_COMPLETED))

    record = json.loads(sink.path.read_text(encoding="utf-8"))
    assert record["kind"] == "subagent.completed"
