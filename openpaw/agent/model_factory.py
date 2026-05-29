"""Model factory for creating provider-specific chat models.

Provides standalone model instantiation used by AgentRunner, AgentFactory,
and any component that needs to resolve a provider:model string into a
LangChain BaseChatModel instance.
"""

import logging
import re
from typing import Any

from langchain_core.language_models import BaseChatModel

from openpaw.core.utils import is_context_overflow_error

logger = logging.getLogger(__name__)

# Surface retry diagnostics from provider SDKs.
# OpenAI SDK logs "Retrying request to %s in %f seconds" at INFO.
# Anthropic SDK logs similar messages at INFO.
logging.getLogger("openai._base_client").setLevel(logging.INFO)
logging.getLogger("anthropic._base_client").setLevel(logging.INFO)

# Models known to produce thinking tokens
THINKING_MODELS = [
    "moonshot.kimi-k2-thinking",
    "moonshotai.kimi-k2.5",
    "kimi-k2-thinking",
    "kimi-thinking",
    "kimi-k2.5",
]

# Bedrock tool name validation pattern (AWS requirement)
BEDROCK_TOOL_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")
MAX_TOOL_NAME_LENGTH = 64


def create_chat_model(
    model_str: str,
    api_key: str | None,
    temperature: float,
    region: str | None = None,
    extra_kwargs: dict[str, Any] | None = None,
) -> BaseChatModel:
    """Create a chat model from a provider:model string.

    Standalone function usable by both AgentRunner and model validation.

    Args:
        model_str: Model identifier in "provider:model" format.
        api_key: API key for the model provider (not used for Bedrock).
        temperature: Model temperature setting.
        region: AWS region for Bedrock models (e.g., us-east-1).
        extra_kwargs: Additional kwargs to pass to the model constructor
            (e.g., base_url for OpenAI-compatible APIs, max_retries for retry config).

    Returns:
        Configured BaseChatModel instance. For Fireworks, returns a
        RunnableRetry wrapper when max_retries > 0 (the Fireworks SDK does not
        implement native retry). Callers that need model attribute access (e.g.
        ``profile``) should hold a reference to the raw model separately — see
        ``AgentRunner._build_agent()`` for the established pattern.

    Raises:
        ValueError: If provider is not supported.
    """
    # Parse provider from model_str (format: "provider:model_name")
    if ":" in model_str:
        provider, model_name = model_str.split(":", 1)
    else:
        provider = "openai"
        model_name = model_str

    # Build kwargs common to all providers
    kwargs: dict[str, Any] = {
        "model": model_name,
        "temperature": temperature,
    }

    # Merge extra kwargs from config (base_url, model_kwargs, extra_body, etc.)
    if extra_kwargs:
        kwargs.update(extra_kwargs)

    # Extract max_retries before merging into provider kwargs.
    # Different providers require different handling (see per-provider logic below).
    max_retries: int | None = kwargs.pop("max_retries", 3)
    effective_retries = max_retries if (max_retries and max_retries > 0) else 0

    # Flatten model_kwargs into direct constructor args so that params like
    # extra_body reach the provider class directly instead of being silently dropped
    nested_model_kwargs = kwargs.pop("model_kwargs", None)
    if nested_model_kwargs and isinstance(nested_model_kwargs, dict):
        kwargs.update(nested_model_kwargs)

    if provider == "openai":
        from langchain_openai import ChatOpenAI

        if api_key:
            kwargs["api_key"] = api_key
        if effective_retries > 0:
            kwargs["max_retries"] = effective_retries
            logger.info(f"Creating ChatOpenAI: model={model_name}, max_retries={effective_retries}")
        else:
            logger.info(f"Creating ChatOpenAI: model={model_name}, kwargs={list(kwargs.keys())}")
        return ChatOpenAI(**kwargs)

    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        if api_key:
            kwargs["api_key"] = api_key
        if effective_retries > 0:
            kwargs["max_retries"] = effective_retries
            logger.info(f"Creating ChatAnthropic: model={model_name}, max_retries={effective_retries}")
        else:
            logger.info(f"Creating ChatAnthropic: model={model_name}")
        return ChatAnthropic(**kwargs)

    if provider in ("bedrock_converse", "bedrock"):
        from langchain_aws import ChatBedrockConverse

        if region:
            kwargs["region_name"] = region
        # Bedrock uses AWS credentials, not api_key.
        # boto3 manages its own retry strategy — do not pass max_retries.
        kwargs.pop("api_key", None)
        logger.info(f"Creating ChatBedrockConverse: model={model_name}, kwargs_keys={list(kwargs.keys())}")
        return ChatBedrockConverse(**kwargs)

    if provider == "xai":
        from langchain_xai import ChatXAI

        if api_key:
            kwargs["xai_api_key"] = api_key
        if effective_retries > 0:
            kwargs["max_retries"] = effective_retries
            logger.info(f"Creating ChatXAI: model={model_name}, max_retries={effective_retries}")
        else:
            logger.info(f"Creating ChatXAI: model={model_name}")
        return ChatXAI(**kwargs)

    if provider == "fireworks":
        import httpx
        import tenacity
        from fireworks.client.error import FireworksError, InvalidRequestError, RateLimitError
        from langchain_fireworks import ChatFireworks

        if api_key:
            kwargs["fireworks_api_key"] = api_key
        logger.info(f"Creating ChatFireworks: model={model_name}")
        model = ChatFireworks(**kwargs)

        # The Fireworks SDK's _max_retries is a no-op — patch _agenerate with
        # tenacity for real retry behavior.  This preserves bind_tools() and all
        # model attributes (unlike .with_retry() which wraps the entire Runnable).
        #
        # Fireworks changed their rate limit error format (Apr 2025): the code
        # field shifted from "too_many_requests" (transient overload) to
        # "invalid_request_error" (hard rate limit).  Hard rate limits need much
        # longer backoff than transient 5xx errors, so we use a composite wait
        # strategy that applies longer delays specifically for RateLimitError.
        if effective_retries > 0:
            # Use more attempts for Fireworks — the default of 3 is too few when
            # multiple workspaces share one API key (rate limits may need 30-60s
            # to clear, and 3 retries only yields ~8s total backoff).
            fireworks_attempts = max(effective_retries, 6)
            logger.info(
                f"Patching ChatFireworks._agenerate with retry "
                f"(max_attempts={fireworks_attempts + 1}, effective_retries={effective_retries})"
            )
            original_agenerate = model._agenerate

            def _is_retryable_fireworks_error(exc: BaseException) -> bool:
                if isinstance(exc, InvalidRequestError):
                    if is_context_overflow_error(exc):
                        return False
                return isinstance(
                    exc,
                    httpx.HTTPStatusError
                    | httpx.ConnectError
                    | httpx.ReadTimeout
                    | ConnectionError
                    | TimeoutError
                    | FireworksError,
                )

            def _fireworks_wait(retry_state: tenacity.RetryCallState) -> float:
                """Rate-limit-aware backoff: longer delays for RateLimitError."""
                exc = retry_state.outcome.exception() if retry_state.outcome and retry_state.outcome.failed else None
                if isinstance(exc, RateLimitError):
                    return tenacity.wait_exponential_jitter(initial=5, max=120)(retry_state)
                return tenacity.wait_exponential_jitter(initial=1, max=60)(retry_state)

            @tenacity.retry(
                retry=tenacity.retry_if_exception(_is_retryable_fireworks_error),
                stop=tenacity.stop_after_attempt(fireworks_attempts + 1),
                wait=_fireworks_wait,
                before_sleep=tenacity.before_sleep_log(logger, logging.WARNING),
                reraise=True,
            )
            async def _agenerate_with_retry(*args: Any, **kw: Any) -> Any:
                return await original_agenerate(*args, **kw)

            model._agenerate = _agenerate_with_retry  # type: ignore[method-assign]

        return model

    raise ValueError(
        f"Unsupported model provider: '{provider}'. "
        f"Supported: openai, anthropic, bedrock_converse, xai, fireworks"
    )


def validate_tool_names(tools: list[Any]) -> None:
    """Validate tool names comply with Bedrock requirements.

    AWS Bedrock requires tool names to:
    - Match pattern [a-zA-Z0-9_-]+
    - Be 64 characters or less

    Args:
        tools: List of tools to validate.

    Raises:
        ValueError: If any tool name is invalid.
    """
    for tool in tools:
        tool_name = getattr(tool, "name", None)
        if not tool_name:
            logger.warning(f"Tool {tool} has no name attribute, skipping validation")
            continue

        # Check length
        if len(tool_name) > MAX_TOOL_NAME_LENGTH:
            raise ValueError(
                f"Tool name '{tool_name}' exceeds max length of {MAX_TOOL_NAME_LENGTH} characters"
            )

        # Check pattern
        if not BEDROCK_TOOL_NAME_PATTERN.match(tool_name):
            raise ValueError(
                f"Tool name '{tool_name}' contains invalid characters. "
                f"Must match pattern: [a-zA-Z0-9_-]+"
            )
