"""Tests for MessageProcessor._schedule_delayed_followup."""

import logging
from unittest.mock import MagicMock, patch

import pytest

from openpaw.workspace.message_processor import MessageProcessor


def _make_processor(builtin_loader: MagicMock | None = None) -> MessageProcessor:
    qm = MagicMock()
    qm.get_session_mode = MagicMock(return_value=None)
    qm.peek_pending = MagicMock(return_value=False)

    sm = MagicMock()
    sm.get_thread_id = MagicMock(return_value="telegram:123:conv1")
    sm.increment_message_count = MagicMock()
    sm.is_session_expired = MagicMock(return_value=False)

    bl = builtin_loader or MagicMock()
    bl.get_tool_instance = MagicMock(return_value=None)

    qmw = MagicMock()
    qmw.was_steered = False
    qmw.pending_steer_message = None

    return MessageProcessor(
        agent_runner=MagicMock(),
        session_manager=sm,
        queue_manager=qm,
        builtin_loader=bl,
        queue_middleware=qmw,
        approval_middleware=MagicMock(),
        approval_manager=None,
        workspace_name="test_workspace",
        token_logger=MagicMock(),
        logger=logging.getLogger("test"),
        conversation_archiver=None,
        auto_compact_config=None,
        lifecycle_config=None,
        status_reminder_middleware=None,
        status_update_middleware=None,
    )


class TestScheduleDelayedFollowup:
    def _make_followup(self, delay: int = 60, prompt: str = "do later") -> MagicMock:
        f = MagicMock()
        f.delay_seconds = delay
        f.prompt = prompt
        return f

    def _make_cron_tool(self) -> MagicMock:
        cron_tool = MagicMock()
        cron_tool.scheduler = MagicMock()
        cron_tool.default_chat_id = "123"
        cron_tool.default_channel = "telegram"
        cron_tool.store = MagicMock()
        return cron_tool

    def test_calls_bridge_with_scheduler_and_task(self):
        """Bug fix: must call _add_to_live_scheduler(scheduler, task), not as instance method."""
        cron_tool = self._make_cron_tool()
        processor = _make_processor()
        # Configure after construction — factory resets get_tool_instance to return None
        processor._builtin_loader.get_tool_instance.return_value = cron_tool

        with patch(
            "openpaw.workspace.message_processor._add_to_live_scheduler"
        ) as mock_bridge:
            processor._schedule_delayed_followup(self._make_followup(), "telegram:123")

        cron_tool.store.add_task.assert_called_once()
        task_added = cron_tool.store.add_task.call_args[0][0]
        mock_bridge.assert_called_once_with(cron_tool.scheduler, task_added)

    def test_no_cron_tool_logs_warning_and_returns(self):
        processor = _make_processor()
        processor._builtin_loader.get_tool_instance.return_value = None

        with patch("openpaw.workspace.message_processor._add_to_live_scheduler") as mock_bridge:
            processor._schedule_delayed_followup(self._make_followup(), "telegram:123")

        mock_bridge.assert_not_called()

    def test_no_scheduler_logs_warning_and_returns(self):
        cron_tool = self._make_cron_tool()
        cron_tool.scheduler = None
        processor = _make_processor()
        processor._builtin_loader.get_tool_instance.return_value = cron_tool

        with patch("openpaw.workspace.message_processor._add_to_live_scheduler") as mock_bridge:
            processor._schedule_delayed_followup(self._make_followup(), "telegram:123")

        mock_bridge.assert_not_called()

    def test_no_default_chat_id_logs_warning_and_returns(self):
        cron_tool = self._make_cron_tool()
        cron_tool.default_chat_id = None
        processor = _make_processor()
        processor._builtin_loader.get_tool_instance.return_value = cron_tool

        with patch("openpaw.workspace.message_processor._add_to_live_scheduler") as mock_bridge:
            processor._schedule_delayed_followup(self._make_followup(), "telegram:123")

        mock_bridge.assert_not_called()
