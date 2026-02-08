"""Tests for CronToolBuiltin timezone handling in _parse_timestamp()."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from openpaw.builtins.tools.cron import CronToolBuiltin


@pytest.fixture
def workspace_path(tmp_path: Path) -> Path:
    """Create a temporary workspace directory."""
    return tmp_path / "test_workspace"


@pytest.fixture
def cron_tool_denver(workspace_path: Path) -> CronToolBuiltin:
    """Create a CronToolBuiltin instance with America/Denver timezone."""
    return CronToolBuiltin(
        config={
            "workspace_path": workspace_path,
            "timezone": "America/Denver",
        }
    )


@pytest.fixture
def cron_tool_utc(workspace_path: Path) -> CronToolBuiltin:
    """Create a CronToolBuiltin instance with UTC timezone."""
    return CronToolBuiltin(
        config={
            "workspace_path": workspace_path,
            "timezone": "UTC",
        }
    )


def test_parse_naive_timestamp_with_denver_timezone(cron_tool_denver: CronToolBuiltin):
    """Naive timestamps should be interpreted in workspace timezone (America/Denver)."""
    # February 8, 2026 at 2pm - this is during Mountain Standard Time (MST, UTC-7)
    naive_timestamp = "2026-02-08T14:00:00"

    result = cron_tool_denver._parse_timestamp(naive_timestamp)

    # Should be interpreted as 2pm Denver time, which is 21:00 UTC
    expected = datetime(2026, 2, 8, 21, 0, 0, tzinfo=UTC)
    assert result == expected
    assert result.tzinfo == UTC


def test_parse_naive_timestamp_with_utc_timezone(cron_tool_utc: CronToolBuiltin):
    """Naive timestamps with UTC workspace should be treated as UTC."""
    naive_timestamp = "2026-02-08T14:00:00"

    result = cron_tool_utc._parse_timestamp(naive_timestamp)

    # Should be interpreted as 2pm UTC
    expected = datetime(2026, 2, 8, 14, 0, 0, tzinfo=UTC)
    assert result == expected
    assert result.tzinfo == UTC


def test_parse_explicit_utc_timestamp(cron_tool_denver: CronToolBuiltin):
    """Explicit UTC timestamps (with Z suffix) should be 2pm UTC regardless of workspace timezone."""
    utc_timestamp = "2026-02-08T14:00:00Z"

    result = cron_tool_denver._parse_timestamp(utc_timestamp)

    # Should be 2pm UTC
    expected = datetime(2026, 2, 8, 14, 0, 0, tzinfo=UTC)
    assert result == expected
    assert result.tzinfo == UTC


def test_parse_explicit_offset_timestamp(cron_tool_denver: CronToolBuiltin):
    """Explicit timezone offset should be respected regardless of workspace timezone."""
    # 2pm Mountain Time (MST = UTC-7)
    offset_timestamp = "2026-02-08T14:00:00-07:00"

    result = cron_tool_denver._parse_timestamp(offset_timestamp)

    # Should be 2pm Mountain Time = 21:00 UTC
    expected = datetime(2026, 2, 8, 21, 0, 0, tzinfo=UTC)
    assert result == expected
    assert result.tzinfo == UTC


def test_parse_explicit_offset_timestamp_with_utc_workspace(cron_tool_utc: CronToolBuiltin):
    """Explicit timezone offset should work even with UTC workspace."""
    # 2pm Mountain Time (MST = UTC-7)
    offset_timestamp = "2026-02-08T14:00:00-07:00"

    result = cron_tool_utc._parse_timestamp(offset_timestamp)

    # Should be 2pm Mountain Time = 21:00 UTC
    expected = datetime(2026, 2, 8, 21, 0, 0, tzinfo=UTC)
    assert result == expected
    assert result.tzinfo == UTC


def test_parse_naive_timestamp_dst_transition(cron_tool_denver: CronToolBuiltin):
    """Test naive timestamp during DST transition (if applicable)."""
    # March 9, 2026 at 2pm - this is during Mountain Daylight Time (MDT, UTC-6)
    naive_timestamp = "2026-03-09T14:00:00"

    result = cron_tool_denver._parse_timestamp(naive_timestamp)

    # Should be interpreted as 2pm Denver time (MDT), which is 20:00 UTC
    expected = datetime(2026, 3, 9, 20, 0, 0, tzinfo=UTC)
    assert result == expected
    assert result.tzinfo == UTC


def test_parse_invalid_timestamp_raises_error(cron_tool_denver: CronToolBuiltin):
    """Invalid timestamp format should raise ValueError."""
    invalid_timestamp = "not-a-timestamp"

    with pytest.raises(ValueError, match="Invalid ISO 8601 timestamp"):
        cron_tool_denver._parse_timestamp(invalid_timestamp)


def test_parse_timestamp_preserves_utc_internal_format(cron_tool_denver: CronToolBuiltin):
    """All parsed timestamps should be converted to UTC for internal storage."""
    timestamps = [
        "2026-02-08T14:00:00",        # Naive
        "2026-02-08T14:00:00Z",       # Explicit UTC
        "2026-02-08T14:00:00-07:00",  # Explicit offset
    ]

    for timestamp in timestamps:
        result = cron_tool_denver._parse_timestamp(timestamp)
        assert result.tzinfo == UTC, f"Timestamp {timestamp} should be converted to UTC"
