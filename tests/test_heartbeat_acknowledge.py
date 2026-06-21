"""Tests for HeartbeatScheduler + AcknowledgeTool integration.

Covers:
- acknowledge_event suppresses channel delivery and logs "acknowledged" outcome
- acknowledge_event takes precedence over HEARTBEAT_OK when both occur
- HEARTBEAT_OK backward compatibility when ack_tool is None
- ack_tool.reset() is called after every heartbeat run (stale-state guard)
"""

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest

from openpaw.builtins.tools.acknowledge import AcknowledgeRequest, AcknowledgeTool
from openpaw.core.config import HeartbeatConfig
from openpaw.runtime.scheduling.heartbeat import HeartbeatScheduler


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_workspace(tmp_path: Path) -> Path:
    """Temporary workspace with required subdirectories."""
    workspace = tmp_path / "test_workspace"
    workspace.mkdir()
    (workspace / "agent").mkdir()
    (workspace / "data").mkdir()
    return workspace


def _write_heartbeat_md(workspace: Path, content: str = "# Heartbeat\nMonitor the deploy.") -> None:
    """Write HEARTBEAT.md at the canonical agent/ subdirectory location."""
    (workspace / "agent" / "HEARTBEAT.md").write_text(content)


def _read_heartbeat_log(workspace: Path) -> list[dict]:
    """Parse heartbeat_log.jsonl and return all events as a list of dicts."""
    log_path = workspace / "data" / "heartbeat_log.jsonl"
    if not log_path.exists():
        return []
    return [json.loads(line) for line in log_path.read_text().splitlines() if line.strip()]


def _make_scheduler(
    workspace: Path,
    ack_tool: Any | None = None,
    suppress_ok: bool = True,
) -> HeartbeatScheduler:
    """Build a HeartbeatScheduler with minimal mocks and an optional ack_tool."""
    config = HeartbeatConfig(
        enabled=True,
        interval_minutes=30,
        suppress_ok=suppress_ok,
        target_channel="telegram",
        target_chat_id=123456789,
    )

    mock_channel = AsyncMock()
    mock_channel.build_session_key = Mock(return_value="telegram:123456789")

    return HeartbeatScheduler(
        workspace_name="test-workspace",
        workspace_path=workspace,
        agent_factory=Mock(),
        channels={"telegram": mock_channel},
        config=config,
        ack_tool=ack_tool,
    )


def _make_ack_tool(pending_reason: str | None = None) -> AcknowledgeTool:
    """Return a real AcknowledgeTool, optionally pre-loaded with a pending ack."""
    tool = AcknowledgeTool(config={})
    tool.reset()
    if pending_reason is not None:
        tool._pending_ack = AcknowledgeRequest(reason=pending_reason)
    return tool


def _make_agent_runner(response: str = "some output") -> AsyncMock:
    """Return a mock agent_runner that yields the given response."""
    agent_runner = AsyncMock()
    agent_runner.run = AsyncMock(return_value=response)
    agent_runner.last_metrics = None
    agent_runner.last_tools_used = []
    return agent_runner


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestHeartbeatAcknowledge:
    """HeartbeatScheduler respects acknowledge_event calls from the agent."""

    @pytest.mark.asyncio
    async def test_acknowledge_suppresses_delivery(self, tmp_workspace: Path) -> None:
        """When agent calls acknowledge_event, no message is sent to the channel."""
        _write_heartbeat_md(tmp_workspace)

        ack_tool = _make_ack_tool(pending_reason="all quiet, routine check passed")
        scheduler = _make_scheduler(tmp_workspace, ack_tool=ack_tool)
        scheduler.agent_factory = Mock(return_value=_make_agent_runner("Everything looks good."))

        await scheduler._run_heartbeat()

        channel = scheduler.channels["telegram"]
        channel.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_acknowledge_logs_acknowledged_outcome(self, tmp_workspace: Path) -> None:
        """acknowledge_event logs event with outcome='acknowledged' and the reason."""
        _write_heartbeat_md(tmp_workspace)

        reason = "system healthy, no actions required"
        ack_tool = _make_ack_tool(pending_reason=reason)
        scheduler = _make_scheduler(tmp_workspace, ack_tool=ack_tool)
        scheduler.agent_factory = Mock(return_value=_make_agent_runner("All clear."))

        await scheduler._run_heartbeat()

        events = _read_heartbeat_log(tmp_workspace)
        assert events, "heartbeat_log.jsonl should have at least one entry"
        last = events[-1]
        assert last["outcome"] == "acknowledged"
        assert last["reason"] == reason

    @pytest.mark.asyncio
    async def test_acknowledge_takes_precedence_over_heartbeat_ok(
        self, tmp_workspace: Path
    ) -> None:
        """When both acknowledge_event is called AND response contains HEARTBEAT_OK,
        the logged outcome must be 'acknowledged', not 'heartbeat_ok'."""
        _write_heartbeat_md(tmp_workspace)

        ack_tool = _make_ack_tool(pending_reason="nothing to do")
        scheduler = _make_scheduler(tmp_workspace, ack_tool=ack_tool)
        # Response also contains the magic string — ack_tool should win
        scheduler.agent_factory = Mock(return_value=_make_agent_runner("HEARTBEAT_OK"))

        await scheduler._run_heartbeat()

        events = _read_heartbeat_log(tmp_workspace)
        assert events, "heartbeat_log.jsonl should have at least one entry"
        last = events[-1]
        assert last["outcome"] == "acknowledged", (
            f"Expected 'acknowledged' but got '{last['outcome']}'. "
            "acknowledge_event must take precedence over HEARTBEAT_OK."
        )

    @pytest.mark.asyncio
    async def test_heartbeat_ok_still_works_without_ack_tool(
        self, tmp_workspace: Path
    ) -> None:
        """HEARTBEAT_OK magic string suppression is unaffected when ack_tool=None."""
        _write_heartbeat_md(tmp_workspace)

        # No ack_tool — backward-compat path
        scheduler = _make_scheduler(tmp_workspace, ack_tool=None, suppress_ok=True)
        scheduler.agent_factory = Mock(return_value=_make_agent_runner("HEARTBEAT_OK"))

        await scheduler._run_heartbeat()

        channel = scheduler.channels["telegram"]
        channel.send_message.assert_not_called()

        events = _read_heartbeat_log(tmp_workspace)
        assert events, "heartbeat_log.jsonl should have at least one entry"
        last = events[-1]
        assert last["outcome"] == "heartbeat_ok"

    @pytest.mark.asyncio
    async def test_ack_tool_reset_called_after_acknowledged_run(
        self, tmp_workspace: Path
    ) -> None:
        """ack_tool.reset() is called in the finally block after an acknowledged run."""
        _write_heartbeat_md(tmp_workspace)

        ack_tool = MagicMock(spec=AcknowledgeTool)
        ack_tool.get_pending_ack.return_value = AcknowledgeRequest(reason="all clear")
        ack_tool.reset = MagicMock()

        scheduler = _make_scheduler(tmp_workspace, ack_tool=ack_tool)
        scheduler.agent_factory = Mock(return_value=_make_agent_runner("All clear."))

        await scheduler._run_heartbeat()

        ack_tool.reset.assert_called_once()

    @pytest.mark.asyncio
    async def test_ack_tool_reset_called_after_normal_delivery(
        self, tmp_workspace: Path
    ) -> None:
        """ack_tool.reset() is called after a normal (delivered) heartbeat run."""
        _write_heartbeat_md(tmp_workspace)

        ack_tool = MagicMock(spec=AcknowledgeTool)
        ack_tool.get_pending_ack.return_value = None  # no ack this cycle
        ack_tool.reset = MagicMock()

        scheduler = _make_scheduler(tmp_workspace, ack_tool=ack_tool)
        scheduler.agent_factory = Mock(
            return_value=_make_agent_runner("Checked everything, sending update.")
        )

        await scheduler._run_heartbeat()

        ack_tool.reset.assert_called_once()

    @pytest.mark.asyncio
    async def test_ack_tool_reset_called_after_failed_run(
        self, tmp_workspace: Path
    ) -> None:
        """ack_tool.reset() is called even when the agent run raises an exception."""
        _write_heartbeat_md(tmp_workspace)

        ack_tool = MagicMock(spec=AcknowledgeTool)
        ack_tool.get_pending_ack.return_value = None
        ack_tool.reset = MagicMock()

        scheduler = _make_scheduler(tmp_workspace, ack_tool=ack_tool)

        failing_runner = AsyncMock()
        failing_runner.run = AsyncMock(side_effect=RuntimeError("agent exploded"))
        failing_runner.last_metrics = None
        failing_runner.last_tools_used = []
        scheduler.agent_factory = Mock(return_value=failing_runner)

        await scheduler._run_heartbeat()  # must not propagate the error

        ack_tool.reset.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_ack_no_heartbeat_ok_sends_response(
        self, tmp_workspace: Path
    ) -> None:
        """When neither acknowledge_event nor HEARTBEAT_OK, the response is delivered."""
        _write_heartbeat_md(tmp_workspace)

        ack_tool = _make_ack_tool(pending_reason=None)  # no pending ack
        scheduler = _make_scheduler(tmp_workspace, ack_tool=ack_tool)

        response_text = "Found a stalled task; notifying user."
        scheduler.agent_factory = Mock(return_value=_make_agent_runner(response_text))

        await scheduler._run_heartbeat()

        channel = scheduler.channels["telegram"]
        channel.send_message.assert_called_once()
