"""Tests for HeartbeatScheduler."""

from datetime import datetime, time
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

import pytest

from openpaw.core.config import HeartbeatConfig
from openpaw.runtime.scheduling.heartbeat import HEARTBEAT_PROMPT, HeartbeatScheduler


@pytest.fixture
def tmp_workspace(tmp_path):
    """Create a temporary workspace path."""
    workspace = tmp_path / "test_workspace"
    workspace.mkdir()
    return workspace


class TestHeartbeatConfig:
    """Test HeartbeatConfig defaults and customization."""

    def test_default_values(self, tmp_workspace) -> None:
        """Test default configuration values."""
        config = HeartbeatConfig()

        assert config.enabled is False
        assert config.interval_minutes == 30
        assert config.active_hours is None
        assert config.suppress_ok is True
        assert config.target_channel == "telegram"
        assert config.target_chat_id is None

    def test_custom_values(self, tmp_workspace) -> None:
        """Test overriding all fields."""
        config = HeartbeatConfig(
            enabled=True,
            interval_minutes=15,
            active_hours="08:00-22:00",
            suppress_ok=False,
            target_channel="slack",
            target_chat_id=123456789,
        )

        assert config.enabled is True
        assert config.interval_minutes == 15
        assert config.active_hours == "08:00-22:00"
        assert config.suppress_ok is False
        assert config.target_channel == "slack"
        assert config.target_chat_id == 123456789


class TestParseActiveHours:
    """Test active hours parsing logic."""

    def test_parse_active_hours_valid(self, tmp_workspace) -> None:
        """Test parsing valid active hours string."""
        config = HeartbeatConfig(active_hours="08:00-22:00")
        scheduler = HeartbeatScheduler(
            workspace_name="test",
            workspace_path=tmp_workspace,
            agent_factory=Mock(),
            channels={},
            config=config,
        )

        result = scheduler._active_hours

        assert result is not None
        start_time, end_time = result
        assert start_time == time(8, 0)
        assert end_time == time(22, 0)

    def test_parse_active_hours_midnight_span(self, tmp_workspace) -> None:
        """Test parsing active hours that cross midnight."""
        config = HeartbeatConfig(active_hours="22:00-06:00")
        scheduler = HeartbeatScheduler(
            workspace_name="test",
            workspace_path=tmp_workspace,
            agent_factory=Mock(),
            channels={},
            config=config,
        )

        result = scheduler._active_hours

        assert result is not None
        start_time, end_time = result
        assert start_time == time(22, 0)
        assert end_time == time(6, 0)

    def test_parse_active_hours_none(self, tmp_workspace) -> None:
        """Test parsing None active hours (always active)."""
        config = HeartbeatConfig(active_hours=None)
        scheduler = HeartbeatScheduler(
            workspace_name="test",
            workspace_path=tmp_workspace,
            agent_factory=Mock(),
            channels={},
            config=config,
        )

        result = scheduler._active_hours

        assert result is None

    def test_parse_active_hours_invalid_format(self, tmp_workspace) -> None:
        """Test invalid active hours format raises ValueError."""
        config = HeartbeatConfig(active_hours="invalid-format")

        with pytest.raises(ValueError, match="Invalid active_hours format"):
            HeartbeatScheduler(
                workspace_name="test",
                workspace_path=tmp_workspace,
                agent_factory=Mock(),
                channels={},
                config=config,
            )

    def test_parse_active_hours_missing_colon(self, tmp_workspace) -> None:
        """Test active hours without colon raises ValueError."""
        config = HeartbeatConfig(active_hours="0800-2200")

        with pytest.raises(ValueError, match="Invalid active_hours format"):
            HeartbeatScheduler(
                workspace_name="test",
                workspace_path=tmp_workspace,
                agent_factory=Mock(),
                channels={},
                config=config,
            )

    def test_parse_active_hours_invalid_time(self, tmp_workspace) -> None:
        """Test active hours with invalid time values raises ValueError."""
        config = HeartbeatConfig(active_hours="25:00-30:00")

        with pytest.raises(ValueError, match="Invalid active_hours format"):
            HeartbeatScheduler(
                workspace_name="test",
                workspace_path=tmp_workspace,
                agent_factory=Mock(),
                channels={},
                config=config,
            )


class TestIsWithinActiveHours:
    """Test active hours window checking logic."""

    @patch("openpaw.runtime.scheduling.heartbeat.workspace_now")
    def test_is_within_active_hours_inside(self, mock_workspace_now: Any, tmp_workspace) -> None:
        """Test current time within active hours window returns True."""
        mock_dt = Mock()
        mock_dt.time.return_value = time(14, 30)
        mock_workspace_now.return_value = mock_dt

        config = HeartbeatConfig(active_hours="08:00-22:00")
        scheduler = HeartbeatScheduler(
            workspace_name="test",
            workspace_path=tmp_workspace,
            agent_factory=Mock(),
            channels={},
            config=config,
        )

        result = scheduler._is_within_active_hours()

        assert result is True

    @patch("openpaw.runtime.scheduling.heartbeat.workspace_now")
    def test_is_within_active_hours_outside(self, mock_workspace_now: Any, tmp_workspace) -> None:
        """Test current time outside active hours window returns False."""
        mock_dt = Mock()
        mock_dt.time.return_value = time(2, 30)
        mock_workspace_now.return_value = mock_dt

        config = HeartbeatConfig(active_hours="08:00-22:00")
        scheduler = HeartbeatScheduler(
            workspace_name="test",
            workspace_path=tmp_workspace,
            agent_factory=Mock(),
            channels={},
            config=config,
        )

        result = scheduler._is_within_active_hours()

        assert result is False

    @patch("openpaw.runtime.scheduling.heartbeat.workspace_now")
    def test_is_within_active_hours_boundary_start(self, mock_workspace_now: Any, tmp_workspace) -> None:
        """Test current time at start boundary is included."""
        mock_dt = Mock()
        mock_dt.time.return_value = time(8, 0)
        mock_workspace_now.return_value = mock_dt

        config = HeartbeatConfig(active_hours="08:00-22:00")
        scheduler = HeartbeatScheduler(
            workspace_name="test",
            workspace_path=tmp_workspace,
            agent_factory=Mock(),
            channels={},
            config=config,
        )

        result = scheduler._is_within_active_hours()

        assert result is True

    @patch("openpaw.runtime.scheduling.heartbeat.workspace_now")
    def test_is_within_active_hours_boundary_end(self, mock_workspace_now: Any, tmp_workspace) -> None:
        """Test current time at end boundary is included."""
        mock_dt = Mock()
        mock_dt.time.return_value = time(22, 0)
        mock_workspace_now.return_value = mock_dt

        config = HeartbeatConfig(active_hours="08:00-22:00")
        scheduler = HeartbeatScheduler(
            workspace_name="test",
            workspace_path=tmp_workspace,
            agent_factory=Mock(),
            channels={},
            config=config,
        )

        result = scheduler._is_within_active_hours()

        assert result is True

    @patch("openpaw.runtime.scheduling.heartbeat.workspace_now")
    def test_is_within_active_hours_midnight_span_before(self, mock_workspace_now: Any, tmp_workspace) -> None:
        """Test midnight span with time before midnight."""
        mock_dt = Mock()
        mock_dt.time.return_value = time(23, 30)
        mock_workspace_now.return_value = mock_dt

        config = HeartbeatConfig(active_hours="22:00-06:00")
        scheduler = HeartbeatScheduler(
            workspace_name="test",
            workspace_path=tmp_workspace,
            agent_factory=Mock(),
            channels={},
            config=config,
        )

        result = scheduler._is_within_active_hours()

        assert result is True

    @patch("openpaw.runtime.scheduling.heartbeat.workspace_now")
    def test_is_within_active_hours_midnight_span_after(self, mock_workspace_now: Any, tmp_workspace) -> None:
        """Test midnight span with time after midnight."""
        mock_dt = Mock()
        mock_dt.time.return_value = time(3, 30)
        mock_workspace_now.return_value = mock_dt

        config = HeartbeatConfig(active_hours="22:00-06:00")
        scheduler = HeartbeatScheduler(
            workspace_name="test",
            workspace_path=tmp_workspace,
            agent_factory=Mock(),
            channels={},
            config=config,
        )

        result = scheduler._is_within_active_hours()

        assert result is True

    @patch("openpaw.runtime.scheduling.heartbeat.workspace_now")
    def test_is_within_active_hours_midnight_span_outside(self, mock_workspace_now: Any, tmp_workspace) -> None:
        """Test midnight span with time outside window."""
        mock_dt = Mock()
        mock_dt.time.return_value = time(12, 0)
        mock_workspace_now.return_value = mock_dt

        config = HeartbeatConfig(active_hours="22:00-06:00")
        scheduler = HeartbeatScheduler(
            workspace_name="test",
            workspace_path=tmp_workspace,
            agent_factory=Mock(),
            channels={},
            config=config,
        )

        result = scheduler._is_within_active_hours()

        assert result is False

    def test_is_within_active_hours_no_window(self, tmp_workspace) -> None:
        """Test no active hours configured returns True (always active)."""
        config = HeartbeatConfig(active_hours=None)
        scheduler = HeartbeatScheduler(
            workspace_name="test",
            workspace_path=tmp_workspace,
            agent_factory=Mock(),
            channels={},
            config=config,
        )

        result = scheduler._is_within_active_hours()

        assert result is True

    @patch("openpaw.runtime.scheduling.heartbeat.workspace_now")
    def test_is_within_active_hours_timezone_aware_inside(self, mock_workspace_now: Any, tmp_workspace) -> None:
        """Test active hours check with America/Denver timezone - inside window."""
        # Mock workspace_now to return 10:00 AM Mountain Time
        mock_dt = Mock()
        mock_dt.time.return_value = time(10, 0)
        mock_workspace_now.return_value = mock_dt

        config = HeartbeatConfig(active_hours="09:00-17:00")
        scheduler = HeartbeatScheduler(
            workspace_name="test",
            workspace_path=tmp_workspace,
            agent_factory=Mock(),
            channels={},
            config=config,
            timezone="America/Denver",
        )

        result = scheduler._is_within_active_hours()

        assert result is True
        # Verify workspace_now was called with the correct timezone
        mock_workspace_now.assert_called_once_with("America/Denver")

    @patch("openpaw.runtime.scheduling.heartbeat.workspace_now")
    def test_is_within_active_hours_timezone_aware_outside(self, mock_workspace_now: Any, tmp_workspace) -> None:
        """Test active hours check with America/Denver timezone - outside window."""
        # Mock workspace_now to return 20:00 (8:00 PM) Mountain Time
        mock_dt = Mock()
        mock_dt.time.return_value = time(20, 0)
        mock_workspace_now.return_value = mock_dt

        config = HeartbeatConfig(active_hours="09:00-17:00")
        scheduler = HeartbeatScheduler(
            workspace_name="test",
            workspace_path=tmp_workspace,
            agent_factory=Mock(),
            channels={},
            config=config,
            timezone="America/Denver",
        )

        result = scheduler._is_within_active_hours()

        assert result is False
        # Verify workspace_now was called with the correct timezone
        mock_workspace_now.assert_called_once_with("America/Denver")


class TestIsHeartbeatOk:
    """Test heartbeat response validation logic."""

    def test_is_heartbeat_ok_exact(self, tmp_workspace) -> None:
        """Test exact HEARTBEAT_OK response returns True."""
        config = HeartbeatConfig()
        scheduler = HeartbeatScheduler(
            workspace_name="test",
            workspace_path=tmp_workspace,
            agent_factory=Mock(),
            channels={},
            config=config,
        )

        result = scheduler._is_heartbeat_ok("HEARTBEAT_OK")

        assert result is True

    def test_is_heartbeat_ok_case_insensitive(self, tmp_workspace) -> None:
        """Test lowercase heartbeat_ok returns True."""
        config = HeartbeatConfig()
        scheduler = HeartbeatScheduler(
            workspace_name="test",
            workspace_path=tmp_workspace,
            agent_factory=Mock(),
            channels={},
            config=config,
        )

        result = scheduler._is_heartbeat_ok("heartbeat_ok")

        assert result is True

    def test_is_heartbeat_ok_mixed_case(self, tmp_workspace) -> None:
        """Test mixed case HeArTbEaT_oK returns True."""
        config = HeartbeatConfig()
        scheduler = HeartbeatScheduler(
            workspace_name="test",
            workspace_path=tmp_workspace,
            agent_factory=Mock(),
            channels={},
            config=config,
        )

        result = scheduler._is_heartbeat_ok("HeArTbEaT_oK")

        assert result is True

    def test_is_heartbeat_ok_embedded(self, tmp_workspace) -> None:
        """Test HEARTBEAT_OK embedded in longer response returns True."""
        config = HeartbeatConfig()
        scheduler = HeartbeatScheduler(
            workspace_name="test",
            workspace_path=tmp_workspace,
            agent_factory=Mock(),
            channels={},
            config=config,
        )

        result = scheduler._is_heartbeat_ok(
            "I reviewed all tasks. Everything looks good. HEARTBEAT_OK"
        )

        assert result is True

    def test_is_heartbeat_ok_negative(self, tmp_workspace) -> None:
        """Test response without HEARTBEAT_OK returns False."""
        config = HeartbeatConfig()
        scheduler = HeartbeatScheduler(
            workspace_name="test",
            workspace_path=tmp_workspace,
            agent_factory=Mock(),
            channels={},
            config=config,
        )

        result = scheduler._is_heartbeat_ok("I found issues that need attention")

        assert result is False

    def test_is_heartbeat_ok_empty(self, tmp_workspace) -> None:
        """Test empty response returns False."""
        config = HeartbeatConfig()
        scheduler = HeartbeatScheduler(
            workspace_name="test",
            workspace_path=tmp_workspace,
            agent_factory=Mock(),
            channels={},
            config=config,
        )

        result = scheduler._is_heartbeat_ok("")

        assert result is False

    def test_is_heartbeat_ok_partial_match(self, tmp_workspace) -> None:
        """Test partial match like 'HEARTBEAT' alone returns False."""
        config = HeartbeatConfig()
        scheduler = HeartbeatScheduler(
            workspace_name="test",
            workspace_path=tmp_workspace,
            agent_factory=Mock(),
            channels={},
            config=config,
        )

        result = scheduler._is_heartbeat_ok("HEARTBEAT")

        assert result is False


class TestBuildHeartbeatPrompt:
    """Test heartbeat prompt generation."""

    @patch("openpaw.runtime.scheduling.heartbeat.workspace_now")
    def test_build_heartbeat_prompt_includes_timestamp(self, mock_workspace_now: Any, tmp_workspace) -> None:
        """Test generated prompt includes current timestamp."""
        fixed_time = datetime(2026, 2, 6, 14, 30, 0)
        mock_workspace_now.return_value = fixed_time

        config = HeartbeatConfig()
        scheduler = HeartbeatScheduler(
            workspace_name="test",
            workspace_path=tmp_workspace,
            agent_factory=Mock(),
            channels={},
            config=config,
        )

        result = scheduler._build_heartbeat_prompt()

        assert "2026-02-06T14:30:00" in result

    def test_build_heartbeat_prompt_content(self, tmp_workspace) -> None:
        """Test prompt contains expected content."""
        config = HeartbeatConfig()
        scheduler = HeartbeatScheduler(
            workspace_name="test",
            workspace_path=tmp_workspace,
            agent_factory=Mock(),
            channels={},
            config=config,
        )

        result = scheduler._build_heartbeat_prompt()

        assert "[HEARTBEAT CHECK" in result
        assert "HEARTBEAT.md" in result
        assert "HEARTBEAT_OK" in result
        assert "Time-sensitive" in result

    def test_build_heartbeat_prompt_matches_template(self, tmp_workspace) -> None:
        """Test prompt uses HEARTBEAT_PROMPT template."""
        config = HeartbeatConfig()
        scheduler = HeartbeatScheduler(
            workspace_name="test",
            workspace_path=tmp_workspace,
            agent_factory=Mock(),
            channels={},
            config=config,
        )

        result = scheduler._build_heartbeat_prompt()

        # Should contain key sections from template
        assert "Check your HEARTBEAT.md file" in result
        assert "If nothing requires immediate attention" in result


class TestHeartbeatSchedulerInitialization:
    """Test HeartbeatScheduler initialization."""

    def test_initialization_stores_config(self, tmp_workspace) -> None:
        """Test initialization stores configuration."""
        config = HeartbeatConfig(
            enabled=True,
            interval_minutes=15,
            target_chat_id=123456,
        )
        agent_factory = Mock()
        channels = {"telegram": Mock()}

        scheduler = HeartbeatScheduler(
            workspace_name="gilfoyle",
            workspace_path=tmp_workspace,
            agent_factory=agent_factory,
            channels=channels,
            config=config,
        )

        assert scheduler.workspace_name == "gilfoyle"
        assert scheduler.agent_factory is agent_factory
        assert scheduler.channels is channels
        assert scheduler.config is config
        assert scheduler._scheduler is None
        assert scheduler._job is None

    def test_initialization_parses_active_hours(self, tmp_workspace) -> None:
        """Test initialization parses active hours at init time."""
        config = HeartbeatConfig(active_hours="09:00-17:00")

        scheduler = HeartbeatScheduler(
            workspace_name="test",
            workspace_path=tmp_workspace,
            agent_factory=Mock(),
            channels={},
            config=config,
        )

        assert scheduler._active_hours is not None
        start, end = scheduler._active_hours
        assert start == time(9, 0)
        assert end == time(17, 0)


@pytest.mark.asyncio
class TestHeartbeatSchedulerStart:
    """Test HeartbeatScheduler start behavior."""

    async def test_start_disabled_config(self, tmp_workspace) -> None:
        """Test start does nothing when heartbeat is disabled."""
        config = HeartbeatConfig(enabled=False)
        scheduler = HeartbeatScheduler(
            workspace_name="test",
            workspace_path=tmp_workspace,
            agent_factory=Mock(),
            channels={},
            config=config,
        )

        await scheduler.start()

        assert scheduler._scheduler is None
        assert scheduler._job is None

    @patch("openpaw.runtime.scheduling.heartbeat.AsyncIOScheduler")
    async def test_start_enabled_creates_scheduler(self, mock_scheduler_class: Any, tmp_workspace) -> None:
        """Test start creates AsyncIOScheduler when enabled."""
        mock_scheduler_instance = Mock()
        mock_scheduler_class.return_value = mock_scheduler_instance

        config = HeartbeatConfig(enabled=True, interval_minutes=10)
        scheduler = HeartbeatScheduler(
            workspace_name="test",
            workspace_path=tmp_workspace,
            agent_factory=Mock(),
            channels={},
            config=config,
        )

        await scheduler.start()

        # Verify scheduler was created and started
        mock_scheduler_class.assert_called_once()
        mock_scheduler_instance.start.assert_called_once()
        assert scheduler._scheduler is mock_scheduler_instance

    @patch("openpaw.runtime.scheduling.heartbeat.AsyncIOScheduler")
    async def test_start_configures_interval_trigger(self, mock_scheduler_class: Any, tmp_workspace) -> None:
        """Test start configures correct interval trigger."""
        # Create HEARTBEAT.md to prevent skip
        (tmp_workspace / "HEARTBEAT.md").write_text("# Heartbeat\nSome content here")

        mock_scheduler_instance = Mock()
        mock_scheduler_class.return_value = mock_scheduler_instance

        config = HeartbeatConfig(enabled=True, interval_minutes=15)
        scheduler = HeartbeatScheduler(
            workspace_name="gilfoyle",
            workspace_path=tmp_workspace,
            agent_factory=Mock(),
            channels={},
            config=config,
        )

        await scheduler.start()

        # Verify add_job was called with correct parameters
        mock_scheduler_instance.add_job.assert_called_once()
        call_kwargs = mock_scheduler_instance.add_job.call_args[1]

        assert call_kwargs["func"] == scheduler._run_heartbeat
        assert call_kwargs["id"] == "heartbeat_gilfoyle"
        assert call_kwargs["name"] == "Heartbeat: gilfoyle"
        assert call_kwargs["replace_existing"] is True


@pytest.mark.asyncio
class TestHeartbeatSchedulerStop:
    """Test HeartbeatScheduler stop behavior."""

    async def test_stop_no_scheduler(self, tmp_workspace) -> None:
        """Test stop does nothing when scheduler not started."""
        config = HeartbeatConfig()
        scheduler = HeartbeatScheduler(
            workspace_name="test",
            workspace_path=tmp_workspace,
            agent_factory=Mock(),
            channels={},
            config=config,
        )

        # Should not raise an exception
        await scheduler.stop()

    async def test_stop_shutdown_scheduler(self, tmp_workspace) -> None:
        """Test stop shuts down running scheduler."""
        mock_scheduler = Mock()
        mock_scheduler.running = True

        config = HeartbeatConfig()
        scheduler = HeartbeatScheduler(
            workspace_name="test",
            workspace_path=tmp_workspace,
            agent_factory=Mock(),
            channels={},
            config=config,
        )
        scheduler._scheduler = mock_scheduler

        await scheduler.stop()

        mock_scheduler.shutdown.assert_called_once_with(wait=True)

    async def test_stop_non_running_scheduler(self, tmp_workspace) -> None:
        """Test stop does nothing if scheduler not running."""
        mock_scheduler = Mock()
        mock_scheduler.running = False

        config = HeartbeatConfig()
        scheduler = HeartbeatScheduler(
            workspace_name="test",
            workspace_path=tmp_workspace,
            agent_factory=Mock(),
            channels={},
            config=config,
        )
        scheduler._scheduler = mock_scheduler

        await scheduler.stop()

        mock_scheduler.shutdown.assert_not_called()


@pytest.mark.asyncio
class TestRunHeartbeat:
    """Test heartbeat execution logic."""

    @patch("openpaw.runtime.scheduling.heartbeat.workspace_now")
    async def test_run_heartbeat_skips_outside_active_hours(self, mock_workspace_now: Any, tmp_workspace) -> None:
        """Test heartbeat skipped when outside active hours."""
        mock_dt = Mock()
        mock_dt.time.return_value = time(2, 0)
        mock_workspace_now.return_value = mock_dt

        mock_agent_factory = Mock()
        config = HeartbeatConfig(enabled=True, active_hours="08:00-22:00")
        scheduler = HeartbeatScheduler(
            workspace_name="test",
            workspace_path=tmp_workspace,
            agent_factory=mock_agent_factory,
            channels={},
            config=config,
        )

        await scheduler._run_heartbeat()

        # Agent factory should not be called
        mock_agent_factory.assert_not_called()

    @patch("openpaw.runtime.scheduling.heartbeat.workspace_now")
    async def test_run_heartbeat_executes_within_active_hours(self, mock_workspace_now: Any, tmp_workspace) -> None:
        """Test heartbeat executes when within active hours."""
        # Create HEARTBEAT.md to prevent skip
        (tmp_workspace / "HEARTBEAT.md").write_text("# Heartbeat\nSome content here")

        mock_dt = Mock()
        mock_dt.time.return_value = time(14, 0)
        mock_workspace_now.return_value = mock_dt

        mock_agent_runner = AsyncMock()
        mock_agent_runner.run.return_value = "HEARTBEAT_OK"
        mock_agent_factory = Mock(return_value=mock_agent_runner)

        config = HeartbeatConfig(
            enabled=True,
            active_hours="08:00-22:00",
            suppress_ok=True,
        )
        scheduler = HeartbeatScheduler(
            workspace_name="test",
            workspace_path=tmp_workspace,
            agent_factory=mock_agent_factory,
            channels={},
            config=config,
        )

        await scheduler._run_heartbeat()

        # Agent factory should be called
        mock_agent_factory.assert_called_once()
        mock_agent_runner.run.assert_called_once()

    async def test_run_heartbeat_passes_prompt_to_agent(self, tmp_workspace) -> None:
        """Test heartbeat passes generated prompt to agent."""
        # Create HEARTBEAT.md to prevent skip
        (tmp_workspace / "HEARTBEAT.md").write_text("# Heartbeat\nSome content here")

        mock_agent_runner = AsyncMock()
        mock_agent_runner.run.return_value = "HEARTBEAT_OK"
        mock_agent_factory = Mock(return_value=mock_agent_runner)

        config = HeartbeatConfig(enabled=True, suppress_ok=True)
        scheduler = HeartbeatScheduler(
            workspace_name="test",
            workspace_path=tmp_workspace,
            agent_factory=mock_agent_factory,
            channels={},
            config=config,
        )

        await scheduler._run_heartbeat()

        # Verify run was called with heartbeat prompt
        mock_agent_runner.run.assert_called_once()
        call_args = mock_agent_runner.run.call_args
        prompt = call_args[1]["message"]

        assert "[HEARTBEAT CHECK" in prompt
        assert "HEARTBEAT.md" in prompt

    async def test_run_heartbeat_suppresses_ok_response(self, tmp_workspace) -> None:
        """Test HEARTBEAT_OK response is suppressed from channel."""
        mock_agent_runner = AsyncMock()
        mock_agent_runner.run.return_value = "HEARTBEAT_OK"
        mock_agent_factory = Mock(return_value=mock_agent_runner)

        mock_channel = AsyncMock()
        channels = {"telegram": mock_channel}

        config = HeartbeatConfig(
            enabled=True,
            suppress_ok=True,
            target_channel="telegram",
        )
        scheduler = HeartbeatScheduler(
            workspace_name="test",
            workspace_path=tmp_workspace,
            agent_factory=mock_agent_factory,
            channels=channels,
            config=config,
        )

        await scheduler._run_heartbeat()

        # Channel send_message should not be called
        mock_channel.send_message.assert_not_called()

    async def test_run_heartbeat_sends_non_ok_response(self, tmp_workspace) -> None:
        """Test non-OK response is sent to channel."""
        # Create HEARTBEAT.md to prevent skip
        (tmp_workspace / "HEARTBEAT.md").write_text("# Heartbeat\nSome content here")

        response_text = "Found issues requiring attention"
        mock_agent_runner = AsyncMock()
        mock_agent_runner.run.return_value = response_text
        mock_agent_factory = Mock(return_value=mock_agent_runner)

        mock_channel = Mock()
        mock_channel.build_session_key = Mock(return_value="telegram_123456")
        mock_channel.send_message = AsyncMock()
        channels = {"telegram": mock_channel}

        config = HeartbeatConfig(
            enabled=True,
            suppress_ok=True,
            target_channel="telegram",
            target_chat_id=123456,
        )
        scheduler = HeartbeatScheduler(
            workspace_name="test",
            workspace_path=tmp_workspace,
            agent_factory=mock_agent_factory,
            channels=channels,
            config=config,
        )

        await scheduler._run_heartbeat()

        # Channel send_message should be called
        mock_channel.build_session_key.assert_called_once_with(123456)
        mock_channel.send_message.assert_called_once_with(
            session_key="telegram_123456",
            content=response_text,
        )

    async def test_run_heartbeat_sends_ok_when_not_suppressed(self, tmp_workspace) -> None:
        """Test HEARTBEAT_OK is sent when suppress_ok=False."""
        # Create HEARTBEAT.md to prevent skip
        (tmp_workspace / "HEARTBEAT.md").write_text("# Heartbeat\nSome content here")

        mock_agent_runner = AsyncMock()
        mock_agent_runner.run.return_value = "HEARTBEAT_OK"
        mock_agent_factory = Mock(return_value=mock_agent_runner)

        mock_channel = Mock()
        mock_channel.build_session_key = Mock(return_value="telegram_789")
        mock_channel.send_message = AsyncMock()
        channels = {"telegram": mock_channel}

        config = HeartbeatConfig(
            enabled=True,
            suppress_ok=False,  # Don't suppress
            target_channel="telegram",
            target_chat_id=789,
        )
        scheduler = HeartbeatScheduler(
            workspace_name="test",
            workspace_path=tmp_workspace,
            agent_factory=mock_agent_factory,
            channels=channels,
            config=config,
        )

        await scheduler._run_heartbeat()

        # Channel send_message should be called
        mock_channel.send_message.assert_called_once_with(
            session_key="telegram_789",
            content="HEARTBEAT_OK",
        )

    async def test_run_heartbeat_logs_error_when_channel_not_found(self, tmp_workspace) -> None:
        """Test error logged when target channel not found."""
        mock_agent_runner = AsyncMock()
        mock_agent_runner.run.return_value = "Important alert"
        mock_agent_factory = Mock(return_value=mock_agent_runner)

        channels: dict[str, Any] = {}  # No channels configured

        config = HeartbeatConfig(
            enabled=True,
            target_channel="telegram",
            target_chat_id=123,
        )
        scheduler = HeartbeatScheduler(
            workspace_name="test",
            workspace_path=tmp_workspace,
            agent_factory=mock_agent_factory,
            channels=channels,
            config=config,
        )

        # Should not raise exception
        await scheduler._run_heartbeat()

    async def test_run_heartbeat_warns_when_no_routing_config(self, tmp_workspace) -> None:
        """Test warning when response generated but no routing configured."""
        mock_agent_runner = AsyncMock()
        mock_agent_runner.run.return_value = "Important message"
        mock_agent_factory = Mock(return_value=mock_agent_runner)

        mock_channel = Mock()
        channels = {"telegram": mock_channel}

        config = HeartbeatConfig(
            enabled=True,
            target_channel="telegram",
            target_chat_id=None,  # No chat ID configured
        )
        scheduler = HeartbeatScheduler(
            workspace_name="test",
            workspace_path=tmp_workspace,
            agent_factory=mock_agent_factory,
            channels=channels,
            config=config,
        )

        # Should not raise exception, just log warning
        await scheduler._run_heartbeat()

    async def test_run_heartbeat_handles_agent_exception(self, tmp_workspace) -> None:
        """Test heartbeat handles agent execution exceptions gracefully."""
        mock_agent_runner = AsyncMock()
        mock_agent_runner.run.side_effect = Exception("Agent crashed")
        mock_agent_factory = Mock(return_value=mock_agent_runner)

        config = HeartbeatConfig(enabled=True)
        scheduler = HeartbeatScheduler(
            workspace_name="test",
            workspace_path=tmp_workspace,
            agent_factory=mock_agent_factory,
            channels={},
            config=config,
        )

        # Should not raise exception
        await scheduler._run_heartbeat()

    async def test_run_heartbeat_no_active_hours_always_runs(self, tmp_workspace) -> None:
        """Test heartbeat always runs when no active hours set."""
        # Create HEARTBEAT.md to prevent skip
        (tmp_workspace / "HEARTBEAT.md").write_text("# Heartbeat\nSome content here")

        mock_agent_runner = AsyncMock()
        mock_agent_runner.run.return_value = "HEARTBEAT_OK"
        mock_agent_factory = Mock(return_value=mock_agent_runner)

        config = HeartbeatConfig(
            enabled=True,
            active_hours=None,  # Always active
            suppress_ok=True,
        )
        scheduler = HeartbeatScheduler(
            workspace_name="test",
            workspace_path=tmp_workspace,
            agent_factory=mock_agent_factory,
            channels={},
            config=config,
        )

        await scheduler._run_heartbeat()

        # Should execute regardless of current time
        mock_agent_factory.assert_called_once()
        mock_agent_runner.run.assert_called_once()


class TestHeartbeatPromptTemplate:
    """Test HEARTBEAT_PROMPT template constant."""

    def test_prompt_template_has_timestamp_placeholder(self, tmp_workspace) -> None:
        """Test prompt template includes timestamp placeholder."""
        assert "{timestamp}" in HEARTBEAT_PROMPT.template

    def test_prompt_template_has_key_instructions(self, tmp_workspace) -> None:
        """Test prompt template includes key instructions."""
        assert "HEARTBEAT.md" in HEARTBEAT_PROMPT.template
        assert "HEARTBEAT_OK" in HEARTBEAT_PROMPT.template
        assert "Time-sensitive" in HEARTBEAT_PROMPT.template
        assert "pending" in HEARTBEAT_PROMPT.template

    def test_prompt_template_can_be_formatted(self, tmp_workspace) -> None:
        """Test prompt template can be formatted with timestamp."""
        formatted = HEARTBEAT_PROMPT.format(timestamp="2026-02-06T14:30:00")

        assert "[HEARTBEAT CHECK - 2026-02-06T14:30:00]" in formatted
        assert "{timestamp}" not in formatted
