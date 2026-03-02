"""Sandbox path resolution for workspace-confined file operations."""

from pathlib import Path, PurePosixPath

from openpaw.core.paths import AGENT_WRITABLE_FILES, WRITE_PROTECTED_DIRS


def _is_write_protected(relative_path: str) -> bool:
    """Return True if the given workspace-relative path falls inside a write-protected directory.

    Protection is based on path parts rather than string prefix matching, so
    ``data/file.txt`` is protected (starts with ``data``) while a hypothetical
    ``database/file.txt`` is not.

    An explicit exception is made for paths listed in ``AGENT_WRITABLE_FILES``
    (e.g. ``agent/HEARTBEAT.md``), which are always allowed regardless of
    which directory they live under.

    Args:
        relative_path: Workspace-relative path string (no ``..``, no ``/`` prefix).

    Returns:
        True if the path is inside a write-protected directory, False otherwise.
    """
    # Normalise to a PurePosixPath so we work with parts consistently.
    pure = PurePosixPath(relative_path)

    # Explicit writable-file exception takes priority.
    if str(pure) in AGENT_WRITABLE_FILES:
        return False

    # Walk from the full path upward, checking each ancestor against
    # WRITE_PROTECTED_DIRS.  This catches both exact matches (``data``) and
    # deeper paths (``data/uploads/file.txt``).
    parts = pure.parts
    for depth in range(1, len(parts) + 1):
        ancestor = str(PurePosixPath(*parts[:depth]))
        if ancestor in WRITE_PROTECTED_DIRS:
            return True

    return False


def resolve_sandboxed_path(
    workspace_root: Path,
    path: str,
    write_mode: bool = False,
) -> Path:
    """Resolve and validate that a path is within the workspace sandbox.

    Read mode (``write_mode=False``, the default):
        Rejects absolute paths, home-directory expansion (``~``), and path
        traversal (``..``).  No directory restrictions — the agent can read
        any file within the workspace root, including ``data/``.

    Write mode (``write_mode=True``):
        All read-mode checks apply, plus writes to directories listed in
        ``WRITE_PROTECTED_DIRS`` (``data/``, ``config/``, ``memory/logs``,
        ``memory/conversations``) are blocked.  The sole exception is
        ``agent/HEARTBEAT.md``, which is listed in ``AGENT_WRITABLE_FILES``
        and is always permitted.

    Args:
        workspace_root: The workspace root directory (must be resolved/absolute).
        path: Relative path string to resolve.
        write_mode: When True, enforce write-protection rules.

    Returns:
        Resolved absolute Path within the workspace.

    Raises:
        ValueError: If the path attempts to escape the sandbox or violates
            a write-protection rule.
    """
    # Reject absolute paths.
    if Path(path).is_absolute():
        raise ValueError(
            f"Absolute paths not allowed in sandbox. Use relative paths from workspace root. Got: {path}"
        )

    # Reject path traversal attempts.
    if ".." in Path(path).parts:
        raise ValueError(
            f"Path traversal (..) not allowed in sandbox. Got: {path}"
        )

    # Reject home directory expansion.
    if path.startswith("~"):
        raise ValueError(
            f"Home directory expansion (~) not allowed in sandbox. Got: {path}"
        )

    # Enforce write protection when in write mode.
    if write_mode and _is_write_protected(path):
        raise ValueError(
            f"Write access to '{path}' is not allowed. "
            "This path is inside a framework-managed directory. "
            "Write files to the 'workspace/' directory instead."
        )

    # Resolve the path relative to workspace root.
    full_path = (workspace_root / path).resolve()

    # Verify the resolved path stays within the workspace.
    try:
        full_path.relative_to(workspace_root)
    except ValueError:
        raise ValueError(
            f"Path resolves outside workspace root. Workspace: {workspace_root}, Path: {full_path}"
        ) from None

    return full_path
