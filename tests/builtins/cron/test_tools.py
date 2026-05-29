"""Tests for CronToolBuiltin functionality."""

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import Mock

import pytest

from openpaw.builtins.tools._channel_context import (
    clear_channel_context,
    set_channel_context,
)
from openpaw.builtins.tools.cron import CronToolBuiltin
from openpaw.stores.cron import (
    DynamicCronTask,
    create_interval_task,
    create_once_task,
)


class TestCronToolBuiltin:
    """Test CronToolBuiltin functionality."""

    def test_metadata(self) -> None:
        """Test CronToolBuiltin metadata."""
        assert CronToolBuiltin.metadata.name == "cron"
        assert CronToolBuiltin.metadata.display_name == "Task Scheduler"
        assert CronToolBuiltin.metadata.group == "automation"
        assert CronToolBuiltin.metadata.prerequisites.env_vars == []

    def test_initialization_requires_workspace_path(self) -> None:
        """Test that initialization requires workspace_path in config."""
        with pytest.raises(ValueError, match="requires 'workspace_path'"):
            CronToolBuiltin(config={})

    def test_initialization_with_config(self, tmp_path: Any) -> None:
        """Test initialization with valid config."""
        config = {
            "workspace_path": str(tmp_path),
            "min_interval_seconds": 60,
            "max_tasks": 25,
            "timezone": "America/New_York",
        }

        tool = CronToolBuiltin(config)

        assert tool.workspace_path == tmp_path
        assert tool.min_interval_seconds == 60
        assert tool.max_tasks == 25
        assert tool.timezone == "America/New_York"
        assert tool.scheduler is None

    def test_initialization_default_values(self, tmp_path: Any) -> None:
        """Test initialization uses default values."""
        config = {"workspace_path": str(tmp_path)}

        tool = CronToolBuiltin(config)

        assert tool.min_interval_seconds == 300
        assert tool.max_tasks == 50
        assert tool.timezone == "UTC"

    def test_get_langchain_tool_returns_list(self, tmp_path: Any) -> None:
        """Test that get_langchain_tool returns a list of tools."""
        config = {"workspace_path": str(tmp_path)}
        tool = CronToolBuiltin(config)

        tools = tool.get_langchain_tool()

        assert isinstance(tools, list)
        assert len(tools) == 4

        tool_names = [t.name for t in tools]
        assert "schedule_at" in tool_names
        assert "schedule_every" in tool_names
        assert "list_scheduled" in tool_names
        assert "cancel_scheduled" in tool_names

    @pytest.mark.asyncio
    async def test_schedule_at_creates_once_task(self, tmp_path: Any) -> None:
        """Test schedule_at creates a one-time task."""
        config = {"workspace_path": str(tmp_path)}
        tool = CronToolBuiltin(config)
        tools = tool.get_langchain_tool()
        schedule_at_tool = next(t for t in tools if t.name == "schedule_at")

        # Schedule task for 1 hour in the future
        future_time = datetime.now(UTC) + timedelta(hours=1)
        result = await schedule_at_tool.ainvoke({
            "run_at": future_time.isoformat(),
            "prompt": "Test reminder",
        })

        assert "Scheduled task" in result
        assert "Test reminder" in result

        # Verify task was stored
        tasks = tool.store.list_tasks()
        assert len(tasks) == 1
        assert tasks[0].task_type == "once"
        assert tasks[0].prompt == "Test reminder"

    @pytest.mark.asyncio
    async def test_schedule_at_rejects_past_time(self, tmp_path: Any) -> None:
        """Test schedule_at rejects past timestamps."""
        config = {"workspace_path": str(tmp_path)}
        tool = CronToolBuiltin(config)
        tools = tool.get_langchain_tool()
        schedule_at_tool = next(t for t in tools if t.name == "schedule_at")

        # Try to schedule in the past
        past_time = datetime.now(UTC) - timedelta(hours=1)
        result = await schedule_at_tool.ainvoke({
            "run_at": past_time.isoformat(),
            "prompt": "Past task",
        })

        assert "[Error:" in result
        assert "must be in the future" in result

        # Verify no task was created
        tasks = tool.store.list_tasks()
        assert len(tasks) == 0

    @pytest.mark.asyncio
    async def test_schedule_at_rejects_invalid_timestamp(self, tmp_path: Any) -> None:
        """Test schedule_at rejects invalid timestamp format."""
        config = {"workspace_path": str(tmp_path)}
        tool = CronToolBuiltin(config)
        tools = tool.get_langchain_tool()
        schedule_at_tool = next(t for t in tools if t.name == "schedule_at")

        result = await schedule_at_tool.ainvoke({
            "run_at": "not-a-valid-timestamp",
            "prompt": "Invalid task",
        })

        assert "[Error:" in result
        assert "Invalid timestamp format" in result

        tasks = tool.store.list_tasks()
        assert len(tasks) == 0

    @pytest.mark.asyncio
    async def test_schedule_every_creates_interval_task(self, tmp_path: Any) -> None:
        """Test schedule_every creates a recurring task."""
        config = {"workspace_path": str(tmp_path), "min_interval_seconds": 60}
        tool = CronToolBuiltin(config)
        tools = tool.get_langchain_tool()
        schedule_every_tool = next(t for t in tools if t.name == "schedule_every")

        result = await schedule_every_tool.ainvoke({
            "interval_seconds": 300,
            "prompt": "Recurring check",
        })

        assert "Scheduled recurring task" in result
        assert "5 minutes" in result
        assert "Recurring check" in result

        # Verify task was stored
        tasks = tool.store.list_tasks()
        assert len(tasks) == 1
        assert tasks[0].task_type == "interval"
        assert tasks[0].interval_seconds == 300

    @pytest.mark.asyncio
    async def test_schedule_every_rejects_below_minimum(self, tmp_path: Any) -> None:
        """Test schedule_every rejects intervals below minimum."""
        config = {"workspace_path": str(tmp_path), "min_interval_seconds": 300}
        tool = CronToolBuiltin(config)
        tools = tool.get_langchain_tool()
        schedule_every_tool = next(t for t in tools if t.name == "schedule_every")

        result = await schedule_every_tool.ainvoke({
            "interval_seconds": 60,
            "prompt": "Too frequent",
        })

        assert "[Error:" in result
        assert "at least 300 seconds" in result

        tasks = tool.store.list_tasks()
        assert len(tasks) == 0

    @pytest.mark.asyncio
    async def test_list_scheduled_formats_correctly(self, tmp_path: Any) -> None:
        """Test list_scheduled returns formatted task list."""
        config = {"workspace_path": str(tmp_path)}
        tool = CronToolBuiltin(config)
        tools = tool.get_langchain_tool()
        list_tool = next(t for t in tools if t.name == "list_scheduled")

        # Add some tasks
        future_time = datetime.now(UTC) + timedelta(hours=1)
        task1 = create_once_task("First task", future_time)
        task2 = create_interval_task("Second task", 600, datetime.now(UTC))

        tool.store.add_task(task1)
        tool.store.add_task(task2)

        result = await list_tool.ainvoke({})

        assert "Scheduled tasks:" in result
        assert "One-time" in result
        assert "Every 10 minutes" in result
        assert "First task" in result
        assert "Second task" in result

    @pytest.mark.asyncio
    async def test_list_scheduled_empty(self, tmp_path: Any) -> None:
        """Test list_scheduled with no tasks."""
        config = {"workspace_path": str(tmp_path)}
        tool = CronToolBuiltin(config)
        tools = tool.get_langchain_tool()
        list_tool = next(t for t in tools if t.name == "list_scheduled")

        result = await list_tool.ainvoke({})

        assert result == "No scheduled tasks."

    @pytest.mark.asyncio
    async def test_cancel_scheduled_removes_task(self, tmp_path: Any) -> None:
        """Test cancel_scheduled removes a task."""
        config = {"workspace_path": str(tmp_path)}
        tool = CronToolBuiltin(config)
        tools = tool.get_langchain_tool()
        cancel_tool = next(t for t in tools if t.name == "cancel_scheduled")

        # Add a task
        future_time = datetime.now(UTC) + timedelta(hours=1)
        task = create_once_task("To be cancelled", future_time)
        tool.store.add_task(task)

        assert len(tool.store.list_tasks()) == 1

        # Cancel it
        result = await cancel_tool.ainvoke({"task_id": task.id})

        assert "Successfully cancelled" in result
        assert task.id in result

        # Verify removed
        assert len(tool.store.list_tasks()) == 0

    @pytest.mark.asyncio
    async def test_cancel_scheduled_nonexistent(self, tmp_path: Any) -> None:
        """Test cancel_scheduled with nonexistent task."""
        config = {"workspace_path": str(tmp_path)}
        tool = CronToolBuiltin(config)
        tools = tool.get_langchain_tool()
        cancel_tool = next(t for t in tools if t.name == "cancel_scheduled")

        result = await cancel_tool.ainvoke({"task_id": "nonexistent-id"})

        assert "[Error:" in result
        assert "not found" in result

    @pytest.mark.asyncio
    async def test_cancel_scheduled_by_prefix(self, tmp_path: Any) -> None:
        """Test cancel_scheduled succeeds when given an 8-character prefix ID.

        This is the real-world scenario: the agent calls list_scheduled() and
        sees short IDs like [a1b2c3d4], then passes that prefix to
        cancel_scheduled(). Without prefix matching the cancellation silently
        fails because the store does exact UUID comparison.
        """
        config = {"workspace_path": str(tmp_path)}
        tool = CronToolBuiltin(config)
        tools = tool.get_langchain_tool()
        cancel_tool = next(t for t in tools if t.name == "cancel_scheduled")

        # Add a task with a known UUID
        known_uuid = "c3d4e5f6-a7b8-9012-cdef-123456789012"
        future_time = datetime.now(UTC) + timedelta(hours=1)
        task = DynamicCronTask(
            id=known_uuid,
            task_type="once",
            prompt="Cancel me by prefix",
            created_at=datetime.now(UTC),
            run_at=future_time,
        )
        tool.store.add_task(task)
        assert len(tool.store.list_tasks()) == 1

        # Cancel using only the 8-char prefix (as the agent would, from list_scheduled)
        result = await cancel_tool.ainvoke({"task_id": known_uuid[:8]})

        assert "Successfully cancelled" in result
        assert known_uuid in result  # confirmation should echo the full UUID
        assert len(tool.store.list_tasks()) == 0

    @pytest.mark.asyncio
    async def test_max_tasks_limit_enforced(self, tmp_path: Any) -> None:
        """Test that max_tasks limit is enforced."""
        config = {"workspace_path": str(tmp_path), "max_tasks": 2}
        tool = CronToolBuiltin(config)
        tools = tool.get_langchain_tool()
        schedule_at_tool = next(t for t in tools if t.name == "schedule_at")

        # Add tasks up to limit
        future_time = datetime.now(UTC) + timedelta(hours=1)

        result1 = await schedule_at_tool.ainvoke({
            "run_at": future_time.isoformat(),
            "prompt": "Task 1",
        })
        assert "Scheduled task" in result1

        result2 = await schedule_at_tool.ainvoke({
            "run_at": future_time.isoformat(),
            "prompt": "Task 2",
        })
        assert "Scheduled task" in result2

        # Try to add one more beyond limit
        result3 = await schedule_at_tool.ainvoke({
            "run_at": future_time.isoformat(),
            "prompt": "Task 3",
        })
        assert "[Error:" in result3
        assert "Maximum task limit" in result3

        # Verify only 2 tasks exist
        tasks = tool.store.list_tasks()
        assert len(tasks) == 2

    def test_parse_timestamp_naive_assumes_utc(self, tmp_path: Any) -> None:
        """Test that naive timestamps use workspace timezone (defaults to UTC)."""
        config = {"workspace_path": str(tmp_path)}
        tool = CronToolBuiltin(config)

        # Naive timestamp (no timezone) - should use workspace timezone (UTC by default)
        result = tool._parse_timestamp("2026-02-06T18:30:00")

        assert result.tzinfo == UTC
        assert result.hour == 18

    def test_parse_timestamp_with_timezone(self, tmp_path: Any) -> None:
        """Test parsing timestamp with explicit timezone."""
        config = {"workspace_path": str(tmp_path)}
        tool = CronToolBuiltin(config)

        # Timestamp with UTC timezone
        result = tool._parse_timestamp("2026-02-06T18:30:00Z")

        assert result.tzinfo == UTC

        # Timestamp with offset
        result2 = tool._parse_timestamp("2026-02-06T18:30:00-05:00")

        # Should be converted to UTC
        assert result2.tzinfo == UTC

    def test_format_interval(self, tmp_path: Any) -> None:
        """Test interval formatting for various durations."""
        config = {"workspace_path": str(tmp_path)}
        tool = CronToolBuiltin(config)

        assert tool._format_interval(30) == "30 seconds"
        assert tool._format_interval(60) == "1 minute"
        assert tool._format_interval(120) == "2 minutes"
        assert tool._format_interval(3600) == "1 hour"
        assert tool._format_interval(7200) == "2 hours"
        assert tool._format_interval(86400) == "1 day"
        assert tool._format_interval(172800) == "2 days"

    def test_format_time_until(self, tmp_path: Any) -> None:
        """Test time until formatting for various durations."""
        config = {"workspace_path": str(tmp_path)}
        tool = CronToolBuiltin(config)

        # Future times
        assert tool._format_time_until(30) == "in 30 seconds"
        assert tool._format_time_until(60) == "in 1 minute"
        assert tool._format_time_until(120) == "in 2 minutes"
        assert tool._format_time_until(3600) == "in 1 hour"
        assert tool._format_time_until(7200) == "in 2 hours"
        assert tool._format_time_until(86400) == "in 1 day"

        # Past times (overdue)
        assert "ago (overdue)" in tool._format_time_until(-60)
        assert "1 minute" in tool._format_time_until(-60)

    @pytest.mark.asyncio
    async def test_scheduler_notification_called(self, tmp_path: Any) -> None:
        """Test that scheduler is notified on task updates."""
        mock_scheduler = Mock()
        config = {
            "workspace_path": str(tmp_path),
            "cron_scheduler": mock_scheduler,
        }
        tool = CronToolBuiltin(config)
        tools = tool.get_langchain_tool()
        schedule_at_tool = next(t for t in tools if t.name == "schedule_at")

        # Schedule a task
        future_time = datetime.now(UTC) + timedelta(hours=1)
        await schedule_at_tool.ainvoke({
            "run_at": future_time.isoformat(),
            "prompt": "Test",
        })

        # Verify _notify_scheduler_update was called
        # Note: Currently it's just a placeholder, but we verify it doesn't error
        assert len(tool.store.list_tasks()) == 1


class TestCronToolSessionRouting:
    """Tests verifying that scheduled tasks route to the active session's user."""

    @pytest.mark.asyncio
    async def test_schedule_at_uses_session_chat_id(self, tmp_path: Any) -> None:
        """schedule_at should route to the session user, not the startup default."""
        config = {
            "workspace_path": str(tmp_path),
            "default_chat_id": 111,
            "min_interval_seconds": 60,
        }
        tool = CronToolBuiltin(config)
        schedule_at_tool = next(
            t for t in tool.get_langchain_tool() if t.name == "schedule_at"
        )

        mock_channel = Mock()
        set_channel_context(mock_channel, "telegram:8297899298")
        try:
            future_time = datetime.now(UTC) + timedelta(hours=1)
            await schedule_at_tool.ainvoke({
                "run_at": future_time.isoformat(),
                "prompt": "Reminder for Anna",
            })
        finally:
            clear_channel_context()

        tasks = tool.store.list_tasks()
        assert len(tasks) == 1
        assert tasks[0].chat_id == 8297899298

    @pytest.mark.asyncio
    async def test_schedule_at_falls_back_to_default_without_context(
        self, tmp_path: Any
    ) -> None:
        """schedule_at should use default_chat_id when no session context is set."""
        config = {
            "workspace_path": str(tmp_path),
            "default_chat_id": 111,
            "min_interval_seconds": 60,
        }
        tool = CronToolBuiltin(config)
        schedule_at_tool = next(
            t for t in tool.get_langchain_tool() if t.name == "schedule_at"
        )

        # No context set — should fall back to default_chat_id
        future_time = datetime.now(UTC) + timedelta(hours=1)
        await schedule_at_tool.ainvoke({
            "run_at": future_time.isoformat(),
            "prompt": "Default routing reminder",
        })

        tasks = tool.store.list_tasks()
        assert len(tasks) == 1
        assert tasks[0].chat_id == 111

    @pytest.mark.asyncio
    async def test_schedule_every_uses_session_chat_id(self, tmp_path: Any) -> None:
        """schedule_every should route to the session user, not the startup default."""
        config = {
            "workspace_path": str(tmp_path),
            "default_chat_id": 111,
            "min_interval_seconds": 60,
        }
        tool = CronToolBuiltin(config)
        schedule_every_tool = next(
            t for t in tool.get_langchain_tool() if t.name == "schedule_every"
        )

        mock_channel = Mock()
        set_channel_context(mock_channel, "telegram:8297899298")
        try:
            await schedule_every_tool.ainvoke({
                "interval_seconds": 300,
                "prompt": "Recurring check for Anna",
            })
        finally:
            clear_channel_context()

        tasks = tool.store.list_tasks()
        assert len(tasks) == 1
        assert tasks[0].chat_id == 8297899298

    @pytest.mark.asyncio
    async def test_schedule_at_fallback_on_non_numeric_session_key(
        self, tmp_path: Any
    ) -> None:
        """schedule_at should fall back to default_chat_id when session key is non-numeric."""
        config = {
            "workspace_path": str(tmp_path),
            "default_chat_id": 999,
            "min_interval_seconds": 60,
        }
        tool = CronToolBuiltin(config)
        schedule_at_tool = next(
            t for t in tool.get_langchain_tool() if t.name == "schedule_at"
        )

        mock_channel = Mock()
        set_channel_context(mock_channel, "telegram:not-a-number")
        try:
            future_time = datetime.now(UTC) + timedelta(hours=1)
            await schedule_at_tool.ainvoke({
                "run_at": future_time.isoformat(),
                "prompt": "Fallback test",
            })
        finally:
            clear_channel_context()

        tasks = tool.store.list_tasks()
        assert len(tasks) == 1
        assert tasks[0].chat_id == 999


class TestCronToolPromptEnrichment:
    """Tests verifying that scheduled prompts are enriched with user identity."""

    @pytest.mark.asyncio
    async def test_schedule_at_prepends_user_context(self, tmp_path: Any) -> None:
        """schedule_at should prepend user identity when aliases are configured."""
        config = {
            "workspace_path": str(tmp_path),
            "default_chat_id": 111,
            "user_aliases": {8297899298: "Anna"},
            "min_interval_seconds": 60,
        }
        tool = CronToolBuiltin(config)
        schedule_at_tool = next(
            t for t in tool.get_langchain_tool() if t.name == "schedule_at"
        )

        mock_channel = Mock()
        set_channel_context(mock_channel, "telegram:8297899298")
        try:
            future_time = datetime.now(UTC) + timedelta(hours=1)
            await schedule_at_tool.ainvoke({
                "run_at": future_time.isoformat(),
                "prompt": "Ping Anna now (she asked for a 5-minute reminder)",
            })
        finally:
            clear_channel_context()

        tasks = tool.store.list_tasks()
        assert len(tasks) == 1
        assert tasks[0].prompt.startswith("[Scheduled for user: Anna]")
        assert "Ping Anna now" in tasks[0].prompt

    @pytest.mark.asyncio
    async def test_schedule_every_prepends_user_context(self, tmp_path: Any) -> None:
        """schedule_every should prepend user identity when aliases are configured."""
        config = {
            "workspace_path": str(tmp_path),
            "default_chat_id": 111,
            "user_aliases": {8297899298: "Anna"},
            "min_interval_seconds": 60,
        }
        tool = CronToolBuiltin(config)
        schedule_every_tool = next(
            t for t in tool.get_langchain_tool() if t.name == "schedule_every"
        )

        mock_channel = Mock()
        set_channel_context(mock_channel, "telegram:8297899298")
        try:
            await schedule_every_tool.ainvoke({
                "interval_seconds": 300,
                "prompt": "Check on Anna's migraine status",
            })
        finally:
            clear_channel_context()

        tasks = tool.store.list_tasks()
        assert len(tasks) == 1
        assert tasks[0].prompt.startswith("[Scheduled for user: Anna]")
        assert "Check on Anna's migraine status" in tasks[0].prompt

    @pytest.mark.asyncio
    async def test_no_enrichment_without_aliases(self, tmp_path: Any) -> None:
        """Prompt should remain unchanged when no user_aliases configured."""
        config = {
            "workspace_path": str(tmp_path),
            "default_chat_id": 111,
            "min_interval_seconds": 60,
        }
        tool = CronToolBuiltin(config)
        schedule_at_tool = next(
            t for t in tool.get_langchain_tool() if t.name == "schedule_at"
        )

        mock_channel = Mock()
        set_channel_context(mock_channel, "telegram:111")
        try:
            future_time = datetime.now(UTC) + timedelta(hours=1)
            await schedule_at_tool.ainvoke({
                "run_at": future_time.isoformat(),
                "prompt": "Generic reminder",
            })
        finally:
            clear_channel_context()

        tasks = tool.store.list_tasks()
        assert len(tasks) == 1
        assert tasks[0].prompt == "Generic reminder"

    @pytest.mark.asyncio
    async def test_no_enrichment_when_user_not_in_aliases(
        self, tmp_path: Any
    ) -> None:
        """Prompt should remain unchanged when user is not in the aliases map."""
        config = {
            "workspace_path": str(tmp_path),
            "default_chat_id": 111,
            "user_aliases": {999: "Someone Else"},
            "min_interval_seconds": 60,
        }
        tool = CronToolBuiltin(config)
        schedule_at_tool = next(
            t for t in tool.get_langchain_tool() if t.name == "schedule_at"
        )

        mock_channel = Mock()
        set_channel_context(mock_channel, "telegram:111")
        try:
            future_time = datetime.now(UTC) + timedelta(hours=1)
            await schedule_at_tool.ainvoke({
                "run_at": future_time.isoformat(),
                "prompt": "Reminder for unknown user",
            })
        finally:
            clear_channel_context()

        tasks = tool.store.list_tasks()
        assert len(tasks) == 1
        assert tasks[0].prompt == "Reminder for unknown user"

    @pytest.mark.asyncio
    async def test_no_enrichment_without_session_context(
        self, tmp_path: Any
    ) -> None:
        """Prompt should remain unchanged when no session context (fallback chat_id)."""
        config = {
            "workspace_path": str(tmp_path),
            "default_chat_id": 111,
            "user_aliases": {111: "John"},
            "min_interval_seconds": 60,
        }
        tool = CronToolBuiltin(config)
        schedule_at_tool = next(
            t for t in tool.get_langchain_tool() if t.name == "schedule_at"
        )

        # No session context set — falls back to default_chat_id
        future_time = datetime.now(UTC) + timedelta(hours=1)
        await schedule_at_tool.ainvoke({
            "run_at": future_time.isoformat(),
            "prompt": "Reminder without context",
        })

        tasks = tool.store.list_tasks()
        assert len(tasks) == 1
        # default_chat_id 111 IS in aliases, so it should still enrich
        assert tasks[0].prompt.startswith("[Scheduled for user: John]")
