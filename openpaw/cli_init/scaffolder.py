"""Validation and workspace creation for CLI scaffolding."""

from __future__ import annotations

import re
from pathlib import Path

from openpaw.core.paths import (
    AGENT_DIR,
    AGENT_MD,
    AGENT_YAML,
    CONFIG_DIR,
    CRONS_DIR,
    DATA_DIR,
    DOT_ENV,
    HEARTBEAT_MD,
    MEMORY_CONVERSATIONS_DIR,
    MEMORY_DIR,
    MEMORY_LOGS_DIR,
    SKILLS_DIR,
    SOUL_MD,
    TEAM_DIR,
    TOOLS_DIR,
    USER_MD,
    WORKSPACE_DIR,
)

from .templates import (
    TEMPLATE_AGENT_MD,
    TEMPLATE_ENV,
    TEMPLATE_HEARTBEAT_MD,
    TEMPLATE_SOUL_MD,
    TEMPLATE_USER_MD,
    _build_agent_yaml,
)

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


def _scaffold_default_profiles(workspace_path: Path) -> None:
    """Copy bundled default team profiles into a new workspace.

    Copies YAML profiles from ``openpaw/builtins/profiles/`` into the
    workspace's ``agent/team/`` directory. These provide a starter team
    of sub-agent profiles that work with builtin tools.

    Args:
        workspace_path: Root path of the new workspace.
    """
    source_dir = Path(__file__).resolve().parent.parent / "builtins" / "profiles"
    if not source_dir.exists():
        return

    target_dir = workspace_path / str(TEAM_DIR)
    target_dir.mkdir(parents=True, exist_ok=True)

    for profile_file in sorted(source_dir.glob("*.yaml")):
        target_file = target_dir / profile_file.name
        if not target_file.exists():
            target_file.write_text(
                profile_file.read_text(encoding="utf-8"),
                encoding="utf-8",
            )


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

    # Create all required subdirectories.
    for subdir in [
        AGENT_DIR,
        TOOLS_DIR,
        SKILLS_DIR,
        TEAM_DIR,
        CONFIG_DIR,
        CRONS_DIR,
        DATA_DIR,
        MEMORY_DIR,
        MEMORY_CONVERSATIONS_DIR,
        MEMORY_LOGS_DIR,
        WORKSPACE_DIR,
    ]:
        (workspace_path / str(subdir)).mkdir(parents=True, exist_ok=True)

    # Write the four required identity files under agent/.
    (workspace_path / str(AGENT_MD)).write_text(
        TEMPLATE_AGENT_MD.format(name=name), encoding="utf-8"
    )
    (workspace_path / str(USER_MD)).write_text(TEMPLATE_USER_MD, encoding="utf-8")
    (workspace_path / str(SOUL_MD)).write_text(
        TEMPLATE_SOUL_MD.format(name=name), encoding="utf-8"
    )
    (workspace_path / str(HEARTBEAT_MD)).write_text(TEMPLATE_HEARTBEAT_MD, encoding="utf-8")

    # Write config files under config/.
    (workspace_path / str(AGENT_YAML)).write_text(
        _build_agent_yaml(name, channel, model), encoding="utf-8"
    )
    (workspace_path / str(DOT_ENV)).write_text(TEMPLATE_ENV, encoding="utf-8")

    # Scaffold default team profiles from bundled defaults.
    _scaffold_default_profiles(workspace_path)

    return workspace_path


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
    print("  1. Edit config/agent.yaml with your model and channel settings")
    print("  2. Add API keys to config/.env")
    print("  3. Customize agent/AGENT.md, agent/USER.md, and agent/SOUL.md")
    print("  4. Review agent/team/ for default sub-agent profiles (edit or remove)")
    print(f"  5. Run: openpaw -c config.yaml -w {name}")
