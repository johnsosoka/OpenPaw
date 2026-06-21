"""File read tools for agent workspace access.

Provides LangChain tools for read-only file operations restricted to a workspace directory.
All paths are validated to prevent directory traversal and stay within the sandbox.
"""

import json
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from langchain_core.tools import BaseTool, tool

from openpaw.agent.tools.helpers.formatting import format_content_with_line_numbers, format_file_listing
from openpaw.agent.tools.sandbox import resolve_sandboxed_path

_MAX_READ_LINES = 5_000  # Safety cap for read_file limit


class FileReadTools:
    """Read-only filesystem tools for agent workspace access."""

    def __init__(self, root: Path, timezone: str, workspace_name: str, max_read_output_chars: int = 100_000):
        """Initialize read tools with workspace root.

        Args:
            root: Root directory for all file operations.
            timezone: IANA timezone identifier for timestamp display.
            workspace_name: Human-readable workspace name for output enrichment.
            max_read_output_chars: Character safety valve for read_file output.
        """
        self.root = root
        self._timezone = timezone
        self._workspace_name = workspace_name
        self._max_read_output_chars = max_read_output_chars

    def _resolve_path(self, path: str) -> Path:
        """Resolve a path relative to workspace root with security checks."""
        return resolve_sandboxed_path(self.root, path)

    def get_tools(self) -> list[BaseTool]:
        """Return list of LangChain read tools with workspace root captured in closure."""

        @tool
        def ls(path: str = ".") -> str:
            """List directory contents.

            Args:
                path: Directory path relative to workspace root (default: ".")

            Returns:
                Formatted listing of files and directories with size and modified time
            """
            try:
                dir_path = self._resolve_path(path)
            except ValueError as e:
                error_msg = f"Error: {e}"
                if self._workspace_name:
                    error_msg += (
                        f"\nHint: Use paths relative to your '{self._workspace_name}' workspace "
                        f"(e.g., 'notes.md', 'research/report.txt')"
                    )
                return error_msg

            if not dir_path.exists():
                not_found_msg = f"Error: Directory '{path}' does not exist"
                not_found_msg += "\nUse ls('.') to see available files in your workspace."
                return not_found_msg

            if not dir_path.is_dir():
                return f"Error: '{path}' is not a directory"

            try:
                results = []
                for child in sorted(dir_path.iterdir()):
                    try:
                        is_file = child.is_file()
                        is_dir = child.is_dir()
                    except OSError:
                        continue

                    # Get relative path from workspace root
                    try:
                        rel_path = child.relative_to(self.root)
                    except ValueError:
                        continue

                    if is_file:
                        try:
                            st = child.stat()
                            tz = ZoneInfo(self._timezone)
                            modified_at = datetime.fromtimestamp(st.st_mtime, tz=tz).strftime(
                                "%Y-%m-%d %H:%M:%S"
                            )
                            results.append({
                                "path": str(rel_path),
                                "is_dir": False,
                                "size": int(st.st_size),
                                "modified_at": modified_at,
                            })
                        except OSError:
                            results.append({"path": str(rel_path), "is_dir": False})
                    elif is_dir:
                        try:
                            st = child.stat()
                            tz = ZoneInfo(self._timezone)
                            modified_at = datetime.fromtimestamp(st.st_mtime, tz=tz).strftime(
                                "%Y-%m-%d %H:%M:%S"
                            )
                            results.append({
                                "path": str(rel_path),
                                "is_dir": True,
                                "size": 0,
                                "modified_at": modified_at,
                            })
                        except OSError:
                            results.append({"path": str(rel_path), "is_dir": True})

                if not results:
                    return f"Directory '{path}' is empty"

                listing = "\n".join(format_file_listing(r) for r in results)

                # Prefix with workspace header when workspace name is set
                if self._workspace_name:
                    listing = f"[Workspace: {self._workspace_name}] Contents of {path}/:\n{listing}"

                return listing

            except (OSError, PermissionError) as e:
                return f"Error listing directory: {e}"

        @tool
        def read_file(file_path: str, offset: int = 0, limit: int = 2000) -> str:
            """Read file contents with line numbers.

            Args:
                file_path: File path relative to workspace root
                offset: Line offset to start reading from (0-indexed, default: 0)
                limit: Maximum number of lines to read (default: 2000, max: 5000)

            Returns:
                File content with line numbers, or error message
            """
            if limit > _MAX_READ_LINES:
                return f"Error: limit exceeds maximum of {_MAX_READ_LINES} lines"

            try:
                resolved_path = self._resolve_path(file_path)
            except ValueError as e:
                error_msg = f"Error: {e}"
                if self._workspace_name:
                    error_msg += (
                        f"\nHint: Use paths relative to your '{self._workspace_name}' workspace "
                        f"(e.g., 'notes.md', 'research/report.txt')"
                    )
                return error_msg

            if not resolved_path.exists():
                return (
                    f"Error: File '{file_path}' not found"
                    "\nUse ls('.') to see available files in your workspace."
                )

            if not resolved_path.is_file():
                return f"Error: '{file_path}' is not a file"

            try:
                # Open with O_NOFOLLOW to prevent symlink traversal
                fd = os.open(resolved_path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
                with os.fdopen(fd, "r", encoding="utf-8") as f:
                    content = f.read()

                if not content:
                    return f"File '{file_path}' is empty"

                lines = content.splitlines()
                start_idx = offset
                end_idx = min(start_idx + limit, len(lines))

                if start_idx >= len(lines):
                    return f"Error: Line offset {offset} exceeds file length ({len(lines)} lines)"

                selected_lines = lines[start_idx:end_idx]
                result = format_content_with_line_numbers(selected_lines, start_line=start_idx + 1)

                # Add footer if file was truncated
                if end_idx < len(lines):
                    result += f"\n... ({len(lines) - end_idx} more lines)"

                # Character safety valve
                if len(result) > self._max_read_output_chars:
                    result = result[:self._max_read_output_chars]
                    result += (
                        f"\n\n... (output truncated at {self._max_read_output_chars:,} characters. "
                        f"Use offset/limit parameters to read specific sections.)"
                    )

                return result

            except FileNotFoundError:
                return (
                    f"Error: File '{file_path}' not found"
                    "\nUse ls('.') to see available files in your workspace."
                )
            except UnicodeDecodeError:
                return f"Error: File '{file_path}' is not a text file (binary content detected)"
            except OSError:
                return f"Error: Unable to read file '{file_path}'"

        @tool
        def file_info(path: str) -> str:
            """Get file metadata without reading content.

            Returns file size, line count (for text files), type detection,
            and suggested read strategy for large files.

            Args:
                path: Relative path to the file within the workspace.

            Returns:
                JSON string with file metadata
            """
            try:
                resolved_path = self._resolve_path(path)
            except ValueError as e:
                return json.dumps({"path": path, "exists": False, "error": str(e)})

            if not resolved_path.exists():
                return json.dumps({
                    "path": path,
                    "exists": False,
                    "error": "File not found. Use ls('.') to see available files in your workspace.",
                })

            if resolved_path.is_dir():
                return json.dumps({
                    "path": path,
                    "exists": True,
                    "is_directory": True,
                    "error": "Use ls for directories"
                })

            try:
                # Get file stats
                stat_info = resolved_path.stat()
                size_bytes = stat_info.st_size
                tz = ZoneInfo(self._timezone)
                last_modified = datetime.fromtimestamp(stat_info.st_mtime, tz=tz).isoformat()

                # Format human-readable size
                if size_bytes < 1024:
                    size_human = f"{size_bytes} B"
                elif size_bytes < 1024 * 1024:
                    size_human = f"{size_bytes / 1024:.1f} KB"
                elif size_bytes < 1024 * 1024 * 1024:
                    size_human = f"{size_bytes / (1024 * 1024):.1f} MB"
                else:
                    size_human = f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"

                # Check if binary by reading first 8KB
                is_binary = False
                try:
                    with open(resolved_path, "rb") as f:
                        sample = f.read(8192)
                        is_binary = b"\x00" in sample
                except (OSError, PermissionError):
                    pass

                result = {
                    "path": path,
                    "exists": True,
                    "size_bytes": size_bytes,
                    "size_human": size_human,
                    "is_binary": is_binary,
                    "last_modified": last_modified,
                }

                # For text files, count lines and suggest read strategy
                if not is_binary:
                    line_count: int | str | None = None
                    # For very large files (>10MB), use streaming approach or cap
                    if size_bytes > 10 * 1024 * 1024:
                        try:
                            # Stream count for large files
                            count = 0
                            with open(resolved_path, encoding="utf-8", errors="ignore") as f:
                                for _ in f:
                                    count += 1
                                    if count > 10000:
                                        line_count = "10000+"
                                        break
                            if line_count is None:
                                line_count = count
                        except (OSError, PermissionError):
                            line_count = None
                    else:
                        try:
                            with open(resolved_path, encoding="utf-8", errors="ignore") as f:
                                line_count = sum(1 for _ in f)
                        except (OSError, PermissionError, UnicodeDecodeError):
                            line_count = None

                    if line_count is not None:
                        result["line_count"] = line_count

                    # Suggest read strategy based on line count
                    if isinstance(line_count, int):
                        if line_count < 50:
                            result["suggested_read_strategy"] = "Small file. Safe to read in full."
                        elif line_count > 500:
                            result["suggested_read_strategy"] = (
                                f"Large file. Use read_file('{path}', offset=0, limit=100) for preview."
                            )
                    elif line_count == "10000+":
                        result["suggested_read_strategy"] = (
                            f"Very large file (10000+ lines). Use read_file('{path}', offset=0, limit=100) for preview."
                        )
                else:
                    result["suggested_read_strategy"] = "Binary file. Use appropriate tool for this file type."

                return json.dumps(result)

            except (OSError, PermissionError) as e:
                return json.dumps({
                    "path": path,
                    "exists": True,
                    "error": f"Permission or I/O error: {e}"
                })

        return [ls, read_file, file_info]
