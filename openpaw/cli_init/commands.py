"""CLI command handlers for workspace scaffolding."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .scaffolder import (
    _create_workspace,
    _ensure_root_config,
    _print_next_steps,
    _validate_workspace_name,
)
from .templates import _parse_model_string

_HARNESS_CHOICES = ("react", "balanced", "ultra")
_DEFAULT_HARNESS = "balanced"
_HARNESS_MENU = {"1": "react", "2": "balanced", "3": "ultra"}


def _resolve_harness_choice(raw: str) -> str:
    """Map raw interactive input to a harness name, defaulting to balanced.

    Accepts either the menu number (``1``/``2``/``3``) or the harness name.
    Empty or unrecognized input falls back to ``balanced``.

    Args:
        raw: Raw user input from the interactive prompt.

    Returns:
        A valid harness tier name.
    """
    choice = raw.strip().lower()
    if choice in _HARNESS_MENU:
        return _HARNESS_MENU[choice]
    if choice in _HARNESS_CHOICES:
        return choice
    return _DEFAULT_HARNESS


def _prompt_harness() -> str:
    """Prompt the user to choose a reasoning harness (interactive TTY only).

    Returns:
        The chosen harness tier, defaulting to balanced on empty/invalid input.
    """
    print("Choose a reasoning harness for this agent:")
    print("  1) react    — fast single-loop, no plan tracking")
    print("  2) balanced — single-loop with a live plan checklist + creative lenses (recommended)")
    print("  3) ultra    — full planning graph, per-node models, step isolation (most capable, most expensive)")
    raw = input("Harness [2]: ")
    return _resolve_harness_choice(raw)


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
    parser.add_argument(
        "--harness",
        choices=list(_HARNESS_CHOICES),
        default=None,
        help=(
            "Reasoning harness tier: react (fast single-loop), balanced "
            "(plan checklist + creative lenses, recommended), or ultra "
            "(full planning graph). Prompts interactively when a TTY; "
            "defaults to balanced otherwise."
        ),
    )

    parsed = parser.parse_args(args)

    if parsed.harness is None:
        if sys.stdin.isatty() and sys.stdout.isatty():
            parsed.harness = _prompt_harness()
        else:
            parsed.harness = _DEFAULT_HARNESS

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
            parsed.path, parsed.name, parsed.channel, parsed.model, parsed.harness
        )
    except FileExistsError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    except OSError as exc:
        print(f"Error creating workspace: {exc}", file=sys.stderr)
        sys.exit(1)

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
