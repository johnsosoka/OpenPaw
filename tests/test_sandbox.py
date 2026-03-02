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

    def test_data_directory_readable(self, tmp_path: Path):
        """data/ directory is readable (no longer protected like .openpaw was)."""
        result = resolve_sandboxed_path(tmp_path, "data/sessions.json")
        assert result == (tmp_path / "data" / "sessions.json").resolve()

    def test_nested_data_directory_readable(self, tmp_path: Path):
        """Nested data/ access is also allowed for reads."""
        result = resolve_sandboxed_path(tmp_path, "subdir/data/file")
        assert result == (tmp_path / "subdir" / "data" / "file").resolve()

    def test_dotfile_allowed(self, tmp_path: Path):
        result = resolve_sandboxed_path(tmp_path, ".env")
        assert result == (tmp_path / ".env").resolve()

    def test_tasks_yaml_in_data_allowed(self, tmp_path: Path):
        result = resolve_sandboxed_path(tmp_path, "data/TASKS.yaml")
        assert result == (tmp_path / "data" / "TASKS.yaml").resolve()

    def test_agent_subdir_allowed(self, tmp_path: Path):
        result = resolve_sandboxed_path(tmp_path, "agent/AGENT.md")
        assert result == (tmp_path / "agent" / "AGENT.md").resolve()

    def test_config_subdir_allowed(self, tmp_path: Path):
        result = resolve_sandboxed_path(tmp_path, "config/agent.yaml")
        assert result == (tmp_path / "config" / "agent.yaml").resolve()
