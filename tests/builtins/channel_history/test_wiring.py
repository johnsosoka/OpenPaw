"""Tests for WorkspaceRunner wiring with channel history tool."""

from unittest.mock import MagicMock, Mock

from openpaw.channels.base import ChannelAdapter
from openpaw.channels.discord import DiscordChannel
from openpaw.workspace.runner import WorkspaceRunner


def _make_mock_discord_channel(
    name: str = "discord",
    entries: list | None = None,
) -> MagicMock:
    """Build a MagicMock ChannelAdapter that supports history browsing."""
    from unittest.mock import AsyncMock
    channel = MagicMock(spec=DiscordChannel)
    channel.name = name
    channel.supports_history_browsing = True
    channel.fetch_channel_history = AsyncMock(return_value=entries or [])
    return channel


def _make_mock_runner_for_history(
    history_tool: Mock | None = None,
    channels: dict | None = None,
) -> MagicMock:
    """Build a minimal mock WorkspaceRunner for _connect_channel_history_tool tests.

    Mirrors the pattern used by test_memory_search_availability.py.
    """
    runner = MagicMock(spec=WorkspaceRunner)
    runner.workspace_name = "test_workspace"
    runner.logger = MagicMock()

    runner._builtin_loader = MagicMock()
    runner._builtin_loader.get_tool_instance.return_value = history_tool

    runner._channels = channels if channels is not None else {}
    runner._agent_factory = MagicMock()
    runner._agent_factory.create_harness.return_value = MagicMock()
    runner._agent_runner = MagicMock()
    runner._message_processor = MagicMock()
    runner._checkpointer = MagicMock()

    return runner


class TestConnectChannelHistoryTool:
    """Runner wiring tests for WorkspaceRunner._connect_channel_history_tool."""

    def test_no_history_channels_removes_tool(self) -> None:
        """When no channels support history, the tool is removed from the agent."""
        history_tool = MagicMock()
        telegram = MagicMock(spec=ChannelAdapter)
        telegram.supports_history_browsing = False

        runner = _make_mock_runner_for_history(
            history_tool=history_tool,
            channels={"telegram": telegram},
        )

        WorkspaceRunner._connect_channel_history_tool(runner)

        runner._agent_factory.remove_builtin_tools.assert_called_once_with(
            {"browse_channel_history"}
        )
        runner._agent_factory.remove_enabled_builtin.assert_called_once_with(
            "channel_history"
        )
        runner._agent_factory.create_harness.assert_called_once_with(
            checkpointer=runner._checkpointer
        )
        runner._message_processor.update_agent_runner.assert_called_once()

    def test_history_channels_present_calls_set_channels(self) -> None:
        """When history-capable channels exist, set_channels is called with only those."""
        history_tool = MagicMock()
        discord_ch = _make_mock_discord_channel()
        telegram_ch = MagicMock(spec=ChannelAdapter)
        telegram_ch.supports_history_browsing = False

        runner = _make_mock_runner_for_history(
            history_tool=history_tool,
            channels={"discord": discord_ch, "telegram": telegram_ch},
        )

        WorkspaceRunner._connect_channel_history_tool(runner)

        history_tool.set_channels.assert_called_once_with({"discord": discord_ch})
        runner._agent_factory.remove_builtin_tools.assert_not_called()
        runner._agent_factory.create_harness.assert_not_called()
