"""Tests for sub-agent tool filtering."""

from unittest.mock import AsyncMock, Mock

import pytest

from openpaw.agent.runner import AgentRunner
from openpaw.channels.base import ChannelAdapter
from openpaw.model.subagent import SubAgentRequest, SubAgentStatus
from openpaw.runtime.subagent.filter import SUBAGENT_EXCLUDED_TOOLS, filter_subagent_tools
from openpaw.runtime.subagent.runner import SubAgentRunner
from openpaw.stores.subagent import SubAgentStore


@pytest.fixture
def mock_store():
    """Create a mock SubAgentStore."""
    store = Mock(spec=SubAgentStore)
    store.update_status = Mock()
    store.save_result = Mock()
    store.get = Mock(return_value=None)
    store.get_result = Mock(return_value=None)
    store.list_active = Mock(return_value=[])
    store.list_recent = Mock(return_value=[])
    return store


@pytest.fixture
def mock_channel():
    """Create a mock ChannelAdapter."""
    channel = Mock(spec=ChannelAdapter)
    channel.send_message = AsyncMock()
    return channel


@pytest.fixture
def mock_token_logger():
    """Create a mock TokenUsageLogger."""
    from openpaw.agent.metrics import TokenUsageLogger
    logger = Mock(spec=TokenUsageLogger)
    logger.log = Mock()
    return logger


def test_subagent_excluded_tools_contains_expected_names():
    """Test that SUBAGENT_EXCLUDED_TOOLS contains expected tool names."""
    expected_tools = {
        # Prevent sub-sub-agents
        "spawn_agent",
        "list_subagents",
        "get_subagent_result",
        "cancel_subagent",
        # Prevent self-continuation
        "request_followup",
        # Prevent unsolicited user messaging
        "send_message",
        "send_file",
        # Prevent persistence that outlives sub-agent lifecycle
        "schedule_at",
        "schedule_every",
        "list_scheduled",
        "cancel_scheduled",
        # Prevent orphaned browser sessions
        "browser_navigate",
        "browser_snapshot",
        "browser_click",
        "browser_type",
        "browser_select",
        "browser_scroll",
        "browser_back",
        "browser_screenshot",
        "browser_close",
        "browser_tabs",
        "browser_switch_tab",
        # Prevent persistent cron side effects
        "create_cron",
        "list_crons",
        "update_cron",
        "delete_cron",
        # Plan tool requires session key (undefined in subagent context)
        "write_plan",
        "read_plan",
    }

    assert SUBAGENT_EXCLUDED_TOOLS == expected_tools


@pytest.mark.asyncio
async def test_tool_filtering_removes_excluded_tools(
    mock_store, mock_channel, mock_token_logger
):
    """Test that tool filtering removes excluded tools."""
    # Create mock tools
    allowed_tool = Mock()
    allowed_tool.name = "allowed_tool"

    excluded_tool = Mock()
    excluded_tool.name = "spawn_agent"

    mock_runner = Mock(spec=AgentRunner)
    mock_runner.run = AsyncMock(return_value="Test response")
    mock_runner.additional_tools = [allowed_tool, excluded_tool]
    mock_runner._build_agent = Mock(return_value=Mock())
    mock_runner._agent = Mock()
    mock_runner.last_metrics = None

    def factory():
        return mock_runner

    runner = SubAgentRunner(
        agent_factory=factory,
        store=mock_store,
        channels={"telegram": mock_channel},
        token_logger=mock_token_logger,
        workspace_name="test",
        max_concurrent=2,
    )

    request = SubAgentRequest(
        id="test-req",
        task="Test task",
        label="test-label",
        status=SubAgentStatus.RUNNING,
        session_key="telegram:12345",
        timeout_minutes=30,
        notify=False,
    )

    # Execute
    await runner._execute_subagent(request)

    # Verify excluded tool was removed
    assert allowed_tool in mock_runner.additional_tools
    assert excluded_tool not in mock_runner.additional_tools
    assert len(mock_runner.additional_tools) == 1

    # Verify _build_agent was called to rebuild with filtered tools
    mock_runner._build_agent.assert_called_once()


import logging
from unittest.mock import patch


def test_filter_warns_when_allowed_tools_includes_excluded():
    """Test that filter_subagent_tools warns when allowed_tools includes excluded tools."""
    tool = Mock()
    tool.name = "read_file"

    with patch("openpaw.runtime.subagent.filter.logger") as mock_logger:
        result = filter_subagent_tools(
            [tool],
            allowed_tools=["spawn_agent", "read_file"],
        )

        assert len(result) == 1
        assert result[0].name == "read_file"
        mock_logger.warning.assert_called_once()
        call_args = mock_logger.warning.call_args[0][0]
        assert "spawn_agent" in call_args


def test_filter_does_not_warn_for_excluded_tools_in_denied():
    """Test that filter_subagent_tools does not produce false warning for excluded tools in denied_tools."""
    tool = Mock()
    tool.name = "read_file"

    with patch("openpaw.runtime.subagent.filter.logger") as mock_logger:
        result = filter_subagent_tools(
            [tool],
            denied_tools=["spawn_agent", "read_file"],
        )

        assert len(result) == 0
        # Should only warn about unknown tools, not excluded ones
        calls = [c[0][0] for c in mock_logger.warning.call_args_list]
        assert not any("spawn_agent" in c for c in calls)


def test_filter_warns_for_unknown_tools_in_denied():
    """Test that filter_subagent_tools warns for genuinely unknown tools in denied_tools."""
    tool = Mock()
    tool.name = "read_file"

    with patch("openpaw.runtime.subagent.filter.logger") as mock_logger:
        result = filter_subagent_tools(
            [tool],
            denied_tools=["nonexistent_tool"],
        )

        assert len(result) == 1
        mock_logger.warning.assert_called_once()
        call_args = mock_logger.warning.call_args[0][0]
        assert "nonexistent_tool" in call_args
