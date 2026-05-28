"""Tests for SubAgentExecutor execution behavior."""

import asyncio
import logging
from unittest.mock import ANY, AsyncMock, Mock

import pytest

from openpaw.agent.metrics import InvocationMetrics, TokenUsageLogger
from openpaw.agent.runner import AgentRunner
from openpaw.agent.session_logger import SessionLogger
from openpaw.channels.base import ChannelAdapter
from openpaw.model.subagent import SubAgentRequest, SubAgentResult, SubAgentStatus
from openpaw.runtime.subagent.executor import SubAgentExecutor
from openpaw.runtime.subagent.runner import SubAgentRunner
from openpaw.stores.subagent import SubAgentStore


@pytest.fixture
def mock_store():
    """Create a mock SubAgentStore."""
    store = Mock(spec=SubAgentStore)
    store.update_status = Mock()
    store.save_result = Mock()
    store.get = Mock(return_value=None)
    store.get_result = Mock(return_value=None)
    store.list_active = Mock(return_value=[])
    store.list_recent = Mock(return_value=[])
    return store


@pytest.fixture
def mock_channel():
    """Create a mock ChannelAdapter."""
    channel = Mock(spec=ChannelAdapter)
    channel.send_message = AsyncMock()
    return channel


@pytest.fixture
def mock_token_logger():
    """Create a mock TokenUsageLogger."""
    logger = Mock(spec=TokenUsageLogger)
    logger.log = Mock()
    return logger


@pytest.fixture
def mock_agent_runner():
    """Create a mock AgentRunner."""
    runner = Mock(spec=AgentRunner)

    # Default behavior: return quickly
    async def quick_run(message):
        await asyncio.sleep(0.01)  # Small delay to simulate work
        return "Test response"

    runner.run = AsyncMock(side_effect=quick_run)
    runner.additional_tools = []
    runner._build_agent = Mock(return_value=Mock())
    runner._agent = Mock()
    runner.last_metrics = InvocationMetrics(
        input_tokens=100, output_tokens=50, total_tokens=150, llm_calls=1
    )
    return runner


@pytest.fixture
def agent_factory(mock_agent_runner):
    """Create an agent factory that returns a mock runner."""
    return lambda: mock_agent_runner


@pytest.mark.asyncio
async def test_notification_sent_on_completion_when_notify_true(
    agent_factory, mock_store, mock_channel, mock_token_logger
):
    """Test that notification is sent on completion when notify=True."""
    runner = SubAgentRunner(
        agent_factory=agent_factory,
        store=mock_store,
        channels={"telegram": mock_channel},
        token_logger=mock_token_logger,
        workspace_name="test",
        max_concurrent=2,
    )

    request = SubAgentRequest(
        id="test-req",
        task="Test task",
        label="test-label",
        status=SubAgentStatus.RUNNING,
        session_key="telegram:12345",
        timeout_minutes=30,
        notify=True,
    )

    # Execute
    await runner._execute_subagent(request)

    # Verify notification was sent
    mock_channel.send_message.assert_called_once()
    call_args = mock_channel.send_message.call_args
    assert call_args[1]["session_key"] == request.session_key
    assert "test-label" in call_args[1]["content"]
    assert "completed" in call_args[1]["content"]


@pytest.mark.asyncio
async def test_notification_not_sent_when_notify_false(
    agent_factory, mock_store, mock_channel, mock_token_logger
):
    """Test that notification is not sent when notify=False."""
    runner = SubAgentRunner(
        agent_factory=agent_factory,
        store=mock_store,
        channels={"telegram": mock_channel},
        token_logger=mock_token_logger,
        workspace_name="test",
        max_concurrent=2,
    )

    request = SubAgentRequest(
        id="test-req",
        task="Test task",
        label="test-label",
        status=SubAgentStatus.RUNNING,
        session_key="telegram:12345",
        timeout_minutes=30,
        notify=False,
    )

    # Execute
    await runner._execute_subagent(request)

    # Verify notification was NOT sent
    mock_channel.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_token_usage_logged_for_subagent_invocations(
    agent_factory, mock_store, mock_channel, mock_token_logger, mock_agent_runner
):
    """Test that token usage is logged for sub-agent invocations."""
    runner = SubAgentRunner(
        agent_factory=agent_factory,
        store=mock_store,
        channels={"telegram": mock_channel},
        token_logger=mock_token_logger,
        workspace_name="test-workspace",
        max_concurrent=2,
    )

    request = SubAgentRequest(
        id="test-req",
        task="Test task",
        label="test-label",
        status=SubAgentStatus.RUNNING,
        session_key="telegram:12345",
        timeout_minutes=30,
        notify=False,
    )

    # Execute
    await runner._execute_subagent(request)

    # Verify token usage was logged
    mock_token_logger.log.assert_called_once()
    call_args = mock_token_logger.log.call_args
    assert call_args[1]["workspace"] == "test-workspace"
    assert call_args[1]["invocation_type"] == "subagent"
    assert call_args[1]["session_key"] == request.session_key
    assert isinstance(call_args[1]["metrics"], InvocationMetrics)


@pytest.mark.asyncio
async def test_timeout_sends_notification_when_notify_true(
    mock_store, mock_channel, mock_token_logger
):
    """Test that timeout sends notification when notify=True."""
    # Create agent runner that hangs
    mock_runner = Mock(spec=AgentRunner)

    async def slow_run(message):
        await asyncio.sleep(10)
        return "Should not reach here"

    mock_runner.run = slow_run
    mock_runner.additional_tools = []
    mock_runner._build_agent = Mock(return_value=Mock())
    mock_runner._agent = Mock()
    mock_runner.last_metrics = None
    mock_runner.timeout_seconds = 300.0

    mock_callback = AsyncMock()

    runner = SubAgentRunner(
        agent_factory=lambda: mock_runner,
        store=mock_store,
        channels={"telegram": mock_channel},
        token_logger=mock_token_logger,
        workspace_name="test",
        max_concurrent=2,
        result_callback=mock_callback,
    )

    request = SubAgentRequest(
        id="test-req",
        task="Test task",
        label="timeout-test",
        status=SubAgentStatus.RUNNING,
        session_key="telegram:12345",
        timeout_minutes=0.01,  # 0.6 seconds timeout
        notify=True,
    )

    await runner._execute_subagent(request)

    # Verify timeout notification was sent via callback
    mock_callback.assert_called_once()
    call_args = mock_callback.call_args
    assert call_args[0][0] == "telegram:12345"
    assert "timed out" in call_args[0][1]
    assert "timeout-test" in call_args[0][1]


@pytest.mark.asyncio
async def test_timeout_override_sets_inner_timeout_higher(
    mock_store, mock_channel, mock_token_logger
):
    """Test that _execute_subagent overrides runner.timeout_seconds to be higher than outer."""
    captured_timeout = None

    mock_runner = Mock(spec=AgentRunner)
    mock_runner.timeout_seconds = 300.0  # Default workspace timeout

    async def capture_run(message):
        nonlocal captured_timeout
        captured_timeout = mock_runner.timeout_seconds
        await asyncio.sleep(0.01)
        return "Test response"

    mock_runner.run = capture_run
    mock_runner.additional_tools = []
    mock_runner._build_agent = Mock(return_value=Mock())
    mock_runner._agent = Mock()
    mock_runner.last_metrics = None

    runner = SubAgentRunner(
        agent_factory=lambda: mock_runner,
        store=mock_store,
        channels={"telegram": mock_channel},
        token_logger=mock_token_logger,
        workspace_name="test",
        max_concurrent=2,
    )

    request = SubAgentRequest(
        id="test-req",
        task="Test task",
        label="test-label",
        status=SubAgentStatus.RUNNING,
        session_key="telegram:12345",
        timeout_minutes=30,
        notify=False,
    )

    await runner._execute_subagent(request)

    # Verify the inner timeout was overridden to be higher than the outer
    assert captured_timeout is not None
    outer_timeout = request.timeout_minutes * 60  # 1800s
    assert captured_timeout > outer_timeout
    assert captured_timeout == outer_timeout + 30


@pytest.mark.asyncio
async def test_notification_sent_on_failure_when_notify_true(
    mock_store, mock_channel, mock_token_logger
):
    """Test that notification is sent on failure when notify=True."""
    mock_runner = Mock(spec=AgentRunner)
    mock_runner.run = AsyncMock(side_effect=RuntimeError("boom"))
    mock_runner.additional_tools = []
    mock_runner._build_agent = Mock(return_value=Mock())
    mock_runner._agent = Mock()
    mock_runner.last_metrics = None
    mock_runner.timeout_seconds = 1800

    mock_callback = AsyncMock()

    runner = SubAgentRunner(
        agent_factory=lambda: mock_runner,
        store=mock_store,
        channels={"telegram": mock_channel},
        token_logger=mock_token_logger,
        workspace_name="test",
        max_concurrent=2,
        result_callback=mock_callback,
    )

    request = SubAgentRequest(
        id="test-req",
        task="Test task",
        label="fail-test",
        status=SubAgentStatus.RUNNING,
        session_key="telegram:12345",
        timeout_minutes=30,
        notify=True,
    )

    await runner._execute_subagent(request)

    mock_callback.assert_called_once()
    content = mock_callback.call_args[0][1]
    assert "fail-test" in content
    assert "failed" in content


@pytest.mark.asyncio
async def test_notification_not_sent_on_failure_when_notify_false(
    mock_store, mock_channel, mock_token_logger
):
    """Test that notification is NOT sent on failure when notify=False."""
    mock_runner = Mock(spec=AgentRunner)
    mock_runner.run = AsyncMock(side_effect=RuntimeError("boom"))
    mock_runner.additional_tools = []
    mock_runner._build_agent = Mock(return_value=Mock())
    mock_runner._agent = Mock()
    mock_runner.last_metrics = None
    mock_runner.timeout_seconds = 1800

    mock_callback = AsyncMock()

    runner = SubAgentRunner(
        agent_factory=lambda: mock_runner,
        store=mock_store,
        channels={"telegram": mock_channel},
        token_logger=mock_token_logger,
        workspace_name="test",
        max_concurrent=2,
        result_callback=mock_callback,
    )

    request = SubAgentRequest(
        id="test-req",
        task="Test task",
        label="fail-test",
        status=SubAgentStatus.RUNNING,
        session_key="telegram:12345",
        timeout_minutes=30,
        notify=False,
    )

    await runner._execute_subagent(request)

    mock_callback.assert_not_called()


@pytest.mark.asyncio
async def test_notification_sent_on_cancellation_when_notify_true(
    mock_store, mock_channel, mock_token_logger
):
    """Test that notification is sent on cancellation when notify=True."""
    mock_runner = Mock(spec=AgentRunner)

    async def slow_run(message):
        await asyncio.sleep(10)
        return "unreachable"

    mock_runner.run = slow_run
    mock_runner.additional_tools = []
    mock_runner._build_agent = Mock(return_value=Mock())
    mock_runner._agent = Mock()
    mock_runner.last_metrics = None
    mock_runner.timeout_seconds = 1800

    mock_callback = AsyncMock()

    runner = SubAgentRunner(
        agent_factory=lambda: mock_runner,
        store=mock_store,
        channels={"telegram": mock_channel},
        token_logger=mock_token_logger,
        workspace_name="test",
        max_concurrent=2,
        result_callback=mock_callback,
    )

    request = SubAgentRequest(
        id="test-req",
        task="Test task",
        label="cancel-test",
        status=SubAgentStatus.RUNNING,
        session_key="telegram:12345",
        timeout_minutes=30,
        notify=True,
    )

    task = asyncio.create_task(runner._execute_subagent(request))
    await asyncio.sleep(0.1)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    mock_callback.assert_called_once()
    content = mock_callback.call_args[0][1]
    assert "cancel-test" in content
    assert "failed" in content or "cancelled" in content


def test_session_logger_write_session_concurrent_unique_paths(tmp_path):
    """Concurrent write_session calls must produce separate JSONL files."""
    import threading

    logger_instance = SessionLogger(workspace_path=tmp_path, session_type="subagent")
    paths: list[str] = []
    lock = threading.Lock()

    def write_one():
        path = logger_instance.write_session(
            name="subagent_worker",
            prompt="do something",
            response="done",
            tools_used=[],
            metrics=None,
            duration_ms=100.0,
        )
        with lock:
            paths.append(path)

    threads = [threading.Thread(target=write_one) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Every write must produce a distinct file
    assert len(paths) == 10
    assert len(set(paths)) == 10, "Concurrent write_session calls produced duplicate paths"

    # Every file must exist on disk with 3 records
    for rel_path in paths:
        abs_path = tmp_path / rel_path
        assert abs_path.exists(), f"Session log file missing: {rel_path}"
        lines = abs_path.read_text().strip().split("\n")
        assert len(lines) == 3, f"Expected 3 records in {rel_path}, got {len(lines)}"


def test_session_logger_write_session_returns_relative_path(tmp_path):
    """write_session must return a path relative to workspace root."""
    logger_instance = SessionLogger(workspace_path=tmp_path, session_type="subagent")
    rel_path = logger_instance.write_session(
        name="subagent_test",
        prompt="prompt",
        response="response",
        tools_used=["read_file"],
        metrics=None,
        duration_ms=50.0,
    )

    assert not rel_path.startswith("/"), "Path should be relative, not absolute"
    assert (tmp_path / rel_path).exists()


@pytest.mark.asyncio
async def test_session_log_path_set_on_result_after_success(
    mock_store, mock_channel, mock_token_logger, tmp_path
):
    """session_log_path should be set on the result after a successful run."""
    session_logger = SessionLogger(workspace_path=tmp_path, session_type="subagent")

    # Build a runner with properly configured tools_used so JSON serialization works.
    local_runner = Mock(spec=AgentRunner)
    local_runner.run = AsyncMock(return_value="Test response")
    local_runner.additional_tools = []
    local_runner._build_agent = Mock(return_value=Mock())
    local_runner._agent = Mock()
    local_runner.last_metrics = InvocationMetrics(
        input_tokens=10, output_tokens=5, total_tokens=15, llm_calls=1
    )
    local_runner.last_tools_used = ["read_file"]
    local_runner.timeout_seconds = 1800

    saved_results: list[SubAgentResult] = []
    mock_store.save_result = Mock(side_effect=lambda r: saved_results.append(r))

    runner = SubAgentRunner(
        agent_factory=lambda: local_runner,
        store=mock_store,
        channels={"telegram": mock_channel},
        token_logger=mock_token_logger,
        workspace_name="test",
        max_concurrent=2,
        session_logger=session_logger,
    )

    request = SubAgentRequest(
        id="test-req",
        task="Test task",
        label="log-path-test",
        status=SubAgentStatus.RUNNING,
        session_key="telegram:12345",
        timeout_minutes=30,
        notify=False,
    )

    await runner._execute_subagent(request)

    # The last save_result call should have session_log_path set
    assert saved_results, "save_result was never called"
    final_result = saved_results[-1]
    assert final_result.session_log_path is not None
    assert "log-path-test" in final_result.session_log_path


@pytest.mark.asyncio
async def test_session_log_path_appears_in_notification(
    mock_store, mock_channel, mock_token_logger, tmp_path
):
    """session_log_path should appear in the notification message when set."""
    session_logger = SessionLogger(workspace_path=tmp_path, session_type="subagent")
    mock_callback = AsyncMock()

    local_runner = Mock(spec=AgentRunner)
    local_runner.run = AsyncMock(return_value="Test response")
    local_runner.additional_tools = []
    local_runner._build_agent = Mock(return_value=Mock())
    local_runner._agent = Mock()
    local_runner.last_metrics = InvocationMetrics(
        input_tokens=10, output_tokens=5, total_tokens=15, llm_calls=1
    )
    local_runner.last_tools_used = []
    local_runner.timeout_seconds = 1800

    runner = SubAgentRunner(
        agent_factory=lambda: local_runner,
        store=mock_store,
        channels={"telegram": mock_channel},
        token_logger=mock_token_logger,
        workspace_name="test",
        max_concurrent=2,
        result_callback=mock_callback,
        session_logger=session_logger,
    )

    request = SubAgentRequest(
        id="test-req",
        task="Test task",
        label="notif-log-test",
        status=SubAgentStatus.RUNNING,
        session_key="telegram:12345",
        timeout_minutes=30,
        notify=True,
    )

    await runner._execute_subagent(request)

    mock_callback.assert_called_once()
    content = mock_callback.call_args[0][1]
    assert "Full session log:" in content


@pytest.mark.asyncio
async def test_finalize_failure_consolidates_timeout_and_error_paths(mock_store):
    """Test that _finalize_failure produces correct result for both timeout and error."""
    executor = SubAgentExecutor(
        store=mock_store,
        token_logger=None,
        session_logger=None,
        workspace_name="test",
        result_callback=None,
    )

    request = SubAgentRequest(
        id="test-req",
        task="test",
        label="test",
        status=SubAgentStatus.RUNNING,
        session_key="telegram:12345",
        timeout_minutes=30,
    )

    # Test timeout path
    result = await executor._finalize_failure(
        request, 0.0, SubAgentStatus.TIMED_OUT, "timed out", "(timed out)", logging.WARNING
    )
    assert result.error == "timed out"
    assert result.request_id == "test-req"
    mock_store.update_status.assert_called_with(
        "test-req", SubAgentStatus.TIMED_OUT, completed_at=ANY
    )

    # Test error path
    mock_store.reset_mock()
    result = await executor._finalize_failure(
        request, 0.0, SubAgentStatus.FAILED, "failed", "(failed: failed)", logging.ERROR
    )
    assert result.error == "failed"
    mock_store.update_status.assert_called_with(
        "test-req", SubAgentStatus.FAILED, completed_at=ANY
    )


@pytest.mark.asyncio
async def test_exc_info_passed_to_warning_logs(mock_store):
    """Test that exception warnings include exc_info=True."""
    from unittest.mock import patch

    executor = SubAgentExecutor(
        store=mock_store,
        token_logger=None,
        session_logger=None,
        workspace_name="test",
        result_callback=None,
    )

    with patch("openpaw.runtime.subagent.executor.logger") as mock_logger:
        # Simulate progress callback failure
        executor._result_callback = AsyncMock(side_effect=RuntimeError("boom"))
        request = SubAgentRequest(
            id="test-req",
            task="test",
            label="test",
            status=SubAgentStatus.RUNNING,
            session_key="telegram:12345",
            timeout_minutes=30,
            progress_interval_minutes=0,
        )
        # Trigger the warning via _progress_timer (cancel immediately)
        from unittest.mock import patch as mock_patch
        mock_runner = Mock(spec=AgentRunner)
        mock_runner._last_tools_used = None
        mock_runner._current_tool_name = None
        with mock_patch("asyncio.sleep", side_effect=[None, asyncio.CancelledError()]):
            try:
                await executor._progress_timer(request, mock_runner, 0.0)
            except asyncio.CancelledError:
                pass

        # Verify the warning was called with exc_info=True
        warning_calls = [c for c in mock_logger.warning.call_args_list]
        assert len(warning_calls) > 0
        for call in warning_calls:
            assert call.kwargs.get("exc_info") is True


