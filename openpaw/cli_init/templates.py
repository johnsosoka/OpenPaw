"""Template constants and helpers for workspace scaffolding."""

from __future__ import annotations

# Template constants

TEMPLATE_AGENT_MD = """\
# AGENT: {name}

## Role

<!-- TODO: Define this agent's role and responsibilities -->

## Mission

<!-- TODO: What is this agent's core mission? -->

## Guidelines

- Be clear and concise
- Ask for clarification when unsure
- Track multi-step work with tasks
"""

TEMPLATE_USER_MD = """\
# USER CONTEXT

<!-- TODO: Describe the user(s) who will interact with this agent -->

## Preferences

- Communication style preferences
- Domain expertise level
"""

TEMPLATE_SOUL_MD = """\
# SOUL: {name}

## Identity

<!-- TODO: Define this agent's personality and character -->

## Core Values

- Accuracy over speed
- Clarity over cleverness
- Helpfulness without overstepping

## Voice

<!-- TODO: How should this agent communicate? Formal? Casual? Technical? -->
"""

TEMPLATE_HEARTBEAT_MD = """\
<!-- Heartbeat scratchpad: notes for proactive check-ins -->
<!-- Leave empty if heartbeat is not configured -->
"""

TEMPLATE_ENV = """\
# API keys for this workspace
# ANTHROPIC_API_KEY=
# OPENAI_API_KEY=
# XAI_API_KEY=
# BRAVE_API_KEY=
# DISCORD_BOT_TOKEN=
"""

_PROVIDER_API_KEY_ENV: dict[str, str | None] = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "xai": "XAI_API_KEY",
    "bedrock_converse": None,
    "bedrock": None,
}


def _parse_model_string(model: str) -> tuple[str, str]:
    """Parse a combined model string into (provider, model_id).

    Args:
        model: Model string, e.g. ``anthropic:claude-sonnet-4-20250514`` or bare ``gpt-4o``.

    Returns:
        Tuple of (provider, model_id).

    Raises:
        ValueError: If provider or model_id is empty after splitting.
    """
    if ":" in model:
        provider, _, model_id = model.partition(":")
    else:
        provider = "anthropic"
        model_id = model

    if not provider:
        raise ValueError(f"Invalid model string '{model}': provider is empty.")
    if not model_id:
        raise ValueError(f"Invalid model string '{model}': model ID is empty.")
    return provider, model_id


def _provider_api_key_env(provider: str) -> str | None:
    """Map a provider name to its conventional API key environment variable.

    Args:
        provider: Provider identifier (e.g., ``anthropic``, ``openai``).

    Returns:
        Environment variable name string, or None for providers that use
        external credentials (e.g., Bedrock uses AWS IAM, not an api_key).
    """
    if provider in _PROVIDER_API_KEY_ENV:
        return _PROVIDER_API_KEY_ENV[provider]
    return f"{provider.upper()}_API_KEY"


def _build_agent_yaml(name: str, channel: str | None, model: str | None) -> str:
    """Build agent.yaml content for a new workspace.

    When --model is provided the model section is uncommented and populated.
    When --channel is provided the channel section is uncommented with
    placeholder values.  Both, one, or neither may be supplied.

    Args:
        name: Workspace name (used in the ``name`` field).
        channel: Optional channel type string (e.g., ``telegram``).
        model: Optional combined model string (e.g., ``anthropic:claude-sonnet-4-20250514``).

    Returns:
        YAML string suitable for writing to ``agent.yaml``.
    """
    lines: list[str] = [
        f"name: {name}",
        'description: ""',
        "",
    ]

    # Model section
    if model:
        provider, model_id = _parse_model_string(model)
        api_key_env = _provider_api_key_env(provider)

        lines += [
            "model:",
            f"  provider: {provider}",
            f"  model: {model_id}",
        ]
        if api_key_env:
            lines.append(f"  api_key: ${{{api_key_env}}}")
        lines += [
            "  temperature: 0.7",
        ]

        # For well-known native providers, hint at the shorthand alternative.
        if provider in _PROVIDER_API_KEY_ENV:
            lines += [
                "",
                "# Or use shorthand with a configured provider:",
                f"# model: {provider}:{model_id}",
            ]
        lines.append("")
    else:
        lines += [
            "# model:",
            "#   provider: anthropic",
            "#   model: claude-sonnet-4-20250514",
            "#   api_key: ${ANTHROPIC_API_KEY}",
            "#   temperature: 0.7",
            "",
        ]

    # Channel section
    if channel:
        if channel == "telegram":
            lines += [
                "channel:",
                f"  type: {channel}",
                "  token: ${TELEGRAM_BOT_TOKEN}",
                "  allowed_users: []",
                "",
            ]
        elif channel == "discord":
            lines += [
                "channel:",
                f"  type: {channel}",
                "  token: ${DISCORD_BOT_TOKEN}",
                "  allowed_users: []",
                "  allowed_groups: []  # Guild IDs",
                "",
            ]
        else:
            lines += [
                "channel:",
                f"  type: {channel}",
                "",
            ]
    else:
        lines += [
            "# channel:",
            "#   type: telegram  # or discord",
            "#   token: ${TELEGRAM_BOT_TOKEN}",
            "#   allowed_users: []",
            "",
        ]

    # Queue section (always included, valid defaults)
    lines += [
        "queue:",
        "  mode: collect",
        "  debounce_ms: 1000",
        "",
        "status_updates:",
        "  enabled: true",
        "  typing_indicator: true",
        "  reactions: true",
        "  use_emojis: true",
        "  agent_start: true",
        "  tool_calls_detected: true",
        "  tool_start: true",
        "  subagent_spawned: true",
        "  edit_in_place: true",
    ]

    return "\n".join(lines) + "\n"
