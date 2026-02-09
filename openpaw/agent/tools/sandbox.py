"""Sandbox path resolution for workspace-confined file operations."""

from pathlib import Path


def resolve_sandboxed_path(workspace_root: Path, path: str) -> Path:
    """Resolve and validate that a path is within the workspace sandbox.

    Rejects:
    - Absolute paths (starting with /)
    - Home directory expansion (~)
    - Path traversal (..)
    - Access to .openpaw/ framework directory

    Args:
        workspace_root: The workspace root directory (must be resolved/absolute).
        path: Relative path string to resolve.

    Returns:
        Resolved absolute Path within the workspace.

    Raises:
        ValueError: If the path attempts to escape the sandbox or access protected dirs.
    """
    # Reject absolute paths
    if Path(path).is_absolute():
        raise ValueError(
            f"Absolute paths not allowed in sandbox. Use relative paths from workspace root. Got: {path}"
        )

    # Reject path traversal attempts
    if ".." in Path(path).parts:
        raise ValueError(
            f"Path traversal (..) not allowed in sandbox. Got: {path}"
        )

    # Reject home directory expansion
    if path.startswith("~"):
        raise ValueError(
            f"Home directory expansion (~) not allowed in sandbox. Got: {path}"
        )

    # Reject framework internal directory
    if any(part == ".openpaw" for part in Path(path).parts):
        raise ValueError(
            "Access to .openpaw/ directory is not allowed. "
            "This directory contains framework internals."
        )

    # Resolve path relative to workspace root
    full_path = (workspace_root / path).resolve()

    # Verify resolved path stays within workspace
    try:
        full_path.relative_to(workspace_root)
    except ValueError:
        raise ValueError(
            f"Path resolves outside workspace root. Workspace: {workspace_root}, Path: {full_path}"
        ) from None

    return full_path
