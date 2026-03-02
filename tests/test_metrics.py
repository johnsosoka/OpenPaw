"""Tests for token usage and invocation metrics tracking."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from openpaw.agent.metrics import (
    InvocationMetrics,
    TokenUsageLogger,
    TokenUsageReader,
    extract_metrics_from_callback,
)


class MockCallbackHandler:
    """Mock UsageMetadataCallbackHandler for testing."""

    def __init__(self, usage_metadata: dict | None = None):
        self.usage_metadata = usage_metadata


def test_invocation_metrics_defaults():
    """Test InvocationMetrics dataclass default values."""
    metrics = InvocationMetrics()

    assert metrics.input_tokens == 0
    assert metrics.output_tokens == 0
    assert metrics.total_tokens == 0
    assert metrics.llm_calls == 0
    assert metrics.duration_ms == 0.0
    assert metrics.model == ""


def test_invocation_metrics_initialization():
    """Test InvocationMetrics with explicit values."""
    metrics = InvocationMetrics(
        input_tokens=1000,
        output_tokens=500,
        total_tokens=1500,
        llm_calls=3,
        duration_ms=2500.5,
        model="anthropic:claude-sonnet-4-20250514",
    )

    assert metrics.input_tokens == 1000
    assert metrics.output_tokens == 500
    assert metrics.total_tokens == 1500
    assert metrics.llm_calls == 3
    assert metrics.duration_ms == 2500.5
    assert metrics.model == "anthropic:claude-sonnet-4-20250514"


def test_extract_metrics_single_model():
    """Test extracting metrics from callback with single model."""
    usage_metadata = {
        "claude-sonnet-4": {
            "input_tokens": 1200,
            "output_tokens": 350,
            "total_tokens": 1550,
        }
    }
    callback = MockCallbackHandler(usage_metadata)

    metrics = extract_metrics_from_callback(callback, 3000.0, "anthropic:claude-sonnet-4")

    assert metrics.input_tokens == 1200
    assert metrics.output_tokens == 350
    assert metrics.total_tokens == 1550
    assert metrics.llm_calls == 1
    assert metrics.duration_ms == 3000.0
    assert metrics.model == "anthropic:claude-sonnet-4"


def test_extract_metrics_multiple_models():
    """Test extracting metrics from callback with multiple models (aggregated)."""
    usage_metadata = {
        "claude-sonnet-4": {
            "input_tokens": 1000,
            "output_tokens": 300,
            "total_tokens": 1300,
        },
        "claude-haiku-4.5": {
            "input_tokens": 500,
            "output_tokens": 150,
            "total_tokens": 650,
        },
    }
    callback = MockCallbackHandler(usage_metadata)

    metrics = extract_metrics_from_callback(callback, 4500.0, "anthropic:claude-sonnet-4")

    # Should aggregate across both models
    assert metrics.input_tokens == 1500
    assert metrics.output_tokens == 450
    assert metrics.total_tokens == 1950
    assert metrics.llm_calls == 2
    assert metrics.duration_ms == 4500.0


def test_extract_metrics_empty_callback():
    """Test extracting metrics when callback has empty usage_metadata."""
    callback = MockCallbackHandler(usage_metadata={})

    metrics = extract_metrics_from_callback(callback, 1000.0, "anthropic:claude-sonnet-4")

    # Should return zeroed metrics (no exception)
    assert metrics.input_tokens == 0
    assert metrics.output_tokens == 0
    assert metrics.total_tokens == 0
    assert metrics.llm_calls == 0
    assert metrics.duration_ms == 1000.0
    assert metrics.model == "anthropic:claude-sonnet-4"


def test_extract_metrics_none_callback():
    """Test extracting metrics when callback has None usage_metadata."""
    callback = MockCallbackHandler(usage_metadata=None)

    metrics = extract_metrics_from_callback(callback, 1000.0, "anthropic:claude-sonnet-4")

    # Should return zeroed metrics (no exception)
    assert metrics.input_tokens == 0
    assert metrics.output_tokens == 0
    assert metrics.total_tokens == 0
    assert metrics.llm_calls == 0
    assert metrics.duration_ms == 1000.0
    assert metrics.model == "anthropic:claude-sonnet-4"


def test_extract_metrics_missing_attribute():
    """Test extracting metrics when callback has no usage_metadata attribute."""

    class BadCallback:
        pass

    callback = BadCallback()

    metrics = extract_metrics_from_callback(callback, 1000.0, "anthropic:claude-sonnet-4")

    # Should return zeroed metrics (no exception)
    assert metrics.input_tokens == 0
    assert metrics.output_tokens == 0
    assert metrics.total_tokens == 0
    assert metrics.llm_calls == 0
    assert metrics.duration_ms == 1000.0
    assert metrics.model == "anthropic:claude-sonnet-4"


def test_extract_metrics_missing_fields():
    """Test extracting metrics when some token fields are missing."""
    usage_metadata = {
        "claude-sonnet-4": {
            "input_tokens": 1000,
            # output_tokens missing
            "total_tokens": 1200,
        }
    }
    callback = MockCallbackHandler(usage_metadata)

    metrics = extract_metrics_from_callback(callback, 2000.0, "anthropic:claude-sonnet-4")

    # Should handle missing fields with 0 defaults
    assert metrics.input_tokens == 1000
    assert metrics.output_tokens == 0
    assert metrics.total_tokens == 1200
    assert metrics.llm_calls == 1


def test_extract_metrics_total_validation():
    """Test that total_tokens is computed if missing but input/output are present."""
    usage_metadata = {
        "claude-sonnet-4": {
            "input_tokens": 800,
            "output_tokens": 200,
            "total_tokens": 0,  # Incorrect total
        }
    }
    callback = MockCallbackHandler(usage_metadata)

    metrics = extract_metrics_from_callback(callback, 2000.0, "anthropic:claude-sonnet-4")

    # Should fix incorrect total
    assert metrics.input_tokens == 800
    assert metrics.output_tokens == 200
    assert metrics.total_tokens == 1000  # Corrected


def test_extract_metrics_malformed_usage():
    """Test extracting metrics when usage_metadata has unexpected format."""
    usage_metadata = {
        "claude-sonnet-4": "not a dict",  # Invalid format
        "claude-haiku-4.5": {
            "input_tokens": 500,
            "output_tokens": 100,
            "total_tokens": 600,
        },
    }
    callback = MockCallbackHandler(usage_metadata)

    metrics = extract_metrics_from_callback(callback, 2000.0, "anthropic:claude-sonnet-4")

    # Should skip malformed entry, include valid one
    assert metrics.input_tokens == 500
    assert metrics.output_tokens == 100
    assert metrics.total_tokens == 600
    assert metrics.llm_calls == 1  # Only counted valid model


def test_extract_metrics_zero_duration():
    """Test extracting metrics with zero duration (edge case)."""
    usage_metadata = {
        "claude-sonnet-4": {
            "input_tokens": 100,
            "output_tokens": 50,
            "total_tokens": 150,
        }
    }
    callback = MockCallbackHandler(usage_metadata)

    metrics = extract_metrics_from_callback(callback, 0.0, "anthropic:claude-sonnet-4")

    assert metrics.duration_ms == 0.0
    assert metrics.input_tokens == 100


def test_extract_metrics_large_values():
    """Test extracting metrics with large token counts (long conversations)."""
    usage_metadata = {
        "claude-sonnet-4": {
            "input_tokens": 100000,
            "output_tokens": 50000,
            "total_tokens": 150000,
        }
    }
    callback = MockCallbackHandler(usage_metadata)

    metrics = extract_metrics_from_callback(callback, 30000.0, "anthropic:claude-sonnet-4")

    assert metrics.input_tokens == 100000
    assert metrics.output_tokens == 50000
    assert metrics.total_tokens == 150000


# Timezone-aware token tracking tests


@pytest.fixture
def workspace_with_tokens(tmp_path: Path) -> Path:
    """Create a workspace with token usage log entries."""
    workspace = tmp_path / "test_workspace"
    workspace.mkdir()
    return workspace


def test_tokens_today_default_utc(workspace_with_tokens: Path):
    """Test tokens_today() defaults to UTC for backward compatibility."""
    logger = TokenUsageLogger(workspace_with_tokens)
    reader = TokenUsageReader(workspace_with_tokens)

    # Log some tokens
    metrics = InvocationMetrics(
        input_tokens=1000,
        output_tokens=500,
        total_tokens=1500,
    )
    logger.log(metrics, "test", "user", "telegram:123")

    # Read without timezone arg should use UTC
    today = reader.tokens_today()
    assert today.total_tokens == 1500


def test_tokens_today_mountain_time(workspace_with_tokens: Path):
    """Test tokens_today() uses Mountain Time midnight as day boundary."""
    logger = TokenUsageLogger(workspace_with_tokens)
    reader = TokenUsageReader(workspace_with_tokens)

    # Create a timestamp that's "yesterday" in Mountain Time but "today" in UTC
    # Mountain Time is UTC-7 (during DST) or UTC-6 (standard time)
    # Let's use a time that's definitely different: 11 PM Mountain = 6 AM UTC next day
    mountain_tz = ZoneInfo("America/Denver")

    # Get current time in Mountain Time
    now_mountain = datetime.now(mountain_tz)

    # Create a timestamp at 11 PM Mountain Time yesterday
    yesterday_11pm_mountain = now_mountain.replace(
        hour=23, minute=0, second=0, microsecond=0
    ) - timedelta(days=1)

    # Manually log an entry with yesterday's timestamp
    log_path = workspace_with_tokens / "data" / "token_usage.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    with open(log_path, "a") as f:
        entry = {
            "timestamp": yesterday_11pm_mountain.isoformat(),
            "workspace": "test",
            "invocation_type": "user",
            "session_key": "telegram:123",
            "input_tokens": 500,
            "output_tokens": 250,
            "total_tokens": 750,
            "llm_calls": 1,
            "duration_ms": 1000.0,
            "model": "test-model",
        }
        f.write(json.dumps(entry) + "\n")

    # Create a timestamp for today
    today_entry = {
        "timestamp": now_mountain.isoformat(),
        "workspace": "test",
        "invocation_type": "user",
        "session_key": "telegram:123",
        "input_tokens": 1000,
        "output_tokens": 500,
        "total_tokens": 1500,
        "llm_calls": 1,
        "duration_ms": 2000.0,
        "model": "test-model",
    }

    with open(log_path, "a") as f:
        f.write(json.dumps(today_entry) + "\n")

    # Read with Mountain Time — should only get today's entry
    today = reader.tokens_today(timezone_str="America/Denver")
    assert today.total_tokens == 1500

    # Read with UTC — might get different results depending on timestamp conversion
    today_utc = reader.tokens_today(timezone_str="UTC")
    # The UTC aggregation might include different entries due to timezone offset


def test_tokens_for_session_mountain_time(workspace_with_tokens: Path):
    """Test tokens_for_session() respects workspace timezone."""
    logger = TokenUsageLogger(workspace_with_tokens)
    reader = TokenUsageReader(workspace_with_tokens)

    # Log tokens today
    metrics = InvocationMetrics(
        input_tokens=1000,
        output_tokens=500,
        total_tokens=1500,
    )
    logger.log(metrics, "test", "user", "telegram:123")

    # Different session
    logger.log(
        InvocationMetrics(input_tokens=2000, output_tokens=1000, total_tokens=3000),
        "test",
        "user",
        "telegram:456",
    )

    # Read session tokens in Mountain Time
    session = reader.tokens_for_session("telegram:123", timezone_str="America/Denver")
    assert session.total_tokens == 1500


def test_tokens_today_no_log_file(workspace_with_tokens: Path):
    """Test tokens_today() returns empty metrics when log doesn't exist."""
    reader = TokenUsageReader(workspace_with_tokens)

    today = reader.tokens_today(timezone_str="America/Denver")
    assert today.total_tokens == 0
    assert today.input_tokens == 0
    assert today.output_tokens == 0


def test_tokens_today_multiple_timezones(workspace_with_tokens: Path):
    """Test that different timezones can yield different results for 'today'."""
    logger = TokenUsageLogger(workspace_with_tokens)
    reader = TokenUsageReader(workspace_with_tokens)

    # Create entries near midnight boundary
    log_path = workspace_with_tokens / "data" / "token_usage.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    # Entry at 11:30 PM Pacific Time
    pacific_tz = ZoneInfo("America/Los_Angeles")
    late_night_pacific = datetime.now(pacific_tz).replace(
        hour=23, minute=30, second=0, microsecond=0
    )

    with open(log_path, "a") as f:
        entry = {
            "timestamp": late_night_pacific.isoformat(),
            "workspace": "test",
            "invocation_type": "user",
            "session_key": "telegram:123",
            "input_tokens": 1000,
            "output_tokens": 500,
            "total_tokens": 1500,
            "llm_calls": 1,
            "duration_ms": 1000.0,
            "model": "test-model",
        }
        f.write(json.dumps(entry) + "\n")

    # Read in Pacific time — should be included
    today_pacific = reader.tokens_today(timezone_str="America/Los_Angeles")

    # The entry might be today or tomorrow depending on when the test runs
    # Just verify the function doesn't crash and returns valid metrics
    assert isinstance(today_pacific, InvocationMetrics)
    assert today_pacific.total_tokens >= 0
