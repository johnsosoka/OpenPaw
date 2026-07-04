"""Tests for auto-compact pre-run context check."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from openpaw.core.config.models import AutoCompactConfig
from openpaw.core.prompts.commands import FLUSH_NOOP_MARKER
from openpaw.workspace.processors.compactor import AutoCompactor


def _make_compactor(config: AutoCompactConfig) -> AutoCompactor:
    """Create an AutoCompactor with mocked dependencies."""
    return AutoCompactor(
        session_manager=MagicMock(),
        conversation_archiver=AsyncMock(),
        auto_compact_config=config,
        lifecycle_config=None,
        logger=MagicMock(),
    )


@pytest.fixture
def mock_compactor():
    """AutoCompactor with flush disabled (legacy two-turn compact path)."""
    return _make_compactor(AutoCompactConfig(enabled=True, trigger=0.8, flush=False))


@pytest.fixture
def flush_compactor():
    """AutoCompactor with flush enabled (default)."""
    return _make_compactor(AutoCompactConfig(enabled=True, trigger=0.8))


@pytest.mark.asyncio
async def test_auto_compact_disabled_returns_none(mock_compactor):
    """When config disabled, returns None immediately."""
    mock_compactor._auto_compact_config.enabled = False
    channel = AsyncMock()
    agent_runner = AsyncMock()

    result = await mock_compactor.check_compact(
        "telegram:123", "telegram:123:conv_old", channel, agent_runner
    )

    assert result is None
    agent_runner.get_context_info.assert_not_called()


@pytest.mark.asyncio
async def test_auto_compact_below_threshold_returns_none(mock_compactor):
    """Utilization 0.5 < 0.8 trigger returns None."""
    agent_runner = AsyncMock()
    agent_runner.get_context_info = AsyncMock(
        return_value={
            "max_input_tokens": 200000,
            "approximate_tokens": 100000,
            "utilization": 0.5,
            "message_count": 50,
        }
    )

    channel = AsyncMock()
    result = await mock_compactor.check_compact(
        "telegram:123", "telegram:123:conv_old", channel, agent_runner
    )

    assert result is None
    mock_compactor._conversation_archiver.archive.assert_not_called()


@pytest.mark.asyncio
async def test_auto_compact_no_archiver_returns_none(mock_compactor):
    """No conversation_archiver returns None."""
    mock_compactor._conversation_archiver = None
    channel = AsyncMock()
    agent_runner = AsyncMock()

    result = await mock_compactor.check_compact(
        "telegram:123", "telegram:123:conv_old", channel, agent_runner
    )

    assert result is None


@pytest.mark.asyncio
async def test_auto_compact_triggers_above_threshold(mock_compactor):
    """Utilization 0.85 > 0.8 triggers archive, creates new conversation, returns new thread_id."""
    agent_runner = AsyncMock()
    agent_runner.get_context_info = AsyncMock(
        return_value={
            "max_input_tokens": 200000,
            "approximate_tokens": 170000,
            "utilization": 0.85,
            "message_count": 150,
        }
    )
    agent_runner.run = AsyncMock(return_value="Summary of conversation")
    agent_runner.checkpointer = MagicMock()

    mock_compactor._session_manager.new_conversation = MagicMock(
        return_value="conv_new_123"
    )

    channel = AsyncMock()
    result = await mock_compactor.check_compact(
        "telegram:123", "telegram:123:conv_old", channel, agent_runner
    )

    assert result is not None
    assert "conv_new_123" in result
    assert result == "telegram:123:conv_new_123"

    mock_compactor._conversation_archiver.archive.assert_called_once()
    archive_call = mock_compactor._conversation_archiver.archive.call_args
    assert archive_call.kwargs["conversation_id"] == "conv_old"
    assert "auto-compact" in archive_call.kwargs["tags"]

    mock_compactor._session_manager.new_conversation.assert_called_once_with(
        "telegram:123"
    )


@pytest.mark.asyncio
async def test_auto_compact_generates_summary(mock_compactor):
    """Verify agent_runner.run is called with SUMMARIZE_PROMPT."""
    agent_runner = AsyncMock()
    agent_runner.get_context_info = AsyncMock(
        return_value={
            "max_input_tokens": 200000,
            "approximate_tokens": 170000,
            "utilization": 0.85,
            "message_count": 150,
        }
    )
    mock_compactor._conversation_archiver.archive = AsyncMock(return_value=MagicMock())

    summary_text = "This is a conversation summary"
    agent_runner.run = AsyncMock(return_value=summary_text)
    agent_runner.checkpointer = MagicMock()

    mock_compactor._session_manager.new_conversation = MagicMock(
        return_value="conv_new_456"
    )

    channel = AsyncMock()
    await mock_compactor.check_compact(
        "telegram:123", "telegram:123:conv_old", channel, agent_runner
    )

    assert agent_runner.run.call_count == 2

    first_call = agent_runner.run.call_args_list[0]
    assert "summarize" in first_call.kwargs["message"].lower()
    assert first_call.kwargs["thread_id"] == "telegram:123:conv_old"

    second_call = agent_runner.run.call_args_list[1]
    assert summary_text in second_call.kwargs["message"]
    assert second_call.kwargs["thread_id"] == "telegram:123:conv_new_456"


@pytest.mark.asyncio
async def test_auto_compact_notifies_user(mock_compactor):
    """Verify channel.send_message called with compact notification."""
    agent_runner = AsyncMock()
    agent_runner.get_context_info = AsyncMock(
        return_value={
            "max_input_tokens": 200000,
            "approximate_tokens": 170000,
            "utilization": 0.85,
            "message_count": 150,
        }
    )
    mock_compactor._conversation_archiver.archive = AsyncMock(return_value=MagicMock())
    agent_runner.run = AsyncMock(return_value="Summary")
    agent_runner.checkpointer = MagicMock()

    mock_compactor._session_manager.new_conversation = MagicMock(
        return_value="conv_new_789"
    )

    channel = AsyncMock()
    await mock_compactor.check_compact(
        "telegram:123", "telegram:123:conv_old", channel, agent_runner
    )

    channel.send_message.assert_called_once()
    call_args = channel.send_message.call_args
    assert call_args.args[0] == "telegram:123"
    message_text = call_args.args[1]
    assert "auto-compacted" in message_text.lower()
    assert "150 messages" in message_text
    assert "170,000 tokens" in message_text


@pytest.mark.asyncio
async def test_auto_compact_error_handling(mock_compactor):
    """get_context_info raises exception returns None, logs error."""
    agent_runner = AsyncMock()
    agent_runner.get_context_info = AsyncMock(side_effect=Exception("Database error"))

    channel = AsyncMock()
    result = await mock_compactor.check_compact(
        "telegram:123", "telegram:123:conv_old", channel, agent_runner
    )

    assert result is None
    mock_compactor._logger.error.assert_called_once()
    error_call = mock_compactor._logger.error.call_args
    assert "Auto-compact failed" in error_call.args[0]
    assert "telegram:123" in error_call.args[0]


_OVER_THRESHOLD_CONTEXT = {
    "max_input_tokens": 200000,
    "approximate_tokens": 170000,
    "utilization": 0.85,
    "message_count": 150,
}


def _make_agent_runner(run_side_effect: list) -> AsyncMock:
    """Agent runner mock over the compact threshold."""
    agent_runner = AsyncMock()
    agent_runner.get_context_info = AsyncMock(return_value=_OVER_THRESHOLD_CONTEXT)
    agent_runner.run = AsyncMock(side_effect=run_side_effect)
    agent_runner.checkpointer = MagicMock()
    return agent_runner


def test_flush_config_defaults_to_enabled():
    """flush is on by default — it is protective."""
    assert AutoCompactConfig().flush is True


@pytest.mark.asyncio
async def test_flush_turn_runs_before_summarize(flush_compactor):
    """With flush enabled, a flush turn precedes summarization and the
    injected summary references the flush file."""
    agent_runner = _make_agent_runner(["Saved context.", "Summary", None])
    flush_compactor._session_manager.new_conversation = MagicMock(
        return_value="conv_new"
    )

    result = await flush_compactor.check_compact(
        "telegram:123", "telegram:123:conv_old", AsyncMock(), agent_runner
    )

    assert result == "telegram:123:conv_new"
    assert agent_runner.run.call_count == 3

    flush_call, summarize_call, inject_call = agent_runner.run.call_args_list
    assert "[PRE-COMPACT FLUSH]" in flush_call.kwargs["message"]
    assert "memory/compact-flush-" in flush_call.kwargs["message"]
    assert flush_call.kwargs["thread_id"] == "telegram:123:conv_old"
    assert "summarize" in summarize_call.kwargs["message"].lower()
    assert "memory/compact-flush-" in inject_call.kwargs["message"]
    assert inject_call.kwargs["thread_id"] == "telegram:123:conv_new"


@pytest.mark.asyncio
async def test_flush_disabled_skips_flush_turn(mock_compactor):
    """flush=False keeps the legacy two-turn compact path untouched."""
    agent_runner = _make_agent_runner(["Summary", None])
    mock_compactor._session_manager.new_conversation = MagicMock(
        return_value="conv_new"
    )

    result = await mock_compactor.check_compact(
        "telegram:123", "telegram:123:conv_old", AsyncMock(), agent_runner
    )

    assert result == "telegram:123:conv_new"
    assert agent_runner.run.call_count == 2
    first_call = agent_runner.run.call_args_list[0]
    assert "[PRE-COMPACT FLUSH]" not in first_call.kwargs["message"]
    assert "summarize" in first_call.kwargs["message"].lower()


@pytest.mark.asyncio
async def test_flush_noop_marker_omits_flush_note(flush_compactor):
    """Agent replying NOTHING_TO_FLUSH means no flush-file reference is injected."""
    agent_runner = _make_agent_runner([FLUSH_NOOP_MARKER, "Summary", None])
    flush_compactor._session_manager.new_conversation = MagicMock(
        return_value="conv_new"
    )

    result = await flush_compactor.check_compact(
        "telegram:123", "telegram:123:conv_old", AsyncMock(), agent_runner
    )

    assert result == "telegram:123:conv_new"
    inject_call = agent_runner.run.call_args_list[2]
    assert "memory/compact-flush-" not in inject_call.kwargs["message"]


@pytest.mark.asyncio
async def test_flush_failure_does_not_block_compaction(flush_compactor):
    """A failing flush turn is fail-open: compaction proceeds without it."""
    agent_runner = _make_agent_runner([Exception("flush boom"), "Summary", None])
    flush_compactor._session_manager.new_conversation = MagicMock(
        return_value="conv_new"
    )

    result = await flush_compactor.check_compact(
        "telegram:123", "telegram:123:conv_old", AsyncMock(), agent_runner
    )

    assert result == "telegram:123:conv_new"
    assert agent_runner.run.call_count == 3
    flush_compactor._logger.warning.assert_called_once()
    assert "flush" in flush_compactor._logger.warning.call_args.args[0].lower()
    inject_call = agent_runner.run.call_args_list[2]
    assert "memory/compact-flush-" not in inject_call.kwargs["message"]


@pytest.mark.asyncio
async def test_auto_compact_no_config_returns_none(mock_compactor):
    """When auto_compact_config is None returns None."""
    mock_compactor._auto_compact_config = None
    channel = AsyncMock()
    agent_runner = AsyncMock()

    result = await mock_compactor.check_compact(
        "telegram:123", "telegram:123:conv_old", channel, agent_runner
    )

    assert result is None
    agent_runner.get_context_info.assert_not_called()
