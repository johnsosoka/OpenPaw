"""Model resolution for agent creation.

Encapsulates provider catalog resolution, API key lookup, and model validation
previously embedded in AgentFactory.
"""

import logging
import os
from typing import Any

from openpaw.core.config.models import ProviderDefinition
from openpaw.core.config.providers import ResolvedProvider, resolve_provider

logger = logging.getLogger(__name__)


class ModelResolver:
    """Resolves model strings through provider catalog and validates instantiation."""

    # Provider to environment variable mapping for API keys
    _PROVIDER_KEY_ENV_VARS = {
        "anthropic": "ANTHROPIC_API_KEY",
        "openai": "OPENAI_API_KEY",
        "bedrock_converse": None,
        "bedrock": None,
        "xai": "XAI_API_KEY",
        "fireworks": "FIREWORKS_API_KEY",
    }

    def __init__(
        self,
        provider_catalog: dict[str, ProviderDefinition],
        configured_model: str,
        api_key: str | None,
        region: str | None,
        extra_model_kwargs: dict[str, Any],
    ):
        """Initialize the model resolver.

        Args:
            provider_catalog: Named provider catalog from global config.
            configured_model: Statically configured model identifier.
            api_key: API key for the configured model's provider.
            region: AWS region for Bedrock models.
            extra_model_kwargs: Additional model parameters from workspace config.
        """
        self._provider_catalog = provider_catalog
        self._configured_model = configured_model
        self._api_key = api_key
        self._region = region
        self._extra_model_kwargs = extra_model_kwargs

    def resolve(self, model_str: str) -> ResolvedProvider:
        """Resolve a model string through the provider catalog.

        Args:
            model_str: Model identifier, e.g. ``"moonshot:kimi-k2.5"``.

        Returns:
            ResolvedProvider with LangChain model_str, display_str, api_key,
            region, and extra_kwargs.
        """
        return resolve_provider(model_str, self._provider_catalog)

    def resolve_api_key(self, model_str: str) -> str | None:
        """Resolve API key for the given model's provider.

        Catalog resolution takes priority: if the provider is defined in the
        catalog and carries an api_key, that value is returned immediately.
        Otherwise the original logic applies (same-provider reuse, then env
        var lookup).
        """
        resolved = self.resolve(model_str)
        if resolved.api_key is not None:
            return resolved.api_key

        # Extract LangChain provider name from the resolved model string.
        lc_model = resolved.model_str
        provider = lc_model.split(":")[0] if ":" in lc_model else "openai"
        configured_provider = (
            self._configured_model.split(":")[0]
            if ":" in self._configured_model
            else "openai"
        )

        if provider == configured_provider:
            return self._api_key
        if provider in ("bedrock_converse", "bedrock"):
            return None

        env_var = self._PROVIDER_KEY_ENV_VARS.get(provider)
        if env_var:
            return os.environ.get(env_var)
        return None

    def validate(self, model_str: str, temperature: float) -> tuple[bool, str]:
        """Validate a model string by attempting instantiation.

        Resolves through the catalog first so that catalog providers (e.g.
        ``moonshot``) are validated against their underlying LangChain type.
        """
        from openpaw.agent.model_factory import create_chat_model

        resolved = self.resolve(model_str)
        lc_model = resolved.model_str

        if ":" in lc_model:
            provider, _model_name = lc_model.split(":", 1)
        else:
            provider = "openai"

        supported = {"openai", "anthropic", "bedrock_converse", "bedrock", "xai", "fireworks"}
        if provider not in supported:
            return False, (
                f"Unsupported provider: '{provider}'. "
                f"Supported: {', '.join(sorted(supported))}"
            )

        api_key = resolved.api_key if resolved.api_key is not None else self.resolve_api_key(model_str)
        if provider not in ("bedrock_converse", "bedrock") and not api_key:
            env_var = self._PROVIDER_KEY_ENV_VARS.get(provider, f"{provider.upper()}_API_KEY")
            return False, f"No API key for provider '{provider}'. Set {env_var} in environment."

        # Merge catalog extras with workspace extras (workspace wins).
        merged_extra = {**resolved.extra_kwargs, **self._extra_model_kwargs}
        region = resolved.region or self._region

        try:
            create_chat_model(lc_model, api_key, temperature, region, merged_extra)
            return True, f"Model validated: {model_str}"
        except Exception as e:
            return False, f"Invalid model '{model_str}': {e}"

    def display_str(self, model_str: str) -> str:
        """Return the user-facing display name for a model string."""
        return self.resolve(model_str).display_str
