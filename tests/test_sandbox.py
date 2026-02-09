"""Tests for the standalone sandbox path resolution utility."""

from pathlib import Path

import pytest

from openpaw.agent.tools.sandbox import resolve_sandboxed_path


class TestResolveSandboxedPath:
    """Tests for resolve_sandboxed_path."""

    def test_valid_relative_path(self, tmp_path: Path):
        result = resolve_sandboxed_path(tmp_path, "notes.txt")
        assert result == (tmp_path / "notes.txt").resolve()

    def test_valid_subdirectory_path(self, tmp_path: Path):
        result = resolve_sandboxed_path(tmp_path, "subdir/nested/file.md")
        assert result == (tmp_path / "subdir" / "nested" / "file.md").resolve()

    def test_current_directory(self, tmp_path: Path):
        result = resolve_sandboxed_path(tmp_path, ".")
        assert result == tmp_path.resolve()

    def test_absolute_path_rejected(self, tmp_path: Path):
        with pytest.raises(ValueError, match="Absolute paths"):
            resolve_sandboxed_path(tmp_path, "/etc/passwd")

    def test_home_expansion_rejected(self, tmp_path: Path):
        with pytest.raises(ValueError, match="Home directory"):
            resolve_sandboxed_path(tmp_path, "~/secrets.txt")

    def test_path_traversal_rejected(self, tmp_path: Path):
        with pytest.raises(ValueError, match="Path traversal"):
            resolve_sandboxed_path(tmp_path, "../etc/passwd")

    def test_nested_path_traversal_rejected(self, tmp_path: Path):
        with pytest.raises(ValueError, match="Path traversal"):
            resolve_sandboxed_path(tmp_path, "subdir/../../etc/passwd")

    def test_openpaw_directory_rejected(self, tmp_path: Path):
        with pytest.raises(ValueError, match=r"\.openpaw"):
            resolve_sandboxed_path(tmp_path, ".openpaw/conversations.db")

    def test_nested_openpaw_directory_rejected(self, tmp_path: Path):
        with pytest.raises(ValueError, match=r"\.openpaw"):
            resolve_sandboxed_path(tmp_path, "subdir/.openpaw/file")

    def test_openpaw_like_filename_allowed(self, tmp_path: Path):
        result = resolve_sandboxed_path(tmp_path, "openpaw_notes.txt")
        assert result == (tmp_path / "openpaw_notes.txt").resolve()

    def test_dotfile_allowed(self, tmp_path: Path):
        result = resolve_sandboxed_path(tmp_path, ".env")
        assert result == (tmp_path / ".env").resolve()

    def test_tasks_yaml_allowed(self, tmp_path: Path):
        result = resolve_sandboxed_path(tmp_path, "TASKS.yaml")
        assert result == (tmp_path / "TASKS.yaml").resolve()
