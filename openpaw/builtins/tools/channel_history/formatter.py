"""Output formatting for channel history browsing."""

import logging
from datetime import UTC
from typing import Any

logger = logging.getLogger(__name__)

# Per-message content truncation (consistent with format_channel_context)
_MESSAGE_TRUNCATION = 500

# Total output cap (consistent with read_file safety valve)
_OUTPUT_CAP = 50_000

# Over-fetch multiplier when filters are active
_OVER_FETCH_RATIO = 3

# Hard cap on adapter fetch when filters are active
_OVER_FETCH_CAP = 300


def _build_filter_qualifier(
    keyword: str | None,
    user: str | None,
    include_bots: bool,
) -> str:
    """Build a human-readable description of active filters for no-result messages.

    Args:
        keyword: Active keyword filter, or None.
        user: Active user filter, or None.
        include_bots: Whether bot messages are included.

    Returns:
        Qualifier string like " (keyword='deploy', user='Alice')" or "".
    """
    parts = []
    if keyword:
        parts.append(f"keyword='{keyword}'")
    if user:
        parts.append(f"user='{user}'")
    if not include_bots:
        parts.append("bots excluded")
    return f" ({', '.join(parts)})" if parts else ""


def _format_history_output(
    entries: list[Any],
    channel_name: str,
    adapter_type: str,
    requested_limit: int,
    matched_count: int,
    before_cursor: str | None,
    content_truncation: int,
) -> str:
    """Format channel history entries as readable text.

    Args:
        entries: ChannelHistoryEntry list (already filtered and truncated to limit).
        channel_name: Human-readable channel name for the header.
        adapter_type: Platform type string (e.g., "discord") for the header.
        requested_limit: The limit the agent requested.
        matched_count: Total matched entries before truncation to limit.
        before_cursor: The 'before' cursor used in this request, for header display.
        content_truncation: Per-message character truncation limit.

    Returns:
        Formatted multi-line string suitable for agent consumption.
    """
    lines: list[str] = []

    # Header
    count = len(entries)
    lines.append(
        f"[Channel History: #{channel_name} ({adapter_type}) — {count} message(s), oldest first]"
    )
    if before_cursor:
        lines.append(f"[Showing messages before ID: {before_cursor}]")
    lines.append("")

    # Message lines
    for entry in entries:
        timestamp_str = _format_timestamp(entry.timestamp)
        content = entry.content
        if len(content) > content_truncation:
            content = content[:content_truncation] + "..."

        suffix = ""
        if entry.attachments_summary:
            suffix = f" {entry.attachments_summary}"

        lines.append(
            f"[{timestamp_str}] {entry.display_name} (id:{entry.user_id}): {content}{suffix}"
        )

    # Pagination footer
    lines.append("")
    if entries:
        oldest_id = entries[0].message_id
        if oldest_id:
            lines.append(
                f"[Pagination: oldest_message_id={oldest_id} — "
                f"use before=\"{oldest_id}\" to load older messages]"
            )

    if matched_count > requested_limit:
        lines.append(
            f"[Showing {requested_limit} of {matched_count} matched — "
            f"use before= to continue paging]"
        )
    elif count == requested_limit:
        lines.append(
            f"[Showing {count} of {requested_limit} requested — more history may be available]"
        )

    return "\n".join(lines)


def _format_timestamp(ts: Any) -> str:
    """Format a datetime to a consistent UTC string for agent output.

    Args:
        ts: datetime object (naive or timezone-aware).

    Returns:
        Formatted string like "2026-03-08 14:30 UTC".
    """
    try:
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        utc_ts = ts.astimezone(UTC)
        return utc_ts.strftime("%Y-%m-%d %H:%M UTC")  # type: ignore[no-any-return]
    except Exception:
        return str(ts)
