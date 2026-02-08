"""Tests for grep_files context_lines parameter."""

import tempfile
from pathlib import Path

import pytest

from openpaw.tools.filesystem import FilesystemTools


@pytest.fixture
def temp_workspace():
    """Create a temporary workspace with test files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)

        # Create test file with numbered lines
        test_file = workspace / "test.py"
        test_file.write_text(
            """line 1
line 2
line 3 match
line 4
line 5
line 6 match
line 7
line 8
line 9
line 10 match
line 11
line 12
"""
        )

        # Create another file
        another_file = workspace / "another.py"
        another_file.write_text(
            """first line
second line
third line with match
fourth line
"""
        )

        yield workspace


def test_grep_context_lines_zero_backward_compatible(temp_workspace):
    """Test that context_lines=0 behaves identically to current implementation."""
    fs_tools = FilesystemTools(temp_workspace)
    tools = fs_tools.get_tools()
    grep_tool = tools[6]  # grep_files is 7th tool

    # Search without context
    result = grep_tool.invoke({"pattern": "match", "context_lines": 0})

    # Should get standard format (no context)
    assert "test.py:3: line 3 match" in result
    assert "test.py:6: line 6 match" in result
    assert "test.py:10: line 10 match" in result
    assert "another.py:3: third line with match" in result

    # Should NOT have context markers
    assert "-" not in result.split(":")[0]  # No hyphen separator in file path
    assert "--" not in result  # No group separator


def test_grep_context_lines_default_is_zero(temp_workspace):
    """Test that omitting context_lines parameter defaults to 0."""
    fs_tools = FilesystemTools(temp_workspace)
    tools = fs_tools.get_tools()
    grep_tool = tools[6]

    # Search without specifying context_lines
    result = grep_tool.invoke({"pattern": "match"})

    # Should behave same as context_lines=0
    assert "test.py:3: line 3 match" in result
    assert "--" not in result


def test_grep_context_lines_basic(temp_workspace):
    """Test basic context_lines functionality."""
    fs_tools = FilesystemTools(temp_workspace)
    tools = fs_tools.get_tools()
    grep_tool = tools[6]

    # Search with 1 line of context
    result = grep_tool.invoke({"pattern": "line 3 match", "context_lines": 1})

    # Should include match line with colon
    assert "test.py:3: line 3 match" in result

    # Should include context lines with hyphen
    assert "test.py-2- line 2" in result
    assert "test.py-4- line 4" in result


def test_grep_context_lines_multiple_lines(temp_workspace):
    """Test with multiple context lines."""
    fs_tools = FilesystemTools(temp_workspace)
    tools = fs_tools.get_tools()
    grep_tool = tools[6]

    # Search with 2 lines of context
    result = grep_tool.invoke({"pattern": "line 6 match", "context_lines": 2})

    # Should include 2 lines before
    assert "test.py-4- line 4" in result
    assert "test.py-5- line 5" in result

    # Match line
    assert "test.py:6: line 6 match" in result

    # Should include 2 lines after
    assert "test.py-7- line 7" in result
    assert "test.py-8- line 8" in result


def test_grep_context_lines_at_file_boundaries(temp_workspace):
    """Test that context doesn't go beyond file boundaries."""
    fs_tools = FilesystemTools(temp_workspace)
    tools = fs_tools.get_tools()
    grep_tool = tools[6]

    # Match on line 1 of another.py with context=2
    result = grep_tool.invoke({"pattern": "first", "context_lines": 2})

    # Should have match
    assert "another.py:1: first line" in result

    # Should have context after but not before (file starts at line 1)
    assert "another.py-2- second line" in result
    assert "another.py-0-" not in result  # No line 0


def test_grep_context_with_group_separator(temp_workspace):
    """Test that non-contiguous match groups are separated by --."""
    fs_tools = FilesystemTools(temp_workspace)
    tools = fs_tools.get_tools()
    grep_tool = tools[6]

    # Search for pattern with multiple non-contiguous matches
    result = grep_tool.invoke({"pattern": "match", "context_lines": 1})

    # Should have -- separators between groups
    lines = result.split("\n")
    separator_count = lines.count("--")

    # We have matches on lines 3, 6, 10 in test.py and line 3 in another.py
    # With context=1:
    # - Match at line 3: lines 2-4
    # - Match at line 6: lines 5-7 (overlaps with previous? No, line 5 vs line 4)
    # - Match at line 10: lines 9-11
    # - Match in another.py: separate file
    # So we should have separators between non-contiguous groups
    assert separator_count >= 1


def test_grep_context_overlapping_windows_merged(temp_workspace):
    """Test that overlapping context windows are merged (no duplicate lines)."""
    # Create a file with close matches
    workspace = temp_workspace
    close_match_file = workspace / "close.py"
    close_match_file.write_text(
        """line 1
match 2
match 3
line 4
"""
    )

    fs_tools = FilesystemTools(workspace)
    tools = fs_tools.get_tools()
    grep_tool = tools[6]

    # Search with context that would overlap
    result = grep_tool.invoke({"pattern": "match", "path": "close.py", "context_lines": 1})

    lines = result.split("\n")

    # Count occurrences of each line
    line_counts = {}
    for line in lines:
        if line and line != "--":
            line_counts[line] = line_counts.get(line, 0) + 1

    # Each line should appear at most once (merged, not duplicated)
    for line, count in line_counts.items():
        assert count == 1, f"Line appears {count} times: {line}"


def test_grep_context_respects_max_matches(temp_workspace):
    """Test that context output respects max_matches limit."""
    fs_tools = FilesystemTools(temp_workspace)
    tools = fs_tools.get_tools()
    grep_tool = tools[6]

    # Search with low max_matches
    result = grep_tool.invoke({"pattern": "match", "context_lines": 1, "max_matches": 2})

    # Count actual matches (lines with : separator)
    match_lines = [line for line in result.split("\n") if ":" in line and " match" in line]

    # Should have at most 2 matches
    assert len(match_lines) <= 2


def test_grep_context_truncates_long_lines(temp_workspace):
    """Test that context lines are truncated like match lines."""
    # Create file with very long line
    workspace = temp_workspace
    long_file = workspace / "long.py"
    long_line = "x" * 300
    long_file.write_text(
        f"""short line
match line
{long_line}
"""
    )

    fs_tools = FilesystemTools(workspace)
    tools = fs_tools.get_tools()
    grep_tool = tools[6]

    result = grep_tool.invoke({"pattern": "match", "path": "long.py", "context_lines": 1})

    # Long context line should be truncated with ...
    assert "..." in result
    # Should not contain full long line
    assert long_line not in result


def test_grep_context_case_insensitive(temp_workspace):
    """Test that case_sensitive works with context_lines."""
    fs_tools = FilesystemTools(temp_workspace)
    tools = fs_tools.get_tools()
    grep_tool = tools[6]

    # Create file with mixed case
    mixed_case = temp_workspace / "mixed.py"
    mixed_case.write_text(
        """line 1
MATCH upper
line 3
"""
    )

    # Case-insensitive search with context
    result = grep_tool.invoke({
        "pattern": "match",
        "path": "mixed.py",
        "case_sensitive": False,
        "context_lines": 1,
    })

    assert "mixed.py:2: MATCH upper" in result
    assert "mixed.py-1- line 1" in result
    assert "mixed.py-3- line 3" in result


def test_grep_context_with_file_pattern(temp_workspace):
    """Test that file_pattern filtering works with context."""
    fs_tools = FilesystemTools(temp_workspace)
    tools = fs_tools.get_tools()
    grep_tool = tools[6]

    # Search only .py files
    result = grep_tool.invoke({
        "pattern": "match",
        "file_pattern": "*.py",
        "context_lines": 1,
    })

    # Should find matches in .py files
    assert "test.py" in result
    assert "another.py" in result


def test_grep_context_no_matches_returns_message(temp_workspace):
    """Test that no matches returns appropriate message."""
    fs_tools = FilesystemTools(temp_workspace)
    tools = fs_tools.get_tools()
    grep_tool = tools[6]

    result = grep_tool.invoke({"pattern": "nonexistent", "context_lines": 2})

    assert "No matches found" in result


def test_grep_context_empty_result_edge_case(temp_workspace):
    """Test edge case where context processing returns empty string."""
    fs_tools = FilesystemTools(temp_workspace)
    tools = fs_tools.get_tools()
    grep_tool = tools[6]

    # Create empty file
    empty_file = temp_workspace / "empty.py"
    empty_file.write_text("")

    result = grep_tool.invoke({"pattern": "anything", "path": "empty.py", "context_lines": 1})

    assert "No matches found" in result


def test_grep_python_fallback_with_context(temp_workspace):
    """Test that Python fallback works with context when ripgrep unavailable."""
    # This test verifies the Python fallback path works correctly
    fs_tools = FilesystemTools(temp_workspace)

    # Use _python_search (not _python_search_with_context) which is the public API
    import re
    regex = re.compile("match")
    result = fs_tools._python_search(
        pattern="match",
        base_path=temp_workspace,
        file_pattern="*.py",
        case_sensitive=True,
        max_matches=10,
        context_lines=1,
    )

    # Should produce formatted output when context_lines > 0
    assert isinstance(result, str)
    if result:  # If matches found
        assert "test.py:3: line 3 match" in result
        # Should have context lines
        assert ("-2-" in result or "-4-" in result)
