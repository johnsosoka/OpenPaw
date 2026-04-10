"""Tests for max_retries retry configuration across model providers."""

from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from openpaw.agent.runner import create_chat_model
from openpaw.core.config.models import WorkspaceModelConfig


# ---------------------------------------------------------------------------
# Config model tests
# ---------------------------------------------------------------------------


def test_config_default_is_3() -> None:
    """WorkspaceModelConfig defaults max_retries to 3."""
    config = WorkspaceModelConfig()
    assert config.max_retries == 3


def test_config_accepts_none() -> None:
    """WorkspaceModelConfig accepts None to disable retries."""
    config = WorkspaceModelConfig(max_retries=None)
    assert config.max_retries is None


def test_config_accepts_zero() -> None:
    """WorkspaceModelConfig accepts 0 to disable retries."""
    config = WorkspaceModelConfig(max_retries=0)
    assert config.max_retries == 0


def test_config_accepts_custom_value() -> None:
    """WorkspaceModelConfig accepts custom retry counts."""
    config = WorkspaceModelConfig(max_retries=5)
    assert config.max_retries == 5


# ---------------------------------------------------------------------------
# create_chat_model() per-provider tests
# ---------------------------------------------------------------------------


def test_openai_gets_max_retries() -> None:
    """OpenAI model receives max_retries as a constructor kwarg."""
    with patch("langchain_openai.ChatOpenAI") as mock_cls:
        mock_cls.return_value = Mock()

        create_chat_model(
            model_str="openai:gpt-4o",
            api_key="test-key",
            temperature=0.7,
            extra_kwargs={"max_retries": 3},
        )

        call_kwargs = mock_cls.call_args[1]
        assert call_kwargs["max_retries"] == 3


def test_anthropic_gets_max_retries() -> None:
    """Anthropic model receives max_retries as a constructor kwarg."""
    with patch("langchain_anthropic.ChatAnthropic") as mock_cls:
        mock_cls.return_value = Mock()

        create_chat_model(
            model_str="anthropic:claude-sonnet-4-20250514",
            api_key="test-key",
            temperature=0.7,
            extra_kwargs={"max_retries": 3},
        )

        call_kwargs = mock_cls.call_args[1]
        assert call_kwargs["max_retries"] == 3


def test_xai_gets_max_retries() -> None:
    """xAI model receives max_retries as a constructor kwarg."""
    with patch("langchain_xai.ChatXAI") as mock_cls:
        mock_cls.return_value = Mock()

        create_chat_model(
            model_str="xai:grok-3-mini",
            api_key="test-key",
            temperature=0.7,
            extra_kwargs={"max_retries": 3},
        )

        call_kwargs = mock_cls.call_args[1]
        assert call_kwargs["max_retries"] == 3


def test_bedrock_no_max_retries() -> None:
    """Bedrock models do NOT receive max_retries — boto3 manages its own retry."""
    with patch("langchain_aws.ChatBedrockConverse") as mock_cls:
        mock_cls.return_value = Mock()

        create_chat_model(
            model_str="bedrock_converse:moonshot.kimi-k2-thinking",
            api_key=None,
            temperature=0.7,
            region="us-east-1",
            extra_kwargs={"max_retries": 3},
        )

        call_kwargs = mock_cls.call_args[1]
        assert "max_retries" not in call_kwargs


def test_fireworks_wrapped_with_retry() -> None:
    """Fireworks model is wrapped with .with_retry() since the SDK's native retry is a no-op."""
    import httpx

    mock_raw_model = Mock()
    mock_wrapped = Mock()
    mock_raw_model.with_retry.return_value = mock_wrapped

    with patch("langchain_fireworks.ChatFireworks", return_value=mock_raw_model):
        result = create_chat_model(
            model_str="fireworks:accounts/fireworks/models/deepseek-v3p1",
            api_key="test-key",
            temperature=0.7,
            extra_kwargs={"max_retries": 3},
        )

    # Should have called .with_retry() on the raw model
    mock_raw_model.with_retry.assert_called_once()
    call_kwargs = mock_raw_model.with_retry.call_args[1]
    assert call_kwargs["stop_after_attempt"] == 4  # max_retries + 1
    assert call_kwargs["wait_exponential_jitter"] is True
    # Verify the correct exception types are included
    retry_types = call_kwargs["retry_if_exception_type"]
    assert httpx.HTTPStatusError in retry_types
    assert httpx.ConnectError in retry_types
    assert httpx.ReadTimeout in retry_types
    # The wrapper is returned, not the raw model
    assert result is mock_wrapped


def test_fireworks_no_wrap_when_retries_disabled() -> None:
    """Fireworks model is NOT wrapped when max_retries is 0."""
    mock_raw_model = Mock()

    with patch("langchain_fireworks.ChatFireworks", return_value=mock_raw_model):
        result = create_chat_model(
            model_str="fireworks:accounts/fireworks/models/deepseek-v3p1",
            api_key="test-key",
            temperature=0.7,
            extra_kwargs={"max_retries": 0},
        )

    mock_raw_model.with_retry.assert_not_called()
    assert result is mock_raw_model


def test_disabled_when_zero() -> None:
    """max_retries=0 disables retry for OpenAI (no max_retries kwarg sent)."""
    with patch("langchain_openai.ChatOpenAI") as mock_cls:
        mock_cls.return_value = Mock()

        create_chat_model(
            model_str="openai:gpt-4o",
            api_key="test-key",
            temperature=0.7,
            extra_kwargs={"max_retries": 0},
        )

        call_kwargs = mock_cls.call_args[1]
        assert "max_retries" not in call_kwargs


def test_disabled_when_none() -> None:
    """max_retries=None disables retry for OpenAI (no max_retries kwarg sent)."""
    with patch("langchain_openai.ChatOpenAI") as mock_cls:
        mock_cls.return_value = Mock()

        create_chat_model(
            model_str="openai:gpt-4o",
            api_key="test-key",
            temperature=0.7,
            extra_kwargs={"max_retries": None},
        )

        call_kwargs = mock_cls.call_args[1]
        assert "max_retries" not in call_kwargs


def test_max_retries_not_leaked_to_bedrock_as_extra_kwarg() -> None:
    """Verify max_retries is fully consumed and never appears in Bedrock constructor call."""
    with patch("langchain_aws.ChatBedrockConverse") as mock_cls:
        mock_cls.return_value = Mock()

        create_chat_model(
            model_str="bedrock_converse:us.anthropic.claude-haiku-4-5",
            api_key=None,
            temperature=0.7,
            region="us-east-1",
            extra_kwargs={"max_retries": 5},
        )

        call_kwargs = mock_cls.call_args[1]
        # max_retries must not appear under any name in Bedrock kwargs
        assert "max_retries" not in call_kwargs
        assert "_max_retries" not in call_kwargs
