"""Model factory for creating provider-specific chat models.

Provides standalone model instantiation used by AgentRunner, AgentFactory,
and any component that needs to resolve a provider:model string into a
LangChain BaseChatModel instance.
"""

import logging
import re
from typing import Any, cast

from langchain_core.language_models import BaseChatModel

from openpaw.core.utils import is_context_overflow_error

logger = logging.getLogger(__name__)

# Surface retry diagnostics from provider SDKs.
# OpenAI SDK logs "Retrying request to %s in %f seconds" at INFO.
# Anthropic SDK logs similar messages at INFO.
logging.getLogger("openai._base_client").setLevel(logging.INFO)
logging.getLogger("anthropic._base_client").setLevel(logging.INFO)

# Bedrock-routed Kimi model IDs that emit raw <think> tags in content and need
# regex stripping by ThinkingTokenMiddleware. The native `moonshot:` provider
# uses ChatMoonshot which separates reasoning content via additional_kwargs,
# so it does NOT belong on this list.
THINKING_MODELS = [
    "moonshot.kimi-k2-thinking",
]

# Bedrock tool name validation pattern (AWS requirement)
BEDROCK_TOOL_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")
MAX_TOOL_NAME_LENGTH = 64

# Fireworks expects `thinking` as an object, not a bool. Enabled requires
# budget_tokens >= 1024; the docs example uses 4096.
FIREWORKS_DEFAULT_THINKING_BUDGET = 4096

# Providers whose branch actually consumes the top-level `thinking` toggle.
# For any other provider, `thinking` is popped and ignored with a warning so
# it can never leak into the request body as a raw bool.
THINKING_SUPPORTED_PROVIDERS = {"moonshot", "fireworks"}


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

    # Pop `thinking` centrally so it can NEVER leak into a provider constructor as a
    # raw bool (some SDKs forward unknown kwargs straight into the request body, which
    # the API rejects — see the Fireworks fix above). Only THINKING_SUPPORTED_PROVIDERS
    # consume it; everyone else is warned that it's a no-op.
    thinking = kwargs.pop("thinking", None)
    if thinking is not None and provider not in THINKING_SUPPORTED_PROVIDERS:
        logger.warning(
            f"'thinking' is not supported for provider '{provider}' and will be ignored. "
            f"Supported: {sorted(THINKING_SUPPORTED_PROVIDERS)}. "
            f"(Anthropic uses extra_body.thinking for extended-thinking budgets instead.)"
        )

    if provider == "openai":
        from langchain_openai import ChatOpenAI

        # Hard cutover guard: the legacy "talk to Moonshot through ChatOpenAI"
        # shape used base_url=https://api.moonshot.ai/v1 plus extra_body.thinking.
        # 0.4.3 replaces this with a native `moonshot:` provider; refuse both
        # legacy signals with a migration message rather than silently working.
        base_url = kwargs.get("base_url") or kwargs.get("openai_api_base")
        if base_url and "moonshot.ai" in str(base_url):
            raise ValueError(
                "Direct Moonshot access via the 'openai' provider with "
                "base_url 'https://api.moonshot.ai/v1' was removed in 0.4.3. "
                "Use the native 'moonshot' provider instead:\n"
                "    model:\n"
                "      provider: moonshot\n"
                "      model: kimi-k2.5\n"
                "      thinking: false   # or true\n"
                "      api_key: ${MOONSHOT_API_KEY}"
            )
        if "extra_body" in kwargs and isinstance(kwargs["extra_body"], dict) and "thinking" in kwargs["extra_body"]:
            raise ValueError(
                "'extra_body.thinking' on the 'openai' provider was removed in 0.4.3. "
                "Use the native 'moonshot' provider with the top-level 'thinking' field instead:\n"
                "    model:\n"
                "      provider: moonshot\n"
                "      model: kimi-k2.5\n"
                "      thinking: false   # or true\n"
                "      api_key: ${MOONSHOT_API_KEY}"
            )

        if api_key:
            kwargs["api_key"] = api_key
        if effective_retries > 0:
            kwargs["max_retries"] = effective_retries
            logger.info(f"Creating ChatOpenAI: model={model_name}, max_retries={effective_retries}")
        else:
            logger.info(f"Creating ChatOpenAI: model={model_name}, kwargs={list(kwargs.keys())}")
        return ChatOpenAI(**kwargs)

    if provider == "moonshot":
        try:
            from langchain_moonshot import ChatMoonshot
        except ImportError as exc:
            raise ImportError(
                "The 'moonshot' provider requires the optional langchain-moonshot package. "
                "Install it with: pip install 'openpaw-ai[moonshot]' "
                "(or: pip install langchain-moonshot)."
            ) from exc

        # ChatMoonshot expects bool — coerce None (the WorkspaceModelConfig default)
        # to False so we don't trip its pydantic validation.
        thinking = bool(thinking or False)
        kwargs["thinking"] = thinking

        # Auto-correct temperature when the caller passed the framework default
        # (0.7) — Moonshot enforces 0.6 for thinking=False and 1.0 for thinking=True
        # and would otherwise raise a 400 at request time. We can't reliably tell
        # an unset value from a deliberate "0.7"; if it WAS deliberate, the WARNING
        # makes the override visible in the logs so the user can pin temperature
        # to the value they actually want.
        if kwargs.get("temperature") == 0.7:
            corrected = 1.0 if thinking else 0.6
            logger.warning(
                f"Moonshot: temperature 0.7 is invalid for kimi-k2.5; "
                f"auto-correcting to {corrected} for thinking={thinking}. "
                f"Set temperature explicitly in your model config to silence this warning."
            )
            kwargs["temperature"] = corrected

        if api_key:
            kwargs["api_key"] = api_key
        if effective_retries > 0:
            kwargs["max_retries"] = effective_retries
        logger.info(
            f"Creating ChatMoonshot: model={model_name}, thinking={thinking}, "
            f"temperature={kwargs.get('temperature')}"
        )
        # cast: langchain_moonshot is an optional dep and resolves to Any when
        # not installed (mypy strict + ignore_missing_imports). The cast is safe
        # because ChatMoonshot inherits from BaseChatOpenAI which is a BaseChatModel.
        return cast(BaseChatModel, ChatMoonshot(**kwargs))

    if provider == "ollama":
        try:
            from langchain_ollama import ChatOllama
        except ImportError as exc:
            raise ImportError(
                "The 'ollama' provider requires the optional langchain-ollama package. "
                "Install it with: pip install 'openpaw-ai[ollama]' "
                "(or: pip install langchain-ollama)."
            ) from exc

        # Ollama is local — no API key, and retries don't help for a connection
        # to localhost. Drop both unless the user explicitly opted in.
        kwargs.pop("api_key", None)
        if effective_retries > 0:
            logger.debug(
                "Ignoring max_retries for ollama provider (local server, fast-fail preferred)"
            )

        logger.info(
            f"Creating ChatOllama: model={model_name}, "
            f"base_url={kwargs.get('base_url', 'default')}, kwargs={list(kwargs.keys())}"
        )
        # cast: optional dep — see ChatMoonshot return above for rationale.
        return cast(BaseChatModel, ChatOllama(**kwargs))

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
        if thinking is not None:
            model_kwargs = kwargs.setdefault("model_kwargs", {})
            if thinking:
                budget = FIREWORKS_DEFAULT_THINKING_BUDGET
                max_tokens = kwargs.get("max_tokens")
                # budget must leave room for the visible answer; stay above Fireworks' 1024 floor
                if isinstance(max_tokens, int) and budget >= max_tokens:
                    budget = max(1024, max_tokens // 2)
                model_kwargs["thinking"] = {"type": "enabled", "budget_tokens": budget}
            else:
                model_kwargs["thinking"] = {"type": "disabled"}
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
        f"Supported: openai, anthropic, bedrock_converse, xai, fireworks, moonshot, ollama"
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
