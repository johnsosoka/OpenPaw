"""Tests for channel history browser tool invocation and async browsing."""

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from openpaw.builtins.tools.channel_history import ChannelHistoryToolBuiltin
from openpaw.channels.discord import DiscordChannel
from openpaw.model.channel import ChannelHistoryEntry


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


def _call_tool_sync(tool_builtin: ChannelHistoryToolBuiltin, **kwargs) -> str:
    """Invoke the browse_channel_history tool synchronously for tests.

    Patches the session key context so the channel_id is resolvable.
    Uses the coroutine (async) form of the tool to avoid thread pool issues.
    """
    lc_tool = tool_builtin.get_langchain_tool()[0]

    async def _run() -> str:
        with patch(
            "openpaw.builtins.tools.channel_history.resolver.get_current_session_key",
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


def test_no_session_key_returns_error() -> None:
    """Missing session key context returns a descriptive error."""
    channel = _make_mock_discord_channel(entries=[_make_entry()])
    t = ChannelHistoryToolBuiltin()
    t.set_channels({"discord": channel})

    lc_tool = t.get_langchain_tool()[0]

    async def _run() -> str:
        with patch(
            "openpaw.builtins.tools.channel_history.resolver.get_current_session_key",
            return_value=None,
        ):
            return await lc_tool.coroutine()

    result = asyncio.run(_run())
    assert "Error" in result
    assert "session" in result.lower()
