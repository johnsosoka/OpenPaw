"""Shared utility modules for OpenPaw.

Filename sanitization, deduplication, and user name resolution utilities.
"""

import re
from pathlib import Path


def sanitize_filename(filename: str) -> str:
    """Sanitize filename for safe filesystem use.

    Preserves extension. Replaces spaces with underscores.
    Removes special characters. Lowercases.
    Limits length to 100 characters (stem only).
    Falls back to 'upload' if result is empty.

    Args:
        filename: Original filename to sanitize.

    Returns:
        Sanitized filename safe for filesystem operations.

    Examples:
        >>> sanitize_filename("My Report.pdf")
        'my_report.pdf'
        >>> sanitize_filename("budget (Q3) [final].xlsx")
        'budget_q3_final.xlsx'
        >>> sanitize_filename("!!!.pdf")
        'upload.pdf'
    """
    # Strip null bytes and path separators (security)
    filename = filename.replace("\0", "").replace("/", "").replace("\\", "")

    # Extract extension and stem
    path = Path(filename)
    extension = path.suffix.lower()
    stem = path.stem

    # Replace spaces with underscores
    stem = stem.replace(" ", "_")

    # Replace dots with underscores (avoid multi-dot confusion)
    stem = stem.replace(".", "_")

    # Remove special characters (keep only alphanumeric, underscore, hyphen)
    stem = re.sub(r"[^a-zA-Z0-9_-]", "", stem)

    # Lowercase
    stem = stem.lower()

    # Limit stem length to 100 characters
    if len(stem) > 100:
        stem = stem[:100]

    # Fallback if empty or only underscores/hyphens
    if not stem or not re.search(r"[a-z0-9]", stem):
        stem = "upload"

    # Reconstruct with extension
    return stem + extension


def deduplicate_path(path: Path) -> Path:
    """If path exists, append (1), (2), etc. until unique.

    Inserts the counter before the file extension.
    Safety cap at 1000 iterations to prevent infinite loops.

    Args:
        path: Path to check and potentially deduplicate.

    Returns:
        Unique path (either original or with counter suffix).

    Examples:
        >>> deduplicate_path(Path("report.pdf"))  # if exists
        Path("report(1).pdf")
        >>> deduplicate_path(Path("report.pdf"))  # if doesn't exist
        Path("report.pdf")
    """
    if not path.exists():
        return path

    stem = path.stem
    suffix = path.suffix
    parent = path.parent

    # Try incrementing counter until we find an available name
    for counter in range(1, 1001):
        candidate = parent / f"{stem}({counter}){suffix}"
        if not candidate.exists():
            return candidate

    # Safety cap reached - return the 1000th version anyway
    # (filesystem will handle the conflict)
    return parent / f"{stem}(1000){suffix}"


def resolve_user_name(
    user_id: str,
    metadata: dict,
    user_aliases: dict[int, str] | None,
) -> str | None:
    """Resolve display name for a user from aliases or metadata.

    Uses opt-in semantics: returns None when no aliases are configured,
    skips system messages, and falls back through first_name → username.

    Args:
        user_id: The user's ID string.
        metadata: Message metadata dict (may contain first_name, username).
        user_aliases: Optional mapping of numeric user IDs to display names.

    Returns:
        Display name if resolvable, None otherwise.
    """
    if not user_aliases:
        return None

    if user_id == "system":
        return None

    try:
        name = user_aliases.get(int(user_id))
        if name:
            return name
    except (ValueError, TypeError):
        pass

    first_name = metadata.get("first_name")
    if first_name:
        return str(first_name)

    username = metadata.get("username")
    if username:
        return str(username)

    return None
