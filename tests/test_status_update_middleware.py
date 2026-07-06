"""Tests for StatusUpdateMiddleware."""

import time
from typing import Any
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage

from openpaw.agent.middleware.status_update import StatusUpdateMiddleware
from openpaw.core.config.models import StatusUpdatesConfig


class MockMessage:
    """Mock message returned by send_message."""

    def __init__(self, id: str, session_key: str, content: str):
        self.id = id
        self.session_key = session_key
        self.content = content


class MockChannel:
    """Mock channel adapter for testing."""

    def __init__(self):
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


def _make_config(
    enabled: bool = True,
    agent_start: bool = True,
    tool_calls_detected: bool = True,
    tool_start: bool = False,
    tool_complete: bool = False,
    subagent_spawned: bool = True,
    steer_redirected: bool = True,
    run_interrupted: bool = True,
    collect_queued: bool = True,
    min_interval_seconds: int = 0,
    edit_in_place: bool = True,
    use_emojis: bool = False,
    typing_indicator: bool = True,
    reactions: bool = True,
) -> StatusUpdatesConfig:
    return StatusUpdatesConfig(
        enabled=enabled,
        agent_start=agent_start,
        tool_calls_detected=tool_calls_detected,
        tool_start=tool_start,
        tool_complete=tool_complete,
        subagent_spawned=subagent_spawned,
        steer_redirected=steer_redirected,
        run_interrupted=run_interrupted,
        collect_queued=collect_queued,
        min_interval_seconds=min_interval_seconds,
        edit_in_place=edit_in_place,
        use_emojis=use_emojis,
        typing_indicator=typing_indicator,
        reactions=reactions,
    )


def _make_middleware(
    config: StatusUpdatesConfig | None = None,
    channel: MockChannel | None = None,
    session_key: str = "telegram:123456",
    start_label: str = "Starting work...",
    run_count: int = 1,
) -> StatusUpdateMiddleware:
    cfg = config or _make_config()
    mw = StatusUpdateMiddleware(cfg, start_label=start_label)
    if channel:
        mw.set_context(channel, session_key, run_count=run_count)
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
async def test_abefore_agent_uses_custom_start_label_on_first_run():
    channel = MockChannel()
    mw = _make_middleware(channel=channel, start_label="Considering...")

    result = await mw.abefore_agent({}, None)

    assert result is None
    assert channel.sent_messages[0] == ("telegram:123456", "Considering...")


@pytest.mark.asyncio
async def test_abefore_agent_uses_continuing_label_on_later_run_despite_start_label():
    channel = MockChannel()
    mw = _make_middleware(
        channel=channel, start_label="Considering...", run_count=2
    )

    result = await mw.abefore_agent({}, None)

    assert result is None
    assert channel.sent_messages[0] == ("telegram:123456", "Continuing work...")


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
async def test_aafter_model_includes_tool_details():
    channel = MockChannel()
    mw = _make_middleware(channel=channel)
    state = {
        "messages": [
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "read_file", "id": "call_1", "args": {"file_path": "notes.md"}},
                    {"name": "write_file", "id": "call_2", "args": {"file_path": "report.md"}},
                    {"name": "spawn_agent", "id": "call_3", "args": {"label": "researcher"}},
                ],
            )
        ]
    }

    result = await mw.aafter_model(state, None)

    assert result is None
    assert len(channel.sent_messages) == 1
    assert channel.sent_messages[0] == (
        "telegram:123456",
        "Using tools: read_file (notes.md), write_file (report.md), spawn_agent (researcher)...",
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

    # In edit-in-place mode: 1 sent, 1 edited
    assert len(channel.sent_messages) == 1
    assert len(channel.edited_messages) == 1


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
async def test_awrap_tool_call_reports_tool_start_with_args():
    channel = MockChannel()
    mw = _make_middleware(config=_make_config(tool_start=True), channel=channel)
    req = _make_tool_request("read_file", {"file_path": "notes.md"})

    async def handler(request: Any) -> Any:
        return MagicMock()

    await mw.awrap_tool_call(req, handler)
    assert len(channel.sent_messages) == 1
    assert channel.sent_messages[0] == (
        "telegram:123456",
        "Running tool: read_file (notes.md)...",
    )


@pytest.mark.asyncio
async def test_awrap_tool_call_reports_tool_start_with_spawn_agent_args():
    channel = MockChannel()
    mw = _make_middleware(config=_make_config(tool_start=True), channel=channel)
    req = _make_tool_request("spawn_agent", {"label": "researcher", "task": "do research"})

    async def handler(request: Any) -> Any:
        return MagicMock()

    await mw.awrap_tool_call(req, handler)
    # In edit-in-place mode: subagent_spawned sent first, then tool_start edits it
    assert len(channel.sent_messages) == 1
    assert len(channel.edited_messages) == 1
    assert channel.sent_messages[0] == (
        "telegram:123456",
        "Dispatched sub-agent: researcher",
    )
    assert channel.edited_messages[0] == (
        "telegram:123456",
        "1",
        "Running tool: spawn_agent (researcher)...",
    )


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
    # In edit-in-place mode: first sent, second edited
    assert len(channel.sent_messages) == 1
    assert len(channel.edited_messages) == 1
    assert channel.sent_messages[0] == ("telegram:123456", "Running tool: read_file...")
    assert channel.edited_messages[0] == ("telegram:123456", "1", "Completed: read_file")


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

    # In edit-in-place mode: 1 sent, 1 throttled
    assert len(channel.sent_messages) == 1


@pytest.mark.asyncio
async def test_throttling_time_allows_after_interval():
    channel = MockChannel()
    mw = _make_middleware(
        config=_make_config(min_interval_seconds=0),
        channel=channel,
    )

    await mw._send_status("First update")
    await mw._send_status("Second update")

    # In edit-in-place mode: 1 sent, 1 edited
    assert len(channel.sent_messages) == 1
    assert len(channel.edited_messages) == 1


# ---------------------------------------------------------------------------
# reset
# ---------------------------------------------------------------------------


def test_reset_clears_counters():
    channel = MockChannel()
    mw = _make_middleware(channel=channel)
    mw._last_update_time = time.monotonic()
    mw._last_reported_tools = frozenset(["read_file"])
    mw._status_message_id = "msg123"

    mw.reset()

    assert mw._channel is None
    assert mw._session_key is None
    assert mw._last_update_time == 0.0
    assert mw._last_reported_tools == frozenset()
    assert mw._status_message_id is None


# ---------------------------------------------------------------------------
# Edit-in-place mode
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_edit_in_place_mode_edits_single_message():
    channel = MockChannel()
    mw = _make_middleware(channel=channel)

    # First update: send new message
    await mw._send_status("Starting work...")
    assert len(channel.sent_messages) == 1
    assert len(channel.edited_messages) == 0

    # Second update: edit existing message
    await mw._send_status("Using tools: read_file...")
    assert len(channel.sent_messages) == 1
    assert len(channel.edited_messages) == 1
    assert channel.edited_messages[0] == (
        "telegram:123456",
        "1",  # message_id from MockMessage
        "Using tools: read_file...",
    )


@pytest.mark.asyncio
async def test_edit_in_place_mode_falls_back_to_new_message_on_edit_failure():
    channel = MockChannel()
    # Make edit fail
    async def failing_edit(session_key: str, message_id: str, content: str) -> bool:
        return False

    channel.edit_message = failing_edit
    mw = _make_middleware(channel=channel)

    # First update: send new message
    await mw._send_status("Starting work...")
    assert len(channel.sent_messages) == 1

    # Second update: edit fails, fallback to new message
    await mw._send_status("Using tools: read_file...")
    assert len(channel.sent_messages) == 2
    assert len(channel.edited_messages) == 0


@pytest.mark.asyncio
async def test_edit_in_place_mode_disabled_sends_separate_messages():
    channel = MockChannel()
    mw = _make_middleware(config=_make_config(edit_in_place=False), channel=channel)

    await mw._send_status("Starting work...")
    await mw._send_status("Using tools: read_file...")

    assert len(channel.sent_messages) == 2
    assert len(channel.edited_messages) == 0


@pytest.mark.asyncio
async def test_delete_status_deletes_tracked_message():
    channel = MockChannel()
    mw = _make_middleware(channel=channel)

    # Send a status message
    await mw._send_status("Starting work...")
    assert len(channel.sent_messages) == 1
    message_id = mw._status_message_id
    assert message_id is not None

    # Delete it
    await mw.delete_status()
    assert len(channel.deleted_messages) == 1
    assert channel.deleted_messages[0] == ("telegram:123456", message_id)
    assert mw._status_message_id is None


@pytest.mark.asyncio
async def test_delete_status_noop_without_tracked_message():
    channel = MockChannel()
    mw = _make_middleware(channel=channel)

    await mw.delete_status()
    assert len(channel.deleted_messages) == 0


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
        assert config.tool_start is True
        assert config.tool_complete is False
        assert config.subagent_spawned is True
        assert config.steer_redirected is True
        assert config.run_interrupted is True
        assert config.collect_queued is True
        assert config.min_interval_seconds == 1
        assert config.template == "[{event}] {message}"
        assert config.edit_in_place is True
        assert config.typing_indicator is True
        assert config.reactions is True
        assert config.use_emojis is True
        assert config.typing_indicator is True
        assert config.reactions is True
        assert config.use_emojis is True

    def test_custom_values(self):
        config = StatusUpdatesConfig(
            enabled=False,
            agent_start=False,
            tool_calls_detected=False,
            tool_start=True,
            tool_complete=True,
            subagent_spawned=False,
            steer_redirected=False,
            run_interrupted=False,
            collect_queued=False,
            min_interval_seconds=0,
            template="{message}",
            edit_in_place=False,
            typing_indicator=False,
            reactions=False,
            use_emojis=False,
        )
        assert config.enabled is False
        assert config.agent_start is False
        assert config.tool_calls_detected is False
        assert config.tool_start is True
        assert config.tool_complete is True
        assert config.subagent_spawned is False
        assert config.steer_redirected is False
        assert config.run_interrupted is False
        assert config.collect_queued is False
        assert config.min_interval_seconds == 0
        assert config.template == "{message}"
        assert config.edit_in_place is False
        assert config.typing_indicator is False
        assert config.reactions is False
        assert config.use_emojis is False

    def test_min_interval_bounds(self):
        with pytest.raises(Exception):
            StatusUpdatesConfig(min_interval_seconds=-1)

    def test_percent_bounds(self):
        with pytest.raises(Exception):
            StatusUpdatesConfig(min_interval_seconds=-1)

    def test_new_flags_default_true(self):
        config = StatusUpdatesConfig()
        assert config.steer_redirected is True
        assert config.run_interrupted is True
        assert config.collect_queued is True

    def test_new_flags_custom_values(self):
        config = StatusUpdatesConfig(
            steer_redirected=False,
            run_interrupted=False,
            collect_queued=False,
        )
        assert config.steer_redirected is False
        assert config.run_interrupted is False
        assert config.collect_queued is False


# ---------------------------------------------------------------------------
# Steer / Interrupt / Collect notifications
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_awrap_tool_call_detects_steer_skip():
    from langchain_core.messages import ToolMessage
    from openpaw.core.prompts.system_events import STEER_SKIP_MESSAGE

    channel = MockChannel()
    mw = _make_middleware(channel=channel)
    req = _make_tool_request("read_file")

    async def handler(request: Any) -> Any:
        return ToolMessage(content=STEER_SKIP_MESSAGE, tool_call_id="call_123")

    result = await mw.awrap_tool_call(req, handler)
    assert result.content == STEER_SKIP_MESSAGE
    # No prior status message exists, so it sends a new message
    assert len(channel.sent_messages) == 1
    assert channel.sent_messages[0] == (
        "telegram:123456",
        "🔄 Redirecting to your new message...",
    )


@pytest.mark.asyncio
async def test_awrap_tool_call_detects_steer_skip_with_existing_status():
    from langchain_core.messages import ToolMessage
    from openpaw.core.prompts.system_events import STEER_SKIP_MESSAGE

    channel = MockChannel()
    mw = _make_middleware(channel=channel)
    # Establish a prior status message
    await mw._send_status("Starting work...")
    assert len(channel.sent_messages) == 1

    req = _make_tool_request("read_file")

    async def handler(request: Any) -> Any:
        return ToolMessage(content=STEER_SKIP_MESSAGE, tool_call_id="call_123")

    result = await mw.awrap_tool_call(req, handler)
    assert result.content == STEER_SKIP_MESSAGE
    # In edit-in-place mode: steer notification edits the existing message
    assert len(channel.sent_messages) == 1
    assert len(channel.edited_messages) == 1
    assert channel.edited_messages[0] == (
        "telegram:123456",
        "1",
        "🔄 Redirecting to your new message...",
    )


@pytest.mark.asyncio
async def test_awrap_tool_call_detects_interrupt():
    from openpaw.agent.middleware.queue_aware import InterruptSignalError

    channel = MockChannel()
    mw = _make_middleware(channel=channel)
    req = _make_tool_request("read_file")

    async def handler(request: Any) -> Any:
        raise InterruptSignalError([("telegram", "test")])

    with pytest.raises(InterruptSignalError):
        await mw.awrap_tool_call(req, handler)

    # No prior status message exists, so it sends a new message
    assert len(channel.sent_messages) == 1
    assert channel.sent_messages[0] == (
        "telegram:123456",
        "🛑 Stopping current run — processing your new message",
    )


@pytest.mark.asyncio
async def test_awrap_tool_call_detects_interrupt_with_existing_status():
    from openpaw.agent.middleware.queue_aware import InterruptSignalError

    channel = MockChannel()
    mw = _make_middleware(channel=channel)
    # Establish a prior status message
    await mw._send_status("Starting work...")
    assert len(channel.sent_messages) == 1

    req = _make_tool_request("read_file")

    async def handler(request: Any) -> Any:
        raise InterruptSignalError([("telegram", "test")])

    with pytest.raises(InterruptSignalError):
        await mw.awrap_tool_call(req, handler)

    # In edit-in-place mode: interrupt notification edits the existing message
    assert len(channel.sent_messages) == 1
    assert len(channel.edited_messages) == 1
    assert channel.edited_messages[0] == (
        "telegram:123456",
        "1",
        "🛑 Stopping current run — processing your new message",
    )


@pytest.mark.asyncio
async def test_steer_notification_disabled_by_config():
    from langchain_core.messages import ToolMessage
    from openpaw.core.prompts.system_events import STEER_SKIP_MESSAGE

    channel = MockChannel()
    mw = _make_middleware(
        config=_make_config(steer_redirected=False),
        channel=channel,
    )
    req = _make_tool_request("read_file")

    async def handler(request: Any) -> Any:
        return ToolMessage(content=STEER_SKIP_MESSAGE, tool_call_id="call_123")

    result = await mw.awrap_tool_call(req, handler)
    assert result.content == STEER_SKIP_MESSAGE
    assert len(channel.sent_messages) == 0
    assert len(channel.edited_messages) == 0


@pytest.mark.asyncio
async def test_interrupt_notification_disabled_by_config():
    from openpaw.agent.middleware.queue_aware import InterruptSignalError

    channel = MockChannel()
    mw = _make_middleware(
        config=_make_config(run_interrupted=False),
        channel=channel,
    )
    req = _make_tool_request("read_file")

    async def handler(request: Any) -> Any:
        raise InterruptSignalError([("telegram", "test")])

    with pytest.raises(InterruptSignalError):
        await mw.awrap_tool_call(req, handler)

    assert len(channel.sent_messages) == 0
    assert len(channel.edited_messages) == 0


@pytest.mark.asyncio
async def test_steer_notification_bypasses_throttle():
    from langchain_core.messages import ToolMessage
    from openpaw.core.prompts.system_events import STEER_SKIP_MESSAGE

    channel = MockChannel()
    mw = _make_middleware(
        config=_make_config(min_interval_seconds=999),
        channel=channel,
    )
    req = _make_tool_request("read_file")

    async def handler(request: Any) -> Any:
        return ToolMessage(content=STEER_SKIP_MESSAGE, tool_call_id="call_123")

    result = await mw.awrap_tool_call(req, handler)
    assert result.content == STEER_SKIP_MESSAGE
    # Should still be sent despite extreme throttle
    assert len(channel.sent_messages) == 1
    assert channel.sent_messages[0] == (
        "telegram:123456",
        "🔄 Redirecting to your new message...",
    )


@pytest.mark.asyncio
async def test_awrap_tool_call_steer_notification_fires_exactly_once():
    """Steer notification is sent only once even when multiple tools are skipped."""
    from langchain_core.messages import ToolMessage

    from openpaw.core.prompts.system_events import STEER_SKIP_MESSAGE, STEER_USER_NOTIFICATION

    channel = MockChannel()
    mw = _make_middleware(
        config=_make_config(steer_redirected=True, enabled=True),
        channel=channel,
    )

    async def handler(request: Any) -> Any:
        return ToolMessage(content=STEER_SKIP_MESSAGE, tool_call_id="call_1")

    # Invoke awrap_tool_call three times simulating three skipped tools in one turn
    await mw.awrap_tool_call(_make_tool_request("tool_a"), handler)
    await mw.awrap_tool_call(_make_tool_request("tool_b"), handler)
    await mw.awrap_tool_call(_make_tool_request("tool_c"), handler)

    # Count all channel interactions that contain the steer notification text
    steer_count = sum(
        1 for (_, content) in channel.sent_messages if STEER_USER_NOTIFICATION in content
    ) + sum(
        1 for (_, _, content) in channel.edited_messages if STEER_USER_NOTIFICATION in content
    )
    assert steer_count == 1, f"Expected 1 steer notification, got {steer_count}"
    assert mw._steer_notified is True


@pytest.mark.asyncio
async def test_steer_notified_resets_after_reset():
    """_steer_notified is False after reset(), allowing subsequent runs to notify again."""
    from langchain_core.messages import ToolMessage

    from openpaw.core.prompts.system_events import STEER_SKIP_MESSAGE, STEER_USER_NOTIFICATION

    channel = MockChannel()
    mw = _make_middleware(
        config=_make_config(steer_redirected=True, enabled=True),
        channel=channel,
    )

    async def handler(request: Any) -> Any:
        return ToolMessage(content=STEER_SKIP_MESSAGE, tool_call_id="call_1")

    # First run: notification fires
    await mw.awrap_tool_call(_make_tool_request("tool_a"), handler)
    assert mw._steer_notified is True

    # Reset simulates end of agent run
    mw.reset()
    assert mw._steer_notified is False

    # Set context for second run
    mw.set_context(channel, "telegram:123456")
    assert mw._steer_notified is False

    # Second run: notification fires again
    await mw.awrap_tool_call(_make_tool_request("tool_a"), handler)

    steer_count = sum(
        1 for (_, content) in channel.sent_messages if STEER_USER_NOTIFICATION in content
    ) + sum(
        1 for (_, _, content) in channel.edited_messages if STEER_USER_NOTIFICATION in content
    )
    assert steer_count == 2, f"Expected 2 steer notifications across two runs, got {steer_count}"


@pytest.mark.asyncio
async def test_send_forced_status_bypasses_throttle():
    channel = MockChannel()
    mw = _make_middleware(
        config=_make_config(min_interval_seconds=999),
        channel=channel,
    )

    await mw.send_forced_status("📨 New messages received — bundling...")
    assert len(channel.sent_messages) == 1
    assert channel.sent_messages[0] == ("telegram:123456", "📨 New messages received — bundling...")


@pytest.mark.asyncio
async def test_send_forced_status_edits_when_message_exists():
    channel = MockChannel()
    mw = _make_middleware(channel=channel)

    # Establish a status message
    await mw._send_status("Starting work...")
    assert len(channel.sent_messages) == 1

    # Force-send should edit the existing message
    await mw.send_forced_status("📨 New messages received — bundling...")
    assert len(channel.sent_messages) == 1
    assert len(channel.edited_messages) == 1
    assert channel.edited_messages[0] == (
        "telegram:123456",
        "1",
        "📨 New messages received — bundling...",
    )


# ---------------------------------------------------------------------------
# Emoji behavior
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_abefore_agent_uses_emoji_when_enabled():
    channel = MockChannel()
    mw = _make_middleware(config=_make_config(use_emojis=True), channel=channel)

    result = await mw.abefore_agent({}, None)

    assert result is None
    assert len(channel.sent_messages) == 1
    assert channel.sent_messages[0] == ("telegram:123456", "🚀 Starting work...")


@pytest.mark.asyncio
async def test_aafter_model_uses_emoji_for_tools():
    channel = MockChannel()
    mw = _make_middleware(config=_make_config(use_emojis=True), channel=channel)
    state = {"messages": [_ai_with_tool_calls("read_file", "write_file")]}

    result = await mw.aafter_model(state, None)

    assert result is None
    assert len(channel.sent_messages) == 1
    assert channel.sent_messages[0] == (
        "telegram:123456",
        "📖 Using tools: read_file, write_file...",
    )


@pytest.mark.asyncio
async def test_awrap_tool_call_uses_emoji_for_spawn_agent():
    channel = MockChannel()
    mw = _make_middleware(config=_make_config(use_emojis=True), channel=channel)
    req = _make_tool_request("spawn_agent", {"label": "researcher"})

    async def handler(request: Any) -> Any:
        return MagicMock()

    result = await mw.awrap_tool_call(req, handler)
    assert result is not None
    assert len(channel.sent_messages) == 1
    assert channel.sent_messages[0] == ("telegram:123456", "🤖 Dispatched sub-agent: researcher")


@pytest.mark.asyncio
async def test_emoji_disabled_when_use_emojis_false():
    channel = MockChannel()
    mw = _make_middleware(config=_make_config(use_emojis=False), channel=channel)
    state = {"messages": [_ai_with_tool_calls("read_file")]}

    await mw.abefore_agent({}, None)
    await mw.aafter_model(state, None)

    # In edit-in-place mode: first sent, second edited
    assert len(channel.sent_messages) == 1
    assert len(channel.edited_messages) == 1
    assert channel.sent_messages[0] == ("telegram:123456", "Starting work...")
    assert channel.edited_messages[0] == ("telegram:123456", "1", "Using tools: read_file...")


@pytest.mark.asyncio
async def test_emoji_map_returns_default_for_unknown_tool():
    channel = MockChannel()
    mw = _make_middleware(config=_make_config(use_emojis=True), channel=channel)
    state = {"messages": [_ai_with_tool_calls("unknown_tool")]}

    result = await mw.aafter_model(state, None)

    assert result is None
    assert len(channel.sent_messages) == 1
    assert channel.sent_messages[0] == (
        "telegram:123456",
        "🔧 Using tools: unknown_tool...",
    )


# ---------------------------------------------------------------------------
# Sub-agent status methods
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_subagent_status_sends_message_and_stores_id():
    channel = MockChannel()
    mw = _make_middleware(channel=channel)

    await mw.create_subagent_status("req-1", "researcher")

    assert len(channel.sent_messages) == 1
    content = channel.sent_messages[0][1]
    assert "researcher" in content
    assert "req-1" in mw._subagent_status_ids
    msg_id, label, _ch, _sk = mw._subagent_status_ids["req-1"]
    assert msg_id == "1"
    assert label == "researcher"


@pytest.mark.asyncio
async def test_create_subagent_status_noop_when_disabled():
    channel = MockChannel()
    mw = _make_middleware(config=_make_config(enabled=False), channel=channel)

    await mw.create_subagent_status("req-1", "researcher")

    assert len(channel.sent_messages) == 0
    assert "req-1" not in mw._subagent_status_ids


@pytest.mark.asyncio
async def test_create_subagent_status_noop_when_subagent_status_false():
    channel = MockChannel()
    cfg = _make_config()
    cfg2 = cfg.model_copy(update={"subagent_status": False})
    mw = _make_middleware(config=cfg2, channel=channel)

    await mw.create_subagent_status("req-1", "researcher")

    assert len(channel.sent_messages) == 0


@pytest.mark.asyncio
async def test_create_subagent_status_noop_without_channel_context():
    mw = _make_middleware()
    # No channel set

    await mw.create_subagent_status("req-1", "researcher")

    assert "req-1" not in mw._subagent_status_ids


@pytest.mark.asyncio
async def test_update_subagent_status_edits_correct_message():
    channel = MockChannel()
    mw = _make_middleware(channel=channel)

    await mw.create_subagent_status("req-1", "researcher")
    await mw.update_subagent_status("req-1", "Running tool: brave_search...")

    assert len(channel.edited_messages) == 1
    assert channel.edited_messages[0][1] == "1"
    assert "brave_search" in channel.edited_messages[0][2]


@pytest.mark.asyncio
async def test_update_subagent_status_noop_for_unknown_id():
    channel = MockChannel()
    mw = _make_middleware(channel=channel)

    await mw.update_subagent_status("unknown-id", "Running tool: read_file...")

    assert len(channel.edited_messages) == 0


@pytest.mark.asyncio
async def test_update_subagent_status_noop_when_disabled():
    channel = MockChannel()
    mw = _make_middleware(config=_make_config(enabled=False), channel=channel)
    mw._subagent_status_ids["req-1"] = ("msg-99", "researcher", channel, "telegram:123456")

    await mw.update_subagent_status("req-1", "Running tool: read_file...")

    assert len(channel.edited_messages) == 0


@pytest.mark.asyncio
async def test_finalize_subagent_status_edit_mode_on_completed():
    channel = MockChannel()
    mw = _make_middleware(channel=channel)

    await mw.create_subagent_status("req-1", "researcher")
    await mw.finalize_subagent_status("req-1", "completed")

    assert len(channel.edited_messages) == 1
    content = channel.edited_messages[0][2]
    assert "✅" in content
    assert "req-1" not in mw._subagent_status_ids


@pytest.mark.asyncio
async def test_finalize_subagent_status_edit_mode_on_failed():
    channel = MockChannel()
    mw = _make_middleware(channel=channel)

    await mw.create_subagent_status("req-1", "researcher")
    await mw.finalize_subagent_status("req-1", "failed")

    assert len(channel.edited_messages) == 1
    content = channel.edited_messages[0][2]
    assert "❌" in content
    assert "req-1" not in mw._subagent_status_ids


@pytest.mark.asyncio
async def test_finalize_subagent_status_edit_mode_on_cancelled():
    channel = MockChannel()
    mw = _make_middleware(channel=channel)

    await mw.create_subagent_status("req-1", "researcher")
    await mw.finalize_subagent_status("req-1", "cancelled")

    assert len(channel.edited_messages) == 1
    content = channel.edited_messages[0][2]
    assert "🚫" in content
    assert "req-1" not in mw._subagent_status_ids


@pytest.mark.asyncio
async def test_finalize_subagent_status_delete_mode():
    channel = MockChannel()
    cfg = _make_config()
    cfg2 = cfg.model_copy(update={"subagent_status_cleanup": "delete"})
    mw = _make_middleware(config=cfg2, channel=channel)

    await mw.create_subagent_status("req-1", "researcher")
    await mw.finalize_subagent_status("req-1", "completed")

    assert len(channel.deleted_messages) == 1
    assert channel.deleted_messages[0][1] == "1"
    assert "req-1" not in mw._subagent_status_ids


@pytest.mark.asyncio
async def test_finalize_subagent_status_noop_for_unknown_id():
    channel = MockChannel()
    mw = _make_middleware(channel=channel)

    await mw.finalize_subagent_status("unknown-id", "completed")

    assert len(channel.edited_messages) == 0
    assert len(channel.deleted_messages) == 0


@pytest.mark.asyncio
async def test_finalize_subagent_status_noop_when_subagent_status_false():
    channel = MockChannel()
    cfg = _make_config()
    cfg2 = cfg.model_copy(update={"subagent_status": False})
    mw = _make_middleware(config=cfg2, channel=channel)
    mw._subagent_status_ids["req-1"] = ("msg-1", "researcher", channel, "telegram:123456")

    await mw.finalize_subagent_status("req-1", "completed")

    assert len(channel.edited_messages) == 0
    # ID stays because the method no-opped before cleanup
    assert "req-1" in mw._subagent_status_ids


@pytest.mark.asyncio
async def test_concurrent_subagents_have_separate_message_ids():
    channel = MockChannel()
    mw = _make_middleware(channel=channel)

    await mw.create_subagent_status("req-1", "researcher")
    await mw.create_subagent_status("req-2", "writer")

    assert len(channel.sent_messages) == 2
    msg_id_1 = mw._subagent_status_ids["req-1"][0]
    msg_id_2 = mw._subagent_status_ids["req-2"][0]
    assert msg_id_1 != msg_id_2


@pytest.mark.asyncio
async def test_concurrent_subagents_edits_do_not_cross():
    channel = MockChannel()
    mw = _make_middleware(channel=channel)

    await mw.create_subagent_status("req-1", "researcher")
    await mw.create_subagent_status("req-2", "writer")

    await mw.update_subagent_status("req-1", "Running tool: brave_search...")
    await mw.update_subagent_status("req-2", "Running tool: read_file...")

    # Each edit targets its own message ID
    assert channel.edited_messages[0][1] == "1"
    assert channel.edited_messages[1][1] == "2"
    assert channel.edited_messages[0][1] != channel.edited_messages[1][1]


def test_reset_does_not_clear_subagent_status_ids():
    """Sub-agent status IDs survive reset() — sub-agents may outlive the main run."""
    channel = MockChannel()
    mw = _make_middleware(channel=channel)
    mw._subagent_status_ids["req-1"] = ("msg-42", "researcher", channel, "telegram:123456")

    mw.reset()

    assert "req-1" in mw._subagent_status_ids
    assert mw._subagent_status_ids["req-1"][0] == "msg-42"
    assert mw._subagent_status_ids["req-1"][1] == "researcher"


def test_subagent_status_config_defaults():
    config = StatusUpdatesConfig()
    assert config.subagent_status is True
    assert config.subagent_status_cleanup == "edit"


def test_subagent_status_config_custom():
    config = StatusUpdatesConfig(subagent_status=False, subagent_status_cleanup="delete")
    assert config.subagent_status is False
    assert config.subagent_status_cleanup == "delete"


def test_subagent_status_cleanup_invalid_value():
    with pytest.raises(Exception):
        StatusUpdatesConfig(subagent_status_cleanup="archive")


@pytest.mark.asyncio
async def test_finalize_removes_entry_even_without_channel_context():
    """Entry is popped and status updated even when self._channel is None after reset().

    The fix stores (channel, session_key) in the tuple at create time, so finalize
    uses the stored refs rather than the cleared self._channel / self._session_key.
    """
    channel = MockChannel()
    mw = _make_middleware(channel=channel)

    await mw.create_subagent_status("sub-1", "researcher")
    assert "sub-1" in mw._subagent_status_ids

    mw.reset()
    # Channel and session_key are now None, but the dict entry remains.
    assert mw._channel is None
    assert mw._session_key is None
    assert "sub-1" in mw._subagent_status_ids

    await mw.finalize_subagent_status("sub-1", "completed")

    # Entry is cleaned up.
    assert "sub-1" not in mw._subagent_status_ids
    # Stored channel refs allow the edit to proceed despite reset() clearing self._channel.
    assert len(channel.edited_messages) == 1
    assert "✅" in channel.edited_messages[0][2]


@pytest.mark.asyncio
async def test_finalize_works_after_reset_clears_channel():
    """finalize_subagent_status uses stored (channel, session_key) after reset()."""
    channel = MockChannel()
    mw = _make_middleware(channel=channel)

    await mw.create_subagent_status("sub-1", "researcher")
    stored_msg_id = mw._subagent_status_ids["sub-1"][0]
    stored_session_key = mw._subagent_status_ids["sub-1"][3]

    mw.reset()
    assert mw._channel is None
    assert mw._session_key is None

    await mw.finalize_subagent_status("sub-1", "completed")

    assert "sub-1" not in mw._subagent_status_ids
    assert len(channel.edited_messages) == 1
    edit_session_key, edit_msg_id, edit_content = channel.edited_messages[0]
    assert edit_session_key == stored_session_key
    assert edit_msg_id == stored_msg_id
    assert "✅" in edit_content


@pytest.mark.asyncio
async def test_update_works_after_reset_clears_channel():
    """update_subagent_status uses stored (channel, session_key) after reset()."""
    channel = MockChannel()
    mw = _make_middleware(channel=channel)

    await mw.create_subagent_status("sub-1", "researcher")
    stored_msg_id = mw._subagent_status_ids["sub-1"][0]
    stored_session_key = mw._subagent_status_ids["sub-1"][3]

    mw.reset()
    assert mw._channel is None
    assert mw._session_key is None

    await mw.update_subagent_status("sub-1", "Running tool: shell", "💻")

    assert len(channel.edited_messages) == 1
    edit_session_key, edit_msg_id, edit_content = channel.edited_messages[0]
    assert edit_session_key == stored_session_key
    assert edit_msg_id == stored_msg_id
    assert "Running tool: shell" in edit_content
