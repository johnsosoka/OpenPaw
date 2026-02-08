"""Tests for workspace timezone utilities."""

from datetime import datetime
from typing import Any
from unittest.mock import patch
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pytest

from openpaw.core.timezone import format_for_display, workspace_now


class TestWorkspaceNow:
    """Test workspace_now function."""

    @patch("openpaw.core.timezone.datetime")
    def test_workspace_now_mountain_time(self, mock_datetime: Any) -> None:
        """Test workspace_now returns timezone-aware datetime in Mountain Time."""
        fixed_time = datetime(2026, 2, 8, 10, 30, 0, tzinfo=ZoneInfo("America/Denver"))
        mock_datetime.now.return_value = fixed_time

        result = workspace_now("America/Denver")

        mock_datetime.now.assert_called_once_with(ZoneInfo("America/Denver"))
        assert result == fixed_time
        assert result.tzinfo is not None
        assert result.tzinfo == ZoneInfo("America/Denver")

    @patch("openpaw.core.timezone.datetime")
    def test_workspace_now_utc(self, mock_datetime: Any) -> None:
        """Test workspace_now returns timezone-aware datetime in UTC."""
        fixed_time = datetime(2026, 2, 8, 17, 30, 0, tzinfo=ZoneInfo("UTC"))
        mock_datetime.now.return_value = fixed_time

        result = workspace_now("UTC")

        mock_datetime.now.assert_called_once_with(ZoneInfo("UTC"))
        assert result == fixed_time
        assert result.tzinfo is not None
        assert result.tzinfo == ZoneInfo("UTC")

    @patch("openpaw.core.timezone.datetime")
    def test_workspace_now_default_utc(self, mock_datetime: Any) -> None:
        """Test workspace_now defaults to UTC when no timezone provided."""
        fixed_time = datetime(2026, 2, 8, 17, 30, 0, tzinfo=ZoneInfo("UTC"))
        mock_datetime.now.return_value = fixed_time

        result = workspace_now()

        mock_datetime.now.assert_called_once_with(ZoneInfo("UTC"))
        assert result == fixed_time
        assert result.tzinfo == ZoneInfo("UTC")

    def test_workspace_now_invalid_timezone(self) -> None:
        """Test workspace_now raises ZoneInfoNotFoundError for invalid timezone."""
        with pytest.raises(ZoneInfoNotFoundError):
            workspace_now("Invalid/Timezone")

    @patch("openpaw.core.timezone.datetime")
    def test_workspace_now_tokyo(self, mock_datetime: Any) -> None:
        """Test workspace_now with Tokyo timezone."""
        fixed_time = datetime(2026, 2, 9, 2, 30, 0, tzinfo=ZoneInfo("Asia/Tokyo"))
        mock_datetime.now.return_value = fixed_time

        result = workspace_now("Asia/Tokyo")

        mock_datetime.now.assert_called_once_with(ZoneInfo("Asia/Tokyo"))
        assert result == fixed_time
        assert result.tzinfo == ZoneInfo("Asia/Tokyo")


class TestFormatForDisplay:
    """Test format_for_display function."""

    def test_format_for_display_utc_to_mountain(self) -> None:
        """Test converting UTC datetime to Mountain Time for display."""
        utc_dt = datetime(2026, 2, 8, 17, 30, 0, tzinfo=ZoneInfo("UTC"))

        result = format_for_display(utc_dt, "America/Denver")

        # UTC 17:30 -> MST 10:30 (7-hour offset in winter)
        assert "2026-02-08" in result
        assert "10:30" in result
        assert "MST" in result

    def test_format_for_display_naive_to_mountain(self) -> None:
        """Test naive datetime treated as UTC then converted to Mountain Time."""
        naive_dt = datetime(2026, 2, 8, 17, 30, 0)

        result = format_for_display(naive_dt, "America/Denver")

        # Naive interpreted as UTC 17:30 -> MST 10:30
        assert "2026-02-08" in result
        assert "10:30" in result
        assert "MST" in result

    def test_format_for_display_aware_different_tz(self) -> None:
        """Test timezone-aware datetime from different timezone converts correctly."""
        tokyo_dt = datetime(2026, 2, 9, 2, 30, 0, tzinfo=ZoneInfo("Asia/Tokyo"))

        result = format_for_display(tokyo_dt, "America/Denver")

        # Tokyo 02:30 +09:00 -> MST 10:30 -07:00 (previous day)
        assert "2026-02-08" in result
        assert "10:30" in result
        assert "MST" in result

    def test_format_for_display_default_utc(self) -> None:
        """Test format_for_display defaults to UTC when no timezone provided."""
        utc_dt = datetime(2026, 2, 8, 17, 30, 0, tzinfo=ZoneInfo("UTC"))

        result = format_for_display(utc_dt)

        assert "2026-02-08" in result
        assert "17:30" in result
        assert "UTC" in result

    def test_format_for_display_default_format(self) -> None:
        """Test default format string produces expected output."""
        utc_dt = datetime(2026, 2, 8, 17, 30, 0, tzinfo=ZoneInfo("UTC"))

        result = format_for_display(utc_dt, "America/Denver")

        # Default format: "%Y-%m-%d %H:%M %Z"
        assert result == "2026-02-08 10:30 MST"

    def test_format_for_display_custom_format(self) -> None:
        """Test custom format string is respected."""
        utc_dt = datetime(2026, 2, 8, 17, 30, 0, tzinfo=ZoneInfo("UTC"))

        result = format_for_display(utc_dt, "America/Denver", fmt="%I:%M %p on %B %d, %Y (%Z)")

        assert "10:30 AM" in result
        assert "February 08, 2026" in result
        assert "MST" in result

    def test_format_for_display_invalid_timezone(self) -> None:
        """Test invalid timezone raises ZoneInfoNotFoundError."""
        utc_dt = datetime(2026, 2, 8, 17, 30, 0, tzinfo=ZoneInfo("UTC"))

        with pytest.raises(ZoneInfoNotFoundError):
            format_for_display(utc_dt, "Invalid/Timezone")

    def test_format_for_display_dst_boundary_spring_forward(self) -> None:
        """Test DST transition (spring forward) handles correctly."""
        # March 8, 2026 - DST starts (2:00 AM MST -> 3:00 AM MDT)
        # UTC 08:00 (1:00 AM MST) before DST
        before_dst = datetime(2026, 3, 8, 8, 0, 0, tzinfo=ZoneInfo("UTC"))
        result_before = format_for_display(before_dst, "America/Denver")
        assert "01:00" in result_before
        assert "MST" in result_before

        # UTC 10:00 (4:00 AM MDT) after DST
        after_dst = datetime(2026, 3, 8, 10, 0, 0, tzinfo=ZoneInfo("UTC"))
        result_after = format_for_display(after_dst, "America/Denver")
        assert "04:00" in result_after
        assert "MDT" in result_after

    def test_format_for_display_dst_boundary_fall_back(self) -> None:
        """Test DST transition (fall back) handles correctly."""
        # November 1, 2026 - DST ends (2:00 AM -> 1:00 AM)
        # UTC 07:00 (1:00 AM MDT) before fall back
        before_fallback = datetime(2026, 11, 1, 7, 0, 0, tzinfo=ZoneInfo("UTC"))
        result_before = format_for_display(before_fallback, "America/Denver")
        assert "01:00" in result_before
        assert "MDT" in result_before

        # UTC 08:00 (1:00 AM MST) after fall back
        after_fallback = datetime(2026, 11, 1, 8, 0, 0, tzinfo=ZoneInfo("UTC"))
        result_after = format_for_display(after_fallback, "America/Denver")
        assert "01:00" in result_after
        assert "MST" in result_after

    def test_format_for_display_midnight_crossing(self) -> None:
        """Test date changes correctly when crossing midnight."""
        # UTC 06:59 (11:59 PM MST previous day)
        late_night_utc = datetime(2026, 2, 9, 6, 59, 0, tzinfo=ZoneInfo("UTC"))
        result = format_for_display(late_night_utc, "America/Denver")
        assert "2026-02-08" in result
        assert "23:59" in result

        # UTC 07:01 (12:01 AM MST next day)
        early_morning_utc = datetime(2026, 2, 9, 7, 1, 0, tzinfo=ZoneInfo("UTC"))
        result = format_for_display(early_morning_utc, "America/Denver")
        assert "2026-02-09" in result
        assert "00:01" in result

    def test_format_for_display_preserves_microseconds(self) -> None:
        """Test microseconds are preserved when using custom format."""
        utc_dt = datetime(2026, 2, 8, 17, 30, 45, 123456, tzinfo=ZoneInfo("UTC"))

        result = format_for_display(utc_dt, "America/Denver", fmt="%Y-%m-%d %H:%M:%S.%f")

        assert "2026-02-08 10:30:45.123456" in result

    def test_format_for_display_naive_utc_assumption(self) -> None:
        """Test naive datetime is assumed UTC (not local time)."""
        # Create naive datetime
        naive_dt = datetime(2026, 2, 8, 12, 0, 0)

        # Convert to Mountain Time
        result = format_for_display(naive_dt, "America/Denver")

        # Should be interpreted as UTC 12:00 -> MST 05:00
        assert "05:00" in result
        assert "2026-02-08" in result
