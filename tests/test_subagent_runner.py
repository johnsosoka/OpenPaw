"""Tests for SubAgentRunner lifecycle management."""

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from openpaw.channels.base import ChannelAdapter
from openpaw.core.agent import AgentRunner
from openpaw.core.metrics import InvocationMetrics, TokenUsageLogger
from openpaw.subagent.runner import SUBAGENT_EXCLUDED_TOOLS, SubAgentRunner
from openpaw.subagent.store import SubAgentRequest, SubAgentResult, SubAgentStatus, SubAgentStore


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
        "spawn_agent",
        "list_subagents",
        "get_subagent_result",
        "cancel_subagent",
        "request_followup",
        "send_message",
        "send_file",
        "schedule_at",
        "schedule_every",
        "list_scheduled",
        "cancel_scheduled",
    }

    assert SUBAGENT_EXCLUDED_TOOLS == expected_tools
