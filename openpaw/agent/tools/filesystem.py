"""Sandboxed filesystem tools for agent workspace access.

Provides LangChain tools for file operations restricted to a workspace directory.
All paths are validated to prevent directory traversal and stay within the sandbox.

This module is a facade that composes FileReadTools, FileWriteTools, and FileSearchTools.
"""

import re
from pathlib import Path, PurePosixPath

from langchain_core.tools import BaseTool

from openpaw.agent.tools.file_read import FileReadTools
from openpaw.agent.tools.file_search import FileSearchTools
from openpaw.agent.tools.file_write import FileWriteTools
from openpaw.agent.tools.sandbox import resolve_sandboxed_path
from openpaw.core.paths import TOP_LEVEL_DIRS, WORKSPACE_DIR


class FilesystemTools:
    """Sandboxed filesystem tools for agent workspace access.

    All operations are restricted to the workspace root directory with security checks
    to prevent path traversal attacks and access outside the sandbox.
    """

    def __init__(
        self,
        workspace_root: Path,
        max_file_size_mb: int = 10,
        timezone: str = "UTC",
        workspace_name: str = "",
    ):
        """Initialize filesystem tools with workspace sandbox.

        Args:
            workspace_root: Root directory for all file operations
            max_file_size_mb: Maximum file size in MB for operations like grep
            timezone: IANA timezone identifier for timestamp display (default: UTC)
            workspace_name: Human-readable workspace name for output enrichment.
                When set, ls output, write success messages, and error hints include
                the workspace name to help agents maintain spatial orientation.
                Empty string (default) disables enrichment for backward compatibility.
        """
        self.root = workspace_root.resolve()
        self.max_file_size_bytes = max_file_size_mb * 1024 * 1024
        self._max_read_output_chars: int = 100_000
        self._timezone = timezone
        self._workspace_name = workspace_name
        self._search = FileSearchTools(self.root, self.max_file_size_bytes, self._workspace_name)

    def _resolve_path(self, path: str) -> Path:
        """Resolve a path relative to workspace root with security checks."""
        return resolve_sandboxed_path(self.root, path)

    def _resolve_write_path(self, path: str) -> Path:
        """Resolve a path for write operations with protection enforcement.

        Behaviour:
        - Bare filenames and paths whose first component is not a known
          top-level directory (``agent/``, ``config/``, ``data/``,
          ``memory/``, ``workspace/``) are transparently prefixed with
          ``workspace/`` so that the agent's default write area is the
          ``workspace/`` subdirectory.
        - Paths that explicitly target a known top-level directory are
          resolved as-is, then passed through write-mode sandbox validation
          (which blocks writes to ``data/``, ``config/``, ``memory/logs``,
          ``memory/conversations`` — except ``agent/HEARTBEAT.md``).

        Args:
            path: Workspace-relative path string supplied by the agent.

        Returns:
            Resolved absolute Path within the workspace.

        Raises:
            ValueError: If the path violates sandbox or write-protection rules.
        """
        # Determine the first path component so we can detect explicit top-level dir.
        first_part = PurePosixPath(path).parts[0] if PurePosixPath(path).parts else ""

        if first_part not in TOP_LEVEL_DIRS and first_part not in {".", ""}:
            # Bare filename or relative path — redirect to workspace/ transparently.
            effective_path = str(WORKSPACE_DIR / path)
        else:
            effective_path = path

        return resolve_sandboxed_path(self.root, effective_path, write_mode=True)

    def _ripgrep_search(
        self,
        pattern: str,
        base_path: Path,
        file_pattern: str | None,
        case_sensitive: bool,
        max_matches: int,
        context_lines: int = 0,
    ) -> list[tuple[str, int, str]] | str | None:
        return self._search._ripgrep_search(
            pattern, base_path, file_pattern, case_sensitive, max_matches, context_lines
        )

    def _format_ripgrep_with_context(self, rg_output: str, max_matches: int) -> str:
        return self._search._format_ripgrep_with_context(rg_output, max_matches)

    def _python_search(
        self,
        pattern: str,
        base_path: Path,
        file_pattern: str | None,
        case_sensitive: bool,
        max_matches: int,
        context_lines: int = 0,
    ) -> list[tuple[str, int, str]] | str:
        return self._search._python_search(
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
        return self._search._python_search_with_context(
            regex, base_path, file_pattern, max_matches, context_lines
        )

    def get_tools(self) -> list[BaseTool]:
        """Return list of LangChain tools with workspace root captured in closure."""
        read = FileReadTools(self.root, self._timezone, self._workspace_name, self._max_read_output_chars)
        write = FileWriteTools(self.root, self._workspace_name)
        search = FileSearchTools(self.root, self.max_file_size_bytes, self._workspace_name)

        read_tools = read.get_tools()
        write_tools = write.get_tools()
        search_tools = search.get_tools()

        tools = [
            read_tools[0],   # ls
            read_tools[1],   # read_file
            write_tools[0],  # write_file
            write_tools[1],  # overwrite_file
            write_tools[2],  # edit_file
            search_tools[0], # glob_files
            search_tools[1], # grep_files
            read_tools[2],   # file_info
        ]

        # Prefix all tool descriptions with workspace name to reinforce spatial orientation
        if self._workspace_name:
            for tool_instance in tools:
                tool_instance.description = (
                    f"[{self._workspace_name} workspace] {tool_instance.description}"
                )

        return tools
