"""Tests for token usage and invocation metrics tracking."""

import pytest

from openpaw.core.metrics import InvocationMetrics, extract_metrics_from_callback


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
