"""Tests for filesystem tools with security validation."""

from pathlib import Path

import pytest

from openpaw.agent.tools.filesystem import FilesystemTools


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


# ---------------------------------------------------------------------------
# Workspace name enrichment tests
# ---------------------------------------------------------------------------

class TestWorkspaceNameEnrichment:
    """Tests for workspace_name-driven output enrichment."""

    def _make_fs(self, tmp_path: Path, workspace_name: str = "test_agent") -> FilesystemTools:
        """Create a FilesystemTools instance with a workspace name."""
        return FilesystemTools(tmp_path, workspace_name=workspace_name)

    def test_ls_header_includes_workspace_name(self, tmp_path: Path):
        """ls output starts with [Workspace: <name>] header when workspace_name is set."""
        (tmp_path / "notes.md").write_text("hello")
        fs = self._make_fs(tmp_path)
        tools = {t.name: t for t in fs.get_tools()}

        result = tools["ls"].invoke({"path": "."})

        assert result.startswith("[Workspace: test_agent]")
        assert "Contents of ./:" in result
        assert "notes.md" in result

    def test_tool_descriptions_include_workspace_name(self, tmp_path: Path):
        """All tool descriptions are prefixed with [<name> workspace] when workspace_name is set."""
        fs = self._make_fs(tmp_path)
        tools = fs.get_tools()

        for tool_instance in tools:
            assert tool_instance.description.startswith("[test_agent workspace] "), (
                f"Tool '{tool_instance.name}' description missing workspace prefix: "
                f"{tool_instance.description[:60]}"
            )

    def test_write_success_includes_workspace(self, tmp_path: Path):
        """write_file success message includes workspace name when set."""
        fs = self._make_fs(tmp_path)
        tools = {t.name: t for t in fs.get_tools()}

        result = tools["write_file"].invoke({
            "file_path": "new_note.md",
            "content": "line one\nline two\n",
        })

        assert "Successfully wrote" in result
        assert "(workspace: test_agent)" in result

    def test_overwrite_success_includes_workspace(self, tmp_path: Path):
        """overwrite_file success message includes workspace name when set."""
        (tmp_path / "existing.md").write_text("original")
        fs = self._make_fs(tmp_path)
        tools = {t.name: t for t in fs.get_tools()}

        result = tools["overwrite_file"].invoke({
            "file_path": "existing.md",
            "content": "replaced content\n",
        })

        assert "Successfully wrote" in result
        assert "(workspace: test_agent)" in result

    def test_sandbox_error_includes_hint(self, tmp_path: Path):
        """ValueError from _resolve_path includes workspace name hint."""
        fs = self._make_fs(tmp_path)
        tools = {t.name: t for t in fs.get_tools()}

        # Path traversal triggers a ValueError in _resolve_path
        result = tools["read_file"].invoke({"file_path": "../etc/passwd"})

        assert "Error:" in result
        assert "Hint:" in result
        assert "test_agent" in result
        assert "notes.md" in result  # example path in hint

    def test_not_found_includes_ls_hint(self, tmp_path: Path):
        """'not found' errors include ls('.') suggestion."""
        fs = self._make_fs(tmp_path)
        tools = {t.name: t for t in fs.get_tools()}

        result = tools["read_file"].invoke({"file_path": "does_not_exist.txt"})

        assert "not found" in result
        assert "ls('.')" in result

    def test_backward_compat_no_workspace_name(self, tmp_path: Path):
        """FilesystemTools without workspace_name works identically — no prefixes or hints."""
        (tmp_path / "file.txt").write_text("content")
        fs = FilesystemTools(tmp_path)  # no workspace_name
        tools = {t.name: t for t in fs.get_tools()}

        # ls output has no workspace header
        ls_result = tools["ls"].invoke({"path": "."})
        assert "[Workspace:" not in ls_result
        assert "file.txt" in ls_result

        # Tool descriptions have no workspace prefix
        for tool_instance in fs.get_tools():
            assert not tool_instance.description.startswith("[")

        # write_file success has no workspace suffix
        write_result = tools["write_file"].invoke({
            "file_path": "new.txt",
            "content": "hello\n",
        })
        assert "(workspace:" not in write_result
        assert "Successfully wrote" in write_result

        # Path error has no hint
        error_result = tools["read_file"].invoke({"file_path": "../escape.txt"})
        assert "Error:" in error_result
        assert "Hint:" not in error_result
