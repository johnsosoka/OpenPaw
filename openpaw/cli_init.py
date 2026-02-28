"""CLI commands for workspace scaffolding: `openpaw init` and `openpaw list`."""

import argparse
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Template constants
# ---------------------------------------------------------------------------

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
"""

# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_-]*$")
_NAME_MIN_LEN = 2
_NAME_MAX_LEN = 64


def _validate_workspace_name(name: str) -> None:
    """Validate that name is a legal workspace identifier.

    Rules:
    - 2-64 characters
    - Starts with a lowercase letter
    - Contains only lowercase letters, digits, hyphens, and underscores

    Args:
        name: Workspace name candidate.

    Raises:
        ValueError: If the name does not meet the requirements.
    """
    if not name:
        raise ValueError("Workspace name cannot be empty.")

    if len(name) < _NAME_MIN_LEN:
        raise ValueError(
            f"Workspace name '{name}' is too short (minimum {_NAME_MIN_LEN} characters)."
        )

    if len(name) > _NAME_MAX_LEN:
        raise ValueError(
            f"Workspace name '{name}' is too long (maximum {_NAME_MAX_LEN} characters)."
        )

    if not _NAME_PATTERN.match(name):
        raise ValueError(
            f"Workspace name '{name}' is invalid. "
            "Names must start with a lowercase letter and contain only "
            "lowercase letters, digits, hyphens (-), and underscores (_)."
        )


# ---------------------------------------------------------------------------
# agent.yaml generation
# ---------------------------------------------------------------------------

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
            "",
        ]
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
        else:
            lines += [
                "channel:",
                f"  type: {channel}",
                "",
            ]
    else:
        lines += [
            "# channel:",
            "#   type: telegram",
            "#   token: ${TELEGRAM_BOT_TOKEN}",
            "#   allowed_users: []",
            "",
        ]

    # Queue section (always included, valid defaults)
    lines += [
        "queue:",
        "  mode: collect",
        "  debounce_ms: 1000",
    ]

    return "\n".join(lines) + "\n"


_PROVIDER_API_KEY_ENV: dict[str, str | None] = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "xai": "XAI_API_KEY",
    "bedrock_converse": None,
    "bedrock": None,
}


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


# ---------------------------------------------------------------------------
# Workspace creation
# ---------------------------------------------------------------------------

def _create_workspace(
    workspaces_path: Path,
    name: str,
    channel: str | None,
    model: str | None,
) -> Path:
    """Create a new workspace directory with all required template files.

    Args:
        workspaces_path: Parent directory that contains workspaces.
        name: Workspace name (used as the directory name and in templates).
        channel: Optional channel type for agent.yaml.
        model: Optional model string for agent.yaml.

    Returns:
        Path to the newly created workspace directory.

    Raises:
        FileExistsError: If the workspace directory already exists.
        OSError: If the directory or any file cannot be created.
    """
    workspace_path = workspaces_path / name

    if workspace_path.exists():
        raise FileExistsError(
            f"Workspace '{name}' already exists at {workspace_path}"
        )

    workspace_path.mkdir(parents=True, exist_ok=False)

    # Write the four required markdown files, substituting {name} where used.
    (workspace_path / "AGENT.md").write_text(
        TEMPLATE_AGENT_MD.format(name=name), encoding="utf-8"
    )
    (workspace_path / "USER.md").write_text(TEMPLATE_USER_MD, encoding="utf-8")
    (workspace_path / "SOUL.md").write_text(
        TEMPLATE_SOUL_MD.format(name=name), encoding="utf-8"
    )
    (workspace_path / "HEARTBEAT.md").write_text(TEMPLATE_HEARTBEAT_MD, encoding="utf-8")

    # Write optional but recommended files.
    (workspace_path / "agent.yaml").write_text(
        _build_agent_yaml(name, channel, model), encoding="utf-8"
    )
    (workspace_path / ".env").write_text(TEMPLATE_ENV, encoding="utf-8")

    return workspace_path


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def _print_next_steps(workspace_path: Path, name: str) -> None:
    """Print the post-creation summary and suggested next steps.

    Args:
        workspace_path: Absolute path to the created workspace directory.
        name: Workspace name.
    """
    print(f"Created workspace: {name}")
    print(f"  Path: {workspace_path}/")
    print()
    print("Next steps:")
    print("  1. Edit agent.yaml with your model and channel settings")
    print("  2. Add API keys to .env")
    print("  3. Customize AGENT.md, USER.md, and SOUL.md")
    print(f"  4. Run: openpaw -c config.yaml -w {name}")


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

def _handle_init(args: list[str]) -> None:
    """Handle the ``openpaw init <name>`` command.

    Parses arguments, validates the workspace name, creates the workspace
    directory with all required files, and prints next steps.

    Args:
        args: Remaining CLI arguments after the ``init`` subcommand token.
    """
    parser = argparse.ArgumentParser(
        prog="openpaw init",
        description="Scaffold a new OpenPaw agent workspace.",
    )
    parser.add_argument("name", help="Workspace name (e.g., my_agent)")
    parser.add_argument(
        "--path",
        type=Path,
        default=Path("agent_workspaces"),
        help="Parent directory for workspaces (default: ./agent_workspaces)",
    )
    parser.add_argument(
        "--channel",
        default=None,
        help="Pre-configure channel type (e.g., telegram)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Pre-configure model (e.g., anthropic:claude-sonnet-4-20250514)",
    )

    parsed = parser.parse_args(args)

    try:
        _validate_workspace_name(parsed.name)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    if parsed.model:
        try:
            _parse_model_string(parsed.model)
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)

    try:
        workspace_path = _create_workspace(
            parsed.path, parsed.name, parsed.channel, parsed.model
        )
    except FileExistsError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    except OSError as exc:
        print(f"Error creating workspace: {exc}", file=sys.stderr)
        sys.exit(1)

    _print_next_steps(workspace_path, parsed.name)


def _handle_list(args: list[str]) -> None:
    """Handle the ``openpaw list`` command.

    Discovers valid workspaces in the specified directory and prints their
    names, or prints an appropriate message if none are found.

    Args:
        args: Remaining CLI arguments after the ``list`` subcommand token.
    """
    parser = argparse.ArgumentParser(
        prog="openpaw list",
        description="List available OpenPaw agent workspaces.",
    )
    parser.add_argument(
        "--path",
        type=Path,
        default=Path("agent_workspaces"),
        help="Directory to search for workspaces (default: ./agent_workspaces)",
    )

    parsed = parser.parse_args(args)
    workspaces_path = parsed.path

    if not workspaces_path.exists():
        print(f"Directory not found: {workspaces_path}", file=sys.stderr)
        sys.exit(1)

    try:
        from openpaw.workspace.loader import WorkspaceLoader

        loader = WorkspaceLoader(workspaces_path)
        workspace_names = loader.list_workspaces()
    except OSError as exc:
        print(f"Error reading workspaces: {exc}", file=sys.stderr)
        sys.exit(1)

    if not workspace_names:
        print(f"No workspaces found in {workspaces_path}/")
        return

    print(f"Workspaces in {workspaces_path}/:")
    for ws_name in workspace_names:
        print(f"  {ws_name}")
    print(f"{len(workspace_names)} workspace(s) found.")


# ---------------------------------------------------------------------------
# Dispatch entry point
# ---------------------------------------------------------------------------

def dispatch_command(command: str, args: list[str]) -> None:
    """Route a CLI subcommand to its handler.

    Args:
        command: Subcommand name (``init`` or ``list``).
        args: Remaining arguments to pass to the handler.
    """
    if command == "init":
        _handle_init(args)
    elif command == "list":
        _handle_list(args)
    else:
        print(f"Error: Unknown command '{command}'.", file=sys.stderr)
        sys.exit(1)
