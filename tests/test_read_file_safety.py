"""Tests for read_file character safety valve."""

import pytest

from openpaw.agent.tools.filesystem import FilesystemTools


@pytest.fixture
def workspace(tmp_path):
    """Create a workspace with test files."""
    return tmp_path


def test_normal_read_unaffected(workspace):
    """Normal files under the limit are returned unchanged."""
    test_file = workspace / "small.txt"
    test_file.write_text("Hello world\n" * 10)
    fs = FilesystemTools(workspace_root=workspace)
    tools = {t.name: t for t in fs.get_tools()}
    result = tools["read_file"].invoke({"file_path": "small.txt"})
    assert "truncated" not in result


def test_large_read_truncated(workspace):
    """Files exceeding the character limit are truncated."""
    test_file = workspace / "large.txt"
    # Create a file that will exceed 100K chars when formatted
    content = ("x" * 200 + "\n") * 1000
    test_file.write_text(content)
    fs = FilesystemTools(workspace_root=workspace)
    tools = {t.name: t for t in fs.get_tools()}
    result = tools["read_file"].invoke({"file_path": "large.txt"})
    assert "truncated" in result
    assert "offset/limit" in result
    assert len(result) <= 100_000 + 200  # Allow for truncation message


def test_custom_limit(workspace):
    """Custom character limit is respected."""
    test_file = workspace / "medium.txt"
    test_file.write_text("hello world\n" * 100)
    fs = FilesystemTools(workspace_root=workspace)
    fs._max_read_output_chars = 500
    tools = {t.name: t for t in fs.get_tools()}
    result = tools["read_file"].invoke({"file_path": "medium.txt"})
    assert "truncated" in result
