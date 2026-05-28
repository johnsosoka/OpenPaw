"""File search tools for agent workspace access.

Provides LangChain tools for searching files: glob_files and grep_files.
Includes ripgrep and Python fallback search backends.
"""

import json
import re
import subprocess
from pathlib import Path

from langchain_core.tools import BaseTool, tool

from openpaw.agent.tools.sandbox import resolve_sandboxed_path


class FileSearchTools:
    """Search filesystem tools for agent workspace access."""

    def __init__(self, root: Path, max_file_size_bytes: int, workspace_name: str):
        """Initialize search tools with workspace root.

        Args:
            root: Root directory for all file operations.
            max_file_size_bytes: Maximum file size for grep operations.
            workspace_name: Human-readable workspace name for output enrichment.
        """
        self.root = root
        self.max_file_size_bytes = max_file_size_bytes
        self._workspace_name = workspace_name

    def _resolve_path(self, path: str) -> Path:
        """Resolve a path relative to workspace root with security checks."""
        return resolve_sandboxed_path(self.root, path)

    def get_tools(self) -> list[BaseTool]:
        """Return list of LangChain search tools with workspace root captured in closure."""

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
                error_msg = f"Error: {e}"
                if self._workspace_name:
                    error_msg += (
                        f"\nHint: Use paths relative to your '{self._workspace_name}' workspace "
                        f"(e.g., 'notes.md', 'research/report.txt')"
                    )
                return error_msg

            if not search_path.exists():
                not_found_msg = f"Error: Directory '{path}' does not exist"
                not_found_msg += "\nUse ls('.') to see available files in your workspace."
                return not_found_msg

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
                error_msg = f"Error: {e}"
                if self._workspace_name:
                    error_msg += (
                        f"\nHint: Use paths relative to your '{self._workspace_name}' workspace "
                        f"(e.g., 'notes.md', 'research/report.txt')"
                    )
                return error_msg

            if not search_path.exists():
                return (
                    f"Error: Path '{path}' does not exist"
                    "\nUse ls('.') to see available files in your workspace."
                )

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

        return [glob_files, grep_files]

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
