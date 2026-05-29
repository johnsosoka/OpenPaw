"""Tests for FollowupScheduler."""

import logging
from unittest.mock import MagicMock

import pytest

from openpaw.workspace.processors.followup_scheduler import FollowupResult, FollowupScheduler


@pytest.fixture
def scheduler():
    loader = MagicMock()
    return FollowupScheduler(
        builtin_loader=loader,
        logger=logging.getLogger("test"),
    )


class TestFollowupResult:
    def test_continue(self):
        result = FollowupResult(action="continue", combined_content="followup", new_depth=2)
        assert result.action == "continue"
        assert result.new_depth == 2
        assert result.scheduled is False

    def test_break(self):
        result = FollowupResult(action="break")
        assert result.action == "break"
        assert result.scheduled is False


class TestCheck:
    def test_no_followup_tool_returns_break(self, scheduler):
        scheduler._builtin_loader.get_tool_instance.return_value = None
        result = scheduler.check("s1", 0)
        assert result.action == "break"

    def test_no_pending_followup_returns_break(self, scheduler):
        tool = MagicMock()
        tool.get_pending_followup.return_value = None
        scheduler._builtin_loader.get_tool_instance.return_value = tool
        result = scheduler.check("s1", 0)
        assert result.action == "break"

    def test_immediate_followup_returns_continue(self, scheduler):
        followup = MagicMock()
        followup.delay_seconds = 0
        followup.prompt = "do more"
        tool = MagicMock()
        tool.get_pending_followup.return_value = followup
        scheduler._builtin_loader.get_tool_instance.return_value = tool
        result = scheduler.check("s1", 0)
        assert result.action == "continue"
        assert result.new_depth == 1
        assert "do more" in (result.combined_content or "")

    def test_depth_exceeded_returns_break(self, scheduler):
        followup = MagicMock()
        followup.delay_seconds = 0
        followup.prompt = "do more"
        tool = MagicMock()
        tool.get_pending_followup.return_value = followup
        scheduler._builtin_loader.get_tool_instance.return_value = tool
        result = scheduler.check("s1", 5, max_depth=5)
        assert result.action == "break"

    def test_delayed_followup_schedules_and_breaks(self, scheduler):
        followup = MagicMock()
        followup.delay_seconds = 60
        followup.prompt = "do later"
        tool = MagicMock()
        tool.get_pending_followup.return_value = followup
        scheduler._builtin_loader.get_tool_instance.return_value = tool

        cron_tool = MagicMock()
        cron_tool.scheduler = MagicMock()
        cron_tool.default_chat_id = "123"
        cron_tool.default_channel = "telegram"
        cron_tool.store = MagicMock()
        cron_tool._add_to_live_scheduler = MagicMock()

        def side_effect(name):
            if name == "followup":
                return tool
            if name == "cron":
                return cron_tool
            return None

        scheduler._builtin_loader.get_tool_instance.side_effect = side_effect
        result = scheduler.check("s1", 0)
        assert result.action == "break"
        assert result.scheduled is True
        cron_tool.store.add_task.assert_called_once()
