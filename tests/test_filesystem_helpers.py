"""Tests for filesystem helper utilities."""

from openpaw.agent.tools.helpers.formatting import format_content_with_line_numbers, format_file_listing


def test_format_file_listing_file() -> None:
    """Format a regular file entry."""
    info = {
        "path": "notes.md",
        "size": 1234,
        "modified_at": "2026-05-27 14:30:00",
        "is_dir": False,
    }
    result = format_file_listing(info)
    # type_marker is padded to 20 chars regardless of content
    assert result == "notes.md                          1.2KB  2026-05-27 14:30:00"


def test_format_file_listing_directory() -> None:
    """Format a directory entry."""
    info = {
        "path": "workspace",
        "size": 0,
        "modified_at": "2026-05-27 10:00:00",
        "is_dir": True,
    }
    result = format_file_listing(info)
    assert result == "workspace/                            0B  2026-05-27 10:00:00"


def test_format_file_listing_bytes() -> None:
    """Format a small file in bytes."""
    info = {"path": "tiny.txt", "size": 512, "modified_at": "unknown", "is_dir": False}
    result = format_file_listing(info)
    assert result == "tiny.txt                           512B  unknown"


def test_format_file_listing_megabytes() -> None:
    """Format a large file in megabytes."""
    info = {
        "path": "large.zip",
        "size": 5 * 1024 * 1024,
        "modified_at": "2026-05-27 14:30:00",
        "is_dir": False,
    }
    result = format_file_listing(info)
    assert result == "large.zip                          5.0MB  2026-05-27 14:30:00"


def test_format_file_listing_defaults() -> None:
    """Format with minimal info uses defaults."""
    info = {"path": "bare"}
    result = format_file_listing(info)
    assert result == "bare                             0B  unknown"


def test_format_content_with_line_numbers() -> None:
    """Format content with line numbers starting at 1."""
    lines = ["first", "second", "third"]
    result = format_content_with_line_numbers(lines)
    expected = "1→first\n2→second\n3→third"
    assert result == expected


def test_format_content_with_offset() -> None:
    """Format content with a starting line offset."""
    lines = ["alpha", "beta"]
    result = format_content_with_line_numbers(lines, start_line=10)
    expected = "10→alpha\n11→beta"
    assert result == expected


def test_format_content_truncates_long_lines() -> None:
    """Very long lines are truncated to prevent output bloat."""
    long_line = "x" * 2500
    lines = [long_line]
    result = format_content_with_line_numbers(lines)
    assert result.startswith("1→" + "x" * 2000 + "...")
    assert len(result) < 3000


def test_format_content_width_padding() -> None:
    """Line numbers are right-aligned to the width of the largest number."""
    lines = ["line"] * 12
    result = format_content_with_line_numbers(lines, start_line=1)
    first_line = result.split("\n")[0]
    # Width should be 2 for numbers up to 12
    assert first_line == " 1→line"
    last_line = result.split("\n")[-1]
    assert last_line == "12→line"


def test_format_content_single_digit() -> None:
    """Single-digit line numbers have no extra padding."""
    lines = ["a"]
    result = format_content_with_line_numbers(lines)
    assert result == "1→a"


def test_format_file_listing_missing_path_returns_empty() -> None:
    """Missing 'path' key returns empty string and logs a warning."""
    info = {"size": 1234, "modified_at": "2026-05-27 14:30:00"}
    result = format_file_listing(info)
    assert result == ""


def test_format_file_listing_non_dict_returns_empty() -> None:
    """Non-dict input returns empty string and logs a warning."""
    result = format_file_listing("not a dict")  # type: ignore[arg-type]
    assert result == ""


def test_format_file_listing_invalid_size_type_falls_back() -> None:
    """Invalid size type falls back to 0 and logs a warning."""
    info = {
        "path": "bad_size.txt",
        "size": "huge",
        "modified_at": "2026-05-27 14:30:00",
        "is_dir": False,
    }
    result = format_file_listing(info)
    assert "bad_size.txt" in result
    assert "0B" in result


def test_format_file_listing_invalid_modified_at_converts() -> None:
    """Invalid modified_at type is converted to string."""
    info = {
        "path": "bad_date.txt",
        "size": 100,
        "modified_at": 1234567890,
        "is_dir": False,
    }
    result = format_file_listing(info)
    assert "bad_date.txt" in result
    assert "1234567890" in result


def test_format_file_listing_invalid_is_dir_converts() -> None:
    """Invalid is_dir type is converted to bool."""
    info = {
        "path": "maybe_dir",
        "size": 0,
        "modified_at": "unknown",
        "is_dir": "yes",
    }
    result = format_file_listing(info)
    # "yes" is truthy, so is_dir becomes True → trailing slash
    assert "maybe_dir/" in result
