"""Tests for SubAgentRunner lifecycle management."""

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest

from openpaw.agent.metrics import InvocationMetrics, TokenUsageLogger
from openpaw.agent.runner import AgentRunner
from openpaw.channels.base import ChannelAdapter
from openpaw.model.subagent import SubAgentRequest, SubAgentResult, SubAgentStatus
from openpaw.runtime.subagent.runner import SUBAGENT_EXCLUDED_TOOLS, SubAgentRunner
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


@pytest.fixture
def sub_agent_runner(agent_factory, mock_store, mock_channel, mock_token_logger):
    """Create a SubAgentRunner instance with mocks."""
    channels = {"telegram": mock_channel}
    return SubAgentRunner(
        agent_factory=agent_factory,
        store=mock_store,
        channels=channels,
        token_logger=mock_token_logger,
        workspace_name="test-workspace",
        max_concurrent=2,
    )


@pytest.fixture
def sample_request():
    """Create a sample SubAgentRequest."""
    return SubAgentRequest(
        id="test-request-1",
        task="Test task",
        label="test-label",
        status=SubAgentStatus.PENDING,
        session_key="telegram:12345",
        timeout_minutes=30,
        notify=True,
    )


@pytest.mark.asyncio
async def test_spawn_creates_task_and_updates_store(sub_agent_runner, mock_store, sample_request):
    """Test that spawn() creates an asyncio task and updates store to RUNNING."""
    request_id = await sub_agent_runner.spawn(sample_request)

    # Verify request ID returned
    assert request_id == sample_request.id

    # Verify status updated to RUNNING
    mock_store.update_status.assert_called_once()
    call_args = mock_store.update_status.call_args
    assert call_args[0][0] == sample_request.id
    assert call_args[0][1] == SubAgentStatus.RUNNING
    assert "started_at" in call_args[1]

    # Verify task is active
    assert sample_request.id in sub_agent_runner._active_tasks

    # Let the background task start
    await asyncio.sleep(0.1)


@pytest.mark.asyncio
async def test_spawn_enforces_concurrent_limit(mock_store, mock_channel, mock_token_logger):
    """Test that spawn() raises ValueError when max concurrent limit is reached."""
    # Create a long-running agent runner
    slow_runner = Mock(spec=AgentRunner)

    async def slow_run(message):
        await asyncio.sleep(5)  # Long enough to keep tasks active
        return "Test response"

    slow_runner.run = AsyncMock(side_effect=slow_run)
    slow_runner.additional_tools = []
    slow_runner._build_agent = Mock(return_value=Mock())
    slow_runner._agent = Mock()
    slow_runner.last_metrics = None

    def slow_factory():
        return slow_runner

    runner = SubAgentRunner(
        agent_factory=slow_factory,
        store=mock_store,
        channels={"telegram": mock_channel},
        token_logger=mock_token_logger,
        workspace_name="test",
        max_concurrent=2,
    )

    # Create requests
    request1 = SubAgentRequest(
        id="req-1",
        task="Task 1",
        label="label-1",
        status=SubAgentStatus.PENDING,
        session_key="telegram:12345",
        timeout_minutes=30,
    )
    request2 = SubAgentRequest(
        id="req-2",
        task="Task 2",
        label="label-2",
        status=SubAgentStatus.PENDING,
        session_key="telegram:12345",
        timeout_minutes=30,
    )
    request3 = SubAgentRequest(
        id="req-3",
        task="Task 3",
        label="label-3",
        status=SubAgentStatus.PENDING,
        session_key="telegram:12345",
        timeout_minutes=30,
    )

    # Spawn two requests (at capacity)
    await runner.spawn(request1)
    await runner.spawn(request2)

    # Try to spawn third request (should fail immediately)
    with pytest.raises(ValueError, match="max concurrent limit reached"):
        await runner.spawn(request3)

    # Clean up
    await runner.shutdown()


@pytest.mark.asyncio
async def test_execute_saves_result_on_success(
    agent_factory, mock_store, mock_channel, mock_token_logger, mock_agent_runner
):
    """Test that _execute_subagent() saves result to store on success."""
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

    # Execute the sub-agent
    await runner._execute_subagent(request)

    # Verify result was saved
    mock_store.save_result.assert_called()
    result_call = mock_store.save_result.call_args[0][0]
    assert isinstance(result_call, SubAgentResult)
    assert result_call.request_id == request.id
    assert result_call.output == "Test response"
    assert result_call.error is None

    # Verify status updated to COMPLETED
    status_calls = [call for call in mock_store.update_status.call_args_list]
    assert any(call[0][1] == SubAgentStatus.COMPLETED for call in status_calls)


@pytest.mark.asyncio
async def test_execute_saves_error_on_failure(
    mock_store, mock_channel, mock_token_logger, mock_agent_runner
):
    """Test that _execute_subagent() saves error on failure."""
    # Make agent runner raise an exception
    mock_agent_runner.run = AsyncMock(side_effect=RuntimeError("Test error"))

    def failing_factory():
        return mock_agent_runner

    runner = SubAgentRunner(
        agent_factory=failing_factory,
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

    # Execute the sub-agent
    await runner._execute_subagent(request)

    # Verify error result was saved
    mock_store.save_result.assert_called()
    result_call = mock_store.save_result.call_args[0][0]
    assert isinstance(result_call, SubAgentResult)
    assert result_call.request_id == request.id
    assert result_call.error is not None
    assert "Test error" in result_call.error

    # Verify status updated to FAILED
    status_calls = [call for call in mock_store.update_status.call_args_list]
    assert any(call[0][1] == SubAgentStatus.FAILED for call in status_calls)


@pytest.mark.asyncio
async def test_execute_handles_timeout(
    agent_factory, mock_store, mock_channel, mock_token_logger, mock_agent_runner
):
    """Test that _execute_subagent() handles timeout (TIMED_OUT status)."""
    # Make agent runner hang
    async def slow_run(message):
        await asyncio.sleep(10)
        return "Should not reach here"

    mock_agent_runner.run = slow_run

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
        timeout_minutes=0.01,  # 0.6 seconds timeout
        notify=False,
    )

    # Execute the sub-agent (should timeout quickly)
    await runner._execute_subagent(request)

    # Verify timeout result was saved
    mock_store.save_result.assert_called()
    result_call = mock_store.save_result.call_args[0][0]
    assert isinstance(result_call, SubAgentResult)
    assert result_call.request_id == request.id
    assert result_call.error is not None
    assert "timed out" in result_call.error.lower()

    # Verify status updated to TIMED_OUT
    status_calls = [call for call in mock_store.update_status.call_args_list]
    assert any(call[0][1] == SubAgentStatus.TIMED_OUT for call in status_calls)


@pytest.mark.asyncio
async def test_execute_handles_cancellation(
    agent_factory, mock_store, mock_channel, mock_token_logger, mock_agent_runner
):
    """Test that _execute_subagent() handles cancellation (CANCELLED status)."""
    # Make agent runner hang so we can cancel it
    async def slow_run(message):
        await asyncio.sleep(10)
        return "Should not reach here"

    mock_agent_runner.run = slow_run

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

    # Start execution and cancel it
    task = asyncio.create_task(runner._execute_subagent(request))
    await asyncio.sleep(0.1)  # Let it start
    task.cancel()

    # Wait for cancellation to complete
    with pytest.raises(asyncio.CancelledError):
        await task

    # Verify cancellation result was saved
    mock_store.save_result.assert_called()
    result_call = mock_store.save_result.call_args[0][0]
    assert isinstance(result_call, SubAgentResult)
    assert result_call.request_id == request.id
    assert result_call.error is not None
    assert "cancelled" in result_call.error.lower()

    # Verify status updated to CANCELLED
    status_calls = [call for call in mock_store.update_status.call_args_list]
    assert any(call[0][1] == SubAgentStatus.CANCELLED for call in status_calls)


@pytest.mark.asyncio
async def test_cancel_cancels_running_task(mock_store, mock_channel, mock_token_logger):
    """Test that cancel() cancels running task and updates store."""
    # Create a long-running agent runner
    slow_runner = Mock(spec=AgentRunner)

    async def slow_run(message):
        await asyncio.sleep(5)  # Long enough to keep task active
        return "Test response"

    slow_runner.run = AsyncMock(side_effect=slow_run)
    slow_runner.additional_tools = []
    slow_runner._build_agent = Mock(return_value=Mock())
    slow_runner._agent = Mock()
    slow_runner.last_metrics = None

    def slow_factory():
        return slow_runner

    runner = SubAgentRunner(
        agent_factory=slow_factory,
        store=mock_store,
        channels={"telegram": mock_channel},
        token_logger=mock_token_logger,
        workspace_name="test",
        max_concurrent=2,
    )

    request = SubAgentRequest(
        id="test-request-1",
        task="Test task",
        label="test-label",
        status=SubAgentStatus.PENDING,
        session_key="telegram:12345",
        timeout_minutes=30,
        notify=False,
    )

    # Spawn a request
    await runner.spawn(request)
    await asyncio.sleep(0.1)  # Let it start

    # Cancel it
    result = await runner.cancel(request.id)

    assert result is True

    # Verify status updated to CANCELLED
    # Note: update_status is called twice: once by spawn (RUNNING), once by cancel (CANCELLED)
    status_calls = [call for call in mock_store.update_status.call_args_list]
    assert any(call[0][1] == SubAgentStatus.CANCELLED for call in status_calls)

    # Clean up
    await runner.shutdown()


@pytest.mark.asyncio
async def test_cancel_returns_false_for_nonexistent_task(sub_agent_runner):
    """Test that cancel() returns False for non-existent task."""
    result = await sub_agent_runner.cancel("nonexistent-id")
    assert result is False


@pytest.mark.asyncio
async def test_shutdown_cancels_all_active_tasks(mock_store, mock_channel, mock_token_logger):
    """Test that shutdown() cancels all active tasks."""
    # Create a long-running agent runner
    slow_runner = Mock(spec=AgentRunner)

    async def slow_run(message):
        await asyncio.sleep(5)  # Long enough to keep tasks active
        return "Test response"

    slow_runner.run = AsyncMock(side_effect=slow_run)
    slow_runner.additional_tools = []
    slow_runner._build_agent = Mock(return_value=Mock())
    slow_runner._agent = Mock()
    slow_runner.last_metrics = None

    def slow_factory():
        return slow_runner

    runner = SubAgentRunner(
        agent_factory=slow_factory,
        store=mock_store,
        channels={"telegram": mock_channel},
        token_logger=mock_token_logger,
        workspace_name="test",
        max_concurrent=2,
    )

    # Spawn multiple requests
    request1 = SubAgentRequest(
        id="req-1",
        task="Task 1",
        label="label-1",
        status=SubAgentStatus.PENDING,
        session_key="telegram:12345",
        timeout_minutes=30,
    )
    request2 = SubAgentRequest(
        id="req-2",
        task="Task 2",
        label="label-2",
        status=SubAgentStatus.PENDING,
        session_key="telegram:12345",
        timeout_minutes=30,
    )

    await runner.spawn(request1)
    await runner.spawn(request2)
    await asyncio.sleep(0.1)  # Let them start

    # Shutdown
    await runner.shutdown()

    # Verify both tasks were cancelled
    status_calls = [call for call in mock_store.update_status.call_args_list]
    cancelled_calls = [call for call in status_calls if call[0][1] == SubAgentStatus.CANCELLED]
    assert len(cancelled_calls) >= 2  # Both should be cancelled


@pytest.mark.asyncio
async def test_tool_filtering_removes_excluded_tools(
    mock_store, mock_channel, mock_token_logger
):
    """Test that tool filtering removes excluded tools."""
    # Create mock tools
    allowed_tool = Mock()
    allowed_tool.name = "allowed_tool"

    excluded_tool = Mock()
    excluded_tool.name = "spawn_agent"

    mock_runner = Mock(spec=AgentRunner)
    mock_runner.run = AsyncMock(return_value="Test response")
    mock_runner.additional_tools = [allowed_tool, excluded_tool]
    mock_runner._build_agent = Mock(return_value=Mock())
    mock_runner._agent = Mock()
    mock_runner.last_metrics = None

    def factory():
        return mock_runner

    runner = SubAgentRunner(
        agent_factory=factory,
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

    # Verify excluded tool was removed
    assert allowed_tool in mock_runner.additional_tools
    assert excluded_tool not in mock_runner.additional_tools
    assert len(mock_runner.additional_tools) == 1

    # Verify _build_agent was called to rebuild with filtered tools
    mock_runner._build_agent.assert_called_once()


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


def test_list_active_delegates_to_store(sub_agent_runner, mock_store):
    """Test that list_active() delegates to store."""
    expected = [Mock(spec=SubAgentRequest)]
    mock_store.list_active.return_value = expected

    result = sub_agent_runner.list_active()

    assert result == expected
    mock_store.list_active.assert_called_once()


def test_list_recent_delegates_to_store(sub_agent_runner, mock_store):
    """Test that list_recent() delegates to store."""
    expected = [Mock(spec=SubAgentRequest)]
    mock_store.list_recent.return_value = expected

    result = sub_agent_runner.list_recent(limit=5)

    assert result == expected
    mock_store.list_recent.assert_called_once_with(limit=5)


def test_get_status_delegates_to_store(sub_agent_runner, mock_store):
    """Test that get_status() delegates to store."""
    expected = Mock(spec=SubAgentRequest)
    mock_store.get.return_value = expected

    result = sub_agent_runner.get_status("test-id")

    assert result == expected
    mock_store.get.assert_called_once_with("test-id")


def test_get_result_delegates_to_store(sub_agent_runner, mock_store):
    """Test that get_result() delegates to store.get_result()."""
    expected = Mock(spec=SubAgentResult)
    mock_store.get_result.return_value = expected

    result = sub_agent_runner.get_result("test-id")

    assert result == expected
    mock_store.get_result.assert_called_once_with("test-id")


def test_subagent_excluded_tools_contains_expected_names():
    """Test that SUBAGENT_EXCLUDED_TOOLS contains expected tool names."""
    expected_tools = {
        # Prevent sub-sub-agents
        "spawn_agent",
        "list_subagents",
        "get_subagent_result",
        "cancel_subagent",
        # Prevent self-continuation
        "request_followup",
        # Prevent unsolicited user messaging
        "send_message",
        "send_file",
        # Prevent persistence that outlives sub-agent lifecycle
        "schedule_at",
        "schedule_every",
        "list_scheduled",
        "cancel_scheduled",
        # Prevent orphaned browser sessions
        "browser_navigate",
        "browser_snapshot",
        "browser_click",
        "browser_type",
        "browser_select",
        "browser_scroll",
        "browser_back",
        "browser_screenshot",
        "browser_close",
        "browser_tabs",
        "browser_switch_tab",
        # Prevent persistent cron side effects
        "create_cron",
        "list_crons",
        "update_cron",
        "delete_cron",
        # Plan tool requires session key (undefined in subagent context)
        "write_plan",
        "read_plan",
    }

    assert SUBAGENT_EXCLUDED_TOOLS == expected_tools


@pytest.mark.asyncio
async def test_notification_uses_callback_when_provided(
    agent_factory, mock_store, mock_channel, mock_token_logger
):
    """Test that when result_callback is provided, it's called instead of channel.send_message."""
    # Create a mock callback
    mock_callback = AsyncMock()

    runner = SubAgentRunner(
        agent_factory=agent_factory,
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
        label="test-label",
        status=SubAgentStatus.COMPLETED,
        session_key="telegram:12345",
        timeout_minutes=30,
        notify=True,
    )

    result = SubAgentResult(
        request_id="test-req",
        output="Test output",
        token_count=100,
        duration_ms=500,
    )

    # Send notification
    await runner._send_notification(request, result)

    # Verify callback was called
    mock_callback.assert_called_once()
    call_args = mock_callback.call_args
    assert call_args[0][0] == "telegram:12345"  # session_key
    assert "[SYSTEM]" in call_args[0][1]  # content has [SYSTEM] prefix
    assert "test-label" in call_args[0][1]
    assert "completed" in call_args[0][1]

    # Verify channel.send_message was NOT called
    mock_channel.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_notification_falls_back_to_channel_when_no_callback(
    agent_factory, mock_store, mock_channel, mock_token_logger
):
    """Test that when result_callback is None, it falls back to channel.send_message."""
    runner = SubAgentRunner(
        agent_factory=agent_factory,
        store=mock_store,
        channels={"telegram": mock_channel},
        token_logger=mock_token_logger,
        workspace_name="test",
        max_concurrent=2,
        result_callback=None,  # No callback
    )

    request = SubAgentRequest(
        id="test-req",
        task="Test task",
        label="test-label",
        status=SubAgentStatus.COMPLETED,
        session_key="telegram:12345",
        timeout_minutes=30,
        notify=True,
    )

    result = SubAgentResult(
        request_id="test-req",
        output="Test output",
        token_count=100,
        duration_ms=500,
    )

    # Send notification
    await runner._send_notification(request, result)

    # Verify channel.send_message WAS called
    mock_channel.send_message.assert_called_once()
    call_args = mock_channel.send_message.call_args
    assert call_args[1]["session_key"] == "telegram:12345"
    assert "[SYSTEM]" in call_args[1]["content"]
    assert "test-label" in call_args[1]["content"]
    assert "completed" in call_args[1]["content"]


def test_format_notification_success():
    """Test that _format_notification formats success messages correctly."""
    runner = SubAgentRunner(
        agent_factory=lambda: Mock(),
        store=Mock(),
        channels={},
        workspace_name="test",
    )

    request = SubAgentRequest(
        id="test-req-123",
        task="Test task",
        label="research-x",
        status=SubAgentStatus.COMPLETED,
        session_key="telegram:12345",
        timeout_minutes=30,
    )

    result = SubAgentResult(
        request_id="test-req-123",
        output="Short output",
        token_count=100,
        duration_ms=500,
    )

    content = runner._format_notification(request, result)

    assert content.startswith("[SYSTEM]")
    assert "research-x" in content
    assert "completed" in content
    assert "Short output" in content


def test_format_notification_success_truncated():
    """Test that _format_notification truncates long output."""
    runner = SubAgentRunner(
        agent_factory=lambda: Mock(),
        store=Mock(),
        channels={},
        workspace_name="test",
    )

    request = SubAgentRequest(
        id="test-req-123",
        task="Test task",
        label="research-x",
        status=SubAgentStatus.COMPLETED,
        session_key="telegram:12345",
        timeout_minutes=30,
    )

    # Create very long output
    long_output = "A" * 1000
    result = SubAgentResult(
        request_id="test-req-123",
        output=long_output,
        token_count=100,
        duration_ms=500,
    )

    content = runner._format_notification(request, result)

    assert content.startswith("[SYSTEM]")
    assert "research-x" in content
    assert "completed" in content
    assert "get_subagent_result" in content
    assert f'id="{request.id}"' in content
    assert len(content) < len(long_output)  # Truncated


def test_format_notification_failure():
    """Test that _format_notification formats failure messages correctly."""
    runner = SubAgentRunner(
        agent_factory=lambda: Mock(),
        store=Mock(),
        channels={},
        workspace_name="test",
    )

    request = SubAgentRequest(
        id="test-req-123",
        task="Test task",
        label="research-x",
        status=SubAgentStatus.FAILED,
        session_key="telegram:12345",
        timeout_minutes=30,
    )

    result = SubAgentResult(
        request_id="test-req-123",
        output="",
        error="Something went wrong",
        duration_ms=500,
    )

    content = runner._format_notification(request, result)

    assert content.startswith("[SYSTEM]")
    assert "research-x" in content
    assert "failed" in content
    assert "Something went wrong" in content


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


def test_format_notification_timeout():
    """Test that _format_notification formats timeout messages correctly."""
    runner = SubAgentRunner(
        agent_factory=lambda: Mock(),
        store=Mock(),
        channels={},
        workspace_name="test",
    )

    request = SubAgentRequest(
        id="test-req-123",
        task="Test task",
        label="research-x",
        status=SubAgentStatus.TIMED_OUT,
        session_key="telegram:12345",
        timeout_minutes=30,
    )

    result = SubAgentResult(
        request_id="test-req-123",
        output="",
        error="Sub-agent timed out after 30 minutes",
        duration_ms=1800000,
    )

    content = runner._format_notification(request, result)

    assert content.startswith("[SYSTEM]")
    assert "research-x" in content
    assert "timed out" in content
    assert "30 minutes" in content


# ---------------------------------------------------------------------------
# Phase 1A: Notification on failure and cancel paths
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Phase 1B: SessionLogger write_session produces unique files per concurrent call
# ---------------------------------------------------------------------------


def test_session_logger_write_session_concurrent_unique_paths(tmp_path):
    """Concurrent write_session calls must produce separate JSONL files."""
    import threading

    from openpaw.agent.session_logger import SessionLogger

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
    from openpaw.agent.session_logger import SessionLogger

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


# ---------------------------------------------------------------------------
# Phase 1C: session_log_path surfaced in SubAgentResult and notification
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_session_log_path_set_on_result_after_success(
    mock_store, mock_channel, mock_token_logger, tmp_path
):
    """session_log_path should be set on the result after a successful run."""
    from openpaw.agent.session_logger import SessionLogger

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
    from openpaw.agent.session_logger import SessionLogger

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


def test_format_notification_includes_log_path_when_set():
    """_format_notification appends session log path when result.session_log_path is set."""
    runner = SubAgentRunner(
        agent_factory=lambda: Mock(),
        store=Mock(),
        channels={},
        workspace_name="test",
    )

    request = SubAgentRequest(
        id="test-req",
        task="Test task",
        label="log-label",
        status=SubAgentStatus.COMPLETED,
        session_key="telegram:12345",
        timeout_minutes=30,
    )

    result = SubAgentResult(
        request_id="test-req",
        output="done",
        session_log_path="memory/sessions/subagent/subagent_log-label_2026.jsonl",
    )

    content = runner._format_notification(request, result)
    assert "Full session log:" in content
    assert "memory/sessions/subagent" in content


def test_format_notification_no_log_path_when_not_set():
    """_format_notification does not include log path line when session_log_path is None."""
    runner = SubAgentRunner(
        agent_factory=lambda: Mock(),
        store=Mock(),
        channels={},
        workspace_name="test",
    )

    request = SubAgentRequest(
        id="test-req",
        task="Test task",
        label="log-label",
        status=SubAgentStatus.COMPLETED,
        session_key="telegram:12345",
        timeout_minutes=30,
    )

    result = SubAgentResult(
        request_id="test-req",
        output="done",
        session_log_path=None,
    )

    content = runner._format_notification(request, result)
    assert "Full session log:" not in content


# ---------------------------------------------------------------------------
# Phase 4A: Cancel-after-complete race guard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancel_returns_false_for_completed_status(mock_store, mock_channel, mock_token_logger):
    """cancel() returns False when the sub-agent is already COMPLETED."""
    completed_request = SubAgentRequest(
        id="test-req",
        task="task",
        label="label",
        status=SubAgentStatus.COMPLETED,
        session_key="telegram:12345",
    )
    mock_store.get.return_value = completed_request

    # Add a fake active task so cancel doesn't bail out on the first check
    runner = SubAgentRunner(
        agent_factory=lambda: Mock(),
        store=mock_store,
        channels={"telegram": mock_channel},
        token_logger=mock_token_logger,
        workspace_name="test",
        max_concurrent=2,
    )
    fake_task = Mock(spec=asyncio.Task)
    runner._active_tasks["test-req"] = fake_task

    result = await runner.cancel("test-req")

    assert result is False
    fake_task.cancel.assert_not_called()
    mock_store.update_status.assert_not_called()


@pytest.mark.asyncio
async def test_cancel_returns_false_for_failed_status(mock_store, mock_channel, mock_token_logger):
    """cancel() returns False when the sub-agent is already FAILED."""
    failed_request = SubAgentRequest(
        id="test-req",
        task="task",
        label="label",
        status=SubAgentStatus.FAILED,
        session_key="telegram:12345",
    )
    mock_store.get.return_value = failed_request

    runner = SubAgentRunner(
        agent_factory=lambda: Mock(),
        store=mock_store,
        channels={"telegram": mock_channel},
        token_logger=mock_token_logger,
        workspace_name="test",
        max_concurrent=2,
    )
    fake_task = Mock(spec=asyncio.Task)
    runner._active_tasks["test-req"] = fake_task

    result = await runner.cancel("test-req")

    assert result is False
    fake_task.cancel.assert_not_called()
    mock_store.update_status.assert_not_called()


@pytest.mark.asyncio
async def test_cancel_returns_false_for_timed_out_status(mock_store, mock_channel, mock_token_logger):
    """cancel() returns False when the sub-agent is already TIMED_OUT."""
    timed_out_request = SubAgentRequest(
        id="test-req",
        task="task",
        label="label",
        status=SubAgentStatus.TIMED_OUT,
        session_key="telegram:12345",
    )
    mock_store.get.return_value = timed_out_request

    runner = SubAgentRunner(
        agent_factory=lambda: Mock(),
        store=mock_store,
        channels={"telegram": mock_channel},
        token_logger=mock_token_logger,
        workspace_name="test",
        max_concurrent=2,
    )
    fake_task = Mock(spec=asyncio.Task)
    runner._active_tasks["test-req"] = fake_task

    result = await runner.cancel("test-req")

    assert result is False
    fake_task.cancel.assert_not_called()
    mock_store.update_status.assert_not_called()


@pytest.mark.asyncio
async def test_cancel_proceeds_for_running_status(mock_store, mock_channel, mock_token_logger):
    """cancel() proceeds normally when the sub-agent is still RUNNING."""
    running_request = SubAgentRequest(
        id="test-req",
        task="task",
        label="label",
        status=SubAgentStatus.RUNNING,
        session_key="telegram:12345",
    )
    mock_store.get.return_value = running_request

    runner = SubAgentRunner(
        agent_factory=lambda: Mock(),
        store=mock_store,
        channels={"telegram": mock_channel},
        token_logger=mock_token_logger,
        workspace_name="test",
        max_concurrent=2,
    )
    fake_task = Mock(spec=asyncio.Task)
    runner._active_tasks["test-req"] = fake_task

    result = await runner.cancel("test-req")

    assert result is True
    fake_task.cancel.assert_called_once()
