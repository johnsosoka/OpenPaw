"""CLI command handlers for workspace scaffolding."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .scaffolder import (
    _create_workspace,
    _validate_workspace_name,
)
from .templates import _parse_model_string


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
        help="Pre-configure channel type: stdio (local terminal), telegram, or discord",
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

    from .scaffolder import _ensure_root_config, _print_next_steps

    config_path = _ensure_root_config(parsed.path)
    _print_next_steps(workspace_path, parsed.name, config_path, parsed.channel)


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
