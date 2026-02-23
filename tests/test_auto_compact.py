"""Tests for auto-compact pre-run context check."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from openpaw.core.config.models import AutoCompactConfig
from openpaw.workspace.message_processor import MessageProcessor


@pytest.fixture
def mock_processor():
    """Create a MessageProcessor with mocked dependencies."""
    processor = MessageProcessor(
        agent_runner=AsyncMock(),
        session_manager=MagicMock(),
        queue_manager=MagicMock(),
        builtin_loader=MagicMock(),
        queue_middleware=MagicMock(),
        approval_middleware=MagicMock(),
        approval_manager=None,
        workspace_name="test_workspace",
        token_logger=MagicMock(),
        logger=MagicMock(),
        conversation_archiver=AsyncMock(),
        auto_compact_config=AutoCompactConfig(enabled=True, trigger=0.8),
    )
    return processor


@pytest.mark.asyncio
async def test_auto_compact_disabled_returns_none(mock_processor):
    """When config disabled, returns None immediately."""
    # Disable auto-compact
    mock_processor._auto_compact_config.enabled = False

    # Mock channel
    channel = AsyncMock()

    result = await mock_processor._check_auto_compact(
        "telegram:123", "telegram:123:conv_old", channel
    )

    assert result is None
    # Ensure get_context_info was never called (early exit)
    mock_processor._agent_runner.get_context_info.assert_not_called()


@pytest.mark.asyncio
async def test_auto_compact_below_threshold_returns_none(mock_processor):
    """Utilization 0.5 < 0.8 trigger returns None."""
    # Mock context info showing low utilization
    mock_processor._agent_runner.get_context_info = AsyncMock(
        return_value={
            "max_input_tokens": 200000,
            "approximate_tokens": 100000,
            "utilization": 0.5,
            "message_count": 50,
        }
    )

    channel = AsyncMock()
    result = await mock_processor._check_auto_compact(
        "telegram:123", "telegram:123:conv_old", channel
    )

    assert result is None
    # Verify archiver was not called
    mock_processor._conversation_archiver.archive.assert_not_called()


@pytest.mark.asyncio
async def test_auto_compact_no_archiver_returns_none(mock_processor):
    """No conversation_archiver returns None."""
    # Remove archiver
    mock_processor._conversation_archiver = None

    channel = AsyncMock()
    result = await mock_processor._check_auto_compact(
        "telegram:123", "telegram:123:conv_old", channel
    )

    assert result is None


@pytest.mark.asyncio
async def test_auto_compact_triggers_above_threshold(mock_processor):
    """Utilization 0.85 > 0.8 triggers archive, creates new conversation, returns new thread_id."""
    # Mock context info showing high utilization
    mock_processor._agent_runner.get_context_info = AsyncMock(
        return_value={
            "max_input_tokens": 200000,
            "approximate_tokens": 170000,
            "utilization": 0.85,
            "message_count": 150,
        }
    )

    # Mock archiver
    mock_processor._conversation_archiver.archive = AsyncMock(
        return_value=MagicMock()
    )

    # Mock agent run for summary
    mock_processor._agent_runner.run = AsyncMock(
        return_value="Summary of conversation"
    )
    mock_processor._agent_runner.checkpointer = MagicMock()

    # Mock session manager
    mock_processor._session_manager.new_conversation = MagicMock(
        return_value="conv_new_123"
    )

    channel = AsyncMock()
    result = await mock_processor._check_auto_compact(
        "telegram:123", "telegram:123:conv_old", channel
    )

    # Verify new thread_id returned
    assert result is not None
    assert "conv_new_123" in result
    assert result == "telegram:123:conv_new_123"

    # Verify archiver called
    mock_processor._conversation_archiver.archive.assert_called_once()
    archive_call = mock_processor._conversation_archiver.archive.call_args
    assert archive_call.kwargs["conversation_id"] == "conv_old"
    assert "auto-compact" in archive_call.kwargs["tags"]

    # Verify new conversation created
    mock_processor._session_manager.new_conversation.assert_called_once_with(
        "telegram:123"
    )


@pytest.mark.asyncio
async def test_auto_compact_generates_summary(mock_processor):
    """Verify agent_runner.run is called with SUMMARIZE_PROMPT."""
    # Mock context info showing high utilization
    mock_processor._agent_runner.get_context_info = AsyncMock(
        return_value={
            "max_input_tokens": 200000,
            "approximate_tokens": 170000,
            "utilization": 0.85,
            "message_count": 150,
        }
    )

    # Mock archiver
    mock_processor._conversation_archiver.archive = AsyncMock(
        return_value=MagicMock()
    )

    # Mock agent run
    summary_text = "This is a conversation summary"
    mock_processor._agent_runner.run = AsyncMock(return_value=summary_text)
    mock_processor._agent_runner.checkpointer = MagicMock()

    # Mock session manager
    mock_processor._session_manager.new_conversation = MagicMock(
        return_value="conv_new_456"
    )

    channel = AsyncMock()
    await mock_processor._check_auto_compact(
        "telegram:123", "telegram:123:conv_old", channel
    )

    # Verify agent.run was called twice: once for summary, once for injection
    assert mock_processor._agent_runner.run.call_count == 2

    # First call should contain SUMMARIZE_PROMPT
    first_call = mock_processor._agent_runner.run.call_args_list[0]
    assert "summarize" in first_call.kwargs["message"].lower()
    assert first_call.kwargs["thread_id"] == "telegram:123:conv_old"

    # Second call should inject summary into new thread
    second_call = mock_processor._agent_runner.run.call_args_list[1]
    assert summary_text in second_call.kwargs["message"]
    assert second_call.kwargs["thread_id"] == "telegram:123:conv_new_456"


@pytest.mark.asyncio
async def test_auto_compact_notifies_user(mock_processor):
    """Verify channel.send_message called with compact notification."""
    # Mock context info
    mock_processor._agent_runner.get_context_info = AsyncMock(
        return_value={
            "max_input_tokens": 200000,
            "approximate_tokens": 170000,
            "utilization": 0.85,
            "message_count": 150,
        }
    )

    # Mock archiver
    mock_processor._conversation_archiver.archive = AsyncMock(
        return_value=MagicMock()
    )

    # Mock agent run
    mock_processor._agent_runner.run = AsyncMock(return_value="Summary")
    mock_processor._agent_runner.checkpointer = MagicMock()

    # Mock session manager
    mock_processor._session_manager.new_conversation = MagicMock(
        return_value="conv_new_789"
    )

    channel = AsyncMock()
    await mock_processor._check_auto_compact(
        "telegram:123", "telegram:123:conv_old", channel
    )

    # Verify notification sent to user
    channel.send_message.assert_called_once()
    call_args = channel.send_message.call_args
    assert call_args.args[0] == "telegram:123"
    message_text = call_args.args[1]
    assert "auto-compacted" in message_text.lower()
    assert "150 messages" in message_text
    assert "170,000 tokens" in message_text


@pytest.mark.asyncio
async def test_auto_compact_error_handling(mock_processor):
    """get_context_info raises exception returns None, logs error."""
    # Mock get_context_info to raise exception
    mock_processor._agent_runner.get_context_info = AsyncMock(
        side_effect=Exception("Database error")
    )

    channel = AsyncMock()
    result = await mock_processor._check_auto_compact(
        "telegram:123", "telegram:123:conv_old", channel
    )

    # Should return None on error
    assert result is None

    # Verify error logged
    mock_processor._logger.error.assert_called_once()
    error_call = mock_processor._logger.error.call_args
    assert "Auto-compact failed" in error_call.args[0]
    assert "telegram:123" in error_call.args[0]


@pytest.mark.asyncio
async def test_auto_compact_no_config_returns_none(mock_processor):
    """When auto_compact_config is None returns None."""
    # Set config to None
    mock_processor._auto_compact_config = None

    channel = AsyncMock()
    result = await mock_processor._check_auto_compact(
        "telegram:123", "telegram:123:conv_old", channel
    )

    assert result is None
    # Ensure get_context_info was never called
    mock_processor._agent_runner.get_context_info.assert_not_called()
