"""Workspace layout migration from flat to structured directory layout.

Runs automatically on workspace startup. Moves files from legacy locations
to the new directory structure. Idempotent — safe to run multiple times.

Legacy layout (flat):
    {workspace}/
        AGENT.md, USER.md, SOUL.md, HEARTBEAT.md
        agent.yaml, .env
        TASKS.yaml, dynamic_crons.json, heartbeat_log.jsonl
        tools/, skills/, crons/, uploads/, downloads/, screenshots/
        .openpaw/conversations.db, .openpaw/sessions.json, ...
        memory/sessions/{type}/

New structured layout:
    {workspace}/
        agent/        — identity files and extensions
        config/       — agent.yaml, .env, crons/
        data/         — framework-managed state (conversations.db, etc.)
        memory/       — conversations/ and logs/
        workspace/    — agent work area (downloads/, screenshots/)
"""

import logging
import shutil
from pathlib import Path

from openpaw.core.paths import (
    AGENT_DIR,
    AGENT_MD,
    AGENT_YAML,
    BROWSER_COOKIES_JSON,
    CONFIG_DIR,
    CONVERSATIONS_DB,
    CRONS_DIR,
    DATA_DIR,
    DOT_ENV,
    DOWNLOADS_DIR,
    DYNAMIC_CRONS_JSON,
    HEARTBEAT_LOG_JSONL,
    HEARTBEAT_MD,
    MEMORY_CONVERSATIONS_DIR,
    MEMORY_DIR,
    MEMORY_LOGS_DIR,
    SCREENSHOTS_DIR,
    SESSIONS_JSON,
    SKILLS_DIR,
    SOUL_MD,
    SUBAGENTS_YAML,
    TASKS_YAML,
    TOKEN_USAGE_JSONL,
    TOOLS_DIR,
    UPLOADS_DIR,
    USER_MD,
    VECTORS_DB,
    WORKSPACE_DIR,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Top-level directories created during migration
# ---------------------------------------------------------------------------

_TARGET_DIRS = [
    AGENT_DIR,
    CONFIG_DIR,
    DATA_DIR,
    MEMORY_DIR,
    WORKSPACE_DIR,
    MEMORY_CONVERSATIONS_DIR,
    MEMORY_LOGS_DIR,
]

# ---------------------------------------------------------------------------
# File migration table: (old_relative, new_relative)
# ---------------------------------------------------------------------------

_FILE_MIGRATIONS = [
    # Identity files → agent/
    ("AGENT.md",      AGENT_MD),
    ("USER.md",       USER_MD),
    ("SOUL.md",       SOUL_MD),
    ("HEARTBEAT.md",  HEARTBEAT_MD),
    # Config → config/
    ("agent.yaml",    AGENT_YAML),
    (".env",          DOT_ENV),
    # Root-level state → data/
    ("TASKS.yaml",           TASKS_YAML),
    ("dynamic_crons.json",   DYNAMIC_CRONS_JSON),
    ("heartbeat_log.jsonl",  HEARTBEAT_LOG_JSONL),
    # .openpaw/ contents → data/
    (".openpaw/conversations.db",    CONVERSATIONS_DB),
    (".openpaw/sessions.json",       SESSIONS_JSON),
    (".openpaw/subagents.yaml",      SUBAGENTS_YAML),
    (".openpaw/token_usage.jsonl",   TOKEN_USAGE_JSONL),
    (".openpaw/vectors.db",          VECTORS_DB),
    (".openpaw/browser_cookies.json", BROWSER_COOKIES_JSON),
    # SQLite WAL/SHM companion files (handled separately for clarity)
    (".openpaw/conversations.db-wal", DATA_DIR / "conversations.db-wal"),
    (".openpaw/conversations.db-shm", DATA_DIR / "conversations.db-shm"),
]

# ---------------------------------------------------------------------------
# Directory migration table: (old_relative, new_relative)
# ---------------------------------------------------------------------------

_DIR_MIGRATIONS = [
    # Extension directories → agent/
    ("tools",    TOOLS_DIR),
    ("skills",   SKILLS_DIR),
    # Config → config/
    ("crons",    CRONS_DIR),
    # Data → data/
    ("uploads",  UPLOADS_DIR),
    # Agent work area → workspace/
    ("downloads",   DOWNLOADS_DIR),
    ("screenshots", SCREENSHOTS_DIR),
    # memory/sessions → memory/logs (rename)
    ("memory/sessions", MEMORY_LOGS_DIR),
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def migrate_workspace(workspace_path: Path) -> list[str]:
    """Migrate a workspace from the legacy flat layout to the structured layout.

    Creates target directories, moves files and directories from their old
    locations to new locations, then cleans up the (now-empty) .openpaw/
    directory.

    This function is idempotent. If a file or directory already exists at the
    target location, the migration for that item is skipped and a warning is
    logged. Existing data is never overwritten or deleted.

    Args:
        workspace_path: Absolute path to the workspace root directory.

    Returns:
        A list of human-readable action strings describing what was moved.
        Returns an empty list when no migration was needed.
    """
    actions: list[str] = []

    _ensure_target_dirs(workspace_path, actions)

    for old_rel, new_rel in _FILE_MIGRATIONS:
        _migrate_file(workspace_path, old_rel, str(new_rel), actions)

    for old_rel, new_rel in _DIR_MIGRATIONS:
        _migrate_dir(workspace_path, old_rel, str(new_rel), actions)

    _cleanup_empty_dir(workspace_path / ".openpaw", actions)

    return actions


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _ensure_target_dirs(workspace: Path, actions: list[str]) -> None:
    """Create all target directories that do not yet exist.

    ``memory/logs/`` is skipped when ``memory/sessions/`` is still present: the
    directory migration that renames sessions → logs will create it.  Creating
    the empty target first would block the rename and leave the content stranded
    in ``memory/sessions/``.
    """
    legacy_sessions = workspace / "memory" / "sessions"

    for rel_dir in _TARGET_DIRS:
        target = workspace / str(rel_dir)

        # Defer memory/logs creation when the rename migration will handle it.
        if rel_dir == MEMORY_LOGS_DIR and legacy_sessions.exists():
            continue

        if not target.exists():
            target.mkdir(parents=True, exist_ok=True)
            msg = f"Created {rel_dir}/"
            actions.append(msg)
            logger.info("Migration: %s", msg)


def _migrate_file(
    workspace: Path,
    old: str,
    new: str,
    actions: list[str],
) -> None:
    """Move a single file from *old* to *new* if the old path exists.

    Skips the move if the target path already exists (logs a warning so the
    operator knows there is a conflict). The source file is left in place when
    skipped — data is never deleted.

    Args:
        workspace: Workspace root directory.
        old: Relative path of the source file.
        new: Relative path of the destination file.
        actions: Accumulator list for human-readable action strings.
    """
    src = workspace / old
    dst = workspace / new

    if not src.exists():
        return

    if dst.exists():
        logger.warning(
            "Migration conflict: cannot move %s → %s (destination already exists). "
            "Leaving source in place.",
            old,
            new,
        )
        return

    dst.parent.mkdir(parents=True, exist_ok=True)
    src.rename(dst)
    msg = f"Moved {old} → {new}"
    actions.append(msg)
    logger.info("Migration: %s", msg)


def _migrate_dir(
    workspace: Path,
    old: str,
    new: str,
    actions: list[str],
) -> None:
    """Move a directory from *old* to *new* if the old path exists.

    Uses :func:`shutil.move` to handle cross-filesystem moves. Skips the move
    if the target path already exists (logs a warning). The source directory is
    left in place when skipped — data is never deleted.

    Args:
        workspace: Workspace root directory.
        old: Relative path of the source directory.
        new: Relative path of the destination directory.
        actions: Accumulator list for human-readable action strings.
    """
    src = workspace / old
    dst = workspace / new

    if not src.exists():
        return

    if dst.exists():
        logger.warning(
            "Migration conflict: cannot move %s → %s (destination already exists). "
            "Leaving source in place.",
            old,
            new,
        )
        return

    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    msg = f"Moved {old}/ → {new}/"
    actions.append(msg)
    logger.info("Migration: %s", msg)


def _cleanup_empty_dir(dir_path: Path, actions: list[str]) -> None:
    """Remove *dir_path* if it exists and is empty.

    Performs no action when the directory does not exist or still contains
    files (which would indicate un-migrated items).

    Args:
        dir_path: Absolute path to the directory to (possibly) remove.
        actions: Accumulator list for human-readable action strings.
    """
    if not dir_path.exists():
        return

    try:
        dir_path.rmdir()  # Only succeeds when directory is empty
        rel = dir_path.name
        msg = f"Removed empty {rel}/"
        actions.append(msg)
        logger.info("Migration: %s", msg)
    except OSError:
        # Directory still has contents — leave it alone.
        pass
