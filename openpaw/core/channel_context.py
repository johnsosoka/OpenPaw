"""Utility for formatting channel history entries as XML context blocks.

This module is a pure formatting layer -- no I/O, no framework dependencies.
It converts a list of ChannelHistoryEntry dataclasses into an XML string
suitable for prepending to an agent's inbound message content.
"""

from datetime import UTC, datetime

from openpaw.model.channel import ChannelHistoryEntry

_CONTENT_TRUNCATION_LIMIT = 500


def _ensure_aware(dt: datetime) -> datetime:
    """Return a timezone-aware datetime, assuming UTC if naive."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def _relative_timestamp(entry_time: datetime, reference_time: datetime) -> str:
    """Compute a human-readable relative timestamp string.

    Both arguments must be timezone-aware datetimes.

    Args:
        entry_time: The timestamp of the history entry.
        reference_time: The reference point (typically the last entry's timestamp).

    Returns:
        A compact relative string such as "just now", "5m ago", "1h ago",
        "1d ago", or "Mar 01" for entries older than 7 days.
    """
    delta_seconds = max(0.0, (reference_time - entry_time).total_seconds())

    minutes = int(delta_seconds // 60)
    hours = int(delta_seconds // 3600)
    days = int(delta_seconds // 86400)

    if minutes < 1:
        return "just now"
    if hours < 1:
        return f"{minutes}m ago"
    if days < 1:
        return f"{hours}h ago"
    if days < 7:
        return f"{days}d ago"

    return entry_time.strftime("%b %d")


def _format_entry_line(
    entry: ChannelHistoryEntry,
    reference_time: datetime,
    bot_user_id: str | None,
) -> str:
    """Format a single history entry as a timestamped display line.

    Args:
        entry: The history entry to format.
        reference_time: Timezone-aware reference point for relative timestamps.
        bot_user_id: The bot's user ID; messages matching this ID are labelled [BOT].

    Returns:
        A single formatted line string.
    """
    entry_time = _ensure_aware(entry.timestamp)
    timestamp_str = _relative_timestamp(entry_time, reference_time)

    is_bot_message = entry.is_bot or (
        bot_user_id is not None and entry.user_id == bot_user_id
    )
    display_name = f"[BOT] {entry.display_name}" if is_bot_message else entry.display_name

    content = entry.content
    if len(content) > _CONTENT_TRUNCATION_LIMIT:
        content = content[:_CONTENT_TRUNCATION_LIMIT] + "..."

    parts = [content] if content else []
    if entry.attachments_summary:
        parts.append(entry.attachments_summary)

    body = " ".join(parts)

    return f"[{timestamp_str}] {display_name}: {body}"


def format_channel_context(
    entries: list[ChannelHistoryEntry],
    bot_user_id: str | None = None,
    channel_name: str = "unknown",
    source: str = "discord",
) -> str:
    """Format channel history entries as an XML context block.

    The returned string is intended to be prepended to the triggering message's
    content so the agent has awareness of the recent conversation that preceded
    the current message.

    Relative timestamps are computed against the LAST entry's timestamp (the
    most recent message), keeping them self-consistent regardless of when this
    function is called after processing.

    Args:
        entries: History entries in chronological order (oldest first).
        bot_user_id: The bot's platform user ID. Messages whose user_id matches
            are labelled [BOT] in addition to those already flagged by is_bot.
        channel_name: Human-readable name of the channel (e.g., "general").
        source: Channel type identifier (e.g., "discord", "telegram").

    Returns:
        XML-tagged context string, or empty string if entries is empty.

    Example output::

        <channel_context source="discord" channel="general" messages="3">
        [5m ago] Alice: Has anyone looked at the PR?
        [3m ago] Bob: Yeah I left comments
        [1m ago] Alice: @bot please review PR #42
        </channel_context>
    """
    if not entries:
        return ""

    reference_time = _ensure_aware(entries[-1].timestamp)

    lines = [
        _format_entry_line(entry, reference_time, bot_user_id)
        for entry in entries
    ]

    message_count = len(entries)
    header = f'<channel_context source="{source}" channel="{channel_name}" messages="{message_count}">'
    body = "\n".join(lines)
    return f"{header}\n{body}\n</channel_context>"
