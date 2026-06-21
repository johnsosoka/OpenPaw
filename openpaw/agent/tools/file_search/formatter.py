"""Shared formatting utilities for grep search results with context lines."""


class GrepContextFormatter:
    """Format search results with context lines for display.

    Shared helper used by both ripgrep and Python fallback backends.
    """

    @staticmethod
    def truncate_line(text: str, max_length: int = 200) -> str:
        """Truncate a line to max_length, appending '...' if truncated."""
        if len(text) > max_length:
            return text[:max_length] + "..."
        return text

    @staticmethod
    def format_match_line(rel_path: str, line_num: int, text: str) -> str:
        """Format a match line as 'file:line: text'."""
        return f"{rel_path}:{line_num}: {text}"

    @staticmethod
    def format_context_line(rel_path: str, line_num: int, text: str) -> str:
        """Format a context line as 'file-line- text'."""
        return f"{rel_path}-{line_num}- {text}"

    @staticmethod
    def build_output(groups: list[list[str]], max_matches: int) -> str:
        """Build final output string from grouped formatted lines.

        Args:
            groups: List of line groups, each group is a list of formatted strings.
            max_matches: Maximum number of match groups to include.

        Returns:
            Formatted string with '--' separators between non-contiguous groups.
        """
        output_parts = []
        match_count = 0
        for i, group in enumerate(groups[:max_matches]):
            if i > 0:
                output_parts.append("--")
            output_parts.extend(group)
            match_count += 1

        if not output_parts:
            return ""

        result = "\n".join(output_parts)
        if match_count > max_matches:
            result += f"\n\n(Showing first {max_matches} matches)"

        return result
