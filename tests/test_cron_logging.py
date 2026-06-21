"""Tests for CronScheduler execution logging (_log_cron_event)."""

import json
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest

from openpaw.core.paths import CRON_LOG_JSONL
from openpaw.runtime.scheduling.cron import CronScheduler


@pytest.fixture
def tmp_workspace(tmp_path: Path) -> Path:
    """Create a temporary workspace directory."""
    workspace = tmp_path / "test_workspace"
    workspace.mkdir()
    return workspace


@pytest.fixture
def scheduler(tmp_workspace: Path) -> CronScheduler:
    """Create a minimal CronScheduler for testing _log_cron_event."""
    return CronScheduler(
        workspace_path=tmp_workspace,
        agent_factory=Mock(),
        channels={},
        workspace_name="gilfoyle",
    )


def _read_log_lines(workspace: Path) -> list[dict[str, Any]]:
    """Read all JSONL lines from the cron log file."""
    log_path = workspace / str(CRON_LOG_JSONL)
    return [json.loads(line) for line in log_path.read_text().splitlines() if line.strip()]


class TestLogCronEventWritesJsonl:
    """Verify that _log_cron_event writes the correct JSONL record."""

    def test_log_cron_event_writes_jsonl(self, scheduler: CronScheduler, tmp_workspace: Path) -> None:
        """A completed event is written as a valid JSONL record with required fields."""
        scheduler._log_cron_event(
            cron_name="daily-check",
            outcome="completed",
            duration_ms=4500.1,
            input_tokens=1234,
            output_tokens=567,
            total_tokens=1801,
            llm_calls=3,
            session_path="memory/sessions/cron/daily-check_20260321T090000.jsonl",
            delivery="channel",
            tools_used=["brave_search"],
        )

        lines = _read_log_lines(tmp_workspace)
        assert len(lines) == 1

        record = lines[0]
        assert record["workspace"] == "gilfoyle"
        assert record["cron_name"] == "daily-check"
        assert record["outcome"] == "completed"
        assert record["duration_ms"] == 4500.1
        assert record["input_tokens"] == 1234
        assert record["output_tokens"] == 567
        assert record["total_tokens"] == 1801
        assert record["llm_calls"] == 3
        assert record["session_path"] == "memory/sessions/cron/daily-check_20260321T090000.jsonl"
        assert record["delivery"] == "channel"
        assert record["tools_used"] == ["brave_search"]
        assert "timestamp" in record

    def test_log_cron_event_appends_multiple_records(
        self, scheduler: CronScheduler, tmp_workspace: Path
    ) -> None:
        """Multiple calls append multiple lines to the same file."""
        scheduler._log_cron_event(cron_name="job-a", outcome="completed")
        scheduler._log_cron_event(cron_name="job-b", outcome="error", error="timeout")

        lines = _read_log_lines(tmp_workspace)
        assert len(lines) == 2
        assert lines[0]["cron_name"] == "job-a"
        assert lines[1]["cron_name"] == "job-b"


class TestLogCronEventCreatesParentDir:
    """Verify that the parent directory is created if missing."""

    def test_log_cron_event_creates_parent_dir(self, tmp_path: Path) -> None:
        """Log file is created even when the workspace has no data/ directory yet."""
        # Use a completely new workspace directory with no sub-directories
        bare_workspace = tmp_path / "bare"
        bare_workspace.mkdir()

        # Build the scheduler directly without going through DynamicCronStore
        # by using a mock to avoid side-effect directory creation
        import unittest.mock as mock

        with mock.patch("openpaw.runtime.scheduling.cron.DynamicCronStore"):
            sched = CronScheduler(
                workspace_path=bare_workspace,
                agent_factory=Mock(),
                channels={},
                workspace_name="test",
            )

        log_path = bare_workspace / str(CRON_LOG_JSONL)
        # Manually remove the data dir to confirm mkdir(parents=True) does the work
        data_dir = log_path.parent
        if data_dir.exists():
            data_dir.rmdir()

        assert not data_dir.exists()

        sched._log_cron_event(cron_name="morning-check", outcome="completed")

        assert log_path.exists()
        lines = _read_log_lines(bare_workspace)
        assert len(lines) == 1


class TestLogCronEventOnError:
    """Verify error outcome records include the error field."""

    def test_log_cron_event_on_error_includes_error_field(
        self, scheduler: CronScheduler, tmp_workspace: Path
    ) -> None:
        """Error outcome record includes the error message."""
        scheduler._log_cron_event(
            cron_name="failing-job",
            outcome="error",
            error="Connection refused",
        )

        lines = _read_log_lines(tmp_workspace)
        record = lines[0]
        assert record["outcome"] == "error"
        assert record["error"] == "Connection refused"

    def test_log_cron_event_on_error_without_duration(
        self, scheduler: CronScheduler, tmp_workspace: Path
    ) -> None:
        """Error recorded without duration still writes a valid record."""
        scheduler._log_cron_event(
            cron_name="crashing-job",
            outcome="error",
            error="Unexpected exception",
        )

        lines = _read_log_lines(tmp_workspace)
        record = lines[0]
        assert record["cron_name"] == "crashing-job"
        assert "duration_ms" not in record


class TestLogCronEventOptionalFields:
    """Verify that None optional fields are omitted from the record."""

    def test_log_cron_event_optional_fields_absent_when_none(
        self, scheduler: CronScheduler, tmp_workspace: Path
    ) -> None:
        """Fields that are None are not included in the JSONL record."""
        scheduler._log_cron_event(cron_name="minimal-job", outcome="completed")

        lines = _read_log_lines(tmp_workspace)
        record = lines[0]

        # Required fields always present
        assert "timestamp" in record
        assert "workspace" in record
        assert "cron_name" in record
        assert "outcome" in record

        # Optional fields absent when not provided
        assert "duration_ms" not in record
        assert "error" not in record
        assert "input_tokens" not in record
        assert "output_tokens" not in record
        assert "total_tokens" not in record
        assert "llm_calls" not in record
        assert "session_path" not in record
        assert "delivery" not in record
        assert "tools_used" not in record

    def test_log_cron_event_tools_used_absent_when_empty_list(
        self, scheduler: CronScheduler, tmp_workspace: Path
    ) -> None:
        """tools_used is omitted when passed as an empty list (falsy)."""
        scheduler._log_cron_event(
            cron_name="no-tools-job",
            outcome="completed",
            tools_used=[],
        )

        lines = _read_log_lines(tmp_workspace)
        assert "tools_used" not in lines[0]


class TestLogCronEventDynamicTaskPrefix:
    """Verify that dynamic tasks use the 'dynamic_' prefix for cron_name."""

    def test_log_cron_event_dynamic_task_prefix(
        self, scheduler: CronScheduler, tmp_workspace: Path
    ) -> None:
        """Dynamic tasks use 'dynamic_<id[:8]>' as the cron_name."""
        task_id = "abcdef1234567890"
        expected_name = f"dynamic_{task_id[:8]}"

        scheduler._log_cron_event(
            cron_name=expected_name,
            outcome="completed",
            duration_ms=1200.5,
        )

        lines = _read_log_lines(tmp_workspace)
        record = lines[0]
        assert record["cron_name"] == "dynamic_abcdef12"
        assert record["cron_name"].startswith("dynamic_")

    def test_log_cron_event_dynamic_prefix_is_eight_chars(
        self, scheduler: CronScheduler, tmp_workspace: Path
    ) -> None:
        """The ID suffix in dynamic cron_name is exactly 8 characters."""
        full_id = "0123456789abcdef"
        cron_name = f"dynamic_{full_id[:8]}"

        scheduler._log_cron_event(cron_name=cron_name, outcome="completed")

        lines = _read_log_lines(tmp_workspace)
        name = lines[0]["cron_name"]
        prefix = "dynamic_"
        assert name.startswith(prefix)
        assert len(name) == len(prefix) + 8


class TestLogCronEventOsError:
    """Verify OSError is handled gracefully without crashing."""

    def test_log_cron_event_os_error_does_not_raise(
        self, scheduler: CronScheduler, tmp_workspace: Path, caplog: Any
    ) -> None:
        """An OSError during log write is caught and logged as a warning."""
        import logging
        import unittest.mock as mock

        # Ensure the data/ directory exists so mkdir succeeds before open
        data_dir = tmp_workspace / str(CRON_LOG_JSONL.parent)
        data_dir.mkdir(parents=True, exist_ok=True)

        # Patch Path.open to raise OSError (the code calls log_path.open(...))
        with caplog.at_level(logging.WARNING, logger="openpaw.runtime.scheduling.cron"):
            with mock.patch("pathlib.Path.open", side_effect=OSError("disk full")):
                # Should not raise
                scheduler._log_cron_event(cron_name="some-job", outcome="completed")

        assert any("Failed to write cron log" in record.message for record in caplog.records)
