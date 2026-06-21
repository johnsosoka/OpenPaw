"""File search tools for agent workspace access.

Provides LangChain tools for searching files: glob_files and grep_files.
Includes ripgrep and Python fallback search backends.
"""

import re
from pathlib import Path

from langchain_core.tools import BaseTool, tool

from openpaw.agent.tools.file_search.formatter import GrepContextFormatter
from openpaw.agent.tools.file_search.python_backend import PythonBackend
from openpaw.agent.tools.file_search.ripgrep_backend import RipgrepBackend
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
        self._ripgrep = RipgrepBackend(root)
        self._python = PythonBackend(root, max_file_size_bytes)
        self._formatter = GrepContextFormatter()

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
                if "**" in pattern:
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
                re.compile(pattern)
            except re.error as e:
                return f"Error: Invalid regex pattern: {e}"

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

            result = self._ripgrep.search(
                pattern, search_path, file_pattern, case_sensitive, max_matches, context_lines
            )

            if result is None:
                result = self._python.search(
                    pattern, search_path, file_pattern, case_sensitive, max_matches, context_lines
                )

            if not result:
                return f"No matches found for pattern '{pattern}' in '{path}'"

            if isinstance(result, str):
                return result
            else:
                matches = result
                results = []
                for file_path, line_num, line_text in matches[:max_matches]:
                    display_line = line_text[:200] + "..." if len(line_text) > 200 else line_text
                    results.append(f"{file_path}:{line_num}: {display_line}")

                count_msg = (
                    f"\n\n(Showing {len(results)} of {len(matches)} matches)"
                    if len(matches) > max_matches
                    else ""
                )
                return "\n".join(results) + count_msg

        return [glob_files, grep_files]

    # Backward-compatible delegation methods for FilesystemTools proxy
    def _ripgrep_search(
        self,
        pattern: str,
        base_path: Path,
        file_pattern: str | None,
        case_sensitive: bool,
        max_matches: int,
        context_lines: int = 0,
    ) -> list[tuple[str, int, str]] | str | None:
        """Backward-compatible wrapper around RipgrepBackend.search()."""
        return self._ripgrep.search(
            pattern, base_path, file_pattern, case_sensitive, max_matches, context_lines
        )

    def _format_ripgrep_with_context(self, rg_output: str, max_matches: int) -> str:
        """Backward-compatible wrapper around RipgrepBackend._format_with_context()."""
        return self._ripgrep._format_with_context(rg_output, max_matches)

    def _python_search(
        self,
        pattern: str,
        base_path: Path,
        file_pattern: str | None,
        case_sensitive: bool,
        max_matches: int,
        context_lines: int = 0,
    ) -> list[tuple[str, int, str]] | str:
        """Backward-compatible wrapper around PythonBackend.search()."""
        return self._python.search(
            pattern, base_path, file_pattern, case_sensitive, max_matches, context_lines
        )

    def _python_search_with_context(
        self,
        regex: re.Pattern[str],
        base_path: Path,
        file_pattern: str | None,
        max_matches: int,
        context_lines: int,
    ) -> str:
        """Backward-compatible wrapper around PythonBackend._search_with_context()."""
        return self._python._search_with_context(regex, base_path, file_pattern, max_matches, context_lines)
