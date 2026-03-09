"""Tests for the channel context formatter utility.

Tests cover: empty input, single entry, multiple entries, relative timestamp
buckets, bot message detection (by user_id and is_bot flag), content
truncation, attachment summary appending, XML attribute values, and special
characters in content.
"""

from datetime import UTC, datetime, timedelta

from openpaw.core.channel_context import format_channel_context
from openpaw.model.channel import ChannelHistoryEntry

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_entry(
    minutes_ago: float,
    reference: datetime,
    display_name: str = "Alice",
    user_id: str = "user_1",
    content: str = "Hello",
    is_bot: bool = False,
    attachments_summary: str | None = None,
) -> ChannelHistoryEntry:
    """Build a ChannelHistoryEntry at a given offset before a reference time."""
    return ChannelHistoryEntry(
        timestamp=reference - timedelta(minutes=minutes_ago),
        user_id=user_id,
        display_name=display_name,
        content=content,
        is_bot=is_bot,
        attachments_summary=attachments_summary,
    )


_NOW = datetime(2026, 3, 7, 12, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Edge cases: empty and single entry
# ---------------------------------------------------------------------------

def test_empty_entries_returns_empty_string():
    result = format_channel_context([])
    assert result == ""


def test_single_entry_wrapped_in_xml_tags():
    entry = _make_entry(minutes_ago=0, reference=_NOW, content="Hey there")
    result = format_channel_context([entry], channel_name="general", source="discord")

    assert result.startswith('<channel_context source="discord" channel="general" messages="1">')
    assert result.endswith("</channel_context>")
    assert "Hey there" in result


# ---------------------------------------------------------------------------
# XML attribute values
# ---------------------------------------------------------------------------

def test_xml_attributes_reflect_arguments():
    entries = [_make_entry(0, _NOW)]
    result = format_channel_context(entries, channel_name="dev-chat", source="telegram")

    assert 'source="telegram"' in result
    assert 'channel="dev-chat"' in result
    assert 'messages="1"' in result


def test_messages_count_matches_entry_count():
    entries = [_make_entry(i, _NOW) for i in range(5)]
    result = format_channel_context(entries)

    assert 'messages="5"' in result


# ---------------------------------------------------------------------------
# Chronological order
# ---------------------------------------------------------------------------

def test_entries_appear_in_chronological_order():
    entries = [
        _make_entry(10, _NOW, display_name="Alice", content="First"),
        _make_entry(5, _NOW, display_name="Bob", content="Second"),
        _make_entry(0, _NOW, display_name="Carol", content="Third"),
    ]
    result = format_channel_context(entries)

    first_pos = result.index("First")
    second_pos = result.index("Second")
    third_pos = result.index("Third")

    assert first_pos < second_pos < third_pos


# ---------------------------------------------------------------------------
# Relative timestamp buckets
# ---------------------------------------------------------------------------

def test_timestamp_just_now_when_less_than_one_minute():
    entry = _make_entry(minutes_ago=0, reference=_NOW)
    result = format_channel_context([entry])
    assert "[just now]" in result


def test_timestamp_shows_minutes_ago():
    # The last entry is the reference; the first entry is 5 minutes before it.
    entries = [
        _make_entry(minutes_ago=5, reference=_NOW, content="Older"),
        _make_entry(minutes_ago=0, reference=_NOW, content="Newest"),
    ]
    result = format_channel_context(entries)
    assert "[5m ago]" in result


def test_timestamp_shows_one_minute_ago():
    entries = [
        _make_entry(minutes_ago=1, reference=_NOW, content="One minute back"),
        _make_entry(minutes_ago=0, reference=_NOW, content="Newest"),
    ]
    result = format_channel_context(entries)
    assert "[1m ago]" in result


def test_timestamp_shows_hours_ago():
    entries = [
        _make_entry(minutes_ago=90, reference=_NOW, content="Hour and a half"),
        _make_entry(minutes_ago=0, reference=_NOW, content="Newest"),
    ]
    result = format_channel_context(entries)
    assert "[1h ago]" in result


def test_timestamp_shows_two_hours_ago():
    entries = [
        _make_entry(minutes_ago=150, reference=_NOW, content="Two and a half hours"),
        _make_entry(minutes_ago=0, reference=_NOW, content="Newest"),
    ]
    result = format_channel_context(entries)
    assert "[2h ago]" in result


def test_timestamp_shows_days_ago_when_less_than_seven_days():
    entries = [
        _make_entry(minutes_ago=60 * 36, reference=_NOW, content="Day and a half"),
        _make_entry(minutes_ago=0, reference=_NOW, content="Newest"),
    ]
    result = format_channel_context(entries)
    assert "[1d ago]" in result


def test_timestamp_shows_date_format_when_older_than_seven_days():
    # 8 days ago from March 7 = February 27
    entries = [
        _make_entry(minutes_ago=60 * 24 * 8, reference=_NOW, content="Old message"),
        _make_entry(minutes_ago=0, reference=_NOW, content="Newest"),
    ]
    result = format_channel_context(entries)
    assert "[Feb 27]" in result


def test_timestamps_computed_relative_to_last_entry():
    """All timestamps are relative to the last (most recent) entry, not now()."""
    # Last entry is the reference; first entry is 10 minutes before it.
    last_entry = _make_entry(minutes_ago=0, reference=_NOW)
    first_entry = _make_entry(minutes_ago=10, reference=_NOW)

    result = format_channel_context([first_entry, last_entry])

    assert "[10m ago]" in result
    assert "[just now]" in result


# ---------------------------------------------------------------------------
# Bot message detection
# ---------------------------------------------------------------------------

def test_bot_labelled_by_is_bot_flag():
    entry = _make_entry(0, _NOW, display_name="Paw", is_bot=True)
    result = format_channel_context([entry])
    assert "[BOT] Paw" in result


def test_bot_labelled_by_user_id_match():
    entry = _make_entry(0, _NOW, display_name="Paw", user_id="bot_123", is_bot=False)
    result = format_channel_context([entry], bot_user_id="bot_123")
    assert "[BOT] Paw" in result


def test_non_bot_user_not_labelled():
    entry = _make_entry(0, _NOW, display_name="Alice", user_id="user_1", is_bot=False)
    result = format_channel_context([entry], bot_user_id="bot_999")
    assert "[BOT]" not in result


def test_bot_detected_by_either_flag_or_id():
    """Both is_bot=True and user_id match independently trigger [BOT] label."""
    entry_by_flag = _make_entry(5, _NOW, display_name="Bot A", user_id="x", is_bot=True)
    entry_by_id = _make_entry(0, _NOW, display_name="Bot B", user_id="bot_id", is_bot=False)

    result = format_channel_context([entry_by_flag, entry_by_id], bot_user_id="bot_id")

    assert "[BOT] Bot A" in result
    assert "[BOT] Bot B" in result


def test_no_bot_label_when_bot_user_id_not_provided():
    entry = _make_entry(0, _NOW, display_name="Paw", user_id="bot_123", is_bot=False)
    result = format_channel_context([entry], bot_user_id=None)
    assert "[BOT]" not in result


# ---------------------------------------------------------------------------
# Content truncation
# ---------------------------------------------------------------------------

def test_content_truncated_at_500_characters():
    long_content = "x" * 600
    entry = _make_entry(0, _NOW, content=long_content)
    result = format_channel_context([entry])

    # The truncated content should appear with ellipsis, not the full string.
    assert "x" * 500 + "..." in result
    assert "x" * 501 not in result


def test_content_at_exactly_500_characters_not_truncated():
    content = "a" * 500
    entry = _make_entry(0, _NOW, content=content)
    result = format_channel_context([entry])

    assert "a" * 500 in result
    assert "..." not in result


def test_short_content_not_truncated():
    entry = _make_entry(0, _NOW, content="Short message")
    result = format_channel_context([entry])
    assert "Short message" in result
    assert "..." not in result


# ---------------------------------------------------------------------------
# Attachment summary
# ---------------------------------------------------------------------------

def test_attachment_summary_appended_after_content():
    entry = _make_entry(0, _NOW, content="See this", attachments_summary="[image]")
    result = format_channel_context([entry])

    # Both content and attachment summary must appear, attachment after content.
    content_pos = result.index("See this")
    attachment_pos = result.index("[image]")
    assert content_pos < attachment_pos


def test_attachment_summary_shown_when_content_is_empty():
    entry = _make_entry(0, _NOW, content="", attachments_summary="[file: report.pdf]")
    result = format_channel_context([entry])
    assert "[file: report.pdf]" in result


def test_no_attachment_summary_when_none():
    entry = _make_entry(0, _NOW, content="Just text", attachments_summary=None)
    result = format_channel_context([entry])
    assert "None" not in result


# ---------------------------------------------------------------------------
# Special characters in content
# ---------------------------------------------------------------------------

def test_angle_brackets_in_content_preserved():
    """Angle brackets in message content should pass through unchanged."""
    entry = _make_entry(0, _NOW, content="Use <br> tags here")
    result = format_channel_context([entry])
    assert "<br>" in result


def test_quotes_in_content_preserved():
    entry = _make_entry(0, _NOW, content='She said "hello"')
    result = format_channel_context([entry])
    assert '"hello"' in result


# ---------------------------------------------------------------------------
# Naive datetime handling
# ---------------------------------------------------------------------------

def test_naive_datetimes_handled_without_error():
    """Entries with naive (no tzinfo) datetimes should not raise."""
    naive_now = datetime(2026, 3, 7, 12, 0, 0)  # no tzinfo
    entry = ChannelHistoryEntry(
        timestamp=naive_now - timedelta(minutes=3),
        user_id="u1",
        display_name="Alice",
        content="Naive time test",
    )
    last = ChannelHistoryEntry(
        timestamp=naive_now,
        user_id="u2",
        display_name="Bob",
        content="Last entry",
    )
    result = format_channel_context([entry, last])

    assert "[3m ago]" in result
    assert "Naive time test" in result
