"""Formatting helpers for cron tool output."""

import logging
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)


def _parse_timestamp(timestamp_str: str, timezone: str) -> datetime:
    """Parse ISO 8601 timestamp string to timezone-aware datetime.

    Args:
        timestamp_str: ISO 8601 formatted timestamp.
        timezone: Workspace timezone name (e.g., "UTC", "America/Denver").

    Returns:
        Timezone-aware datetime in UTC.

    Raises:
        ValueError: If timestamp format is invalid.
    """
    try:
        dt = datetime.fromisoformat(timestamp_str)

        # If naive, interpret in workspace timezone
        if dt.tzinfo is None:
            # Interpret naive timestamps in workspace timezone
            workspace_tz = ZoneInfo(timezone)
            dt = dt.replace(tzinfo=workspace_tz)
            # Convert to UTC for internal storage
            dt = dt.astimezone(UTC)
        else:
            # Convert to UTC
            dt = dt.astimezone(UTC)

        return dt

    except ValueError as e:
        raise ValueError(
            f"Invalid ISO 8601 timestamp: {timestamp_str}. "
            f"Expected format: 'YYYY-MM-DDTHH:MM:SS' or 'YYYY-MM-DDTHH:MM:SSZ'. "
            f"Error: {e}"
        ) from e


def _format_interval(seconds: int) -> str:
    """Format interval in human-readable form.

    Args:
        seconds: Interval in seconds.

    Returns:
        Human-readable string (e.g., "5 minutes", "2 hours").
    """
    if seconds < 60:
        return f"{seconds} seconds"
    elif seconds < 3600:
        minutes = seconds // 60
        return f"{minutes} minute{'s' if minutes != 1 else ''}"
    elif seconds < 86400:
        hours = seconds // 3600
        return f"{hours} hour{'s' if hours != 1 else ''}"
    else:
        days = seconds // 86400
        return f"{days} day{'s' if days != 1 else ''}"


def _format_time_until(seconds: float) -> str:
    """Format time until next run in human-readable form.

    Args:
        seconds: Seconds until next run (can be negative for overdue).

    Returns:
        Human-readable string (e.g., "in 5 minutes", "2 hours ago").
    """
    if seconds < 0:
        return f"{_format_interval(int(abs(seconds)))} ago (overdue)"

    if seconds < 60:
        return f"in {int(seconds)} seconds"
    elif seconds < 3600:
        minutes = int(seconds // 60)
        return f"in {minutes} minute{'s' if minutes != 1 else ''}"
    elif seconds < 86400:
        hours = int(seconds // 3600)
        return f"in {hours} hour{'s' if hours != 1 else ''}"
    else:
        days = int(seconds // 86400)
        return f"in {days} day{'s' if days != 1 else ''}"
