"""Tests for ChannelLogger — persistent JSONL channel message logger."""

import asyncio
import json
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

from openpaw.model.channel import ChannelEvent
from openpaw.runtime.channel_logger import ChannelLogger

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_event(
    *,
    server_name: str | None = "My Server",
    server_id: str | None = "111222333",
    channel_label: str = "general",
    channel_id: str = "444555666",
    channel_name: str = "discord",
    user_id: str = "987654321",
    display_name: str = "Alice",
    content: str = "Hello world",
    attachment_names: list[str] | None = None,
    message_id: str = "1234567890",
    timestamp: datetime | None = None,
) -> ChannelEvent:
    """Build a ChannelEvent with sensible defaults."""
    return ChannelEvent(
        timestamp=timestamp or datetime(2026, 3, 7, 14, 30, 0, tzinfo=UTC),
        channel_name=channel_name,
        channel_id=channel_id,
        channel_label=channel_label,
        server_name=server_name,
        server_id=server_id,
        user_id=user_id,
        display_name=display_name,
        content=content,
        attachment_names=attachment_names or [],
        message_id=message_id,
    )


def _make_logger(tmp_path: Path, **kwargs) -> ChannelLogger:
    """Create a ChannelLogger pointed at a temp workspace."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return ChannelLogger(workspace, **kwargs)


def _channel_logs_dir(tmp_path: Path) -> Path:
    return tmp_path / "workspace" / "memory" / "logs" / "channel"


def _read_lines(path: Path) -> list[dict]:
    """Read all JSONL lines from a file."""
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# Directory structure
# ---------------------------------------------------------------------------

def test_log_event_creates_correct_directory_structure(tmp_path: Path) -> None:
    """log_event() creates server/channel subdirectory hierarchy."""
    channel_logger = _make_logger(tmp_path)
    event = _make_event(server_name="My Server", channel_label="general")

    asyncio.run(channel_logger.log_event(event))

    logs_dir = _channel_logs_dir(tmp_path)
    # sanitize_filename lowercases and replaces spaces with underscores
    assert (logs_dir / "my_server" / "general").is_dir()


def test_log_event_creates_daily_log_file(tmp_path: Path) -> None:
    """log_event() creates a YYYY-MM-DD.jsonl file inside the channel dir."""
    channel_logger = _make_logger(tmp_path)
    event = _make_event()

    asyncio.run(channel_logger.log_event(event))

    logs_dir = _channel_logs_dir(tmp_path)
    # Find any .jsonl file inside the hierarchy
    jsonl_files = list(logs_dir.rglob("*.jsonl"))
    assert len(jsonl_files) == 1
    assert jsonl_files[0].suffix == ".jsonl"
    # Stem must be a valid date
    stem = jsonl_files[0].stem
    datetime.strptime(stem, "%Y-%m-%d")  # raises if not a date


# ---------------------------------------------------------------------------
# JSONL record format
# ---------------------------------------------------------------------------

def test_log_event_writes_all_expected_fields(tmp_path: Path) -> None:
    """log_event() writes a complete, valid JSONL record with all required keys."""
    channel_logger = _make_logger(tmp_path)
    event = _make_event(
        server_name="My Server",
        server_id="111",
        channel_id="444",
        user_id="987",
        display_name="Alice",
        content="Has anyone tried the new deployment?",
        attachment_names=["screenshot.png"],
        message_id="msg42",
    )

    asyncio.run(channel_logger.log_event(event))

    jsonl_files = list(_channel_logs_dir(tmp_path).rglob("*.jsonl"))
    records = _read_lines(jsonl_files[0])

    assert len(records) == 1
    rec = records[0]
    assert rec["msg_id"] == "msg42"
    assert rec["user_id"] == "987"
    assert rec["display_name"] == "Alice"
    assert rec["content"] == "Has anyone tried the new deployment?"
    assert rec["attachments"] == ["screenshot.png"]
    assert rec["channel_id"] == "444"
    assert rec["server_id"] == "111"
    assert "ts" in rec


def test_log_event_timestamp_is_utc_iso8601(tmp_path: Path) -> None:
    """Timestamps in the log are always UTC ISO 8601."""
    channel_logger = _make_logger(tmp_path)
    ts = datetime(2026, 3, 7, 14, 30, 0, tzinfo=UTC)
    event = _make_event(timestamp=ts)

    asyncio.run(channel_logger.log_event(event))

    jsonl_files = list(_channel_logs_dir(tmp_path).rglob("*.jsonl"))
    rec = _read_lines(jsonl_files[0])[0]
    # Should be parseable and UTC
    parsed = datetime.fromisoformat(rec["ts"])
    assert parsed.utcoffset() is not None
    assert parsed.utcoffset().total_seconds() == 0


def test_log_event_normalises_naive_timestamp_to_utc(tmp_path: Path) -> None:
    """Naive timestamps (no tzinfo) are treated as UTC."""
    channel_logger = _make_logger(tmp_path)
    naive_ts = datetime(2026, 3, 7, 10, 0, 0)  # no tzinfo
    event = _make_event(timestamp=naive_ts)

    asyncio.run(channel_logger.log_event(event))

    jsonl_files = list(_channel_logs_dir(tmp_path).rglob("*.jsonl"))
    rec = _read_lines(jsonl_files[0])[0]
    parsed = datetime.fromisoformat(rec["ts"])
    assert parsed.utcoffset().total_seconds() == 0


# ---------------------------------------------------------------------------
# Append behaviour
# ---------------------------------------------------------------------------

def test_log_event_appends_to_existing_file(tmp_path: Path) -> None:
    """Multiple log_event() calls for the same day append to one file."""
    channel_logger = _make_logger(tmp_path)
    event1 = _make_event(message_id="msg1", content="First message")
    event2 = _make_event(message_id="msg2", content="Second message")

    asyncio.run(channel_logger.log_event(event1))
    asyncio.run(channel_logger.log_event(event2))

    jsonl_files = list(_channel_logs_dir(tmp_path).rglob("*.jsonl"))
    assert len(jsonl_files) == 1
    records = _read_lines(jsonl_files[0])
    assert len(records) == 2
    assert records[0]["msg_id"] == "msg1"
    assert records[1]["msg_id"] == "msg2"


def test_log_event_creates_separate_file_per_channel(tmp_path: Path) -> None:
    """Events from different channels produce separate log files."""
    channel_logger = _make_logger(tmp_path)
    event_general = _make_event(channel_label="general", channel_id="111")
    event_random = _make_event(channel_label="random", channel_id="222")

    asyncio.run(channel_logger.log_event(event_general))
    asyncio.run(channel_logger.log_event(event_random))

    jsonl_files = list(_channel_logs_dir(tmp_path).rglob("*.jsonl"))
    assert len(jsonl_files) == 2


# ---------------------------------------------------------------------------
# DM exclusion
# ---------------------------------------------------------------------------

def test_log_event_skips_dm_events(tmp_path: Path) -> None:
    """Events with server_name=None (DMs) are silently skipped."""
    channel_logger = _make_logger(tmp_path)
    dm_event = _make_event(server_name=None, server_id=None)

    asyncio.run(channel_logger.log_event(dm_event))

    logs_dir = _channel_logs_dir(tmp_path)
    assert not logs_dir.exists() or not list(logs_dir.rglob("*.jsonl"))


# ---------------------------------------------------------------------------
# Filename sanitisation
# ---------------------------------------------------------------------------

def test_log_event_sanitises_server_name(tmp_path: Path) -> None:
    """Server names with special characters are sanitised for directory paths."""
    channel_logger = _make_logger(tmp_path)
    event = _make_event(server_name="My Awesome Server! #1", channel_label="general")

    asyncio.run(channel_logger.log_event(event))

    logs_dir = _channel_logs_dir(tmp_path)
    server_dirs = [d for d in logs_dir.iterdir() if d.is_dir()]
    assert len(server_dirs) == 1
    # Must be a valid directory name (no spaces, no special chars)
    name = server_dirs[0].name
    assert " " not in name
    assert "!" not in name
    assert "#" not in name


def test_log_event_sanitises_channel_name(tmp_path: Path) -> None:
    """Channel labels with special characters are sanitised for directory paths."""
    channel_logger = _make_logger(tmp_path)
    event = _make_event(channel_label="off-topic & memes")

    asyncio.run(channel_logger.log_event(event))

    logs_dir = _channel_logs_dir(tmp_path)
    jsonl_files = list(logs_dir.rglob("*.jsonl"))
    assert len(jsonl_files) == 1
    channel_dir = jsonl_files[0].parent
    assert " " not in channel_dir.name
    assert "&" not in channel_dir.name


# ---------------------------------------------------------------------------
# Error resilience (best-effort)
# ---------------------------------------------------------------------------

def test_log_event_does_not_propagate_errors(tmp_path: Path) -> None:
    """Errors during log_event() are swallowed and never raise to the caller."""
    # Make the workspace read-only to provoke an I/O error.
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    logs_dir = workspace / "memory" / "logs" / "channel"
    logs_dir.mkdir(parents=True)
    logs_dir.chmod(0o444)

    channel_logger = ChannelLogger(workspace)
    event = _make_event()

    # Must not raise.
    asyncio.run(channel_logger.log_event(event))

    logs_dir.chmod(0o755)  # restore so tmp_path cleanup works


# ---------------------------------------------------------------------------
# archive_old_logs
# ---------------------------------------------------------------------------

def _write_log_file(
    logs_dir: Path, server: str, channel: str, date_str: str, content: str = ""
) -> Path:
    """Write a stub log file at the expected path."""
    path = logs_dir / server / channel / f"{date_str}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content or json.dumps({"ts": "2026-01-01T00:00:00+00:00"}) + "\n")
    return path


def test_archive_old_logs_moves_old_files(tmp_path: Path) -> None:
    """archive_old_logs() moves files older than retention_days to _archive/."""
    channel_logger = _make_logger(tmp_path, retention_days=30)
    logs_dir = _channel_logs_dir(tmp_path)

    old_date = (datetime.now(UTC).date() - timedelta(days=60)).strftime("%Y-%m-%d")
    old_file = _write_log_file(logs_dir, "my_server", "general", old_date)

    count = channel_logger.archive_old_logs()

    assert count == 1
    assert not old_file.exists()
    archive_path = logs_dir / "_archive" / "my_server" / "general" / f"{old_date}.jsonl"
    assert archive_path.exists()


def test_archive_old_logs_leaves_recent_files(tmp_path: Path) -> None:
    """archive_old_logs() does not touch files within the retention window."""
    channel_logger = _make_logger(tmp_path, retention_days=30)
    logs_dir = _channel_logs_dir(tmp_path)

    recent_date = (datetime.now(UTC).date() - timedelta(days=5)).strftime("%Y-%m-%d")
    recent_file = _write_log_file(logs_dir, "my_server", "general", recent_date)

    count = channel_logger.archive_old_logs()

    assert count == 0
    assert recent_file.exists()


def test_archive_old_logs_preserves_server_channel_structure(tmp_path: Path) -> None:
    """Archived files are stored under _archive/{server}/{channel}/."""
    channel_logger = _make_logger(tmp_path, retention_days=30)
    logs_dir = _channel_logs_dir(tmp_path)

    old_date = (datetime.now(UTC).date() - timedelta(days=90)).strftime("%Y-%m-%d")
    _write_log_file(logs_dir, "corp_server", "announcements", old_date)

    channel_logger.archive_old_logs()

    archive_file = logs_dir / "_archive" / "corp_server" / "announcements" / f"{old_date}.jsonl"
    assert archive_file.exists()


def test_archive_old_logs_cleans_empty_source_directories(tmp_path: Path) -> None:
    """Empty source directories are removed after all their files are archived."""
    channel_logger = _make_logger(tmp_path, retention_days=30)
    logs_dir = _channel_logs_dir(tmp_path)

    old_date = (datetime.now(UTC).date() - timedelta(days=45)).strftime("%Y-%m-%d")
    _write_log_file(logs_dir, "my_server", "general", old_date)

    channel_logger.archive_old_logs()

    # The source server/channel directories should be gone (empty after archival).
    assert not (logs_dir / "my_server" / "general").exists()
    assert not (logs_dir / "my_server").exists()


def test_archive_old_logs_returns_correct_count(tmp_path: Path) -> None:
    """archive_old_logs() returns the exact number of files it moved."""
    channel_logger = _make_logger(tmp_path, retention_days=30)
    logs_dir = _channel_logs_dir(tmp_path)

    old_date_1 = (datetime.now(UTC).date() - timedelta(days=60)).strftime("%Y-%m-%d")
    old_date_2 = (datetime.now(UTC).date() - timedelta(days=90)).strftime("%Y-%m-%d")
    recent_date = (datetime.now(UTC).date() - timedelta(days=5)).strftime("%Y-%m-%d")

    _write_log_file(logs_dir, "srv", "chan", old_date_1)
    _write_log_file(logs_dir, "srv", "chan", old_date_2)
    _write_log_file(logs_dir, "srv", "chan", recent_date)

    count = channel_logger.archive_old_logs()

    assert count == 2


def test_archive_old_logs_handles_empty_directory(tmp_path: Path) -> None:
    """archive_old_logs() returns 0 gracefully when no log directory exists."""
    channel_logger = _make_logger(tmp_path)

    count = channel_logger.archive_old_logs()

    assert count == 0


def test_archive_old_logs_does_not_re_archive_existing_archive(tmp_path: Path) -> None:
    """Files already in _archive/ are not moved again."""
    channel_logger = _make_logger(tmp_path, retention_days=30)
    logs_dir = _channel_logs_dir(tmp_path)

    old_date = (datetime.now(UTC).date() - timedelta(days=60)).strftime("%Y-%m-%d")
    # Write directly into _archive/ to simulate an already-archived file.
    already_archived = logs_dir / "_archive" / "srv" / "chan" / f"{old_date}.jsonl"
    already_archived.parent.mkdir(parents=True, exist_ok=True)
    already_archived.write_text("{}\n")

    count = channel_logger.archive_old_logs()

    assert count == 0
    assert already_archived.exists()  # untouched


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------

def test_concurrent_writes_do_not_corrupt_file(tmp_path: Path) -> None:
    """Concurrent synchronous writes from multiple threads produce valid JSONL."""
    channel_logger = _make_logger(tmp_path)
    n_threads = 20
    n_events_per_thread = 10
    errors: list[Exception] = []

    def write_events() -> None:
        for i in range(n_events_per_thread):
            event = _make_event(message_id=f"msg_{threading.current_thread().name}_{i}")
            try:
                channel_logger._write_event(event)
            except Exception as exc:
                errors.append(exc)

    threads = [threading.Thread(target=write_events, name=f"t{i}") for i in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors

    jsonl_files = list(_channel_logs_dir(tmp_path).rglob("*.jsonl"))
    assert len(jsonl_files) == 1

    records = _read_lines(jsonl_files[0])
    assert len(records) == n_threads * n_events_per_thread


# ---------------------------------------------------------------------------
# JSONL format validation
# ---------------------------------------------------------------------------

def test_each_line_is_valid_json(tmp_path: Path) -> None:
    """Every line written to the log file is valid JSON."""
    channel_logger = _make_logger(tmp_path)

    for i in range(5):
        event = _make_event(
            message_id=f"msg{i}",
            content=f"Message {i}",
            attachment_names=[f"file{i}.png"] if i % 2 == 0 else [],
        )
        asyncio.run(channel_logger.log_event(event))

    jsonl_files = list(_channel_logs_dir(tmp_path).rglob("*.jsonl"))
    raw_lines = jsonl_files[0].read_text(encoding="utf-8").splitlines()

    assert len(raw_lines) == 5
    for line in raw_lines:
        parsed = json.loads(line)  # raises json.JSONDecodeError on invalid JSON
        assert isinstance(parsed, dict)
