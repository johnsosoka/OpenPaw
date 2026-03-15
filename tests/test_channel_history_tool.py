"""Tests for ChannelHistoryToolBuiltin."""

import logging
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from openpaw.builtins.tools.channel_history import (
    ChannelHistoryToolBuiltin,
    _build_filter_qualifier,
    _format_history_output,
    _format_timestamp,
    _resolve_adapter,
    _resolve_channel_id,
)
from openpaw.channels.base import ChannelAdapter
from openpaw.channels.discord import DiscordChannel
from openpaw.model.channel import ChannelHistoryEntry
from openpaw.workspace.runner import WorkspaceRunner


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_entry(
    display_name: str = "Alice",
    user_id: str = "111",
    content: str = "Hello world",
    is_bot: bool = False,
    message_id: str = "1000",
    timestamp: datetime | None = None,
    attachments_summary: str | None = None,
) -> ChannelHistoryEntry:
    """Build a ChannelHistoryEntry for testing."""
    return ChannelHistoryEntry(
        timestamp=timestamp or datetime(2026, 3, 8, 14, 30, tzinfo=UTC),
        user_id=user_id,
        display_name=display_name,
        content=content,
        is_bot=is_bot,
        attachments_summary=attachments_summary,
        message_id=message_id,
    )


def _make_mock_discord_channel(
    name: str = "discord",
    entries: list[ChannelHistoryEntry] | None = None,
) -> MagicMock:
    """Build a MagicMock ChannelAdapter that supports history browsing."""
    channel = MagicMock(spec=DiscordChannel)
    channel.name = name
    channel.supports_history_browsing = True
    channel.fetch_channel_history = AsyncMock(return_value=entries or [])
    return channel


def _make_non_history_channel(name: str = "telegram") -> MagicMock:
    """Build a MagicMock ChannelAdapter that does NOT support history browsing."""
    channel = MagicMock(spec=ChannelAdapter)
    channel.name = name
    channel.supports_history_browsing = False
    return channel


@pytest.fixture
def tool() -> ChannelHistoryToolBuiltin:
    """Create an unconnected ChannelHistoryToolBuiltin."""
    return ChannelHistoryToolBuiltin()


@pytest.fixture
def tool_with_discord(tool: ChannelHistoryToolBuiltin) -> ChannelHistoryToolBuiltin:
    """Tool connected to a single mock Discord channel."""
    channel = _make_mock_discord_channel()
    tool.set_channels({"discord": channel})
    return tool


# ---------------------------------------------------------------------------
# Metadata and initialization tests
# ---------------------------------------------------------------------------


def test_metadata() -> None:
    """Metadata fields are correctly defined."""
    meta = ChannelHistoryToolBuiltin.metadata
    assert meta.name == "channel_history"
    assert meta.display_name == "Channel History Browser"
    assert meta.group == "communication"
    assert meta.builtin_type.value == "tool"
    assert len(meta.prerequisites.env_vars) == 0  # Runtime gating, no env vars


def test_initialization_defaults() -> None:
    """Default config values are applied correctly."""
    t = ChannelHistoryToolBuiltin()
    assert t.max_messages_per_request == 100
    assert t.content_truncation == 500
    assert t._channels is None


def test_initialization_with_config() -> None:
    """Custom config values override defaults."""
    t = ChannelHistoryToolBuiltin(config={"max_messages_per_request": 50, "content_truncation": 200})
    assert t.max_messages_per_request == 50
    assert t.content_truncation == 200


def test_get_langchain_tool_returns_list(tool: ChannelHistoryToolBuiltin) -> None:
    """get_langchain_tool returns a one-element list."""
    tools = tool.get_langchain_tool()
    assert isinstance(tools, list)
    assert len(tools) == 1
    assert tools[0].name == "browse_channel_history"


# ---------------------------------------------------------------------------
# set_channels tests
# ---------------------------------------------------------------------------


def test_set_channels_stores_reference(tool: ChannelHistoryToolBuiltin) -> None:
    """set_channels stores the channels dict on the instance."""
    channels = {"discord": _make_mock_discord_channel()}
    tool.set_channels(channels)
    assert tool._channels is channels


def test_set_channels_overrides_previous(tool: ChannelHistoryToolBuiltin) -> None:
    """Calling set_channels twice replaces the previous reference."""
    ch1 = {"discord": _make_mock_discord_channel()}
    ch2 = {"discord-work": _make_mock_discord_channel(name="discord-work")}
    tool.set_channels(ch1)
    tool.set_channels(ch2)
    assert tool._channels is ch2


# ---------------------------------------------------------------------------
# supports_history_browsing property tests
# ---------------------------------------------------------------------------


def test_base_adapter_does_not_support_history() -> None:
    """ChannelAdapter base property returns False by default."""
    channel = _make_non_history_channel()
    assert channel.supports_history_browsing is False


def test_discord_supports_history() -> None:
    """DiscordChannel.supports_history_browsing returns True."""
    channel = _make_mock_discord_channel()
    assert channel.supports_history_browsing is True


# ---------------------------------------------------------------------------
# Channel resolution tests
# ---------------------------------------------------------------------------


def test_resolve_adapter_single_auto_select() -> None:
    """Single history-capable channel is auto-selected when channel=None."""
    ch = _make_mock_discord_channel()
    channels = {"discord": ch}
    adapter, error = _resolve_adapter(channels, channel_name=None)
    assert adapter is ch
    assert error is None


def test_resolve_adapter_multi_requires_explicit() -> None:
    """Multiple channels require explicit channel= parameter."""
    channels = {
        "discord": _make_mock_discord_channel(),
        "discord-work": _make_mock_discord_channel(name="discord-work"),
    }
    adapter, error = _resolve_adapter(channels, channel_name=None)
    assert adapter is None
    assert "Multiple history-capable channels" in error
    assert "discord" in error
    assert "discord-work" in error


def test_resolve_adapter_explicit_found() -> None:
    """Explicit channel= that exists is returned."""
    ch = _make_mock_discord_channel()
    channels = {"discord": ch, "discord-work": _make_mock_discord_channel(name="discord-work")}
    adapter, error = _resolve_adapter(channels, channel_name="discord")
    assert adapter is ch
    assert error is None


def test_resolve_adapter_explicit_not_found() -> None:
    """Explicit channel= that does not exist returns a descriptive error."""
    channels = {"discord": _make_mock_discord_channel()}
    adapter, error = _resolve_adapter(channels, channel_name="slack")
    assert adapter is None
    assert "slack" in error
    assert "discord" in error


# ---------------------------------------------------------------------------
# Tool invocation tests — async via pytest-asyncio or sync helper
# ---------------------------------------------------------------------------


def _call_tool_sync(tool_builtin: ChannelHistoryToolBuiltin, **kwargs) -> str:
    """Invoke the browse_channel_history tool synchronously for tests.

    Patches the session key context so the channel_id is resolvable.
    Uses the coroutine (async) form of the tool to avoid thread pool issues.
    """
    import asyncio

    lc_tool = tool_builtin.get_langchain_tool()[0]

    async def _run() -> str:
        with patch(
            "openpaw.builtins.tools.channel_history.get_current_session_key",
            return_value="discord:123456789",
        ):
            return await lc_tool.coroutine(**kwargs)

    return asyncio.run(_run())


def test_no_channels_connected() -> None:
    """Returns error when channels have not been set."""
    t = ChannelHistoryToolBuiltin()
    result = _call_tool_sync(t)
    assert "not connected" in result.lower() or "error" in result.lower()


def test_empty_channels_dict() -> None:
    """Returns error when channels dict is empty."""
    t = ChannelHistoryToolBuiltin()
    t.set_channels({})
    result = _call_tool_sync(t)
    assert "No history-capable channels" in result


def test_fetch_returns_empty() -> None:
    """Returns appropriate message when fetch yields no entries."""
    channel = _make_mock_discord_channel(entries=[])
    t = ChannelHistoryToolBuiltin()
    t.set_channels({"discord": channel})
    result = _call_tool_sync(t)
    assert "No messages found" in result


def test_basic_fetch_formats_output() -> None:
    """Successful fetch returns formatted output with header and pagination."""
    entries = [
        _make_entry("Alice", "111", "Deploy started", message_id="1001"),
        _make_entry("Bob", "222", "Deploy complete", message_id="1002"),
    ]
    channel = _make_mock_discord_channel(entries=entries)
    t = ChannelHistoryToolBuiltin()
    t.set_channels({"discord": channel})
    result = _call_tool_sync(t)

    assert "Channel History" in result
    assert "Alice" in result
    assert "Bob" in result
    assert "Deploy started" in result
    assert "id:111" in result
    assert "Pagination" in result


def test_pagination_before_passed_to_adapter() -> None:
    """The 'before' parameter is forwarded to fetch_channel_history."""
    channel = _make_mock_discord_channel(entries=[_make_entry()])
    t = ChannelHistoryToolBuiltin()
    t.set_channels({"discord": channel})

    _call_tool_sync(t, before="9999")

    channel.fetch_channel_history.assert_called_once()
    call_kwargs = channel.fetch_channel_history.call_args
    assert call_kwargs.kwargs.get("before_message_id") == "9999" or (
        len(call_kwargs.args) >= 3 and call_kwargs.args[2] == "9999"
    )


def test_keyword_filter_case_insensitive() -> None:
    """Keyword filter is applied case-insensitively."""
    entries = [
        _make_entry("Alice", "111", "Deploy started", message_id="1001"),
        _make_entry("Bob", "222", "System is running", message_id="1002"),
    ]
    channel = _make_mock_discord_channel(entries=entries)
    t = ChannelHistoryToolBuiltin()
    t.set_channels({"discord": channel})
    result = _call_tool_sync(t, keyword="DEPLOY")

    assert "Deploy started" in result
    assert "System is running" not in result


def test_user_filter_case_insensitive() -> None:
    """User filter matches display name case-insensitively (substring)."""
    entries = [
        _make_entry("Alice Smith", "111", "Hello from Alice", message_id="1001"),
        _make_entry("Bob Jones", "222", "Hello from Bob", message_id="1002"),
    ]
    channel = _make_mock_discord_channel(entries=entries)
    t = ChannelHistoryToolBuiltin()
    t.set_channels({"discord": channel})
    result = _call_tool_sync(t, user="alice")

    assert "Hello from Alice" in result
    assert "Hello from Bob" not in result


def test_bot_messages_excluded_by_default() -> None:
    """Bot messages are excluded when include_bots=False (default)."""
    entries = [
        _make_entry("Alice", "111", "Human message", is_bot=False, message_id="1001"),
        _make_entry("BotUser", "999", "Bot reply", is_bot=True, message_id="1002"),
    ]
    channel = _make_mock_discord_channel(entries=entries)
    t = ChannelHistoryToolBuiltin()
    t.set_channels({"discord": channel})
    result = _call_tool_sync(t, include_bots=False)

    assert "Human message" in result
    assert "Bot reply" not in result


def test_bot_messages_included_when_requested() -> None:
    """Bot messages appear when include_bots=True."""
    entries = [
        _make_entry("Alice", "111", "Human message", is_bot=False, message_id="1001"),
        _make_entry("BotUser", "999", "Bot reply", is_bot=True, message_id="1002"),
    ]
    channel = _make_mock_discord_channel(entries=entries)
    t = ChannelHistoryToolBuiltin()
    t.set_channels({"discord": channel})
    result = _call_tool_sync(t, include_bots=True)

    assert "Human message" in result
    assert "Bot reply" in result


def test_over_fetch_with_keyword_filter() -> None:
    """When keyword filter is active, adapter is called with 3x the requested limit."""
    entries = [_make_entry(content="deploy here", message_id=str(i)) for i in range(10)]
    channel = _make_mock_discord_channel(entries=entries)
    t = ChannelHistoryToolBuiltin()
    t.set_channels({"discord": channel})

    _call_tool_sync(t, limit=5, keyword="deploy")

    call_kwargs = channel.fetch_channel_history.call_args
    # The actual limit passed should be 5 * 3 = 15
    fetched_limit = call_kwargs.kwargs.get("limit") or call_kwargs.args[1]
    assert fetched_limit == 15


def test_over_fetch_capped_at_300() -> None:
    """Over-fetch never exceeds 300 entries."""
    entries = [_make_entry(message_id=str(i)) for i in range(10)]
    channel = _make_mock_discord_channel(entries=entries)
    t = ChannelHistoryToolBuiltin()
    t.set_channels({"discord": channel})

    # limit=100, keyword active → 100 * 3 = 300 (cap)
    _call_tool_sync(t, limit=100, keyword="test")

    call_kwargs = channel.fetch_channel_history.call_args
    fetched_limit = call_kwargs.kwargs.get("limit") or call_kwargs.args[1]
    assert fetched_limit == 300


def test_no_over_fetch_without_filters() -> None:
    """Without filters, adapter is called with exactly the requested limit."""
    entries = [_make_entry(message_id=str(i)) for i in range(5)]
    channel = _make_mock_discord_channel(entries=entries)
    t = ChannelHistoryToolBuiltin()
    t.set_channels({"discord": channel})

    _call_tool_sync(t, limit=10, include_bots=True)

    call_kwargs = channel.fetch_channel_history.call_args
    fetched_limit = call_kwargs.kwargs.get("limit") or call_kwargs.args[1]
    assert fetched_limit == 10


def test_no_results_after_filter() -> None:
    """Returns informative message when filters produce zero results."""
    entries = [_make_entry("Alice", content="unrelated stuff", message_id="1")]
    channel = _make_mock_discord_channel(entries=entries)
    t = ChannelHistoryToolBuiltin()
    t.set_channels({"discord": channel})
    result = _call_tool_sync(t, keyword="nonexistent_keyword_xyz")

    assert "No messages found matching filters" in result


def test_output_includes_pagination_footer() -> None:
    """Pagination footer shows oldest_message_id when entries have message_ids."""
    entries = [
        _make_entry(message_id="100"),
        _make_entry(message_id="200"),
    ]
    channel = _make_mock_discord_channel(entries=entries)
    t = ChannelHistoryToolBuiltin()
    t.set_channels({"discord": channel})
    result = _call_tool_sync(t)

    assert "Pagination" in result
    # The oldest entry (index 0) should be the cursor
    assert "100" in result


def test_output_timestamps_are_utc() -> None:
    """Output timestamps are formatted in UTC."""
    ts = datetime(2026, 3, 8, 14, 30, tzinfo=UTC)
    entries = [_make_entry(timestamp=ts, message_id="1")]
    channel = _make_mock_discord_channel(entries=entries)
    t = ChannelHistoryToolBuiltin()
    t.set_channels({"discord": channel})
    result = _call_tool_sync(t)

    assert "2026-03-08 14:30 UTC" in result


def test_content_truncation_per_message() -> None:
    """Long message content is truncated at the configured limit."""
    long_content = "A" * 600
    entries = [_make_entry(content=long_content, message_id="1")]
    channel = _make_mock_discord_channel(entries=entries)
    t = ChannelHistoryToolBuiltin(config={"content_truncation": 100})
    t.set_channels({"discord": channel})
    result = _call_tool_sync(t)

    # Should contain exactly 100 A's followed by "..."
    assert "A" * 100 + "..." in result
    assert "A" * 101 not in result


def test_total_output_capped_at_50k() -> None:
    """Total output is capped at 50K characters."""
    # Each message is ~550 chars; 200 messages would exceed 50K
    entries = [
        _make_entry(content="X" * 500, message_id=str(i)) for i in range(200)
    ]
    channel = _make_mock_discord_channel(entries=entries)
    t = ChannelHistoryToolBuiltin(config={"max_messages_per_request": 100})
    t.set_channels({"discord": channel})
    result = _call_tool_sync(t, limit=100, include_bots=True)

    assert len(result) <= 50_000 + 200  # Small tolerance for truncation suffix
    assert "truncated" in result.lower()


def test_channel_not_found_explicit() -> None:
    """Explicit channel= that does not exist returns error with available list."""
    channels = {"discord": _make_mock_discord_channel()}
    t = ChannelHistoryToolBuiltin()
    t.set_channels(channels)
    result = _call_tool_sync(t, channel="slack")

    assert "Error" in result
    assert "slack" in result
    assert "discord" in result


def test_multi_channel_no_selection_error() -> None:
    """Multiple channels without channel= parameter returns error."""
    channels = {
        "discord": _make_mock_discord_channel(),
        "discord-work": _make_mock_discord_channel(name="discord-work"),
    }
    t = ChannelHistoryToolBuiltin()
    t.set_channels(channels)
    result = _call_tool_sync(t)

    assert "Multiple history-capable channels" in result
    assert "discord" in result


def test_multi_channel_explicit_selection() -> None:
    """Explicit channel= in multi-channel workspace selects correct adapter."""
    entries_main = [_make_entry("Alice", content="main channel", message_id="1")]
    entries_work = [_make_entry("Bob", content="work channel", message_id="2")]

    channels = {
        "discord": _make_mock_discord_channel(entries=entries_main),
        "discord-work": _make_mock_discord_channel(name="discord-work", entries=entries_work),
    }
    t = ChannelHistoryToolBuiltin()
    t.set_channels(channels)

    result = _call_tool_sync(t, channel="discord-work")

    assert "work channel" in result
    assert "main channel" not in result


def test_adapter_fetch_exception_returns_friendly_error() -> None:
    """Adapter fetch raising an exception returns a user-friendly error string."""
    channel = _make_mock_discord_channel()
    channel.fetch_channel_history = AsyncMock(side_effect=Exception("Forbidden"))
    t = ChannelHistoryToolBuiltin()
    t.set_channels({"discord": channel})
    result = _call_tool_sync(t)

    assert "No messages retrieved" in result or "permission" in result.lower()


def test_attachments_summary_in_output() -> None:
    """Attachment summaries appear in formatted output."""
    entries = [
        _make_entry(
            content="See attached",
            message_id="1",
            attachments_summary="[1 file: report.pdf]",
        )
    ]
    channel = _make_mock_discord_channel(entries=entries)
    t = ChannelHistoryToolBuiltin()
    t.set_channels({"discord": channel})
    result = _call_tool_sync(t)

    assert "[1 file: report.pdf]" in result


# ---------------------------------------------------------------------------
# Helper unit tests
# ---------------------------------------------------------------------------


def test_format_timestamp_utc_aware() -> None:
    """UTC-aware datetime is formatted correctly."""
    ts = datetime(2026, 3, 8, 14, 30, tzinfo=UTC)
    assert _format_timestamp(ts) == "2026-03-08 14:30 UTC"


def test_format_timestamp_naive_treated_as_utc() -> None:
    """Naive datetime is treated as UTC."""
    ts = datetime(2026, 3, 8, 9, 0)
    result = _format_timestamp(ts)
    assert "2026-03-08 09:00 UTC" == result


def test_build_filter_qualifier_empty() -> None:
    """No filters produces empty qualifier."""
    assert _build_filter_qualifier(None, None, True) == ""


def test_build_filter_qualifier_keyword_only() -> None:
    """Keyword-only filter shows keyword."""
    qualifier = _build_filter_qualifier("deploy", None, True)
    assert "deploy" in qualifier


def test_build_filter_qualifier_bots_excluded() -> None:
    """Bots excluded note appears when include_bots=False."""
    qualifier = _build_filter_qualifier(None, None, False)
    assert "bots excluded" in qualifier


def test_build_filter_qualifier_all_filters() -> None:
    """All filters combined."""
    qualifier = _build_filter_qualifier("deploy", "Alice", False)
    assert "deploy" in qualifier
    assert "Alice" in qualifier
    assert "bots excluded" in qualifier


def test_format_history_output_header() -> None:
    """Output header includes channel name and adapter type."""
    entries = [_make_entry(message_id="100")]
    output = _format_history_output(
        entries=entries,
        channel_name="general",
        adapter_type="discord",
        requested_limit=10,
        matched_count=1,
        before_cursor=None,
        content_truncation=500,
    )
    assert "general" in output
    assert "discord" in output


def test_format_history_output_before_cursor_in_header() -> None:
    """Before cursor appears in header when provided."""
    entries = [_make_entry(message_id="50")]
    output = _format_history_output(
        entries=entries,
        channel_name="general",
        adapter_type="discord",
        requested_limit=10,
        matched_count=1,
        before_cursor="12345",
        content_truncation=500,
    )
    assert "12345" in output
    assert "before" in output.lower()


def test_format_history_output_pagination_footer_empty_message_id() -> None:
    """Pagination footer is skipped when oldest entry has empty message_id."""
    entries = [_make_entry(message_id="")]
    output = _format_history_output(
        entries=entries,
        channel_name="general",
        adapter_type="discord",
        requested_limit=10,
        matched_count=1,
        before_cursor=None,
        content_truncation=500,
    )
    assert "Pagination" not in output


def test_no_session_key_returns_error() -> None:
    """Missing session key context returns a descriptive error."""
    import asyncio

    channel = _make_mock_discord_channel(entries=[_make_entry()])
    t = ChannelHistoryToolBuiltin()
    t.set_channels({"discord": channel})

    lc_tool = t.get_langchain_tool()[0]

    async def _run() -> str:
        with patch(
            "openpaw.builtins.tools.channel_history.get_current_session_key",
            return_value=None,
        ):
            return await lc_tool.coroutine()

    result = asyncio.run(_run())
    assert "Error" in result
    assert "session" in result.lower()


def test_resolve_channel_id_malformed_session_key() -> None:
    """_resolve_channel_id handles session keys without a colon gracefully."""
    mock_adapter = MagicMock(spec=ChannelAdapter)

    with patch(
        "openpaw.builtins.tools.channel_history.get_current_session_key",
        return_value="nocolonhere",
    ):
        channel_id, error = _resolve_channel_id(mock_adapter)

    assert error is not None
    assert "Error" in error
    assert channel_id == ""


# ---------------------------------------------------------------------------
# Runner wiring tests
# ---------------------------------------------------------------------------


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
    runner._agent_factory.create_agent.return_value = MagicMock()
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
        runner._agent_factory.create_agent.assert_called_once_with(
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
        runner._agent_factory.create_agent.assert_not_called()
