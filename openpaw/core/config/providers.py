"""Provider catalog resolution for OpenPaw.

Resolves named provider entries from the global catalog into the concrete
connection details that AgentRunner and create_chat_model() expect.
"""

from dataclasses import dataclass, field
from typing import Any

from openpaw.core.config.models import ProviderDefinition


@dataclass(frozen=True)
class ResolvedProvider:
    """Resolved provider connection details.

    Produced by resolve_provider() after looking up a provider name in the
    catalog.  Carries both the LangChain-level model string (model_str) and
    the original user-facing name (display_str) so callers can show the
    friendly catalog name while passing the correct type to LangChain.
    """

    model_str: str
    """LangChain model string, e.g. 'openai:kimi-k2.5'."""

    display_str: str
    """User-facing string, e.g. 'moonshot:kimi-k2.5'."""

    api_key: str | None
    """API key resolved from the provider definition, if any."""

    region: str | None
    """AWS region resolved from the provider definition, if any."""

    extra_kwargs: dict[str, Any] = field(default_factory=dict)
    """base_url plus any extra provider-specific kwargs."""


def resolve_provider(
    model_input: str,
    catalog: dict[str, ProviderDefinition],
) -> ResolvedProvider:
    """Resolve a model string against the provider catalog.

    Parses ``model_input`` as ``"provider_name:model_id"``, looks up the
    provider name in ``catalog``, and returns a :class:`ResolvedProvider`
    with the concrete connection details.

    If the provider name is not present in the catalog the input is passed
    through unchanged so that all existing behaviour (native LangChain
    providers, bare model strings) continues to work without modification.

    Args:
        model_input: Model string in ``"provider:model_id"`` format, e.g.
            ``"moonshot:kimi-k2.5"`` or ``"anthropic:claude-sonnet-4-20250514"``.
        catalog: Named provider map loaded from ``Config.providers``.

    Returns:
        ResolvedProvider with LangChain model string, display string, API
        key, region, and extra kwargs.
    """
    if ":" in model_input:
        provider_name, _, model_id = model_input.partition(":")
    else:
        # No colon — treat the whole string as a model ID with no provider.
        # Pass through unchanged; LangChain will handle or raise.
        return ResolvedProvider(
            model_str=model_input,
            display_str=model_input,
            api_key=None,
            region=None,
            extra_kwargs={},
        )

    definition = catalog.get(provider_name)
    if definition is None:
        # Unknown provider — pass through unchanged for backward compatibility.
        return ResolvedProvider(
            model_str=model_input,
            display_str=model_input,
            api_key=None,
            region=None,
            extra_kwargs={},
        )

    # The LangChain type defaults to the catalog key name when not specified.
    langchain_type = definition.type or provider_name

    # Build extra_kwargs: start with all fields excluding connection primitives,
    # then exclude None values.  This captures base_url plus any arbitrary
    # provider-specific kwargs stored via model_config extra="allow".
    extra_kwargs: dict[str, Any] = definition.model_dump(
        exclude={"type", "api_key", "region"},
        exclude_none=True,
    )

    return ResolvedProvider(
        model_str=f"{langchain_type}:{model_id}",
        display_str=model_input,
        api_key=definition.api_key,
        region=definition.region,
        extra_kwargs=extra_kwargs,
    )
