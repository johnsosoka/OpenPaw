"""Workspace timezone utilities."""

from datetime import datetime
from zoneinfo import ZoneInfo


def workspace_now(timezone_str: str = "UTC") -> datetime:
    """Get current datetime in workspace timezone.

    Args:
        timezone_str: IANA timezone identifier (e.g., 'America/Denver', 'UTC').

    Returns:
        Timezone-aware datetime in the specified timezone.

    Raises:
        ZoneInfoNotFoundError: If the timezone identifier is invalid.

    Examples:
        >>> workspace_now("America/Denver")
        datetime.datetime(2026, 2, 8, 10, 30, 0, 0, tzinfo=zoneinfo.ZoneInfo(key='America/Denver'))
        >>> workspace_now()  # Defaults to UTC
        datetime.datetime(2026, 2, 8, 17, 30, 0, 0, tzinfo=zoneinfo.ZoneInfo(key='UTC'))
    """
    return datetime.now(ZoneInfo(timezone_str))


def format_for_display(
    dt: datetime,
    timezone_str: str = "UTC",
    fmt: str = "%Y-%m-%d %H:%M %Z",
) -> str:
    """Format a datetime for display in workspace timezone.

    Converts UTC-stored datetimes to workspace timezone for user-facing output.
    Assumes naive datetimes are UTC.

    Args:
        dt: Datetime to format (naive or timezone-aware).
        timezone_str: IANA timezone identifier for display timezone.
        fmt: strftime format string (default: "%Y-%m-%d %H:%M %Z").

    Returns:
        Formatted datetime string in the specified timezone.

    Raises:
        ZoneInfoNotFoundError: If the timezone identifier is invalid.

    Examples:
        >>> utc_dt = datetime(2026, 2, 8, 17, 30, tzinfo=ZoneInfo("UTC"))
        >>> format_for_display(utc_dt, "America/Denver")
        '2026-02-08 10:30 MST'
        >>> naive_dt = datetime(2026, 2, 8, 17, 30)
        >>> format_for_display(naive_dt, "America/Denver")
        '2026-02-08 10:30 MST'
    """
    tz = ZoneInfo(timezone_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    return dt.astimezone(tz).strftime(fmt)
