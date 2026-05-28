"""File write tools for agent workspace access.

Provides LangChain tools for write file operations restricted to a workspace directory.
All paths are validated to prevent directory traversal and write-protected areas are blocked.
"""

import os
from pathlib import Path, PurePosixPath

from langchain_core.tools import BaseTool, tool

from openpaw.agent.tools.sandbox import resolve_sandboxed_path
from openpaw.core.paths import TOP_LEVEL_DIRS, WORKSPACE_DIR


class FileWriteTools:
    """Write filesystem tools for agent workspace access."""

    def __init__(self, root: Path, workspace_name: str):
        """Initialize write tools with workspace root.

        Args:
            root: Root directory for all file operations.
            workspace_name: Human-readable workspace name for output enrichment.
        """
        self.root = root
        self._workspace_name = workspace_name

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

    def get_tools(self) -> list[BaseTool]:
        """Return list of LangChain write tools with workspace root captured in closure."""

        @tool
        def write_file(file_path: str, content: str) -> str:
            """Write content to a new file.

            Creates parent directories if needed. Fails if file already exists.
            Bare filenames (e.g. 'report.md') are written to the workspace/
            subdirectory by default.

            Args:
                file_path: File path relative to workspace root
                content: Text content to write

            Returns:
                Success message or error
            """
            try:
                resolved_path = self._resolve_write_path(file_path)
            except ValueError as e:
                error_msg = f"Error: {e}"
                if self._workspace_name:
                    error_msg += (
                        f"\nHint: Use paths relative to your '{self._workspace_name}' workspace "
                        f"(e.g., 'notes.md', 'research/report.txt')"
                    )
                return error_msg

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
                success_msg = f"Successfully wrote {lines} lines to '{file_path}'"
                if self._workspace_name:
                    success_msg += f" (workspace: {self._workspace_name})"
                return success_msg

            except OSError as e:
                return f"Error writing file '{file_path}': {e}"

        @tool
        def overwrite_file(file_path: str, content: str) -> str:
            """Write content to a file, creating or overwriting as needed.

            Creates parent directories if needed. Overwrites existing file content.
            Use this when you want to replace the entire contents of a file,
            such as updating agent/HEARTBEAT.md or other state files.
            Bare filenames (e.g. 'notes.md') are written to the workspace/
            subdirectory by default.

            Args:
                file_path: File path relative to workspace root
                content: Text content to write

            Returns:
                Success message or error
            """
            try:
                resolved_path = self._resolve_write_path(file_path)
            except ValueError as e:
                error_msg = f"Error: {e}"
                if self._workspace_name:
                    error_msg += (
                        f"\nHint: Use paths relative to your '{self._workspace_name}' workspace "
                        f"(e.g., 'notes.md', 'research/report.txt')"
                    )
                return error_msg

            try:
                resolved_path.parent.mkdir(parents=True, exist_ok=True)

                flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
                if hasattr(os, "O_NOFOLLOW"):
                    flags |= os.O_NOFOLLOW
                fd = os.open(resolved_path, flags, 0o644)
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(content)

                lines = len(content.splitlines())
                success_msg = f"Successfully wrote {lines} lines to '{file_path}'"
                if self._workspace_name:
                    success_msg += f" (workspace: {self._workspace_name})"
                return success_msg

            except OSError as e:
                return f"Error writing file '{file_path}': {e}"

        @tool
        def edit_file(file_path: str, old_text: str, new_text: str, replace_all: bool = False) -> str:
            """Edit existing file by replacing text.

            Bare filenames (e.g. 'notes.md') are resolved under the workspace/
            subdirectory by default.

            Args:
                file_path: File path relative to workspace root
                old_text: Text to search for and replace (must be exact match)
                new_text: Replacement text
                replace_all: If True, replace all occurrences. If False, only replace if exactly one match exists.

            Returns:
                Success message with occurrence count, or error
            """
            try:
                resolved_path = self._resolve_write_path(file_path)
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

        return [write_file, overwrite_file, edit_file]
