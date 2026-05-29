"""Tests for sub-agent periodic progress update feature."""

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock, patch

import pytest

from openpaw.agent.runner import AgentRunner
from openpaw.model.subagent import SubAgentRequest, SubAgentStatus
from openpaw.runtime.subagent.formatter import _format_elapsed, build_origin_suffix
from openpaw.runtime.subagent.runner import SubAgentRunner
from openpaw.stores.subagent import SubAgentStore, create_subagent_request


# ---------------------------------------------------------------------------
# SubAgentRequest model tests
# ---------------------------------------------------------------------------


def _make_request(**kwargs) -> SubAgentRequest:
    """Build a minimal SubAgentRequest for tests."""
    defaults = dict(
        id="test-id",
        task="do something",
        label="test-label",
        status=SubAgentStatus.PENDING,
        session_key="telegram:12345",
    )
    defaults.update(kwargs)
    return SubAgentRequest(**defaults)


class TestSubAgentRequestProgressField:
    def test_defaults_to_zero(self):
        request = _make_request()
        assert request.progress_interval_minutes == 0

    def test_explicit_value_stored(self):
        request = _make_request(progress_interval_minutes=5)
        assert request.progress_interval_minutes == 5

    def test_to_dict_omits_field_when_zero(self):
        request = _make_request(progress_interval_minutes=0)
        data = request.to_dict()
        assert "progress_interval_minutes" not in data

    def test_to_dict_includes_field_when_nonzero(self):
        request = _make_request(progress_interval_minutes=3)
        data = request.to_dict()
        assert data["progress_interval_minutes"] == 3

    def test_from_dict_reads_field(self):
        request = _make_request(progress_interval_minutes=7)
        data = request.to_dict()
        assert "progress_interval_minutes" in data

        restored = SubAgentRequest.from_dict(data)
        assert restored.progress_interval_minutes == 7

    def test_from_dict_defaults_to_zero_when_missing(self):
        request = _make_request(progress_interval_minutes=0)
        data = request.to_dict()
        # Field should have been omitted by to_dict when 0
        assert "progress_interval_minutes" not in data

        restored = SubAgentRequest.from_dict(data)
        assert restored.progress_interval_minutes == 0

    def test_roundtrip_nonzero_value(self):
        original = _make_request(progress_interval_minutes=10)
        data = original.to_dict()
        restored = SubAgentRequest.from_dict(data)
        assert restored.progress_interval_minutes == 10


# ---------------------------------------------------------------------------
# _format_elapsed helper tests
# ---------------------------------------------------------------------------


class TestFormatElapsed:
    def test_seconds_only(self):
        assert _format_elapsed(45) == "45s"

    def test_zero_seconds(self):
        assert _format_elapsed(0) == "0s"

    def test_exactly_one_minute(self):
        assert _format_elapsed(60) == "1m 0s"

    def test_minutes_and_seconds(self):
        assert _format_elapsed(330) == "5m 30s"

    def test_fifty_nine_seconds(self):
        assert _format_elapsed(59) == "59s"

    def test_exactly_one_hour(self):
        assert _format_elapsed(3600) == "1h 0m 0s"

    def test_hours_minutes_seconds(self):
        # 1h 2m 3s = 3600 + 120 + 3 = 3723 seconds
        assert _format_elapsed(3723) == "1h 2m 3s"

    def test_large_value(self):
        # 2h 30m 15s = 7200 + 1800 + 15 = 9015 seconds
        assert _format_elapsed(9015) == "2h 30m 15s"

    def test_float_truncated_to_int(self):
        # Floats should be truncated, not rounded
        assert _format_elapsed(59.9) == "59s"
        assert _format_elapsed(60.9) == "1m 0s"


# ---------------------------------------------------------------------------
# _build_origin_suffix tests
# ---------------------------------------------------------------------------


class TestBuildOriginSuffix:
    def test_no_origin_returns_empty_string(self):
        request = _make_request(origin=None)
        assert build_origin_suffix(request) == ""

    def test_simple_origin(self):
        request = _make_request(origin="gilfoyle")
        assert build_origin_suffix(request) == " (spawned by gilfoyle)"

    def test_colon_separated_origin(self):
        request = _make_request(origin="session:telegram:123456")
        assert build_origin_suffix(request) == " (spawned by session: telegram:123456)"

    def test_simple_colon_origin(self):
        request = _make_request(origin="agent:gilfoyle")
        assert build_origin_suffix(request) == " (spawned by agent: gilfoyle)"


# ---------------------------------------------------------------------------
# _progress_timer tests
#
# The tests below call _progress_timer directly with a very short real sleep
# (via patching at the correct module path) so the coroutine fires quickly.
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_store():
    store = Mock(spec=SubAgentStore)
    store.update_status = Mock()
    store.save_result = Mock()
    store.get = Mock(return_value=None)
    return store


@pytest.fixture
def mock_agent_runner():
    runner = Mock(spec=AgentRunner)
    runner._last_tools_used = ["brave_search", "read_file"]
    runner._current_tool_name = "write_file"
    return runner


@pytest.fixture
def result_callback():
    return AsyncMock()


@pytest.fixture
def sub_runner(mock_store, result_callback):
    return SubAgentRunner(
        agent_factory=lambda: Mock(spec=AgentRunner),
        store=mock_store,
        channels={},
        result_callback=result_callback,
    )


async def _run_timer_once(runner: SubAgentRunner, request: SubAgentRequest, agent_runner) -> None:
    """Run the progress timer for exactly one interval using a real tiny sleep,
    then cancel it. Used as a testing harness."""
    # Override the sleep in the module to 0 seconds so the timer fires immediately
    real_sleep = asyncio.sleep

    call_count = 0

    async def instant_sleep(seconds):
        nonlocal call_count
        call_count += 1
        await real_sleep(0)  # actually yield to the event loop
        if call_count >= 2:
            raise asyncio.CancelledError

    with patch("openpaw.runtime.subagent.executor.asyncio.sleep", side_effect=instant_sleep):
        task = asyncio.create_task(runner._executor._progress_timer(request, agent_runner, 0.0))
        try:
            await task
        except asyncio.CancelledError:
            pass


class TestProgressTimer:
    @pytest.mark.asyncio
    async def test_timer_calls_callback_after_interval(self, sub_runner, mock_agent_runner, result_callback):
        """Timer should call result_callback after sleeping for the interval."""
        request = _make_request(progress_interval_minutes=1, session_key="telegram:99")
        await _run_timer_once(sub_runner, request, mock_agent_runner)
        assert result_callback.call_count >= 1

    @pytest.mark.asyncio
    async def test_timer_reads_runner_state(self, sub_runner, mock_agent_runner, result_callback):
        """Timer should include tool names from runner in the message."""
        mock_agent_runner._last_tools_used = ["brave_search", "read_file", "write_file"]
        mock_agent_runner._current_tool_name = "write_file"

        request = _make_request(progress_interval_minutes=1, session_key="telegram:99")
        await _run_timer_once(sub_runner, request, mock_agent_runner)

        assert result_callback.call_count >= 1
        content = result_callback.call_args[0][1]
        # At least one of the recent tools should appear in the message
        assert any(tool in content for tool in ["brave_search", "read_file", "write_file"])
        assert "[SYSTEM]" in content
        assert "test-label" in content

    @pytest.mark.asyncio
    async def test_timer_message_contains_elapsed(self, sub_runner, mock_agent_runner, result_callback):
        """Progress message should include elapsed time."""
        request = _make_request(progress_interval_minutes=1, session_key="telegram:99")
        await _run_timer_once(sub_runner, request, mock_agent_runner)

        content = result_callback.call_args[0][1]
        assert "Elapsed:" in content

    @pytest.mark.asyncio
    async def test_timer_session_key_passed_to_callback(self, sub_runner, mock_agent_runner, result_callback):
        """Timer should pass the request session_key as the first callback arg."""
        request = _make_request(progress_interval_minutes=1, session_key="telegram:99")
        await _run_timer_once(sub_runner, request, mock_agent_runner)

        assert result_callback.call_count >= 1
        session_key_arg = result_callback.call_args[0][0]
        assert session_key_arg == "telegram:99"

    @pytest.mark.asyncio
    async def test_timer_uses_correct_interval(self, sub_runner, mock_agent_runner, result_callback):
        """Timer should sleep for interval_minutes * 60 seconds."""
        request = _make_request(progress_interval_minutes=5, session_key="telegram:99")

        sleep_args = []
        real_sleep = asyncio.sleep

        async def capturing_sleep(seconds):
            sleep_args.append(seconds)
            await real_sleep(0)
            raise asyncio.CancelledError

        with patch("openpaw.runtime.subagent.executor.asyncio.sleep", side_effect=capturing_sleep):
            task = asyncio.create_task(sub_runner._executor._progress_timer(request, mock_agent_runner, 0.0))
            try:
                await task
            except asyncio.CancelledError:
                pass

        assert sleep_args[0] == 300  # 5 minutes * 60 seconds

    @pytest.mark.asyncio
    async def test_timer_handles_callback_exception_gracefully(self, mock_store, mock_agent_runner):
        """Timer should log a warning and continue if callback raises, not crash."""
        failing_callback = AsyncMock(side_effect=RuntimeError("channel down"))
        runner = SubAgentRunner(
            agent_factory=lambda: Mock(spec=AgentRunner),
            store=mock_store,
            channels={},
            result_callback=failing_callback,
        )

        request = _make_request(progress_interval_minutes=1, session_key="telegram:99")

        call_count = 0
        real_sleep = asyncio.sleep

        async def fast_sleep(seconds):
            nonlocal call_count
            call_count += 1
            await real_sleep(0)
            if call_count >= 3:
                raise asyncio.CancelledError

        with patch("openpaw.runtime.subagent.executor.asyncio.sleep", side_effect=fast_sleep):
            task = asyncio.create_task(runner._executor._progress_timer(request, mock_agent_runner, 0.0))
            try:
                await task
            except asyncio.CancelledError:
                pass

        # Should have attempted multiple callbacks despite failures
        assert failing_callback.call_count >= 2

    @pytest.mark.asyncio
    async def test_timer_no_callback_does_not_raise(self, mock_store, mock_agent_runner):
        """Timer should be silent (no crash) when result_callback is None."""
        runner = SubAgentRunner(
            agent_factory=lambda: Mock(spec=AgentRunner),
            store=mock_store,
            channels={},
            result_callback=None,
        )

        request = _make_request(progress_interval_minutes=1, session_key="telegram:99")
        await _run_timer_once(runner, request, mock_agent_runner)
        # No assertion needed -- just ensuring no exception is raised

    @pytest.mark.asyncio
    async def test_timer_origin_included_in_message(self, sub_runner, mock_agent_runner, result_callback):
        """Origin suffix should appear in the progress message when set."""
        request = _make_request(
            progress_interval_minutes=1,
            session_key="telegram:99",
            origin="agent:gilfoyle",
        )
        await _run_timer_once(sub_runner, request, mock_agent_runner)

        content = result_callback.call_args[0][1]
        assert "spawned by" in content

    @pytest.mark.asyncio
    async def test_timer_no_origin_in_message_when_absent(self, sub_runner, mock_agent_runner, result_callback):
        """No origin suffix should appear when origin is None."""
        request = _make_request(
            progress_interval_minutes=1,
            session_key="telegram:99",
            origin=None,
        )
        await _run_timer_once(sub_runner, request, mock_agent_runner)

        content = result_callback.call_args[0][1]
        assert "spawned by" not in content


# ---------------------------------------------------------------------------
# Integration: progress_task lifecycle in _execute_subagent
# ---------------------------------------------------------------------------


@pytest.fixture
def fast_agent_runner():
    """AgentRunner mock that completes quickly."""
    runner = Mock(spec=AgentRunner)
    runner._last_tools_used = []
    runner._current_tool_name = None
    runner.last_metrics = None
    runner.last_tools_used = []
    runner.additional_tools = []
    runner._build_agent = Mock(return_value=Mock())
    runner._agent = Mock()
    runner.run = AsyncMock(return_value="done")
    runner.timeout_seconds = 1800
    return runner


class TestProgressTimerLifecycle:
    @pytest.mark.asyncio
    async def test_progress_task_started_when_interval_configured(self, mock_store, result_callback, fast_agent_runner):
        """asyncio.create_task should be called when progress_interval_minutes > 0."""
        created_tasks = []
        original_create_task = asyncio.create_task

        def tracking_create_task(coro, **kwargs):
            task = original_create_task(coro, **kwargs)
            created_tasks.append(task)
            return task

        runner = SubAgentRunner(
            agent_factory=lambda: fast_agent_runner,
            store=mock_store,
            channels={},
            result_callback=result_callback,
        )

        request = create_subagent_request(
            task="work",
            label="test",
            session_key="telegram:1",
            progress_interval_minutes=2,
        )
        mock_store.get = Mock(return_value=None)

        with patch("openpaw.runtime.subagent.runner.asyncio.create_task", side_effect=tracking_create_task):
            await runner._execute_subagent(request)

        assert len(created_tasks) >= 1, "Expected progress task to be created"

    @pytest.mark.asyncio
    async def test_no_progress_task_when_interval_zero(self, mock_store, result_callback, fast_agent_runner):
        """asyncio.create_task should NOT be called when progress_interval_minutes is 0."""
        created_tasks = []
        original_create_task = asyncio.create_task

        def tracking_create_task(coro, **kwargs):
            task = original_create_task(coro, **kwargs)
            created_tasks.append(task)
            return task

        runner = SubAgentRunner(
            agent_factory=lambda: fast_agent_runner,
            store=mock_store,
            channels={},
            result_callback=result_callback,
        )

        request = create_subagent_request(
            task="work",
            label="test",
            session_key="telegram:1",
            progress_interval_minutes=0,
        )
        mock_store.get = Mock(return_value=None)

        with patch("openpaw.runtime.subagent.runner.asyncio.create_task", side_effect=tracking_create_task):
            await runner._execute_subagent(request)

        assert len(created_tasks) == 0, "Expected no progress task when interval is 0"

    @pytest.mark.asyncio
    async def test_progress_task_cancelled_on_completion(self, mock_store, result_callback, fast_agent_runner):
        """Progress timer task should be done (cancelled or finished) after agent completes."""
        progress_tasks = []
        original_create_task = asyncio.create_task

        def tracking_create_task(coro, **kwargs):
            task = original_create_task(coro, **kwargs)
            progress_tasks.append(task)
            return task

        runner = SubAgentRunner(
            agent_factory=lambda: fast_agent_runner,
            store=mock_store,
            channels={},
            result_callback=result_callback,
        )

        request = create_subagent_request(
            task="work",
            label="test",
            session_key="telegram:1",
            progress_interval_minutes=5,
        )
        mock_store.get = Mock(return_value=None)

        with patch("openpaw.runtime.subagent.runner.asyncio.create_task", side_effect=tracking_create_task):
            await runner._execute_subagent(request)

        assert len(progress_tasks) >= 1
        for task in progress_tasks:
            assert task.done(), "Progress task was not cancelled after agent completion"
