"""Formatting utilities for filesystem tool output.

Pure functions for formatting file listings and content with line numbers.
No I/O, no side effects, no dependency on FilesystemTools state.
"""

from typing import Any


def format_file_listing(file_info: dict[str, Any]) -> str:
    """Format file info for display.

    Args:
        file_info: Dict with keys "path", "size" (optional), "modified_at"
            (optional), and "is_dir" (optional).

    Returns:
        Formatted string with path, size, and modification time.
    """
    path = file_info["path"]
    size = file_info.get("size", 0)
    modified = file_info.get("modified_at", "unknown")
    is_dir = file_info.get("is_dir", False)

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
