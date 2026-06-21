"""Tests for SubAgentRunner status_callback lifecycle events."""

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest

from openpaw.agent.metrics import InvocationMetrics
from openpaw.agent.runner import AgentRunner
from openpaw.channels.base import ChannelAdapter
from openpaw.model.subagent import SubAgentRequest, SubAgentStatus
from openpaw.runtime.subagent.runner import SubAgentRunner
from openpaw.stores.subagent import SubAgentStore

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_store():
    store = Mock(spec=SubAgentStore)
    store.update_status = AsyncMock()
    store.save_result = AsyncMock()
    store.get = AsyncMock(return_value=None)
    store.get_result = AsyncMock(return_value=None)
    store.list_active = AsyncMock(return_value=[])
    store.list_recent = AsyncMock(return_value=[])
    return store


@pytest.fixture
def mock_channel():
    channel = Mock(spec=ChannelAdapter)
    channel.send_message = AsyncMock()
    return channel


@pytest.fixture
def success_runner():
    runner = Mock(spec=AgentRunner)
    runner.run = AsyncMock(return_value="done")
    runner.additional_tools = []
    runner._build_agent = Mock(return_value=Mock())
    runner._agent = Mock()
    runner._middleware = []
    runner._log_label = "test"
    runner.last_metrics = InvocationMetrics(
        input_tokens=10, output_tokens=5, total_tokens=15, llm_calls=1
    )
    runner._last_tools_used = []
    runner._current_tool_name = None
    return runner


@pytest.fixture
def failing_runner():
    runner = Mock(spec=AgentRunner)
    runner.run = AsyncMock(side_effect=RuntimeError("boom"))
    runner.additional_tools = []
    runner._build_agent = Mock(return_value=Mock())
    runner._agent = Mock()
    runner._middleware = []
    runner._log_label = "test"
    runner.last_metrics = None
    runner._last_tools_used = []
    runner._current_tool_name = None
    return runner


def _make_request(
    request_id: str = "req-1",
    label: str = "researcher",
    notify: bool = False,
) -> SubAgentRequest:
    return SubAgentRequest(
        id=request_id,
        task="Do research",
        label=label,
        status=SubAgentStatus.RUNNING,
        session_key="telegram:12345",
        timeout_minutes=30,
        notify=notify,
    )


def _make_runner(
    agent_runner_fixture,
    mock_store,
    mock_channel,
    status_callback=None,
) -> SubAgentRunner:
    return SubAgentRunner(
        agent_factory=lambda: agent_runner_fixture,
        store=mock_store,
        channels={"telegram": mock_channel},
        workspace_name="test",
        max_concurrent=4,
        status_callback=status_callback,
    )


# ---------------------------------------------------------------------------
# Status callback — start event
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_status_callback_fires_start_on_spawn(
    success_runner, mock_store, mock_channel
):
    events: list[tuple] = []

    async def callback(subagent_id, event, text, emoji):
        events.append((subagent_id, event, text, emoji))

    runner = _make_runner(success_runner, mock_store, mock_channel, callback)
    request = _make_request()
    await runner._execute_subagent(request)

    start_events = [e for e in events if e[1] == "start"]
    assert len(start_events) == 1
    assert start_events[0][0] == "req-1"
    assert start_events[0][2] == "researcher"


# ---------------------------------------------------------------------------
# Status callback — completed event
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_status_callback_fires_completed_on_success(
    success_runner, mock_store, mock_channel
):
    events: list[tuple] = []

    async def callback(subagent_id, event, text, emoji):
        events.append((subagent_id, event, text, emoji))

    runner = _make_runner(success_runner, mock_store, mock_channel, callback)
    request = _make_request()
    await runner._execute_subagent(request)

    terminal = [e for e in events if e[1] in ("completed", "failed", "cancelled")]
    assert len(terminal) == 1
    assert terminal[0][1] == "completed"
    assert terminal[0][0] == "req-1"


# ---------------------------------------------------------------------------
# Status callback — failed event
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_status_callback_fires_failed_on_exception(
    failing_runner, mock_store, mock_channel
):
    events: list[tuple] = []

    async def callback(subagent_id, event, text, emoji):
        events.append((subagent_id, event, text, emoji))

    runner = _make_runner(failing_runner, mock_store, mock_channel, callback)
    request = _make_request()
    await runner._execute_subagent(request)

    terminal = [e for e in events if e[1] in ("completed", "failed", "cancelled")]
    assert len(terminal) == 1
    assert terminal[0][1] == "failed"


# ---------------------------------------------------------------------------
# Status callback — cancelled event (before re-raise)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_status_callback_fires_cancelled_before_reraise(
    mock_store, mock_channel
):
    events: list[tuple] = []

    async def callback(subagent_id, event, text, emoji):
        events.append((subagent_id, event, text, emoji))

    slow_runner = Mock(spec=AgentRunner)

    async def slow_run(message):
        await asyncio.sleep(10)
        return "never"

    slow_runner.run = AsyncMock(side_effect=slow_run)
    slow_runner.additional_tools = []
    slow_runner._build_agent = Mock(return_value=Mock())
    slow_runner._agent = Mock()
    slow_runner._middleware = []
    slow_runner._log_label = "test"
    slow_runner.last_metrics = None
    slow_runner._last_tools_used = []
    slow_runner._current_tool_name = None

    runner = _make_runner(slow_runner, mock_store, mock_channel, callback)
    request = _make_request()

    task = asyncio.create_task(runner._execute_subagent(request))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    cancelled_events = [e for e in events if e[1] == "cancelled"]
    assert len(cancelled_events) == 1
    assert cancelled_events[0][0] == "req-1"


# ---------------------------------------------------------------------------
# Status callback — profile not found fires failed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_status_callback_fires_failed_on_profile_not_found(
    mock_store, mock_channel
):
    from openpaw.runtime.subagent.profiler import ProfileNotFoundError

    events: list[tuple] = []

    async def callback(subagent_id, event, text, emoji):
        events.append((subagent_id, event, text, emoji))

    dummy_runner = Mock(spec=AgentRunner)
    dummy_runner.additional_tools = []
    dummy_runner._middleware = []
    dummy_runner._log_label = "test"

    runner_inst = SubAgentRunner(
        agent_factory=lambda: dummy_runner,
        store=mock_store,
        channels={"telegram": mock_channel},
        workspace_name="test",
        max_concurrent=4,
        status_callback=callback,
    )
    # Force profiler to raise ProfileNotFoundError
    runner_inst._profiler.setup = Mock(
        side_effect=ProfileNotFoundError("missing-profile")
    )

    request = SubAgentRequest(
        id="req-pnf",
        task="task",
        label="label",
        status=SubAgentStatus.RUNNING,
        session_key="telegram:12345",
        timeout_minutes=30,
        notify=False,
        profile="missing-profile",
    )
    await runner_inst._execute_subagent(request)

    failed_events = [e for e in events if e[1] == "failed"]
    assert len(failed_events) == 1
    assert failed_events[0][0] == "req-pnf"


# ---------------------------------------------------------------------------
# Status callback — None is safe (no-op)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_status_callback_runs_fine(success_runner, mock_store, mock_channel):
    """SubAgentRunner with status_callback=None should work without errors."""
    runner = _make_runner(success_runner, mock_store, mock_channel, status_callback=None)
    request = _make_request()

    # Should not raise
    await runner._execute_subagent(request)

    status_calls = mock_store.update_status.call_args_list
    assert any(c[0][1] == SubAgentStatus.COMPLETED for c in status_calls)


# ---------------------------------------------------------------------------
# Status callback — config disabled via WorkspaceRunner closure pattern
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_callback_errors_are_suppressed(success_runner, mock_store, mock_channel):
    """Exceptions in the callback must not propagate into the sub-agent run."""

    async def bad_callback(subagent_id, event, text, emoji):
        raise RuntimeError("callback exploded")

    runner = _make_runner(success_runner, mock_store, mock_channel, bad_callback)
    request = _make_request()

    # Should not raise despite the callback crashing
    await runner._execute_subagent(request)

    status_calls = mock_store.update_status.call_args_list
    assert any(c[0][1] == SubAgentStatus.COMPLETED for c in status_calls)


# ---------------------------------------------------------------------------
# Multiple concurrent sub-agents — callbacks are isolated by subagent_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_subagents_receive_separate_ids(
    mock_store, mock_channel
):
    ids_seen: set[str] = set()

    async def callback(subagent_id, event, text, emoji):
        ids_seen.add(subagent_id)

    async def quick_run(message):
        await asyncio.sleep(0.01)
        return "done"

    def make_agent():
        r = Mock(spec=AgentRunner)
        r.run = AsyncMock(side_effect=quick_run)
        r.additional_tools = []
        r._build_agent = Mock(return_value=Mock())
        r._agent = Mock()
        r._middleware = []
        r._log_label = "test"
        r.last_metrics = InvocationMetrics(
            input_tokens=1, output_tokens=1, total_tokens=2, llm_calls=1
        )
        r._last_tools_used = []
        r._current_tool_name = None
        return r

    runner = SubAgentRunner(
        agent_factory=make_agent,
        store=mock_store,
        channels={"telegram": mock_channel},
        workspace_name="test",
        max_concurrent=4,
        status_callback=callback,
    )

    req1 = _make_request("req-A", "alpha")
    req2 = _make_request("req-B", "beta")

    await asyncio.gather(
        runner._execute_subagent(req1),
        runner._execute_subagent(req2),
    )

    assert "req-A" in ids_seen
    assert "req-B" in ids_seen
