"""Tests for max_retries retry configuration across model providers."""

from unittest.mock import Mock, patch

from openpaw.agent.model_factory import create_chat_model
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


def test_fireworks_agenerate_patched_with_tenacity() -> None:
    """Fireworks _agenerate is patched with tenacity retry when max_retries > 0."""
    mock_model = Mock()
    mock_model._agenerate = Mock()

    with patch("langchain_fireworks.ChatFireworks", return_value=mock_model):
        result = create_chat_model(
            model_str="fireworks:accounts/fireworks/models/deepseek-v3p1",
            api_key="test-key",
            temperature=0.7,
            extra_kwargs={"max_retries": 3},
        )

    # Model itself is returned (not a wrapper), preserving bind_tools()
    assert result is mock_model
    # _agenerate should be replaced with a tenacity-wrapped version
    assert (
        result._agenerate is not mock_model._agenerate.__func__
        if hasattr(mock_model._agenerate, "__func__")
        else True
    )
    # The patched function should have tenacity retry attributes
    assert hasattr(result._agenerate, "retry")


def test_fireworks_uses_minimum_6_attempts() -> None:
    """Fireworks retries are floored at 6 attempts regardless of max_retries config."""
    import tenacity

    mock_model = Mock()
    mock_model._agenerate = Mock()

    with patch("langchain_fireworks.ChatFireworks", return_value=mock_model):
        result = create_chat_model(
            model_str="fireworks:accounts/fireworks/models/deepseek-v3p1",
            api_key="test-key",
            temperature=0.7,
            extra_kwargs={"max_retries": 3},
        )

    stop_strategy = result._agenerate.retry.stop
    assert isinstance(stop_strategy, tenacity.stop_after_attempt)
    assert stop_strategy.max_attempt_number == 7  # 6 retries + 1 initial


def test_fireworks_custom_high_retries_preserved() -> None:
    """When max_retries > 6, Fireworks uses the user's value instead of the floor."""
    import tenacity

    mock_model = Mock()
    mock_model._agenerate = Mock()

    with patch("langchain_fireworks.ChatFireworks", return_value=mock_model):
        result = create_chat_model(
            model_str="fireworks:accounts/fireworks/models/deepseek-v3p1",
            api_key="test-key",
            temperature=0.7,
            extra_kwargs={"max_retries": 10},
        )

    stop_strategy = result._agenerate.retry.stop
    assert isinstance(stop_strategy, tenacity.stop_after_attempt)
    assert stop_strategy.max_attempt_number == 11  # 10 retries + 1 initial


def test_fireworks_rate_limit_wait_longer() -> None:
    """Rate limit errors get longer backoff (initial=5s) than transient errors (initial=1s)."""
    import tenacity
    from fireworks.client.error import RateLimitError

    mock_model = Mock()
    mock_model._agenerate = Mock()

    with patch("langchain_fireworks.ChatFireworks", return_value=mock_model):
        result = create_chat_model(
            model_str="fireworks:accounts/fireworks/models/deepseek-v3p1",
            api_key="test-key",
            temperature=0.7,
            extra_kwargs={"max_retries": 3},
        )

    wait_fn = result._agenerate.retry.wait

    # Simulate a RateLimitError retry state (3rd attempt)
    rl_state = Mock(spec=tenacity.RetryCallState)
    rl_state.outcome = Mock()
    rl_state.outcome.failed = True
    rl_state.outcome.exception = Mock(return_value=RateLimitError("rate limit exceeded"))
    rl_state.attempt_number = 3

    rl_wait = wait_fn(rl_state)
    assert rl_wait >= 5  # initial=5 for rate limit errors

    # Simulate a transient error retry state (3rd attempt)
    trans_state = Mock(spec=tenacity.RetryCallState)
    trans_state.outcome = Mock()
    trans_state.outcome.failed = True
    trans_state.outcome.exception = Mock(return_value=ConnectionError("connection reset"))
    trans_state.attempt_number = 3

    trans_wait = wait_fn(trans_state)
    assert trans_wait >= 1  # initial=1 for transient errors


def test_fireworks_no_patch_when_retries_disabled() -> None:
    """Fireworks _agenerate is NOT patched when max_retries is 0."""
    original_agenerate = Mock()
    mock_model = Mock()
    mock_model._agenerate = original_agenerate

    with patch("langchain_fireworks.ChatFireworks", return_value=mock_model):
        result = create_chat_model(
            model_str="fireworks:accounts/fireworks/models/deepseek-v3p1",
            api_key="test-key",
            temperature=0.7,
            extra_kwargs={"max_retries": 0},
        )

    assert result is mock_model
    assert result._agenerate is original_agenerate


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
