"""Python fallback search backend for file search tools.

Regex-based file search when ripgrep is unavailable.
"""

import re
from pathlib import Path

from openpaw.agent.tools.file_search.formatter import GrepContextFormatter


class PythonBackend:
    """Search files using Python regex as a fallback to ripgrep."""

    def __init__(self, root: Path, max_file_size_bytes: int):
        """Initialize Python backend with workspace root.

        Args:
            root: Root directory for resolving relative paths.
            max_file_size_bytes: Maximum file size for grep operations.
        """
        self.root = root
        self.max_file_size_bytes = max_file_size_bytes
        self._formatter = GrepContextFormatter()

    def search(
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
            List of tuples when context_lines=0 (backward compatible).
            Formatted string when context_lines>0.
        """
        try:
            flags = 0 if case_sensitive else re.IGNORECASE
            regex = re.compile(pattern, flags)
        except re.error as e:
            return [(f"Invalid regex pattern: {e}", 0, "")]

        if context_lines > 0:
            return self._search_with_context(regex, base_path, file_pattern, max_matches, context_lines)

        return self._search_without_context(regex, base_path, file_pattern, max_matches)

    def _search_without_context(
        self,
        regex: re.Pattern[str],
        base_path: Path,
        file_pattern: str | None,
        max_matches: int,
    ) -> list[tuple[str, int, str]]:
        """Python regex search without context lines."""
        matches = []
        search_root = base_path if base_path.is_dir() else base_path.parent

        for file_path in search_root.rglob("*"):
            try:
                if not file_path.is_file():
                    continue
            except (PermissionError, OSError):
                continue

            if file_pattern:
                if not Path(file_path.name).match(file_pattern):
                    continue

            try:
                if file_path.stat().st_size > self.max_file_size_bytes:
                    continue
            except OSError:
                continue

            try:
                content = file_path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, PermissionError, OSError):
                continue

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

    def _search_with_context(
        self,
        regex: re.Pattern[str],
        base_path: Path,
        file_pattern: str | None,
        max_matches: int,
        context_lines: int,
    ) -> str:
        """Python regex search with context lines."""
        match_groups = []
        match_count = 0
        search_root = base_path if base_path.is_dir() else base_path.parent

        for file_path in search_root.rglob("*"):
            try:
                if not file_path.is_file():
                    continue
            except (PermissionError, OSError):
                continue

            if file_pattern:
                if not Path(file_path.name).match(file_pattern):
                    continue

            try:
                if file_path.stat().st_size > self.max_file_size_bytes:
                    continue
            except OSError:
                continue

            try:
                content = file_path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, PermissionError, OSError):
                continue

            try:
                rel_path = str(file_path.relative_to(self.root))
            except ValueError:
                continue

            lines = content.splitlines()

            match_line_nums = []
            for line_num, line in enumerate(lines, 1):
                if regex.search(line):
                    match_line_nums.append(line_num)

            if not match_line_nums:
                continue

            for match_line_num in match_line_nums:
                if match_count >= max_matches:
                    break

                start_line = max(1, match_line_num - context_lines)
                end_line = min(len(lines), match_line_num + context_lines)

                group_lines = []
                for line_num in range(start_line, end_line + 1):
                    line_text = lines[line_num - 1]
                    display_line = self._formatter.truncate_line(line_text)

                    if line_num == match_line_num:
                        formatted = self._formatter.format_match_line(rel_path, line_num, display_line)
                    else:
                        formatted = self._formatter.format_context_line(rel_path, line_num, display_line)

                    group_lines.append(formatted)

                match_groups.append(group_lines)
                match_count += 1

            if match_count >= max_matches:
                break

        if not match_groups:
            return ""

        merged_groups = self._merge_groups(match_groups)
        return self._formatter.build_output(merged_groups, max_matches)

    def _merge_groups(self, groups: list[list[str]]) -> list[list[str]]:
        """Merge overlapping or adjacent context groups within the same file."""
        merged = []
        i = 0
        while i < len(groups):
            current_group = groups[i]
            i += 1

            while i < len(groups):
                next_group = groups[i]

                if not current_group or not next_group:
                    break

                current_last = current_group[-1]
                next_first = next_group[0]

                current_parts = current_last.split(":")
                next_parts = next_first.split(":")
                if len(current_parts) < 2 or len(next_parts) < 2:
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

                        if current_file == next_file and next_line <= current_line + 1:
                            current_group.extend(next_group)
                            i += 1
                            continue
                    except (ValueError, IndexError):
                        pass

                break

            merged.append(current_group)

        return merged
