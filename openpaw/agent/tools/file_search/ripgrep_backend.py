"""Ripgrep search backend for file search tools.

Executes ripgrep subprocess and parses JSON output.
"""

import json
import subprocess
from pathlib import Path

from openpaw.agent.tools.file_search.formatter import GrepContextFormatter


class RipgrepBackend:
    """Search files using ripgrep (rg) command-line tool."""

    def __init__(self, root: Path):
        """Initialize ripgrep backend with workspace root.

        Args:
            root: Root directory for resolving relative paths.
        """
        self.root = root
        self._formatter = GrepContextFormatter()

    def search(
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
            None if ripgrep unavailable.
            List of tuples when context_lines=0 (backward compatible).
            Formatted string when context_lines>0.
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

        if context_lines > 0:
            return self._format_with_context(proc.stdout, max_matches)

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

            try:
                rel_path = Path(file_path).resolve().relative_to(self.root)
            except ValueError:
                continue

            line_num = match_data.get("line_number")
            line_text = match_data.get("lines", {}).get("text", "").rstrip("\n")

            if line_num is None:
                continue

            matches.append((str(rel_path), int(line_num), line_text))

            if len(matches) >= max_matches * 2:
                break

        return matches

    def _format_with_context(self, rg_output: str, max_matches: int) -> str:
        """Format ripgrep JSON output with context lines.

        Args:
            rg_output: JSON output from ripgrep -C command.
            max_matches: Maximum number of match groups to include.

        Returns:
            Formatted string with matches and context.
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

            try:
                rel_path = str(Path(file_path_obj).resolve().relative_to(self.root))
            except ValueError:
                continue

            line_num = record_data.get("line_number")
            line_text = record_data.get("lines", {}).get("text", "").rstrip("\n")

            if line_num is None:
                continue

            display_line = self._formatter.truncate_line(line_text)

            if last_file_path is not None and last_line_num is not None:
                if rel_path != last_file_path or line_num > last_line_num + 1:
                    if current_group:
                        match_groups.append(current_group)
                        current_group = []

            if record_type == "match":
                formatted = self._formatter.format_match_line(rel_path, line_num, display_line)
                match_count += 1
            else:
                formatted = self._formatter.format_context_line(rel_path, line_num, display_line)

            current_group.append(formatted)
            last_line_num = line_num
            last_file_path = rel_path

            if match_count >= max_matches:
                break

        if current_group:
            match_groups.append(current_group)

        return self._formatter.build_output(match_groups, max_matches)
