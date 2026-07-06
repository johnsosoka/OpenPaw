"""Tests for MessageProcessor._check_auto_compact flush-before-compact."""

import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from openpaw.core.config.models import AutoCompactConfig
from openpaw.workspace.message_processor import MessageProcessor

_OVER_THRESHOLD_CONTEXT = {
    "max_input_tokens": 200000,
    "approximate_tokens": 170000,
    "utilization": 0.85,
    "message_count": 150,
}


def _make_processor(
    config: AutoCompactConfig,
    run_side_effect: list,
) -> MessageProcessor:
    agent_runner = AsyncMock()
    agent_runner.get_context_info = AsyncMock(return_value=_OVER_THRESHOLD_CONTEXT)
    agent_runner.run = AsyncMock(side_effect=run_side_effect)
    agent_runner.checkpointer = MagicMock()

    session_manager = MagicMock()
    session_manager.new_conversation = MagicMock(return_value="conv_new")

    return MessageProcessor(
        agent_runner=agent_runner,
        session_manager=session_manager,
        queue_manager=MagicMock(),
        builtin_loader=MagicMock(),
        queue_middleware=MagicMock(),
        approval_middleware=MagicMock(),
        approval_manager=None,
        workspace_name="test_workspace",
        token_logger=MagicMock(),
        logger=logging.getLogger("test"),
        conversation_archiver=AsyncMock(),
        auto_compact_config=config,
        lifecycle_config=None,
    )


@pytest.mark.asyncio
async def test_flush_turn_runs_before_summarize():
    """Default config (flush on): flush turn precedes summarize, injection
    references the flush file."""
    processor = _make_processor(
        AutoCompactConfig(enabled=True, trigger=0.8),
        ["Saved context.", "Summary", None],
    )

    result = await processor._check_auto_compact(
        "telegram:123", "telegram:123:conv_old", AsyncMock()
    )

    assert result == "telegram:123:conv_new"
    runner = processor._agent_runner
    assert runner.run.call_count == 3
    flush_call, summarize_call, inject_call = runner.run.call_args_list
    assert "[PRE-COMPACT FLUSH]" in flush_call.kwargs["message"]
    assert flush_call.kwargs["thread_id"] == "telegram:123:conv_old"
    assert "summarize" in summarize_call.kwargs["message"].lower()
    assert "memory/compact-flush-" in inject_call.kwargs["message"]


@pytest.mark.asyncio
async def test_flush_disabled_matches_legacy_path():
    """flush=False: two turns only, first is the summarize prompt."""
    processor = _make_processor(
        AutoCompactConfig(enabled=True, trigger=0.8, flush=False),
        ["Summary", None],
    )

    result = await processor._check_auto_compact(
        "telegram:123", "telegram:123:conv_old", AsyncMock()
    )

    assert result == "telegram:123:conv_new"
    runner = processor._agent_runner
    assert runner.run.call_count == 2
    assert "summarize" in runner.run.call_args_list[0].kwargs["message"].lower()


@pytest.mark.asyncio
async def test_flush_failure_does_not_block_compaction():
    """A failing flush turn never blocks compaction (fail-open)."""
    processor = _make_processor(
        AutoCompactConfig(enabled=True, trigger=0.8),
        [Exception("flush boom"), "Summary", None],
    )

    result = await processor._check_auto_compact(
        "telegram:123", "telegram:123:conv_old", AsyncMock()
    )

    assert result == "telegram:123:conv_new"
    runner = processor._agent_runner
    assert runner.run.call_count == 3
    inject_call = runner.run.call_args_list[2]
    assert "memory/compact-flush-" not in inject_call.kwargs["message"]


# ---------------------------------------------------------------------------
# Post-compact todo re-injection (balanced harness, DESIGN §2.1 wrinkle)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_balanced_todos_survive_auto_compact():
    """A runner exposing get_todos (balanced) has its live checklist rendered
    into the post-compact injection, read from the OLD thread."""
    processor = _make_processor(
        AutoCompactConfig(enabled=True, trigger=0.8, flush=False),
        ["Summary", None],
    )
    runner = processor._agent_runner
    runner.get_todos = AsyncMock(
        return_value=[
            {"content": "Research", "status": "completed"},
            {"content": "Build", "status": "in_progress"},
        ]
    )

    result = await processor._check_auto_compact(
        "telegram:123", "telegram:123:conv_old", AsyncMock()
    )

    assert result == "telegram:123:conv_new"
    runner.get_todos.assert_awaited_once_with("telegram:123:conv_old")
    inject_call = runner.run.call_args_list[-1]
    message = inject_call.kwargs["message"]
    assert "restored after context compaction" in message
    assert "[x] Research" in message
    assert "[~] Build" in message


@pytest.mark.asyncio
async def test_react_runner_without_get_todos_is_a_noop():
    """No get_todos attribute (react/ultra) -> injection unchanged."""
    processor = _make_processor(
        AutoCompactConfig(enabled=True, trigger=0.8, flush=False),
        ["Summary", None],
    )
    runner = processor._agent_runner
    del runner.get_todos  # AsyncMock auto-creates attributes; make it react-like

    result = await processor._check_auto_compact(
        "telegram:123", "telegram:123:conv_old", AsyncMock()
    )

    assert result == "telegram:123:conv_new"
    inject_call = runner.run.call_args_list[-1]
    assert "restored after context compaction" not in inject_call.kwargs["message"]


@pytest.mark.asyncio
async def test_all_completed_todos_are_not_reinjected():
    """A finished checklist is noise, not context -> no reminder."""
    processor = _make_processor(
        AutoCompactConfig(enabled=True, trigger=0.8, flush=False),
        ["Summary", None],
    )
    runner = processor._agent_runner
    runner.get_todos = AsyncMock(
        return_value=[{"content": "Done thing", "status": "completed"}]
    )

    result = await processor._check_auto_compact(
        "telegram:123", "telegram:123:conv_old", AsyncMock()
    )

    assert result == "telegram:123:conv_new"
    inject_call = runner.run.call_args_list[-1]
    assert "restored after context compaction" not in inject_call.kwargs["message"]


@pytest.mark.asyncio
async def test_todo_read_failure_never_blocks_compaction():
    """A failing get_todos is fail-open: compaction proceeds without it."""
    processor = _make_processor(
        AutoCompactConfig(enabled=True, trigger=0.8, flush=False),
        ["Summary", None],
    )
    runner = processor._agent_runner
    runner.get_todos = AsyncMock(side_effect=Exception("state boom"))

    result = await processor._check_auto_compact(
        "telegram:123", "telegram:123:conv_old", AsyncMock()
    )

    assert result == "telegram:123:conv_new"
    inject_call = runner.run.call_args_list[-1]
    assert "restored after context compaction" not in inject_call.kwargs["message"]
