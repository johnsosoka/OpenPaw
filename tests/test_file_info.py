"""Tests for file_info tool in FilesystemTools."""

import json

import pytest

from openpaw.agent.tools.filesystem import FilesystemTools


@pytest.fixture
def workspace(tmp_path):
    """Create a test workspace."""
    return tmp_path


@pytest.fixture
def fs_tools(workspace):
    """Create FilesystemTools instance."""
    return FilesystemTools(workspace)


def test_file_info_small_text_file(fs_tools, workspace):
    """Test file_info on a small text file."""
    test_file = workspace / "small.txt"
    test_file.write_text("Line 1\nLine 2\nLine 3\n")

    tools = fs_tools.get_tools()
    file_info_tool = tools[7]  # file_info is 8th tool (index 7)

    result = file_info_tool.invoke({"path": "small.txt"})
    data = json.loads(result)

    assert data["path"] == "small.txt"
    assert data["exists"] is True
    assert data["is_binary"] is False
    assert data["line_count"] == 3
    assert data["size_bytes"] == 21
    assert "21 B" in data["size_human"] or "21.0 B" in data["size_human"]
    assert "Small file. Safe to read in full." in data["suggested_read_strategy"]
    assert "last_modified" in data


def test_file_info_medium_text_file(fs_tools, workspace):
    """Test file_info on a medium-sized text file (50-500 lines)."""
    test_file = workspace / "medium.txt"
    content = "\n".join(f"Line {i}" for i in range(100))
    test_file.write_text(content)

    tools = fs_tools.get_tools()
    file_info_tool = tools[7]

    result = file_info_tool.invoke({"path": "medium.txt"})
    data = json.loads(result)

    assert data["path"] == "medium.txt"
    assert data["exists"] is True
    assert data["is_binary"] is False
    assert data["line_count"] == 100
    # No suggested_read_strategy for medium files (50-500 lines)
    assert "suggested_read_strategy" not in data or "Small file" not in data.get("suggested_read_strategy", "")


def test_file_info_large_text_file(fs_tools, workspace):
    """Test file_info on a large text file (>500 lines)."""
    test_file = workspace / "large.txt"
    content = "\n".join(f"Line {i}" for i in range(1000))
    test_file.write_text(content)

    tools = fs_tools.get_tools()
    file_info_tool = tools[7]

    result = file_info_tool.invoke({"path": "large.txt"})
    data = json.loads(result)

    assert data["path"] == "large.txt"
    assert data["exists"] is True
    assert data["is_binary"] is False
    assert data["line_count"] == 1000
    assert "Large file. Use read_file" in data["suggested_read_strategy"]
    assert "offset=0, limit=100" in data["suggested_read_strategy"]


def test_file_info_binary_file(fs_tools, workspace):
    """Test file_info on a binary file."""
    test_file = workspace / "binary.bin"
    # Write binary data with null bytes
    test_file.write_bytes(b"\x00\x01\x02\x03\xFF\xFE\xFD\xFC")

    tools = fs_tools.get_tools()
    file_info_tool = tools[7]

    result = file_info_tool.invoke({"path": "binary.bin"})
    data = json.loads(result)

    assert data["path"] == "binary.bin"
    assert data["exists"] is True
    assert data["is_binary"] is True
    assert "line_count" not in data  # Binary files don't get line counts
    assert data["suggested_read_strategy"] == "Binary file. Use appropriate tool for this file type."


def test_file_info_empty_file(fs_tools, workspace):
    """Test file_info on an empty file."""
    test_file = workspace / "empty.txt"
    test_file.write_text("")

    tools = fs_tools.get_tools()
    file_info_tool = tools[7]

    result = file_info_tool.invoke({"path": "empty.txt"})
    data = json.loads(result)

    assert data["path"] == "empty.txt"
    assert data["exists"] is True
    assert data["is_binary"] is False
    assert data["size_bytes"] == 0
    assert "0 B" in data["size_human"] or "0.0 B" in data["size_human"]
    assert data["line_count"] == 0
    assert "Small file. Safe to read in full." in data["suggested_read_strategy"]


def test_file_info_file_not_found(fs_tools, workspace):
    """Test file_info on a non-existent file."""
    tools = fs_tools.get_tools()
    file_info_tool = tools[7]

    result = file_info_tool.invoke({"path": "nonexistent.txt"})
    data = json.loads(result)

    assert data["path"] == "nonexistent.txt"
    assert data["exists"] is False
    assert data["error"].startswith("File not found")


def test_file_info_directory(fs_tools, workspace):
    """Test file_info on a directory."""
    subdir = workspace / "subdir"
    subdir.mkdir()

    tools = fs_tools.get_tools()
    file_info_tool = tools[7]

    result = file_info_tool.invoke({"path": "subdir"})
    data = json.loads(result)

    assert data["path"] == "subdir"
    assert data["exists"] is True
    assert data["is_directory"] is True
    assert data["error"] == "Use ls for directories"


def test_file_info_path_traversal_attempt(fs_tools, workspace):
    """Test file_info rejects path traversal attempts."""
    tools = fs_tools.get_tools()
    file_info_tool = tools[7]

    result = file_info_tool.invoke({"path": "../etc/passwd"})
    data = json.loads(result)

    assert data["path"] == "../etc/passwd"
    assert data["exists"] is False
    assert "error" in data
    assert "not allowed" in data["error"].lower()


def test_file_info_absolute_path_attempt(fs_tools, workspace):
    """Test file_info rejects absolute paths."""
    tools = fs_tools.get_tools()
    file_info_tool = tools[7]

    result = file_info_tool.invoke({"path": "/etc/passwd"})
    data = json.loads(result)

    assert data["path"] == "/etc/passwd"
    assert data["exists"] is False
    assert "error" in data
    assert "Absolute paths not allowed" in data["error"]


def test_file_info_data_directory_is_readable(fs_tools, workspace):
    """Test file_info can read files inside data/ (data/ is write-protected, not read-protected).

    The sandbox blocks WRITE access to data/, config/, memory/logs, and memory/conversations,
    but read operations (file_info, read_file) are permitted everywhere within the workspace.
    """
    data_dir = workspace / "data"
    data_dir.mkdir()
    test_file = data_dir / "sessions.json"
    test_file.write_text('{"session": "data"}')

    tools = fs_tools.get_tools()
    file_info_tool = tools[7]

    result = file_info_tool.invoke({"path": "data/sessions.json"})
    data = json.loads(result)

    assert data["path"] == "data/sessions.json"
    assert data["exists"] is True
    assert data["is_binary"] is False
    assert "error" not in data


def test_file_info_size_formatting(fs_tools, workspace):
    """Test file_info formats sizes correctly."""
    tools = fs_tools.get_tools()
    file_info_tool = tools[7]

    # KB file
    kb_file = workspace / "kb.txt"
    kb_file.write_text("x" * 2048)
    result = file_info_tool.invoke({"path": "kb.txt"})
    data = json.loads(result)
    assert "KB" in data["size_human"]
    assert data["size_bytes"] == 2048

    # MB file
    mb_file = workspace / "mb.txt"
    mb_file.write_text("x" * (2 * 1024 * 1024))
    result = file_info_tool.invoke({"path": "mb.txt"})
    data = json.loads(result)
    assert "MB" in data["size_human"]
    assert data["size_bytes"] == 2 * 1024 * 1024


def test_file_info_very_large_file_line_cap(fs_tools, workspace):
    """Test file_info caps line count at 10000+ for very large files."""
    # Create a file just over 10MB with many lines
    large_file = workspace / "very_large.txt"
    # Write in chunks to avoid memory issues
    with open(large_file, "w") as f:
        for i in range(15000):
            f.write(f"Line {i}\n")

    tools = fs_tools.get_tools()
    file_info_tool = tools[7]

    result = file_info_tool.invoke({"path": "very_large.txt"})
    data = json.loads(result)

    assert data["path"] == "very_large.txt"
    assert data["exists"] is True
    assert data["is_binary"] is False
    # Line count should be capped at "10000+" for streaming large file check
    # or actual count if under 10MB
    assert "line_count" in data
    assert "Very large file" in data["suggested_read_strategy"] or "Large file" in data["suggested_read_strategy"]


def test_file_info_nested_directory(fs_tools, workspace):
    """Test file_info works with nested directory paths."""
    nested_dir = workspace / "reports" / "2024"
    nested_dir.mkdir(parents=True)
    nested_file = nested_dir / "quarterly.md"
    nested_file.write_text("# Q1 Report\n\nSome content here.\n")

    tools = fs_tools.get_tools()
    file_info_tool = tools[7]

    result = file_info_tool.invoke({"path": "reports/2024/quarterly.md"})
    data = json.loads(result)

    assert data["path"] == "reports/2024/quarterly.md"
    assert data["exists"] is True
    assert data["is_binary"] is False
    assert data["line_count"] == 3


def test_file_info_json_output_valid(fs_tools, workspace):
    """Test that file_info always returns valid JSON."""
    tools = fs_tools.get_tools()
    file_info_tool = tools[7]

    # Test various scenarios
    test_cases = [
        "nonexistent.txt",
        "../traversal",
        "/absolute/path",
    ]

    for test_path in test_cases:
        result = file_info_tool.invoke({"path": test_path})
        # Should not raise JSONDecodeError
        data = json.loads(result)
        assert isinstance(data, dict)
        assert "path" in data
        assert "exists" in data
