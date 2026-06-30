"""Tests for SubAgentNotifier formatting and delivery."""

from unittest.mock import AsyncMock, Mock

import pytest

from openpaw.model.subagent import SubAgentRequest, SubAgentResult, SubAgentStatus
from openpaw.runtime.subagent.runner import SubAgentRunner


@pytest.fixture
def mock_channel():
    """Create a mock ChannelAdapter."""
    from openpaw.channels.base import ChannelAdapter
    channel = Mock(spec=ChannelAdapter)
    channel.send_message = AsyncMock()
    return channel


@pytest.fixture
def mock_store():
    """Create a mock SubAgentStore."""
    from openpaw.stores.subagent import SubAgentStore
    store = Mock(spec=SubAgentStore)
    store.update_status = AsyncMock()
    store.save_result = AsyncMock()
    store.get = AsyncMock(return_value=None)
    store.get_result = AsyncMock(return_value=None)
    return store


@pytest.fixture
def mock_token_logger():
    """Create a mock TokenUsageLogger."""
    from openpaw.agent.metrics import TokenUsageLogger
    logger = Mock(spec=TokenUsageLogger)
    logger.log = Mock()
    return logger


@pytest.fixture
def agent_factory():
    """Create an agent factory that returns a mock runner."""
    from openpaw.agent.runner import AgentRunner
    runner = Mock(spec=AgentRunner)
    runner.run = AsyncMock(return_value="Test response")
    runner.additional_tools = []
    runner._build_agent = Mock(return_value=Mock())
    runner._agent = Mock()
    runner.last_metrics = None
    return lambda: runner


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


@pytest.mark.asyncio
async def test_send_notification_includes_exc_info_on_failure():
    """Test that notification send warnings include exc_info=True."""
    from unittest.mock import patch
    from openpaw.runtime.subagent.notifier import SubAgentNotifier

    request = SubAgentRequest(
        id="test-req",
        task="test",
        label="test",
        status=SubAgentStatus.RUNNING,
        session_key="telegram:12345",
        timeout_minutes=30,
    )
    result = SubAgentResult(request_id="test-req", output="done")

    # Callback that raises
    failing_callback = AsyncMock(side_effect=RuntimeError("boom"))
    notifier = SubAgentNotifier(channels={}, result_callback=failing_callback)

    with patch("openpaw.runtime.subagent.notifier.logger") as mock_logger:
        await notifier.send_notification(request, result)

        mock_logger.warning.assert_called_once()
        assert mock_logger.warning.call_args.kwargs.get("exc_info") is True


def test_format_notification_completed_short_contains_send_message_instruction():
    """SUBAGENT_COMPLETED_SHORT_TEMPLATE instructs agent to use send_message.

    Short template fires when output is <= 500 chars (dispatch threshold is > 500).
    """
    runner = SubAgentRunner(
        agent_factory=lambda: Mock(),
        store=Mock(),
        channels={},
        workspace_name="test",
    )

    request = SubAgentRequest(
        id="req-1",
        task="Test task",
        label="my-agent",
        status=SubAgentStatus.COMPLETED,
        session_key="telegram:12345",
        timeout_minutes=30,
    )

    result = SubAgentResult(
        request_id="req-1",
        output="Done.",  # 5 chars — well below 500, uses SHORT template
    )

    content = runner._format_notification(request, result)
    assert "send_message" in content


def test_format_notification_completed_long_contains_send_message_instruction():
    """SUBAGENT_COMPLETED_TEMPLATE (long) instructs agent to use send_message.

    Long template fires when output is > 500 chars (truncation threshold).
    """
    runner = SubAgentRunner(
        agent_factory=lambda: Mock(),
        store=Mock(),
        channels={},
        workspace_name="test",
    )

    request = SubAgentRequest(
        id="req-3",
        task="Test task",
        label="my-agent",
        status=SubAgentStatus.COMPLETED,
        session_key="telegram:12345",
        timeout_minutes=30,
    )

    result = SubAgentResult(
        request_id="req-3",
        output="X" * 501,  # > 500 chars — triggers SUBAGENT_COMPLETED_TEMPLATE
    )

    content = runner._format_notification(request, result)
    assert "send_message" in content
    # Long template also includes get_subagent_result reference
    assert "get_subagent_result" in content


def test_format_notification_timed_out_contains_send_message_instruction():
    """SUBAGENT_TIMED_OUT_TEMPLATE instructs agent to use send_message."""
    runner = SubAgentRunner(
        agent_factory=lambda: Mock(),
        store=Mock(),
        channels={},
        workspace_name="test",
    )

    request = SubAgentRequest(
        id="req-4",
        task="Test task",
        label="my-agent",
        status=SubAgentStatus.TIMED_OUT,
        session_key="telegram:12345",
        timeout_minutes=30,
    )

    result = SubAgentResult(
        request_id="req-4",
        output="",
        error="Sub-agent timed out after 30 minutes",
    )

    content = runner._format_notification(request, result)
    assert "send_message" in content


def test_format_notification_failed_contains_send_message_instruction():
    """SUBAGENT_FAILED_TEMPLATE now instructs agent to use send_message."""
    runner = SubAgentRunner(
        agent_factory=lambda: Mock(),
        store=Mock(),
        channels={},
        workspace_name="test",
    )

    request = SubAgentRequest(
        id="req-2",
        task="Test task",
        label="my-agent",
        status=SubAgentStatus.FAILED,
        session_key="telegram:12345",
        timeout_minutes=30,
    )

    result = SubAgentResult(
        request_id="req-2",
        output="",
        error="Something broke",
    )

    content = runner._format_notification(request, result)
    assert "send_message" in content
