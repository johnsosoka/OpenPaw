"""Tests for channel history formatter functions."""

from datetime import UTC, datetime

from openpaw.builtins.tools.channel_history.formatter import (
    _build_filter_qualifier,
    _format_history_output,
    _format_timestamp,
)
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
