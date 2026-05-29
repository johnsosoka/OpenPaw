"""Formatting utilities for filesystem tool output.

Pure functions for formatting file listings and content with line numbers.
No I/O, no side effects, no dependency on FilesystemTools state.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


def format_file_listing(file_info: dict[str, Any]) -> str:
    """Format file info for display.

    Args:
        file_info: Dict with keys "path", "size" (optional), "modified_at"
            (optional), and "is_dir" (optional).

    Returns:
        Formatted string with path, size, and modification time.
        Returns an empty string if the input is malformed, with a warning logged.
    """
    if not isinstance(file_info, dict):
        logger.warning(
            f"format_file_listing expected dict, got {type(file_info).__name__}: {file_info!r}"
        )
        return ""

    path = file_info.get("path")
    if path is None:
        logger.warning(
            f"format_file_listing missing required 'path' key in file_info: {file_info!r}"
        )
        return ""

    size = file_info.get("size", 0)
    if not isinstance(size, (int, float)):
        logger.warning(
            f"format_file_listing expected numeric size for '{path}', got {type(size).__name__}: {size!r}"
        )
        size = 0

    modified = file_info.get("modified_at", "unknown")
    if not isinstance(modified, str):
        modified = str(modified)

    is_dir = file_info.get("is_dir", False)
    if not isinstance(is_dir, bool):
        is_dir = bool(is_dir)

    # Format size in human-readable form
    if size < 1024:
        size_str = f"{size}B"
    elif size < 1024 * 1024:
        size_str = f"{size / 1024:.1f}KB"
    else:
        size_str = f"{size / (1024 * 1024):.1f}MB"

    type_marker = "/" if is_dir else ""
    return f"{path}{type_marker:20s} {size_str:>10s}  {modified}"


def format_content_with_line_numbers(lines: list[str], start_line: int = 1) -> str:
    """Format file content with line numbers.

    Args:
        lines: List of content lines.
        start_line: Starting line number (default 1).

    Returns:
        Formatted string with right-aligned line numbers and arrow separators.
    """
    max_line_num = start_line + len(lines) - 1
    width = len(str(max_line_num))

    formatted_lines = []
    for i, line in enumerate(lines, start=start_line):
        # Truncate very long lines to prevent output bloat
        display_line = line[:2000] + "..." if len(line) > 2000 else line
        formatted_lines.append(f"{i:>{width}}→{display_line}")

    return "\n".join(formatted_lines)
