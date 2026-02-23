"""Tests for session persistence + delivery routing feature."""

import json
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from openpaw.agent.metrics import InvocationMetrics
from openpaw.agent.session_logger import SessionLogger, SessionRecord
from openpaw.core.config.models import HeartbeatConfig
from openpaw.core.prompts.system_events import (
    CRON_RESULT_TEMPLATE,
    CRON_RESULT_TRUNCATED_TEMPLATE,
    HEARTBEAT_RESULT_TEMPLATE,
    HEARTBEAT_RESULT_TRUNCATED_TEMPLATE,
    INJECTION_TRUNCATION_LIMIT,
)
from openpaw.model.cron import CronDefinition, CronOutputConfig
from openpaw.model.subagent import SubAgentRequest
from openpaw.runtime.scheduling.cron import CronScheduler
from openpaw.runtime.scheduling.heartbeat import HeartbeatScheduler
from openpaw.runtime.subagent.runner import SubAgentRunner
from openpaw.stores.subagent import SubAgentStore

# --- SessionLogger Tests ---


class TestSessionLogger:
    """Tests for SessionLogger utility."""

    def test_session_logger_creates_directory(self, tmp_path):
        """Verify memory/sessions/{type}/ is created."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        logger = SessionLogger(workspace, session_type="heartbeat")
        logger._ensure_dir()

        sessions_dir = workspace / "memory" / "sessions" / "heartbeat"
        assert sessions_dir.exists()
        assert sessions_dir.is_dir()

    def test_session_logger_write_session(self, tmp_path):
        """Write a complete session, read back JSONL, verify 3 records."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        logger = SessionLogger(workspace, session_type="heartbeat")
        metrics = InvocationMetrics(
            input_tokens=100, output_tokens=50, total_tokens=150, llm_calls=1
        )

        relative_path = logger.write_session(
            name="test_session",
            prompt="Test prompt",
            response="Test response",
            tools_used=["brave_search", "read_file"],
            metrics=metrics,
            duration_ms=1234.5,
        )

        # Verify path is relative
        assert not relative_path.startswith("/")
        assert relative_path.startswith("memory/sessions/heartbeat/")

        # Read back and verify 3 records
        full_path = workspace / relative_path
        assert full_path.exists()

        with full_path.open() as f:
            lines = f.readlines()

        assert len(lines) == 3

        # Parse records
        record1 = json.loads(lines[0])
        record2 = json.loads(lines[1])
        record3 = json.loads(lines[2])

        # Verify prompt record
        assert record1["type"] == "prompt"
        assert record1["content"] == "Test prompt"
        assert "timestamp" in record1

        # Verify response record
        assert record2["type"] == "response"
        assert record2["content"] == "Test response"

        # Verify metadata record
        assert record3["type"] == "metadata"
        assert record3["tools_used"] == ["brave_search", "read_file"]
        assert record3["metrics"]["input_tokens"] == 100
        assert record3["metrics"]["output_tokens"] == 50
        assert record3["metrics"]["total_tokens"] == 150
        assert record3["metrics"]["llm_calls"] == 1
        assert record3["duration_ms"] == 1234.5

    def test_session_logger_returns_relative_path(self, tmp_path):
        """Verify returned path is relative to workspace root."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        logger = SessionLogger(workspace, session_type="cron")
        relative_path = logger.write_session(
            name="test",
            prompt="prompt",
            response="response",
            tools_used=[],
            metrics=None,
            duration_ms=100.0,
        )

        # Should be relative path
        assert not relative_path.startswith("/")
        assert relative_path.startswith("memory/sessions/cron/")

        # Should be readable from workspace root
        full_path = workspace / relative_path
        assert full_path.exists()

    def test_session_logger_with_metrics(self, tmp_path):
        """Verify metrics are serialized correctly in metadata record."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        logger = SessionLogger(workspace, session_type="subagent")
        metrics = InvocationMetrics(
            input_tokens=200, output_tokens=100, total_tokens=300, llm_calls=2
        )

        relative_path = logger.write_session(
            name="with_metrics",
            prompt="prompt",
            response="response",
            tools_used=["tool1"],
            metrics=metrics,
            duration_ms=500.0,
        )

        # Read metadata record (3rd line)
        full_path = workspace / relative_path
        with full_path.open() as f:
            lines = f.readlines()

        metadata = json.loads(lines[2])
        assert metadata["metrics"]["input_tokens"] == 200
        assert metadata["metrics"]["output_tokens"] == 100
        assert metadata["metrics"]["total_tokens"] == 300
        assert metadata["metrics"]["llm_calls"] == 2

    def test_session_logger_without_metrics(self, tmp_path):
        """Verify None metrics produces null in metadata record."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        logger = SessionLogger(workspace, session_type="heartbeat")
        relative_path = logger.write_session(
            name="no_metrics",
            prompt="prompt",
            response="response",
            tools_used=[],
            metrics=None,
            duration_ms=100.0,
        )

        # Read metadata record
        full_path = workspace / relative_path
        with full_path.open() as f:
            lines = f.readlines()

        metadata = json.loads(lines[2])
        assert "metrics" not in metadata  # None metrics are omitted

    def test_session_logger_write_record_no_session_raises(self, tmp_path):
        """Verify RuntimeError if no create_session() first."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        logger = SessionLogger(workspace, session_type="heartbeat")

        record = SessionRecord(type="prompt", timestamp=datetime.now().isoformat(), content="test")

        with pytest.raises(RuntimeError, match="No active session"):
            logger.write_record(record)

    def test_session_logger_handles_io_error(self, tmp_path):
        """Mock file open to raise OSError, verify no crash."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        logger = SessionLogger(workspace, session_type="heartbeat")
        logger.create_session("test")

        record = SessionRecord(type="prompt", timestamp=datetime.now().isoformat(), content="test")

        # Mock open to raise OSError
        with patch("builtins.open", side_effect=OSError("Disk full")):
            # Should not crash, just log warning
            logger.write_record(record)


# --- Config Model Tests ---


class TestConfigModels:
    """Tests for HeartbeatConfig and CronOutputConfig delivery field."""

    def test_heartbeat_config_delivery_default(self):
        """Verify default is 'channel'."""
        config = HeartbeatConfig()
        assert config.delivery == "channel"

    def test_heartbeat_config_delivery_values(self):
        """Test 'channel', 'agent', 'both' all valid."""
        config1 = HeartbeatConfig(delivery="channel")
        assert config1.delivery == "channel"

        config2 = HeartbeatConfig(delivery="agent")
        assert config2.delivery == "agent"

        config3 = HeartbeatConfig(delivery="both")
        assert config3.delivery == "both"

    def test_cron_output_delivery_default(self):
        """Verify default is 'channel'."""
        output = CronOutputConfig(channel="telegram", chat_id=123)
        assert output.delivery == "channel"

    def test_cron_output_delivery_validator(self):
        """Verify 'invalid' raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            CronOutputConfig(channel="telegram", chat_id=123, delivery="invalid")

        assert "Invalid delivery mode" in str(exc_info.value)


# --- System Event Template Tests ---


class TestSystemEventTemplates:
    """Tests for system event template formatting."""

    def test_heartbeat_result_template_format(self):
        """Verify template formats correctly."""
        result = HEARTBEAT_RESULT_TEMPLATE.format(
            output="Test output", session_path="memory/sessions/heartbeat/test.jsonl"
        )
        assert "[SYSTEM] Heartbeat completed." in result
        assert "Test output" in result
        assert "memory/sessions/heartbeat/test.jsonl" in result
        assert "Review and take action if needed." in result

    def test_heartbeat_result_truncated_template_format(self):
        """Verify truncated template includes read_file hint."""
        result = HEARTBEAT_RESULT_TRUNCATED_TEMPLATE.format(
            output="Truncated output", session_path="memory/sessions/heartbeat/test.jsonl"
        )
        assert "[SYSTEM] Heartbeat completed (truncated)." in result
        assert "Truncated output" in result
        assert 'Use read_file("memory/sessions/heartbeat/test.jsonl")' in result

    def test_cron_result_template_format(self):
        """Verify template formats with cron_name."""
        result = CRON_RESULT_TEMPLATE.format(
            cron_name="daily-sync",
            output="Sync complete",
            session_path="memory/sessions/cron/daily-sync.jsonl",
        )
        assert "[SYSTEM] Scheduled task 'daily-sync' completed." in result
        assert "Sync complete" in result
        assert "memory/sessions/cron/daily-sync.jsonl" in result

    def test_cron_result_truncated_template_format(self):
        """Same but truncated."""
        result = CRON_RESULT_TRUNCATED_TEMPLATE.format(
            cron_name="daily-sync",
            output="Truncated",
            session_path="memory/sessions/cron/daily-sync.jsonl",
        )
        assert "[SYSTEM] Scheduled task 'daily-sync' completed (truncated)." in result
        assert 'Use read_file("memory/sessions/cron/daily-sync.jsonl")' in result

    def test_injection_truncation_limit_value(self):
        """Verify it's 2000."""
        assert INJECTION_TRUNCATION_LIMIT == 2000


# --- HeartbeatScheduler Delivery Routing Tests ---


class TestHeartbeatDeliveryRouting:
    """Tests for HeartbeatScheduler delivery routing."""

    @pytest.fixture
    def workspace(self, tmp_path):
        """Create temporary workspace."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        # Create HEARTBEAT.md with content to avoid pre-flight skip
        (workspace / "HEARTBEAT.md").write_text("# Active heartbeat\nSome content here")
        return workspace

    @pytest.fixture
    def mock_agent_runner(self):
        """Create mock agent runner."""
        runner = MagicMock()
        runner.run = AsyncMock(return_value="Test response")
        runner.last_metrics = InvocationMetrics(
            input_tokens=100, output_tokens=50, total_tokens=150, llm_calls=1
        )
        runner.last_tools_used = ["brave_search"]
        return runner

    @pytest.fixture
    def mock_channel(self):
        """Create mock channel."""
        channel = MagicMock()
        channel.send_message = AsyncMock()
        channel.build_session_key = MagicMock(return_value="telegram:123456")
        return channel

    @pytest.mark.asyncio
    async def test_heartbeat_delivery_channel_only(self, workspace, mock_agent_runner, mock_channel):
        """delivery='channel': channel.send_message called, result_callback NOT called."""
        config = HeartbeatConfig(
            enabled=True,
            interval_minutes=30,
            target_channel="telegram",
            target_chat_id=123456,
            delivery="channel",
        )

        result_callback = AsyncMock()
        session_logger = MagicMock()
        session_logger.write_session = MagicMock(return_value="memory/sessions/heartbeat/test.jsonl")

        scheduler = HeartbeatScheduler(
            workspace_name="test",
            workspace_path=workspace,
            agent_factory=lambda: mock_agent_runner,
            channels={"telegram": mock_channel},
            config=config,
            result_callback=result_callback,
            session_logger=session_logger,
        )

        # Mock _should_skip_heartbeat to avoid pre-flight skip
        with patch.object(scheduler, "_should_skip_heartbeat", return_value=(False, "test", None, 0)):
            await scheduler._run_heartbeat()

        # Channel should be called
        mock_channel.send_message.assert_called_once()
        assert mock_channel.send_message.call_args[1]["content"] == "Test response"

        # Result callback should NOT be called
        result_callback.assert_not_called()

    @pytest.mark.asyncio
    async def test_heartbeat_delivery_agent_only(self, workspace, mock_agent_runner, mock_channel):
        """delivery='agent': channel.send_message NOT called, result_callback called with template content."""
        config = HeartbeatConfig(
            enabled=True,
            interval_minutes=30,
            target_channel="telegram",
            target_chat_id=123456,
            delivery="agent",
        )

        result_callback = AsyncMock()
        session_logger = MagicMock()
        session_logger.write_session = MagicMock(return_value="memory/sessions/heartbeat/test.jsonl")

        scheduler = HeartbeatScheduler(
            workspace_name="test",
            workspace_path=workspace,
            agent_factory=lambda: mock_agent_runner,
            channels={"telegram": mock_channel},
            config=config,
            result_callback=result_callback,
            session_logger=session_logger,
        )

        with patch.object(scheduler, "_should_skip_heartbeat", return_value=(False, "test", None, 0)):
            await scheduler._run_heartbeat()

        # Channel should NOT be called
        mock_channel.send_message.assert_not_called()

        # Result callback should be called
        result_callback.assert_called_once()
        call_args = result_callback.call_args[0]
        assert call_args[0] == "telegram:123456"  # session_key
        assert "[SYSTEM] Heartbeat completed." in call_args[1]
        assert "Test response" in call_args[1]

    @pytest.mark.asyncio
    async def test_heartbeat_delivery_both(self, workspace, mock_agent_runner, mock_channel):
        """delivery='both': both called."""
        config = HeartbeatConfig(
            enabled=True,
            interval_minutes=30,
            target_channel="telegram",
            target_chat_id=123456,
            delivery="both",
        )

        result_callback = AsyncMock()
        session_logger = MagicMock()
        session_logger.write_session = MagicMock(return_value="memory/sessions/heartbeat/test.jsonl")

        scheduler = HeartbeatScheduler(
            workspace_name="test",
            workspace_path=workspace,
            agent_factory=lambda: mock_agent_runner,
            channels={"telegram": mock_channel},
            config=config,
            result_callback=result_callback,
            session_logger=session_logger,
        )

        with patch.object(scheduler, "_should_skip_heartbeat", return_value=(False, "test", None, 0)):
            await scheduler._run_heartbeat()

        # Both should be called
        mock_channel.send_message.assert_called_once()
        result_callback.assert_called_once()

    @pytest.mark.asyncio
    async def test_heartbeat_ok_suppresses_all_delivery(self, workspace, mock_agent_runner, mock_channel):
        """HEARTBEAT_OK: neither channel nor callback called (regardless of delivery mode)."""
        # Set response to HEARTBEAT_OK
        mock_agent_runner.run = AsyncMock(return_value="HEARTBEAT_OK")

        config = HeartbeatConfig(
            enabled=True,
            interval_minutes=30,
            target_channel="telegram",
            target_chat_id=123456,
            delivery="both",  # Even with 'both', should suppress
            suppress_ok=True,
        )

        result_callback = AsyncMock()
        session_logger = MagicMock()
        session_logger.write_session = MagicMock(return_value="memory/sessions/heartbeat/test.jsonl")

        scheduler = HeartbeatScheduler(
            workspace_name="test",
            workspace_path=workspace,
            agent_factory=lambda: mock_agent_runner,
            channels={"telegram": mock_channel},
            config=config,
            result_callback=result_callback,
            session_logger=session_logger,
        )

        with patch.object(scheduler, "_should_skip_heartbeat", return_value=(False, "test", None, 0)):
            await scheduler._run_heartbeat()

        # Neither should be called
        mock_channel.send_message.assert_not_called()
        result_callback.assert_not_called()

    @pytest.mark.asyncio
    async def test_heartbeat_session_log_written(self, workspace, mock_agent_runner, mock_channel):
        """session_logger.write_session called after run."""
        config = HeartbeatConfig(
            enabled=True,
            interval_minutes=30,
            target_channel="telegram",
            target_chat_id=123456,
            delivery="channel",
        )

        session_logger = MagicMock()
        session_logger.write_session = MagicMock(return_value="memory/sessions/heartbeat/test.jsonl")

        scheduler = HeartbeatScheduler(
            workspace_name="test",
            workspace_path=workspace,
            agent_factory=lambda: mock_agent_runner,
            channels={"telegram": mock_channel},
            config=config,
            session_logger=session_logger,
        )

        with patch.object(scheduler, "_should_skip_heartbeat", return_value=(False, "test", None, 0)):
            await scheduler._run_heartbeat()

        # Session logger should be called
        session_logger.write_session.assert_called_once()
        call_kwargs = session_logger.write_session.call_args[1]
        assert call_kwargs["name"] == "heartbeat"
        assert call_kwargs["response"] == "Test response"
        assert call_kwargs["metrics"] == mock_agent_runner.last_metrics

    @pytest.mark.asyncio
    async def test_heartbeat_session_log_written_on_heartbeat_ok(
        self, workspace, mock_agent_runner, mock_channel
    ):
        """Session log written even for HEARTBEAT_OK."""
        mock_agent_runner.run = AsyncMock(return_value="HEARTBEAT_OK")

        config = HeartbeatConfig(
            enabled=True,
            interval_minutes=30,
            target_channel="telegram",
            target_chat_id=123456,
            suppress_ok=True,
        )

        session_logger = MagicMock()
        session_logger.write_session = MagicMock(return_value="memory/sessions/heartbeat/test.jsonl")

        scheduler = HeartbeatScheduler(
            workspace_name="test",
            workspace_path=workspace,
            agent_factory=lambda: mock_agent_runner,
            channels={"telegram": mock_channel},
            config=config,
            session_logger=session_logger,
        )

        with patch.object(scheduler, "_should_skip_heartbeat", return_value=(False, "test", None, 0)):
            await scheduler._run_heartbeat()

        # Session log should still be written
        session_logger.write_session.assert_called_once()
        call_kwargs = session_logger.write_session.call_args[1]
        assert call_kwargs["response"] == "HEARTBEAT_OK"


# --- CronScheduler Delivery Routing Tests ---


class TestCronDeliveryRouting:
    """Tests for CronScheduler delivery routing."""

    @pytest.fixture
    def workspace(self, tmp_path):
        """Create temporary workspace."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        return workspace

    @pytest.fixture
    def mock_agent_runner(self):
        """Create mock agent runner."""
        runner = MagicMock()
        runner.run = AsyncMock(return_value="Cron response")
        runner.last_metrics = InvocationMetrics(
            input_tokens=80, output_tokens=40, total_tokens=120, llm_calls=1
        )
        runner.last_tools_used = ["read_file"]
        return runner

    @pytest.fixture
    def mock_channel(self):
        """Create mock channel."""
        channel = MagicMock()
        channel.send_message = AsyncMock()
        channel.build_session_key = MagicMock(return_value="telegram:789")
        return channel

    @pytest.mark.asyncio
    async def test_cron_delivery_channel_only(self, workspace, mock_agent_runner, mock_channel):
        """delivery='channel': send_message called, result_callback NOT called."""
        cron = CronDefinition(
            name="test-cron",
            schedule="0 9 * * *",
            prompt="Test prompt",
            output=CronOutputConfig(channel="telegram", chat_id=789, delivery="channel"),
        )

        result_callback = AsyncMock()
        session_logger = MagicMock()
        session_logger.write_session = MagicMock(return_value="memory/sessions/cron/test-cron.jsonl")

        scheduler = CronScheduler(
            workspace_path=workspace,
            agent_factory=lambda: mock_agent_runner,
            channels={"telegram": mock_channel},
            workspace_name="test",
            result_callback=result_callback,
            session_logger=session_logger,
        )

        await scheduler._execute_cron(cron)

        # Channel should be called
        mock_channel.send_message.assert_called_once()
        assert mock_channel.send_message.call_args[1]["content"] == "Cron response"

        # Result callback should NOT be called
        result_callback.assert_not_called()

    @pytest.mark.asyncio
    async def test_cron_delivery_agent_only(self, workspace, mock_agent_runner, mock_channel):
        """delivery='agent': send_message NOT called, result_callback called."""
        cron = CronDefinition(
            name="test-cron",
            schedule="0 9 * * *",
            prompt="Test prompt",
            output=CronOutputConfig(channel="telegram", chat_id=789, delivery="agent"),
        )

        result_callback = AsyncMock()
        session_logger = MagicMock()
        session_logger.write_session = MagicMock(return_value="memory/sessions/cron/test-cron.jsonl")

        scheduler = CronScheduler(
            workspace_path=workspace,
            agent_factory=lambda: mock_agent_runner,
            channels={"telegram": mock_channel},
            workspace_name="test",
            result_callback=result_callback,
            session_logger=session_logger,
        )

        await scheduler._execute_cron(cron)

        # Channel should NOT be called
        mock_channel.send_message.assert_not_called()

        # Result callback should be called
        result_callback.assert_called_once()
        call_args = result_callback.call_args[0]
        assert call_args[0] == "telegram:789"
        assert "[SYSTEM] Scheduled task 'test-cron' completed." in call_args[1]

    @pytest.mark.asyncio
    async def test_cron_delivery_both(self, workspace, mock_agent_runner, mock_channel):
        """delivery='both': both called."""
        cron = CronDefinition(
            name="test-cron",
            schedule="0 9 * * *",
            prompt="Test prompt",
            output=CronOutputConfig(channel="telegram", chat_id=789, delivery="both"),
        )

        result_callback = AsyncMock()
        session_logger = MagicMock()
        session_logger.write_session = MagicMock(return_value="memory/sessions/cron/test-cron.jsonl")

        scheduler = CronScheduler(
            workspace_path=workspace,
            agent_factory=lambda: mock_agent_runner,
            channels={"telegram": mock_channel},
            workspace_name="test",
            result_callback=result_callback,
            session_logger=session_logger,
        )

        await scheduler._execute_cron(cron)

        # Both should be called
        mock_channel.send_message.assert_called_once()
        result_callback.assert_called_once()

    @pytest.mark.asyncio
    async def test_cron_session_log_written(self, workspace, mock_agent_runner, mock_channel):
        """session_logger.write_session called."""
        cron = CronDefinition(
            name="test-cron",
            schedule="0 9 * * *",
            prompt="Test prompt",
            output=CronOutputConfig(channel="telegram", chat_id=789),
        )

        session_logger = MagicMock()
        session_logger.write_session = MagicMock(return_value="memory/sessions/cron/test-cron.jsonl")

        scheduler = CronScheduler(
            workspace_path=workspace,
            agent_factory=lambda: mock_agent_runner,
            channels={"telegram": mock_channel},
            workspace_name="test",
            session_logger=session_logger,
        )

        await scheduler._execute_cron(cron)

        # Session logger should be called
        session_logger.write_session.assert_called_once()
        call_kwargs = session_logger.write_session.call_args[1]
        assert call_kwargs["name"] == "test-cron"
        assert call_kwargs["prompt"] == "Test prompt"
        assert call_kwargs["response"] == "Cron response"

    @pytest.mark.asyncio
    async def test_cron_dynamic_task_no_delivery_routing(self, workspace, mock_agent_runner, mock_channel):
        """Dynamic tasks get session_logger but no delivery routing changes."""
        from openpaw.model.cron import DynamicCronTask

        task = DynamicCronTask(
            id="dynamic-1",
            task_type="once",
            prompt="Dynamic prompt",
            created_at=datetime.now(),
            run_at=datetime.now(),
            channel="telegram",
            chat_id=789,
        )

        session_logger = MagicMock()
        session_logger.write_session = MagicMock(return_value="memory/sessions/cron/dynamic_dynamic-1.jsonl")

        scheduler = CronScheduler(
            workspace_path=workspace,
            agent_factory=lambda: mock_agent_runner,
            channels={"telegram": mock_channel},
            workspace_name="test",
            session_logger=session_logger,
        )

        await scheduler._execute_dynamic_task(task)

        # Session log should be written
        session_logger.write_session.assert_called_once()

        # Channel send should be called (dynamic tasks always use channel delivery)
        mock_channel.send_message.assert_called_once()


# --- SubAgentRunner Session Logging Tests ---


class TestSubAgentSessionLogging:
    """Tests for SubAgentRunner session logging."""

    @pytest.fixture
    def workspace(self, tmp_path):
        """Create temporary workspace."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        return workspace

    @pytest.fixture
    def store(self, workspace):
        """Create SubAgentStore."""
        return SubAgentStore(workspace)

    @pytest.fixture
    def mock_agent_runner(self):
        """Create mock agent runner."""
        runner = MagicMock()
        runner.run = AsyncMock(return_value="Subagent response")
        runner.last_metrics = InvocationMetrics(
            input_tokens=50, output_tokens=30, total_tokens=80, llm_calls=1
        )
        runner.last_tools_used = ["grep_files"]
        runner.additional_tools = []
        runner._build_agent = MagicMock(return_value=MagicMock())
        runner.timeout_seconds = 120
        return runner

    @pytest.mark.asyncio
    async def test_subagent_session_log_written_on_success(self, workspace, store, mock_agent_runner):
        """Verify session_logger called after successful run."""
        from openpaw.model.subagent import SubAgentStatus

        request = SubAgentRequest(
            id="sub-1",
            label="test-subagent",
            task="Test task",
            status=SubAgentStatus.PENDING,
            session_key="telegram:123",
            timeout_minutes=5,
            notify=False,
        )

        # Store the request first
        store.create(request)

        session_logger = MagicMock()
        session_logger.write_session = MagicMock(return_value="memory/sessions/subagent/subagent_test-subagent.jsonl")

        runner = SubAgentRunner(
            agent_factory=lambda: mock_agent_runner,
            store=store,
            channels={},
            workspace_name="test",
            session_logger=session_logger,
        )

        await runner._execute_subagent(request)

        # Session logger should be called
        session_logger.write_session.assert_called_once()
        call_kwargs = session_logger.write_session.call_args[1]
        assert call_kwargs["name"] == "subagent_test-subagent"
        assert call_kwargs["prompt"] == "Test task"
        assert call_kwargs["response"] == "Subagent response"
        assert call_kwargs["metrics"] == mock_agent_runner.last_metrics

    @pytest.mark.asyncio
    async def test_subagent_session_log_written_on_timeout(self, workspace, store, mock_agent_runner):
        """Verify session_logger called with '(timed out)' on timeout."""
        # Make agent run timeout
        import asyncio

        from openpaw.model.subagent import SubAgentStatus

        async def slow_run(message):
            await asyncio.sleep(10)  # Sleep longer than timeout
            return "Should not reach here"

        mock_agent_runner.run = slow_run

        request = SubAgentRequest(
            id="sub-timeout",
            label="timeout-test",
            task="Test task",
            status=SubAgentStatus.PENDING,
            session_key="telegram:123",
            timeout_minutes=0.01,  # Very short timeout (0.6 seconds)
            notify=False,
        )

        # Store the request first
        store.create(request)

        session_logger = MagicMock()
        session_logger.write_session = MagicMock(return_value="memory/sessions/subagent/timeout.jsonl")

        runner = SubAgentRunner(
            agent_factory=lambda: mock_agent_runner,
            store=store,
            channels={},
            workspace_name="test",
            session_logger=session_logger,
        )

        await runner._execute_subagent(request)

        # Session logger should be called with "(timed out)"
        session_logger.write_session.assert_called_once()
        call_kwargs = session_logger.write_session.call_args[1]
        assert call_kwargs["response"] == "(timed out)"
        assert call_kwargs["metrics"] is None


# --- Backwards Compatibility Tests ---


class TestBackwardsCompatibility:
    """Tests for backwards compatibility without new params."""

    @pytest.mark.asyncio
    async def test_heartbeat_scheduler_without_new_params(self, tmp_path):
        """HeartbeatScheduler works without result_callback/session_logger."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        (workspace / "HEARTBEAT.md").write_text("# Test")

        mock_runner = MagicMock()
        mock_runner.run = AsyncMock(return_value="Test")
        mock_runner.last_metrics = None
        mock_runner.last_tools_used = []

        mock_channel = MagicMock()
        mock_channel.send_message = AsyncMock()
        mock_channel.build_session_key = MagicMock(return_value="telegram:123")

        config = HeartbeatConfig(
            enabled=True, target_channel="telegram", target_chat_id=123
        )

        # Create scheduler WITHOUT result_callback and session_logger
        scheduler = HeartbeatScheduler(
            workspace_name="test",
            workspace_path=workspace,
            agent_factory=lambda: mock_runner,
            channels={"telegram": mock_channel},
            config=config,
            # NO result_callback
            # NO session_logger
        )

        with patch.object(scheduler, "_should_skip_heartbeat", return_value=(False, "test", None, 0)):
            await scheduler._run_heartbeat()

        # Should work without errors
        mock_channel.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_cron_scheduler_without_new_params(self, tmp_path):
        """CronScheduler works without result_callback/session_logger."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        mock_runner = MagicMock()
        mock_runner.run = AsyncMock(return_value="Cron test")
        mock_runner.last_metrics = None
        mock_runner.last_tools_used = []

        mock_channel = MagicMock()
        mock_channel.send_message = AsyncMock()
        mock_channel.build_session_key = MagicMock(return_value="telegram:456")

        cron = CronDefinition(
            name="test",
            schedule="0 9 * * *",
            prompt="Test",
            output=CronOutputConfig(channel="telegram", chat_id=456),
        )

        # Create scheduler WITHOUT result_callback and session_logger
        scheduler = CronScheduler(
            workspace_path=workspace,
            agent_factory=lambda: mock_runner,
            channels={"telegram": mock_channel},
            workspace_name="test",
            # NO result_callback
            # NO session_logger
        )

        await scheduler._execute_cron(cron)

        # Should work without errors
        mock_channel.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_subagent_runner_without_session_logger(self, tmp_path):
        """SubAgentRunner works without session_logger."""
        from openpaw.model.subagent import SubAgentStatus

        workspace = tmp_path / "workspace"
        workspace.mkdir()

        store = SubAgentStore(workspace)

        mock_runner = MagicMock()
        mock_runner.run = AsyncMock(return_value="Subagent test")
        mock_runner.last_metrics = None
        mock_runner.last_tools_used = []
        mock_runner.additional_tools = []
        mock_runner._build_agent = MagicMock(return_value=MagicMock())
        mock_runner.timeout_seconds = 120

        request = SubAgentRequest(
            id="sub-compat",
            label="compat-test",
            task="Test",
            status=SubAgentStatus.PENDING,
            session_key="telegram:789",
            timeout_minutes=5,
            notify=False,
        )

        # Store the request first (required by SubAgentStore)
        store.create(request)

        # Create runner WITHOUT session_logger
        runner = SubAgentRunner(
            agent_factory=lambda: mock_runner,
            store=store,
            channels={},
            workspace_name="test",
            # NO session_logger
        )

        await runner._execute_subagent(request)

        # Should work without errors
        result = store.get_result(request.id)
        assert result is not None
        assert result.output == "Subagent test"
