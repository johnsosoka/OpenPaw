"""Sandboxed filesystem tools for agent workspace access.

Provides LangChain tools for file operations restricted to a workspace directory.
All paths are validated to prevent directory traversal and stay within the sandbox.
"""

import json
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from langchain_core.tools import BaseTool, tool

from openpaw.agent.tools.sandbox import resolve_sandboxed_path


class FilesystemTools:
    """Sandboxed filesystem tools for agent workspace access.

    All operations are restricted to the workspace root directory with security checks
    to prevent path traversal attacks and access outside the sandbox.
    """

    def __init__(self, workspace_root: Path, max_file_size_mb: int = 10, timezone: str = "UTC"):
        """Initialize filesystem tools with workspace sandbox.

        Args:
            workspace_root: Root directory for all file operations
            max_file_size_mb: Maximum file size in MB for operations like grep
            timezone: IANA timezone identifier for timestamp display (default: UTC)
        """
        self.root = workspace_root.resolve()
        self.max_file_size_bytes = max_file_size_mb * 1024 * 1024
        self._max_read_output_chars: int = 100_000  # Character safety valve for read_file output
        self._timezone = timezone

    def _resolve_path(self, path: str) -> Path:
        """Resolve a path relative to workspace root with security checks."""
        return resolve_sandboxed_path(self.root, path)

    def _format_file_listing(self, file_info: dict[str, Any]) -> str:
        """Format file info for display."""
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

    def _format_content_with_line_numbers(
        self, lines: list[str], start_line: int = 1
    ) -> str:
        """Format file content with line numbers."""
        max_line_num = start_line + len(lines) - 1
        width = len(str(max_line_num))

        formatted_lines = []
        for i, line in enumerate(lines, start=start_line):
            # Truncate very long lines to prevent output bloat
            display_line = line[:2000] + "..." if len(line) > 2000 else line
            formatted_lines.append(f"{i:>{width}}→{display_line}")

        return "\n".join(formatted_lines)

    def get_tools(self) -> list[BaseTool]:
        """Return list of LangChain tools with workspace root captured in closure."""

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
                return f"Error: {e}"

            if not dir_path.exists():
                return f"Error: Directory '{path}' does not exist"

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

                return "\n".join(self._format_file_listing(r) for r in results)

            except (OSError, PermissionError) as e:
                return f"Error listing directory: {e}"

        @tool
        def read_file(file_path: str, offset: int = 0, limit: int = 2000) -> str:
            """Read file contents with line numbers.

            Args:
                file_path: File path relative to workspace root
                offset: Line offset to start reading from (0-indexed, default: 0)
                limit: Maximum number of lines to read (default: 2000)

            Returns:
                File content with line numbers, or error message
            """
            try:
                resolved_path = self._resolve_path(file_path)
            except ValueError as e:
                return f"Error: {e}"

            if not resolved_path.exists():
                return f"Error: File '{file_path}' not found"

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
                result = self._format_content_with_line_numbers(selected_lines, start_line=start_idx + 1)

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

            except UnicodeDecodeError:
                return f"Error: File '{file_path}' is not a text file (binary content detected)"
            except OSError as e:
                return f"Error reading file '{file_path}': {e}"

        @tool
        def write_file(file_path: str, content: str) -> str:
            """Write content to a new file.

            Creates parent directories if needed. Fails if file already exists.

            Args:
                file_path: File path relative to workspace root
                content: Text content to write

            Returns:
                Success message or error
            """
            try:
                resolved_path = self._resolve_path(file_path)
            except ValueError as e:
                return f"Error: {e}"

            if resolved_path.exists():
                return f"Error: File '{file_path}' already exists. Use edit_file to modify existing files."

            try:
                # Create parent directories if needed
                resolved_path.parent.mkdir(parents=True, exist_ok=True)

                # Write with O_NOFOLLOW to prevent symlink traversal
                flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
                if hasattr(os, "O_NOFOLLOW"):
                    flags |= os.O_NOFOLLOW
                fd = os.open(resolved_path, flags, 0o644)
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(content)

                lines = len(content.splitlines())
                return f"Successfully wrote {lines} lines to '{file_path}'"

            except OSError as e:
                return f"Error writing file '{file_path}': {e}"

        @tool
        def overwrite_file(file_path: str, content: str) -> str:
            """Write content to a file, creating or overwriting as needed.

            Creates parent directories if needed. Overwrites existing file content.
            Use this when you want to replace the entire contents of a file,
            such as updating HEARTBEAT.md or other state files.

            Args:
                file_path: File path relative to workspace root
                content: Text content to write

            Returns:
                Success message or error
            """
            try:
                resolved_path = self._resolve_path(file_path)
            except ValueError as e:
                return f"Error: {e}"

            try:
                resolved_path.parent.mkdir(parents=True, exist_ok=True)

                flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
                if hasattr(os, "O_NOFOLLOW"):
                    flags |= os.O_NOFOLLOW
                fd = os.open(resolved_path, flags, 0o644)
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(content)

                lines = len(content.splitlines())
                return f"Successfully wrote {lines} lines to '{file_path}'"

            except OSError as e:
                return f"Error writing file '{file_path}': {e}"

        @tool
        def edit_file(file_path: str, old_text: str, new_text: str, replace_all: bool = False) -> str:
            """Edit existing file by replacing text.

            Args:
                file_path: File path relative to workspace root
                old_text: Text to search for and replace (must be exact match)
                new_text: Replacement text
                replace_all: If True, replace all occurrences. If False, only replace if exactly one match exists.

            Returns:
                Success message with occurrence count, or error
            """
            try:
                resolved_path = self._resolve_path(file_path)
            except ValueError as e:
                return f"Error: {e}"

            if not resolved_path.exists():
                return f"Error: File '{file_path}' not found"

            if not resolved_path.is_file():
                return f"Error: '{file_path}' is not a file"

            try:
                # Read current content
                fd = os.open(resolved_path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
                with os.fdopen(fd, "r", encoding="utf-8") as f:
                    content = f.read()

                # Count occurrences
                occurrences = content.count(old_text)

                if occurrences == 0:
                    return f"Error: Text not found in '{file_path}'. No changes made."

                if not replace_all and occurrences > 1:
                    return (
                        f"Error: Found {occurrences} occurrences of text in '{file_path}'. "
                        f"Use replace_all=True to replace all, or provide more context to match exactly one occurrence."
                    )

                # Perform replacement
                new_content = content.replace(old_text, new_text)

                # Write back
                flags = os.O_WRONLY | os.O_TRUNC
                if hasattr(os, "O_NOFOLLOW"):
                    flags |= os.O_NOFOLLOW
                fd = os.open(resolved_path, flags)
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(new_content)

                return f"Successfully replaced {occurrences} occurrence(s) in '{file_path}'"

            except UnicodeDecodeError:
                return f"Error: File '{file_path}' is not a text file"
            except OSError as e:
                return f"Error editing file '{file_path}': {e}"

        @tool
        def glob_files(pattern: str, path: str = ".") -> str:
            """Find files matching a glob pattern.

            Args:
                pattern: Glob pattern (e.g., "*.py", "**/*.txt", "src/**/*.ts")
                path: Base directory to search from (default: ".")

            Returns:
                List of matching file paths relative to workspace root
            """
            try:
                search_path = self._resolve_path(path)
            except ValueError as e:
                return f"Error: {e}"

            if not search_path.exists():
                return f"Error: Directory '{path}' does not exist"

            if not search_path.is_dir():
                return f"Error: '{path}' is not a directory"

            try:
                # Use rglob for recursive patterns, glob for non-recursive
                if "**" in pattern:
                    # Strip leading ** if present
                    clean_pattern = pattern.lstrip("*").lstrip("/")
                    matches = search_path.rglob(clean_pattern)
                else:
                    matches = search_path.glob(pattern)

                results = []
                for matched_path in matches:
                    try:
                        if not matched_path.is_file():
                            continue
                    except (PermissionError, OSError):
                        continue

                    # Get path relative to workspace root
                    try:
                        rel_path = matched_path.relative_to(self.root)
                        results.append(str(rel_path))
                    except ValueError:
                        continue

                if not results:
                    return f"No files matching pattern '{pattern}' in '{path}'"

                results.sort()
                return "\n".join(results)

            except (OSError, ValueError) as e:
                return f"Error searching for pattern '{pattern}': {e}"

        @tool
        def grep_files(
            pattern: str,
            path: str = ".",
            file_pattern: str | None = None,
            case_sensitive: bool = True,
            max_matches: int = 100,
            context_lines: int = 0,
        ) -> str:
            """Search file contents for a pattern.

            Uses ripgrep if available, falls back to Python regex search.

            Args:
                pattern: Regex pattern to search for
                path: Directory to search in (default: ".")
                file_pattern: Optional glob to filter files (e.g., "*.py")
                case_sensitive: Whether search is case-sensitive (default: True)
                max_matches: Maximum number of matches to return (default: 100)
                context_lines: Number of lines to show before and after each match (default: 0)

            Returns:
                Matching lines with file path and line number
            """
            try:
                search_path = self._resolve_path(path)
            except ValueError as e:
                return f"Error: {e}"

            if not search_path.exists():
                return f"Error: Path '{path}' does not exist"

            # Try ripgrep first
            result = self._ripgrep_search(
                pattern, search_path, file_pattern, case_sensitive, max_matches, context_lines
            )

            # Fallback to Python search if ripgrep unavailable
            if result is None:
                result = self._python_search(
                    pattern, search_path, file_pattern, case_sensitive, max_matches, context_lines
                )

            if not result:
                return f"No matches found for pattern '{pattern}' in '{path}'"

            # result is either a formatted string (with context) or a list of tuples (no context)
            if isinstance(result, str):
                # Already formatted with context
                return result
            else:
                # Legacy format: list of tuples
                matches = result
                results = []
                for file_path, line_num, line_text in matches[:max_matches]:
                    # Truncate long lines
                    display_line = line_text[:200] + "..." if len(line_text) > 200 else line_text
                    results.append(f"{file_path}:{line_num}: {display_line}")

                count_msg = (
                    f"\n\n(Showing {len(results)} of {len(matches)} matches)"
                    if len(matches) > max_matches
                    else ""
                )
                return "\n".join(results) + count_msg

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
                return json.dumps({"path": path, "exists": False, "error": "File not found"})

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

        return [ls, read_file, write_file, overwrite_file, edit_file, glob_files, grep_files, file_info]

    def _ripgrep_search(
        self,
        pattern: str,
        base_path: Path,
        file_pattern: str | None,
        case_sensitive: bool,
        max_matches: int,
        context_lines: int = 0,
    ) -> list[tuple[str, int, str]] | str | None:
        """Search using ripgrep (if available).

        Returns:
            None if ripgrep unavailable
            List of tuples when context_lines=0 (backward compatible)
            Formatted string when context_lines>0
        """
        cmd = ["rg", "--json"]

        if not case_sensitive:
            cmd.append("-i")

        if file_pattern:
            cmd.extend(["--glob", file_pattern])

        if context_lines > 0:
            cmd.extend(["-C", str(context_lines)])

        cmd.extend(["--", pattern, str(base_path)])

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return None

        # When context_lines > 0, use new formatting
        if context_lines > 0:
            return self._format_ripgrep_with_context(proc.stdout, max_matches)

        # Legacy path: no context
        matches = []
        for line in proc.stdout.splitlines():
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue

            if data.get("type") != "match":
                continue

            match_data = data.get("data", {})
            file_path = match_data.get("path", {}).get("text")
            if not file_path:
                continue

            # Convert to relative path from workspace root
            try:
                rel_path = Path(file_path).resolve().relative_to(self.root)
            except ValueError:
                continue

            line_num = match_data.get("line_number")
            line_text = match_data.get("lines", {}).get("text", "").rstrip("\n")

            if line_num is None:
                continue

            matches.append((str(rel_path), int(line_num), line_text))

            if len(matches) >= max_matches * 2:  # Get extra for truncation
                break

        return matches

    def _format_ripgrep_with_context(self, rg_output: str, max_matches: int) -> str:
        """Format ripgrep JSON output with context lines.

        Args:
            rg_output: JSON output from ripgrep -C command
            max_matches: Maximum number of match groups to include

        Returns:
            Formatted string with matches and context, using standard grep conventions
        """
        match_groups = []
        current_group = []
        last_line_num = None
        last_file_path = None
        match_count = 0

        for line in rg_output.splitlines():
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue

            record_type = data.get("type")
            if record_type not in ("match", "context"):
                continue

            record_data = data.get("data", {})
            file_path_obj = record_data.get("path", {}).get("text")
            if not file_path_obj:
                continue

            # Convert to relative path from workspace root
            try:
                rel_path = str(Path(file_path_obj).resolve().relative_to(self.root))
            except ValueError:
                continue

            line_num = record_data.get("line_number")
            line_text = record_data.get("lines", {}).get("text", "").rstrip("\n")

            if line_num is None:
                continue

            # Truncate long lines (same as match lines)
            display_line = line_text[:200] + "..." if len(line_text) > 200 else line_text

            # Check if this is a new match group (non-contiguous)
            if last_file_path is not None and last_line_num is not None:
                # New file or gap in line numbers means new group
                if rel_path != last_file_path or line_num > last_line_num + 1:
                    if current_group:
                        match_groups.append(current_group)
                        current_group = []

            # Format line according to type
            if record_type == "match":
                formatted = f"{rel_path}:{line_num}: {display_line}"
                match_count += 1
            else:  # context
                formatted = f"{rel_path}-{line_num}- {display_line}"

            current_group.append(formatted)
            last_line_num = line_num
            last_file_path = rel_path

            # Stop if we've hit max matches
            if match_count >= max_matches:
                break

        # Add final group
        if current_group:
            match_groups.append(current_group)

        # Build output with -- separators
        output_parts = []
        for i, group in enumerate(match_groups[:max_matches]):
            if i > 0:
                output_parts.append("--")
            output_parts.extend(group)

        if not output_parts:
            return ""

        result = "\n".join(output_parts)

        # Add count message if truncated
        if match_count > max_matches:
            result += f"\n\n(Showing first {max_matches} matches)"

        return result

    def _python_search(
        self,
        pattern: str,
        base_path: Path,
        file_pattern: str | None,
        case_sensitive: bool,
        max_matches: int,
        context_lines: int = 0,
    ) -> list[tuple[str, int, str]] | str:
        """Fallback search using Python regex.

        Returns:
            List of tuples when context_lines=0 (backward compatible)
            Formatted string when context_lines>0
        """
        try:
            flags = 0 if case_sensitive else re.IGNORECASE
            regex = re.compile(pattern, flags)
        except re.error as e:
            return [(f"Invalid regex pattern: {e}", 0, "")]

        if context_lines > 0:
            return self._python_search_with_context(
                regex, base_path, file_pattern, max_matches, context_lines
            )

        # Legacy path: no context
        matches = []
        search_root = base_path if base_path.is_dir() else base_path.parent

        for file_path in search_root.rglob("*"):
            try:
                if not file_path.is_file():
                    continue
            except (PermissionError, OSError):
                continue

            # Filter by file pattern if provided
            if file_pattern:
                # Simple glob matching on filename
                if not Path(file_path.name).match(file_pattern):
                    continue

            # Skip files that are too large
            try:
                if file_path.stat().st_size > self.max_file_size_bytes:
                    continue
            except OSError:
                continue

            # Read and search file
            try:
                content = file_path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, PermissionError, OSError):
                continue

            # Get relative path
            try:
                rel_path = file_path.relative_to(self.root)
            except ValueError:
                continue

            for line_num, line in enumerate(content.splitlines(), 1):
                if regex.search(line):
                    matches.append((str(rel_path), line_num, line))

                    if len(matches) >= max_matches * 2:
                        return matches

        return matches

    def _python_search_with_context(
        self,
        regex: re.Pattern[str],
        base_path: Path,
        file_pattern: str | None,
        max_matches: int,
        context_lines: int,
    ) -> str:
        """Python search with context lines.

        Args:
            regex: Compiled regex pattern
            base_path: Path to search in
            file_pattern: Optional glob to filter files
            max_matches: Maximum number of matches
            context_lines: Number of context lines before and after

        Returns:
            Formatted string with matches and context
        """
        match_groups = []
        match_count = 0
        search_root = base_path if base_path.is_dir() else base_path.parent

        for file_path in search_root.rglob("*"):
            try:
                if not file_path.is_file():
                    continue
            except (PermissionError, OSError):
                continue

            # Filter by file pattern if provided
            if file_pattern:
                if not Path(file_path.name).match(file_pattern):
                    continue

            # Skip files that are too large
            try:
                if file_path.stat().st_size > self.max_file_size_bytes:
                    continue
            except OSError:
                continue

            # Read and search file
            try:
                content = file_path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, PermissionError, OSError):
                continue

            # Get relative path
            try:
                rel_path = str(file_path.relative_to(self.root))
            except ValueError:
                continue

            lines = content.splitlines()

            # Find all matches in this file
            match_line_nums = []
            for line_num, line in enumerate(lines, 1):
                if regex.search(line):
                    match_line_nums.append(line_num)

            if not match_line_nums:
                continue

            # Build context windows for each match
            for match_line_num in match_line_nums:
                if match_count >= max_matches:
                    break

                # Calculate context window (1-indexed line numbers)
                start_line = max(1, match_line_num - context_lines)
                end_line = min(len(lines), match_line_num + context_lines)

                group_lines = []
                for line_num in range(start_line, end_line + 1):
                    line_text = lines[line_num - 1]  # Convert to 0-indexed
                    # Truncate long lines
                    display_line = line_text[:200] + "..." if len(line_text) > 200 else line_text

                    if line_num == match_line_num:
                        # Match line
                        formatted = f"{rel_path}:{line_num}: {display_line}"
                    else:
                        # Context line
                        formatted = f"{rel_path}-{line_num}- {display_line}"

                    group_lines.append(formatted)

                match_groups.append(group_lines)
                match_count += 1

            if match_count >= max_matches:
                break

        if not match_groups:
            return ""

        # Merge overlapping groups within same file
        merged_groups = []
        i = 0
        while i < len(match_groups):
            current_group = match_groups[i]
            i += 1

            # Check if next group overlaps with current
            while i < len(match_groups):
                next_group = match_groups[i]

                # Extract file path and line numbers from first line of each group
                if not current_group or not next_group:
                    break

                current_last = current_group[-1]
                next_first = next_group[0]

                # Parse file:linenum or file-linenum from formatted strings
                current_parts = current_last.split(":")
                next_parts = next_first.split(":")
                if len(current_parts) < 2 or len(next_parts) < 2:
                    # Try hyphen separator for context lines
                    current_parts = current_last.split("-")
                    next_parts = next_first.split("-")

                if len(current_parts) >= 2 and len(next_parts) >= 2:
                    current_file = current_parts[0]
                    next_file = next_parts[0]

                    try:
                        current_line_str = current_parts[1].split()[0] if len(current_parts[1].split()) > 0 else "0"
                        next_line_str = next_parts[1].split()[0] if len(next_parts[1].split()) > 0 else "0"
                        current_line = int(current_line_str.rstrip("-"))
                        next_line = int(next_line_str.rstrip("-"))

                        # If same file and overlapping or adjacent, merge
                        if current_file == next_file and next_line <= current_line + 1:
                            # Merge by adding unique lines from next_group
                            current_group.extend(next_group)
                            i += 1
                            continue
                    except (ValueError, IndexError):
                        pass

                break

            merged_groups.append(current_group)

        # Build output with -- separators
        output_parts = []
        for i, group in enumerate(merged_groups):
            if i > 0:
                output_parts.append("--")
            output_parts.extend(group)

        result = "\n".join(output_parts)

        if match_count > max_matches:
            result += f"\n\n(Showing first {max_matches} matches)"

        return result


if __name__ == "__main__":
    """Quick sanity test of filesystem tools."""
    import tempfile

    # Create test workspace
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)

        # Create test files
        (workspace / "test.txt").write_text("Hello World\nLine 2\nLine 3\n")
        (workspace / "subdir").mkdir()
        (workspace / "subdir" / "nested.py").write_text("def hello():\n    pass\n")

        # Initialize tools
        fs_tools = FilesystemTools(workspace)
        tools = fs_tools.get_tools()

        print("Filesystem Tools Test")
        print("=" * 50)

        # Test ls
        ls_tool = tools[0]
        print("\nTest 1: ls('.')")
        print(ls_tool.invoke({"path": "."}))

        # Test read_file
        read_tool = tools[1]
        print("\nTest 2: read_file('test.txt')")
        print(read_tool.invoke({"file_path": "test.txt"}))

        # Test write_file
        write_tool = tools[2]
        print("\nTest 3: write_file('new.txt', 'content')")
        print(write_tool.invoke({"file_path": "new.txt", "content": "New file content\n"}))

        # Test edit_file
        edit_tool = tools[3]
        print("\nTest 4: edit_file('test.txt', 'World', 'Universe')")
        print(edit_tool.invoke({"file_path": "test.txt", "old_text": "World", "new_text": "Universe"}))

        # Test glob_files
        glob_tool = tools[4]
        print("\nTest 5: glob_files('*.txt')")
        print(glob_tool.invoke({"pattern": "*.txt"}))

        # Test grep_files
        grep_tool = tools[5]
        print("\nTest 6: grep_files('def')")
        print(grep_tool.invoke({"pattern": "def"}))

        # Test security: path traversal
        print("\nTest 7: Security - path traversal attempt")
        print(read_tool.invoke({"file_path": "../etc/passwd"}))

        print("\n" + "=" * 50)
        print("All tests completed!")
