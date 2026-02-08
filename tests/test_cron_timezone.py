"""Tests for CronScheduler timezone handling."""

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, Mock, patch
from zoneinfo import ZoneInfo

import pytest

from openpaw.cron.loader import CronDefinition, CronOutputConfig
from openpaw.cron.scheduler import CronScheduler


@pytest.fixture
def mock_agent_factory() -> Mock:
    """Create a mock agent factory."""
    return Mock(return_value=Mock())


@pytest.fixture
def mock_channels() -> dict[str, Any]:
    """Create mock channels."""
    return {"telegram": Mock()}


class TestCronSchedulerTimezone:
    """Test CronScheduler timezone handling."""

    def test_initialization_stores_timezone(
        self,
        tmp_path: Path,
        mock_agent_factory: Mock,
        mock_channels: dict[str, Any],
    ) -> None:
        """Test that CronScheduler stores the timezone parameter."""
        scheduler = CronScheduler(
            workspace_path=tmp_path,
            agent_factory=mock_agent_factory,
            channels=mock_channels,
            workspace_name="test_workspace",
            timezone="America/New_York",
        )

        assert scheduler._timezone == "America/New_York"
        assert scheduler._tz == ZoneInfo("America/New_York")

    def test_initialization_defaults_to_utc(
        self,
        tmp_path: Path,
        mock_agent_factory: Mock,
        mock_channels: dict[str, Any],
    ) -> None:
        """Test that CronScheduler defaults to UTC timezone."""
        scheduler = CronScheduler(
            workspace_path=tmp_path,
            agent_factory=mock_agent_factory,
            channels=mock_channels,
        )

        assert scheduler._timezone == "UTC"
        assert scheduler._tz == ZoneInfo("UTC")

    @pytest.mark.asyncio
    async def test_scheduler_uses_timezone(
        self,
        tmp_path: Path,
        mock_agent_factory: Mock,
        mock_channels: dict[str, Any],
    ) -> None:
        """Test that AsyncIOScheduler is initialized with workspace timezone."""
        scheduler = CronScheduler(
            workspace_path=tmp_path,
            agent_factory=mock_agent_factory,
            channels=mock_channels,
            workspace_name="test_workspace",
            timezone="America/Chicago",
        )

        with patch("openpaw.cron.scheduler.AsyncIOScheduler") as mock_scheduler_class:
            mock_scheduler_instance = MagicMock()
            mock_scheduler_instance.start = MagicMock()
            mock_scheduler_class.return_value = mock_scheduler_instance

            await scheduler.start()

            # Verify AsyncIOScheduler was called with the timezone
            mock_scheduler_class.assert_called_once_with(timezone=ZoneInfo("America/Chicago"))

    @pytest.mark.asyncio
    async def test_cron_trigger_receives_timezone(
        self,
        tmp_path: Path,
        mock_agent_factory: Mock,
        mock_channels: dict[str, Any],
    ) -> None:
        """Test that CronTrigger receives the workspace timezone."""
        scheduler = CronScheduler(
            workspace_path=tmp_path,
            agent_factory=mock_agent_factory,
            channels=mock_channels,
            workspace_name="test_workspace",
            timezone="Europe/London",
        )

        # Create a mock scheduler instance
        mock_scheduler_instance = MagicMock()
        mock_scheduler_instance.add_job = MagicMock()
        scheduler._scheduler = mock_scheduler_instance

        # Create a test cron definition
        cron_def = CronDefinition(
            name="test_cron",
            schedule="0 9 * * *",  # 9 AM daily
            enabled=True,
            prompt="Test prompt",
            output=CronOutputConfig(channel="telegram", chat_id=123456),
        )

        with patch("openpaw.cron.scheduler.CronTrigger") as mock_cron_trigger:
            mock_trigger_instance = MagicMock()
            mock_cron_trigger.from_crontab = MagicMock(return_value=mock_trigger_instance)

            scheduler.add_job(cron_def)

            # Verify CronTrigger.from_crontab was called with the timezone
            mock_cron_trigger.from_crontab.assert_called_once_with(
                "0 9 * * *", timezone=ZoneInfo("Europe/London")
            )

    @pytest.mark.asyncio
    async def test_date_trigger_not_affected(
        self,
        tmp_path: Path,
        mock_agent_factory: Mock,
        mock_channels: dict[str, Any],
    ) -> None:
        """Test that DateTrigger (dynamic once tasks) is not affected by timezone.

        DateTrigger uses UTC-aware datetimes, which are timezone-independent.
        """
        from datetime import UTC, datetime, timedelta

        from openpaw.cron.dynamic import create_once_task

        scheduler = CronScheduler(
            workspace_path=tmp_path,
            agent_factory=mock_agent_factory,
            channels=mock_channels,
            workspace_name="test_workspace",
            timezone="America/Los_Angeles",
        )

        # Start scheduler to initialize _scheduler
        with patch("openpaw.cron.scheduler.AsyncIOScheduler") as mock_scheduler_class:
            mock_scheduler_instance = MagicMock()
            mock_scheduler_instance.start = MagicMock()
            mock_scheduler_instance.add_job = MagicMock()
            mock_scheduler_class.return_value = mock_scheduler_instance

            await scheduler.start()

            # Create a dynamic once task
            future_time = datetime.now(UTC) + timedelta(hours=1)
            task = create_once_task("Test task", future_time)

            with patch("openpaw.cron.scheduler.DateTrigger") as mock_date_trigger:
                mock_trigger_instance = MagicMock()
                mock_date_trigger.return_value = mock_trigger_instance

                scheduler.add_dynamic_job(task)

                # Verify DateTrigger was called without timezone (uses UTC datetime)
                mock_date_trigger.assert_called_once_with(run_date=task.run_at)

    @pytest.mark.asyncio
    async def test_interval_trigger_not_affected(
        self,
        tmp_path: Path,
        mock_agent_factory: Mock,
        mock_channels: dict[str, Any],
    ) -> None:
        """Test that IntervalTrigger (dynamic recurring tasks) is not affected by timezone.

        IntervalTrigger uses intervals, which are timezone-independent.
        """
        from datetime import UTC, datetime, timedelta

        from openpaw.cron.dynamic import create_interval_task

        scheduler = CronScheduler(
            workspace_path=tmp_path,
            agent_factory=mock_agent_factory,
            channels=mock_channels,
            workspace_name="test_workspace",
            timezone="Asia/Tokyo",
        )

        # Start scheduler to initialize _scheduler
        with patch("openpaw.cron.scheduler.AsyncIOScheduler") as mock_scheduler_class:
            mock_scheduler_instance = MagicMock()
            mock_scheduler_instance.start = MagicMock()
            mock_scheduler_instance.add_job = MagicMock()
            mock_scheduler_class.return_value = mock_scheduler_instance

            await scheduler.start()

            # Create a dynamic interval task
            next_run = datetime.now(UTC) + timedelta(minutes=5)
            task = create_interval_task("Recurring task", 300, next_run)

            with patch("openpaw.cron.scheduler.IntervalTrigger") as mock_interval_trigger:
                mock_trigger_instance = MagicMock()
                mock_interval_trigger.return_value = mock_trigger_instance

                scheduler.add_dynamic_job(task)

                # Verify IntervalTrigger was called without timezone (uses seconds)
                mock_interval_trigger.assert_called_once_with(seconds=task.interval_seconds)
