"""Tests for token usage logger and reader."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from openpaw.agent.metrics import InvocationMetrics, TokenUsageLogger, TokenUsageReader


@pytest.fixture
def temp_workspace(tmp_path: Path) -> Path:
    """Create a temporary workspace directory."""
    return tmp_path / "test_workspace"


@pytest.fixture
def logger(temp_workspace: Path) -> TokenUsageLogger:
    """Create a TokenUsageLogger instance."""
    return TokenUsageLogger(temp_workspace)


@pytest.fixture
def reader(temp_workspace: Path) -> TokenUsageReader:
    """Create a TokenUsageReader instance."""
    return TokenUsageReader(temp_workspace)


@pytest.fixture
def sample_metrics() -> InvocationMetrics:
    """Create sample metrics for testing."""
    return InvocationMetrics(
        input_tokens=1000,
        output_tokens=500,
        total_tokens=1500,
        llm_calls=2,
        duration_ms=2500.0,
        model="anthropic:claude-haiku-4-5-20251001",
    )


def test_logger_creates_directory(logger: TokenUsageLogger, temp_workspace: Path) -> None:
    """Test that logger creates data directory on first log."""
    data_dir = temp_workspace / "data"
    assert not data_dir.exists()

    metrics = InvocationMetrics(input_tokens=100, output_tokens=50, total_tokens=150)
    logger.log(metrics, workspace="test", invocation_type="user", session_key="test:123")

    assert data_dir.exists()
    assert data_dir.is_dir()


def test_logger_creates_jsonl_file(logger: TokenUsageLogger, temp_workspace: Path) -> None:
    """Test that logger creates JSONL file on first log."""
    log_file = temp_workspace / "data" / "token_usage.jsonl"
    assert not log_file.exists()

    metrics = InvocationMetrics(input_tokens=100, output_tokens=50, total_tokens=150)
    logger.log(metrics, workspace="test", invocation_type="user", session_key="test:123")

    assert log_file.exists()
    assert log_file.is_file()


def test_logger_writes_valid_json(
    logger: TokenUsageLogger, temp_workspace: Path, sample_metrics: InvocationMetrics
) -> None:
    """Test that logger writes valid JSON entries."""
    logger.log(sample_metrics, workspace="gilfoyle", invocation_type="user", session_key="telegram:123")

    log_file = temp_workspace / "data" / "token_usage.jsonl"
    with open(log_file) as f:
        line = f.readline()
        entry = json.loads(line)

    assert entry["workspace"] == "gilfoyle"
    assert entry["invocation_type"] == "user"
    assert entry["session_key"] == "telegram:123"
    assert entry["input_tokens"] == 1000
    assert entry["output_tokens"] == 500
    assert entry["total_tokens"] == 1500
    assert entry["llm_calls"] == 2
    assert entry["duration_ms"] == 2500.0
    assert entry["model"] == "anthropic:claude-haiku-4-5-20251001"
    assert "timestamp" in entry


def test_logger_appends_multiple_entries(
    logger: TokenUsageLogger, temp_workspace: Path
) -> None:
    """Test that logger appends multiple entries correctly."""
    metrics1 = InvocationMetrics(input_tokens=100, output_tokens=50, total_tokens=150)
    metrics2 = InvocationMetrics(input_tokens=200, output_tokens=100, total_tokens=300)

    logger.log(metrics1, workspace="test", invocation_type="user", session_key="test:123")
    logger.log(metrics2, workspace="test", invocation_type="cron", session_key=None)

    log_file = temp_workspace / "data" / "token_usage.jsonl"
    with open(log_file) as f:
        lines = f.readlines()

    assert len(lines) == 2
    entry1 = json.loads(lines[0])
    entry2 = json.loads(lines[1])

    assert entry1["input_tokens"] == 100
    assert entry2["input_tokens"] == 200
    assert entry1["invocation_type"] == "user"
    assert entry2["invocation_type"] == "cron"


def test_logger_handles_io_errors_gracefully(
    logger: TokenUsageLogger, temp_workspace: Path, caplog
) -> None:
    """Test that logger handles I/O errors without crashing."""
    # Make workspace read-only to trigger I/O error
    temp_workspace.mkdir()
    temp_workspace.chmod(0o444)

    metrics = InvocationMetrics(input_tokens=100)
    # Should not raise exception
    logger.log(metrics, workspace="test", invocation_type="user")

    # Should log warning
    assert any("Failed to log token usage" in record.message for record in caplog.records)


def test_reader_returns_zero_metrics_when_no_file(reader: TokenUsageReader) -> None:
    """Test that reader returns zero metrics when log file doesn't exist."""
    metrics = reader.tokens_today()

    assert metrics.input_tokens == 0
    assert metrics.output_tokens == 0
    assert metrics.total_tokens == 0
    assert metrics.llm_calls == 0


def test_reader_aggregates_today_entries(
    logger: TokenUsageLogger, reader: TokenUsageReader, temp_workspace: Path
) -> None:
    """Test that reader correctly aggregates entries from today."""
    # Log multiple entries
    logger.log(
        InvocationMetrics(input_tokens=100, output_tokens=50, total_tokens=150, llm_calls=1),
        workspace="test",
        invocation_type="user",
        session_key="test:123",
    )
    logger.log(
        InvocationMetrics(input_tokens=200, output_tokens=100, total_tokens=300, llm_calls=2),
        workspace="test",
        invocation_type="user",
        session_key="test:456",
    )
    logger.log(
        InvocationMetrics(input_tokens=50, output_tokens=25, total_tokens=75, llm_calls=1),
        workspace="test",
        invocation_type="cron",
    )

    metrics = reader.tokens_today()

    assert metrics.input_tokens == 350
    assert metrics.output_tokens == 175
    assert metrics.total_tokens == 525
    assert metrics.llm_calls == 4


def test_reader_filters_old_entries(
    logger: TokenUsageLogger, reader: TokenUsageReader, temp_workspace: Path
) -> None:
    """Test that reader filters out entries from previous days."""
    # Manually write an entry from yesterday
    log_file = temp_workspace / "data" / "token_usage.jsonl"
    log_file.parent.mkdir(parents=True, exist_ok=True)

    yesterday = datetime.now(UTC) - timedelta(days=1)
    old_entry = {
        "timestamp": yesterday.isoformat(),
        "workspace": "test",
        "invocation_type": "user",
        "session_key": "test:123",
        "input_tokens": 1000,
        "output_tokens": 500,
        "total_tokens": 1500,
        "llm_calls": 1,
        "duration_ms": 1000.0,
        "model": "test-model",
    }

    with open(log_file, "w") as f:
        f.write(json.dumps(old_entry) + "\n")

    # Log today's entry
    logger.log(
        InvocationMetrics(input_tokens=100, output_tokens=50, total_tokens=150, llm_calls=1),
        workspace="test",
        invocation_type="user",
    )

    metrics = reader.tokens_today()

    # Should only include today's entry
    assert metrics.input_tokens == 100
    assert metrics.output_tokens == 50
    assert metrics.total_tokens == 150


def test_reader_filters_by_session_key(
    logger: TokenUsageLogger, reader: TokenUsageReader, temp_workspace: Path
) -> None:
    """Test that reader filters entries by session key."""
    logger.log(
        InvocationMetrics(input_tokens=100, output_tokens=50, total_tokens=150, llm_calls=1),
        workspace="test",
        invocation_type="user",
        session_key="telegram:123",
    )
    logger.log(
        InvocationMetrics(input_tokens=200, output_tokens=100, total_tokens=300, llm_calls=2),
        workspace="test",
        invocation_type="user",
        session_key="telegram:456",
    )
    logger.log(
        InvocationMetrics(input_tokens=50, output_tokens=25, total_tokens=75, llm_calls=1),
        workspace="test",
        invocation_type="user",
        session_key="telegram:123",
    )

    metrics = reader.tokens_for_session("telegram:123")

    # Should only include entries for session telegram:123
    assert metrics.input_tokens == 150
    assert metrics.output_tokens == 75
    assert metrics.total_tokens == 225
    assert metrics.llm_calls == 2


def test_reader_handles_malformed_entries(
    logger: TokenUsageLogger, reader: TokenUsageReader, temp_workspace: Path, caplog
) -> None:
    """Test that reader handles malformed JSON entries gracefully."""
    log_file = temp_workspace / "data" / "token_usage.jsonl"
    log_file.parent.mkdir(parents=True, exist_ok=True)

    # Write valid entry
    logger.log(
        InvocationMetrics(input_tokens=100, output_tokens=50, total_tokens=150),
        workspace="test",
        invocation_type="user",
    )

    # Append malformed entry
    with open(log_file, "a") as f:
        f.write("this is not json\n")

    # Append another valid entry
    logger.log(
        InvocationMetrics(input_tokens=200, output_tokens=100, total_tokens=300),
        workspace="test",
        invocation_type="user",
    )

    metrics = reader.tokens_today()

    # Should aggregate valid entries only
    assert metrics.input_tokens == 300
    assert metrics.output_tokens == 150
    assert metrics.total_tokens == 450


def test_reader_handles_missing_fields(
    logger: TokenUsageLogger, reader: TokenUsageReader, temp_workspace: Path
) -> None:
    """Test that reader handles entries with missing fields."""
    log_file = temp_workspace / "data" / "token_usage.jsonl"
    log_file.parent.mkdir(parents=True, exist_ok=True)

    # Write entry with missing fields
    partial_entry = {
        "timestamp": datetime.now(UTC).isoformat(),
        "workspace": "test",
        "invocation_type": "user",
        "input_tokens": 100,
        # Missing output_tokens, total_tokens, etc.
    }

    with open(log_file, "w") as f:
        f.write(json.dumps(partial_entry) + "\n")

    metrics = reader.tokens_today()

    # Should handle missing fields gracefully
    assert metrics.input_tokens == 100
    assert metrics.output_tokens == 0
    assert metrics.total_tokens == 0


def test_logger_cron_invocation(logger: TokenUsageLogger, temp_workspace: Path) -> None:
    """Test logging cron invocations (no session_key)."""
    metrics = InvocationMetrics(input_tokens=100, output_tokens=50, total_tokens=150)
    logger.log(metrics, workspace="test", invocation_type="cron", session_key=None)

    log_file = temp_workspace / "data" / "token_usage.jsonl"
    with open(log_file) as f:
        entry = json.loads(f.readline())

    assert entry["invocation_type"] == "cron"
    assert entry["session_key"] is None


def test_logger_heartbeat_invocation(logger: TokenUsageLogger, temp_workspace: Path) -> None:
    """Test logging heartbeat invocations."""
    metrics = InvocationMetrics(input_tokens=200, output_tokens=100, total_tokens=300)
    logger.log(metrics, workspace="test", invocation_type="heartbeat", session_key=None)

    log_file = temp_workspace / "data" / "token_usage.jsonl"
    with open(log_file) as f:
        entry = json.loads(f.readline())

    assert entry["invocation_type"] == "heartbeat"
    assert entry["session_key"] is None
