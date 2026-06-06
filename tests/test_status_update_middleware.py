"""Tests for StatusUpdateMiddleware."""

import time
from typing import Any
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage

from openpaw.agent.middleware.status_update import StatusUpdateMiddleware
from openpaw.core.config.models import StatusUpdatesConfig


class MockChannel:
    """Mock channel adapter for testing."""

    def __init__(self):
        self.sent_messages: list[tuple[str, str]] = []

    async def send_message(self, session_key: str, content: str) -> None:
        self.sent_messages.append((session_key, content))


def _make_config(
    enabled: bool = True,
    agent_start: bool = True,
    tool_calls_detected: bool = True,
    tool_start: bool = False,
    tool_complete: bool = False,
    subagent_spawned: bool = True,
    min_interval_seconds: int = 0,
    max_updates_per_run: int = 10,
) -> StatusUpdatesConfig:
    return StatusUpdatesConfig(
        enabled=enabled,
        agent_start=agent_start,
        tool_calls_detected=tool_calls_detected,
        tool_start=tool_start,
        tool_complete=tool_complete,
        subagent_spawned=subagent_spawned,
        min_interval_seconds=min_interval_seconds,
        max_updates_per_run=max_updates_per_run,
    )


def _make_middleware(
    config: StatusUpdatesConfig | None = None,
    channel: MockChannel | None = None,
    session_key: str = "telegram:123456",
) -> StatusUpdateMiddleware:
    cfg = config or _make_config()
    mw = StatusUpdateMiddleware(cfg)
    if channel:
        mw.set_context(channel, session_key)
    return mw


def _ai_with_tool_calls(*tool_names: str) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[
            {"name": name, "id": f"call_{name}", "args": {}}
            for name in tool_names
        ],
    )


def _make_tool_request(tool_name: str, args: dict[str, Any] | None = None) -> Any:
    req = MagicMock()
    req.tool_call = {"name": tool_name, "id": f"call_{tool_name}", "args": args or {}}
    return req


# ---------------------------------------------------------------------------
# abefore_agent
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_abefore_agent_sends_message_when_enabled():
    channel = MockChannel()
    mw = _make_middleware(channel=channel)

    result = await mw.abefore_agent({}, None)

    assert result is None
    assert len(channel.sent_messages) == 1
    assert channel.sent_messages[0] == ("telegram:123456", "Starting work...")


@pytest.mark.asyncio
async def test_abefore_agent_is_silent_when_disabled():
    channel = MockChannel()
    mw = _make_middleware(config=_make_config(enabled=False), channel=channel)

    result = await mw.abefore_agent({}, None)

    assert result is None
    assert len(channel.sent_messages) == 0


@pytest.mark.asyncio
async def test_abefore_agent_is_silent_when_agent_start_disabled():
    channel = MockChannel()
    mw = _make_middleware(config=_make_config(agent_start=False), channel=channel)

    result = await mw.abefore_agent({}, None)

    assert result is None
    assert len(channel.sent_messages) == 0


@pytest.mark.asyncio
async def test_abefore_agent_is_silent_without_context():
    mw = _make_middleware()
    # No channel/session set

    result = await mw.abefore_agent({}, None)

    assert result is None


# ---------------------------------------------------------------------------
# aafter_model
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_aafter_model_detects_tool_calls():
    channel = MockChannel()
    mw = _make_middleware(channel=channel)
    state = {"messages": [_ai_with_tool_calls("read_file", "write_file")]}

    result = await mw.aafter_model(state, None)

    assert result is None
    assert len(channel.sent_messages) == 1
    assert channel.sent_messages[0] == (
        "telegram:123456",
        "Using tools: read_file, write_file...",
    )


@pytest.mark.asyncio
async def test_aafter_model_silent_when_no_tool_calls():
    channel = MockChannel()
    mw = _make_middleware(channel=channel)
    state = {"messages": [AIMessage(content="plain text response")]}

    result = await mw.aafter_model(state, None)

    assert result is None
    assert len(channel.sent_messages) == 0


@pytest.mark.asyncio
async def test_aafter_model_silent_when_disabled():
    channel = MockChannel()
    mw = _make_middleware(config=_make_config(enabled=False), channel=channel)
    state = {"messages": [_ai_with_tool_calls("read_file")]}

    result = await mw.aafter_model(state, None)

    assert result is None
    assert len(channel.sent_messages) == 0


@pytest.mark.asyncio
async def test_aafter_model_silent_when_tool_calls_detected_disabled():
    channel = MockChannel()
    mw = _make_middleware(config=_make_config(tool_calls_detected=False), channel=channel)
    state = {"messages": [_ai_with_tool_calls("read_file")]}

    result = await mw.aafter_model(state, None)

    assert result is None
    assert len(channel.sent_messages) == 0


@pytest.mark.asyncio
async def test_aafter_model_deduplicates_same_tool_set():
    channel = MockChannel()
    mw = _make_middleware(channel=channel)
    state = {"messages": [_ai_with_tool_calls("read_file")]}

    await mw.aafter_model(state, None)
    await mw.aafter_model(state, None)  # Same tools again

    assert len(channel.sent_messages) == 1


@pytest.mark.asyncio
async def test_aafter_model_reports_different_tool_set():
    channel = MockChannel()
    mw = _make_middleware(channel=channel)

    state1 = {"messages": [_ai_with_tool_calls("read_file")]}
    await mw.aafter_model(state1, None)

    state2 = {"messages": [_ai_with_tool_calls("write_file")]}
    await mw.aafter_model(state2, None)

    assert len(channel.sent_messages) == 2


@pytest.mark.asyncio
async def test_aafter_model_empty_messages():
    channel = MockChannel()
    mw = _make_middleware(channel=channel)

    result = await mw.aafter_model({"messages": []}, None)

    assert result is None
    assert len(channel.sent_messages) == 0


# ---------------------------------------------------------------------------
# awrap_tool_call
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_awrap_tool_call_reports_spawn_agent():
    channel = MockChannel()
    mw = _make_middleware(channel=channel)
    req = _make_tool_request("spawn_agent", {"label": "researcher"})

    async def handler(request: Any) -> Any:
        return MagicMock()

    result = await mw.awrap_tool_call(req, handler)
    assert result is not None
    assert len(channel.sent_messages) == 1
    assert channel.sent_messages[0] == ("telegram:123456", "Dispatched sub-agent: researcher")


@pytest.mark.asyncio
async def test_awrap_tool_call_does_not_report_spawn_when_disabled():
    channel = MockChannel()
    mw = _make_middleware(config=_make_config(subagent_spawned=False), channel=channel)
    req = _make_tool_request("spawn_agent", {"label": "researcher"})

    async def handler(request: Any) -> Any:
        return MagicMock()

    await mw.awrap_tool_call(req, handler)
    assert len(channel.sent_messages) == 0


@pytest.mark.asyncio
async def test_awrap_tool_call_reports_tool_start():
    channel = MockChannel()
    mw = _make_middleware(config=_make_config(tool_start=True), channel=channel)
    req = _make_tool_request("read_file")

    async def handler(request: Any) -> Any:
        return MagicMock()

    await mw.awrap_tool_call(req, handler)
    assert len(channel.sent_messages) == 1
    assert channel.sent_messages[0] == ("telegram:123456", "Running tool: read_file...")


@pytest.mark.asyncio
async def test_awrap_tool_call_reports_tool_complete():
    channel = MockChannel()
    mw = _make_middleware(config=_make_config(tool_complete=True), channel=channel)
    req = _make_tool_request("read_file")

    async def handler(request: Any) -> Any:
        return MagicMock()

    await mw.awrap_tool_call(req, handler)
    assert len(channel.sent_messages) == 1
    assert channel.sent_messages[0] == ("telegram:123456", "Completed: read_file")


@pytest.mark.asyncio
async def test_awrap_tool_call_reports_both_start_and_complete():
    channel = MockChannel()
    mw = _make_middleware(config=_make_config(tool_start=True, tool_complete=True), channel=channel)
    req = _make_tool_request("read_file")

    async def handler(request: Any) -> Any:
        return MagicMock()

    await mw.awrap_tool_call(req, handler)
    assert len(channel.sent_messages) == 2
    assert channel.sent_messages[0] == ("telegram:123456", "Running tool: read_file...")
    assert channel.sent_messages[1] == ("telegram:123456", "Completed: read_file")


@pytest.mark.asyncio
async def test_awrap_tool_call_passes_through_when_disabled():
    channel = MockChannel()
    mw = _make_middleware(config=_make_config(enabled=False), channel=channel)
    req = _make_tool_request("read_file")

    async def handler(request: Any) -> Any:
        return MagicMock(content="result")

    result = await mw.awrap_tool_call(req, handler)
    assert result.content == "result"
    assert len(channel.sent_messages) == 0


# ---------------------------------------------------------------------------
# Throttling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_throttling_time_based():
    channel = MockChannel()
    mw = _make_middleware(
        config=_make_config(min_interval_seconds=5),
        channel=channel,
    )

    await mw._send_status("First update")
    await mw._send_status("Second update")

    assert len(channel.sent_messages) == 1


@pytest.mark.asyncio
async def test_throttling_budget_based():
    channel = MockChannel()
    mw = _make_middleware(
        config=_make_config(max_updates_per_run=2),
        channel=channel,
    )

    await mw._send_status("Update 1")
    await mw._send_status("Update 2")
    await mw._send_status("Update 3")

    assert len(channel.sent_messages) == 2


@pytest.mark.asyncio
async def test_throttling_time_allows_after_interval():
    channel = MockChannel()
    mw = _make_middleware(
        config=_make_config(min_interval_seconds=0),
        channel=channel,
    )

    await mw._send_status("First update")
    await mw._send_status("Second update")

    assert len(channel.sent_messages) == 2


# ---------------------------------------------------------------------------
# reset
# ---------------------------------------------------------------------------


def test_reset_clears_counters():
    channel = MockChannel()
    mw = _make_middleware(channel=channel)
    mw._updates_sent = 5
    mw._last_update_time = time.monotonic()
    mw._last_reported_tools = frozenset(["read_file"])

    mw.reset()

    assert mw._channel is None
    assert mw._session_key is None
    assert mw._updates_sent == 0
    assert mw._last_update_time == 0.0
    assert mw._last_reported_tools == frozenset()


# ---------------------------------------------------------------------------
# Config model
# ---------------------------------------------------------------------------


class TestStatusUpdatesConfig:
    """Config model validation."""

    def test_defaults(self):
        config = StatusUpdatesConfig()
        assert config.enabled is True
        assert config.agent_start is True
        assert config.tool_calls_detected is True
        assert config.tool_start is False
        assert config.tool_complete is False
        assert config.subagent_spawned is True
        assert config.min_interval_seconds == 3
        assert config.max_updates_per_run == 10
        assert config.template == "[{event}] {message}"

    def test_custom_values(self):
        config = StatusUpdatesConfig(
            enabled=False,
            agent_start=False,
            tool_calls_detected=False,
            tool_start=True,
            tool_complete=True,
            subagent_spawned=False,
            min_interval_seconds=0,
            max_updates_per_run=5,
            template="{message}",
        )
        assert config.enabled is False
        assert config.agent_start is False
        assert config.tool_calls_detected is False
        assert config.tool_start is True
        assert config.tool_complete is True
        assert config.subagent_spawned is False
        assert config.min_interval_seconds == 0
        assert config.max_updates_per_run == 5
        assert config.template == "{message}"

    def test_min_interval_bounds(self):
        with pytest.raises(Exception):
            StatusUpdatesConfig(min_interval_seconds=-1)

    def test_max_updates_bounds(self):
        with pytest.raises(Exception):
            StatusUpdatesConfig(max_updates_per_run=-1)

    def test_percent_bounds(self):
        with pytest.raises(Exception):
            StatusUpdatesConfig(min_interval_seconds=-1)
