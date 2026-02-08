"""Tests for filesystem tools with security validation."""

from pathlib import Path

import pytest

from openpaw.tools.filesystem import FilesystemTools


def test_openpaw_directory_rejected(tmp_path: Path):
    """Verify .openpaw/ directory access is blocked."""
    fs = FilesystemTools(tmp_path)

    # Direct access
    with pytest.raises(ValueError, match=r"\.openpaw"):
        fs._resolve_path(".openpaw/conversations.db")

    # Nested access
    with pytest.raises(ValueError, match=r"\.openpaw"):
        fs._resolve_path(".openpaw/sessions.json")

    # Subdirectory access
    with pytest.raises(ValueError, match=r"\.openpaw"):
        fs._resolve_path("subdir/.openpaw/something")


def test_normal_paths_still_work(tmp_path: Path):
    """Verify normal paths are not blocked."""
    fs = FilesystemTools(tmp_path)

    # These should NOT raise
    resolved = fs._resolve_path("memory/conversations")
    assert resolved == (tmp_path / "memory" / "conversations").resolve()

    resolved = fs._resolve_path("TASKS.yaml")
    assert resolved == (tmp_path / "TASKS.yaml").resolve()


def test_openpaw_like_filenames_allowed(tmp_path: Path):
    """Verify files with similar names are not blocked."""
    fs = FilesystemTools(tmp_path)

    # These should NOT raise (only directory named exactly ".openpaw" is blocked)
    resolved = fs._resolve_path("openpaw_notes.txt")
    assert resolved == (tmp_path / "openpaw_notes.txt").resolve()

    resolved = fs._resolve_path("memory/openpaw_archive")
    assert resolved == (tmp_path / "memory" / "openpaw_archive").resolve()


def test_openpaw_directory_blocked_in_tool_operations(tmp_path: Path):
    """Verify .openpaw/ is blocked through actual tool operations."""
    fs = FilesystemTools(tmp_path)
    tools_dict = {tool.name: tool for tool in fs.get_tools()}

    # Create .openpaw directory with a file
    openpaw_dir = tmp_path / ".openpaw"
    openpaw_dir.mkdir()
    (openpaw_dir / "conversations.db").write_text("secret data")

    # Test read_file
    read_tool = tools_dict["read_file"]
    result = read_tool.invoke({"file_path": ".openpaw/conversations.db"})
    assert "Error:" in result
    assert ".openpaw" in result

    # Test write_file
    write_tool = tools_dict["write_file"]
    result = write_tool.invoke({
        "file_path": ".openpaw/new_file.txt",
        "content": "should not work"
    })
    assert "Error:" in result
    assert ".openpaw" in result

    # Test overwrite_file
    overwrite_tool = tools_dict["overwrite_file"]
    result = overwrite_tool.invoke({
        "file_path": ".openpaw/conversations.db",
        "content": "should not work"
    })
    assert "Error:" in result
    assert ".openpaw" in result

    # Test edit_file
    edit_tool = tools_dict["edit_file"]
    result = edit_tool.invoke({
        "file_path": ".openpaw/conversations.db",
        "old_text": "secret",
        "new_text": "public"
    })
    assert "Error:" in result
    assert ".openpaw" in result


def test_existing_security_checks_still_work(tmp_path: Path):
    """Verify existing security checks remain intact."""
    fs = FilesystemTools(tmp_path)

    # Path traversal should still be blocked
    with pytest.raises(ValueError, match=r"Path traversal"):
        fs._resolve_path("../etc/passwd")

    # Absolute paths should still be blocked
    with pytest.raises(ValueError, match="Absolute paths"):
        fs._resolve_path("/etc/passwd")

    # Home directory expansion should still be blocked
    with pytest.raises(ValueError, match="Home directory"):
        fs._resolve_path("~/secrets.txt")
