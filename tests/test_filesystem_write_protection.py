"""Tests for FilesystemTools write protection and workspace/ default root.

Phase 1 additions:
- Write operations (write_file, overwrite_file, edit_file) go through
  _resolve_write_path(), which enforces write protection and transparently
  redirects bare filenames to workspace/.
- Read operations remain unrestricted.
"""

from pathlib import Path

import pytest

from openpaw.agent.tools.filesystem import FilesystemTools


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_fs(tmp_path: Path, workspace_name: str = "") -> FilesystemTools:
    return FilesystemTools(tmp_path, workspace_name=workspace_name)


def get_tools(fs: FilesystemTools) -> dict:
    return {t.name: t for t in fs.get_tools()}


# ---------------------------------------------------------------------------
# _resolve_write_path: unit tests via the private method
# ---------------------------------------------------------------------------


class TestResolveWritePath:
    """Verify _resolve_write_path routing logic directly."""

    def test_bare_filename_redirects_to_workspace(self, tmp_path: Path):
        fs = make_fs(tmp_path)
        result = fs._resolve_write_path("report.md")
        assert result == (tmp_path / "workspace" / "report.md").resolve()

    def test_relative_path_redirects_to_workspace(self, tmp_path: Path):
        fs = make_fs(tmp_path)
        result = fs._resolve_write_path("research/notes.txt")
        assert result == (tmp_path / "workspace" / "research" / "notes.txt").resolve()

    def test_explicit_workspace_path_kept(self, tmp_path: Path):
        fs = make_fs(tmp_path)
        result = fs._resolve_write_path("workspace/report.md")
        assert result == (tmp_path / "workspace" / "report.md").resolve()

    def test_heartbeat_md_path_kept(self, tmp_path: Path):
        fs = make_fs(tmp_path)
        result = fs._resolve_write_path("agent/HEARTBEAT.md")
        assert result == (tmp_path / "agent" / "HEARTBEAT.md").resolve()

    def test_data_path_raises(self, tmp_path: Path):
        fs = make_fs(tmp_path)
        with pytest.raises(ValueError, match="Write access"):
            fs._resolve_write_path("data/TASKS.yaml")

    def test_config_path_raises(self, tmp_path: Path):
        fs = make_fs(tmp_path)
        with pytest.raises(ValueError, match="Write access"):
            fs._resolve_write_path("config/agent.yaml")

    def test_memory_logs_path_raises(self, tmp_path: Path):
        fs = make_fs(tmp_path)
        with pytest.raises(ValueError, match="Write access"):
            fs._resolve_write_path("memory/logs/heartbeat/session.jsonl")

    def test_memory_conversations_path_raises(self, tmp_path: Path):
        fs = make_fs(tmp_path)
        with pytest.raises(ValueError, match="Write access"):
            fs._resolve_write_path("memory/conversations/conv_abc.md")


# ---------------------------------------------------------------------------
# write_file: bare filename goes to workspace/
# ---------------------------------------------------------------------------


class TestWriteFileDefaultRoot:
    """write_file transparently places bare filenames under workspace/."""

    def test_bare_filename_written_to_workspace(self, tmp_path: Path):
        (tmp_path / "workspace").mkdir()
        fs = make_fs(tmp_path)
        tools = get_tools(fs)

        result = tools["write_file"].invoke({"file_path": "report.md", "content": "hello"})

        assert "Error:" not in result
        assert (tmp_path / "workspace" / "report.md").exists()
        assert (tmp_path / "workspace" / "report.md").read_text() == "hello"

    def test_explicit_workspace_path_written(self, tmp_path: Path):
        (tmp_path / "workspace").mkdir()
        fs = make_fs(tmp_path)
        tools = get_tools(fs)

        result = tools["write_file"].invoke({"file_path": "workspace/notes.md", "content": "hi"})

        assert "Error:" not in result
        assert (tmp_path / "workspace" / "notes.md").exists()

    def test_write_to_data_blocked(self, tmp_path: Path):
        (tmp_path / "data").mkdir()
        fs = make_fs(tmp_path)
        tools = get_tools(fs)

        result = tools["write_file"].invoke({"file_path": "data/TASKS.yaml", "content": "bad"})

        assert "Error:" in result
        assert not (tmp_path / "data" / "TASKS.yaml").exists()

    def test_write_to_config_blocked(self, tmp_path: Path):
        (tmp_path / "config").mkdir()
        fs = make_fs(tmp_path)
        tools = get_tools(fs)

        result = tools["write_file"].invoke({"file_path": "config/agent.yaml", "content": "bad"})

        assert "Error:" in result
        assert not (tmp_path / "config" / "agent.yaml").exists()

    def test_write_creates_workspace_subdir_if_needed(self, tmp_path: Path):
        """Parent directories under workspace/ are created automatically."""
        fs = make_fs(tmp_path)
        tools = get_tools(fs)

        result = tools["write_file"].invoke({
            "file_path": "research/deep/notes.txt",
            "content": "deep content",
        })

        assert "Error:" not in result
        assert (tmp_path / "workspace" / "research" / "deep" / "notes.txt").exists()


# ---------------------------------------------------------------------------
# overwrite_file: bare filename goes to workspace/
# ---------------------------------------------------------------------------


class TestOverwriteFileDefaultRoot:
    """overwrite_file transparently places bare filenames under workspace/."""

    def test_bare_filename_overwritten_in_workspace(self, tmp_path: Path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        (ws / "notes.md").write_text("old")

        fs = make_fs(tmp_path)
        tools = get_tools(fs)

        result = tools["overwrite_file"].invoke({"file_path": "notes.md", "content": "new"})

        assert "Error:" not in result
        assert (ws / "notes.md").read_text() == "new"

    def test_overwrite_heartbeat_md_allowed(self, tmp_path: Path):
        agent_dir = tmp_path / "agent"
        agent_dir.mkdir()
        (agent_dir / "HEARTBEAT.md").write_text("old heartbeat")

        fs = make_fs(tmp_path)
        tools = get_tools(fs)

        result = tools["overwrite_file"].invoke({
            "file_path": "agent/HEARTBEAT.md",
            "content": "updated heartbeat",
        })

        assert "Error:" not in result
        assert (agent_dir / "HEARTBEAT.md").read_text() == "updated heartbeat"

    def test_overwrite_to_data_blocked(self, tmp_path: Path):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "TASKS.yaml").write_text("original")

        fs = make_fs(tmp_path)
        tools = get_tools(fs)

        result = tools["overwrite_file"].invoke({"file_path": "data/TASKS.yaml", "content": "evil"})

        assert "Error:" in result
        # Original file must be intact
        assert (data_dir / "TASKS.yaml").read_text() == "original"

    def test_overwrite_to_memory_logs_blocked(self, tmp_path: Path):
        logs_dir = tmp_path / "memory" / "logs" / "heartbeat"
        logs_dir.mkdir(parents=True)
        target = logs_dir / "session.jsonl"
        target.write_text("real logs")

        fs = make_fs(tmp_path)
        tools = get_tools(fs)

        result = tools["overwrite_file"].invoke({
            "file_path": "memory/logs/heartbeat/session.jsonl",
            "content": "tampered",
        })

        assert "Error:" in result
        assert target.read_text() == "real logs"


# ---------------------------------------------------------------------------
# edit_file: bare filename resolved under workspace/
# ---------------------------------------------------------------------------


class TestEditFileDefaultRoot:
    """edit_file transparently resolves bare filenames under workspace/."""

    def test_edit_bare_filename_in_workspace(self, tmp_path: Path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        (ws / "draft.md").write_text("hello world")

        fs = make_fs(tmp_path)
        tools = get_tools(fs)

        result = tools["edit_file"].invoke({
            "file_path": "draft.md",
            "old_text": "world",
            "new_text": "there",
        })

        assert "Error:" not in result
        assert (ws / "draft.md").read_text() == "hello there"

    def test_edit_heartbeat_md_allowed(self, tmp_path: Path):
        agent_dir = tmp_path / "agent"
        agent_dir.mkdir()
        (agent_dir / "HEARTBEAT.md").write_text("check: pending")

        fs = make_fs(tmp_path)
        tools = get_tools(fs)

        result = tools["edit_file"].invoke({
            "file_path": "agent/HEARTBEAT.md",
            "old_text": "pending",
            "new_text": "done",
        })

        assert "Error:" not in result
        assert (agent_dir / "HEARTBEAT.md").read_text() == "check: done"

    def test_edit_data_file_blocked(self, tmp_path: Path):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "TASKS.yaml").write_text("tasks: []")

        fs = make_fs(tmp_path)
        tools = get_tools(fs)

        result = tools["edit_file"].invoke({
            "file_path": "data/TASKS.yaml",
            "old_text": "tasks",
            "new_text": "evil",
        })

        assert "Error:" in result
        assert (data_dir / "TASKS.yaml").read_text() == "tasks: []"

    def test_edit_config_file_blocked(self, tmp_path: Path):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "agent.yaml").write_text("name: test")

        fs = make_fs(tmp_path)
        tools = get_tools(fs)

        result = tools["edit_file"].invoke({
            "file_path": "config/agent.yaml",
            "old_text": "test",
            "new_text": "hacked",
        })

        assert "Error:" in result
        assert (config_dir / "agent.yaml").read_text() == "name: test"


# ---------------------------------------------------------------------------
# Read operations: protected directories are still readable
# ---------------------------------------------------------------------------


class TestReadFromProtectedDirs:
    """Agent reads from data/, config/, memory/logs/ should succeed."""

    def test_read_from_data(self, tmp_path: Path):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "TASKS.yaml").write_text("tasks: []")

        fs = make_fs(tmp_path)
        tools = get_tools(fs)

        result = tools["read_file"].invoke({"file_path": "data/TASKS.yaml"})

        assert "Error:" not in result
        assert "tasks: []" in result

    def test_read_from_config(self, tmp_path: Path):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "agent.yaml").write_text("name: gilfoyle")

        fs = make_fs(tmp_path)
        tools = get_tools(fs)

        result = tools["read_file"].invoke({"file_path": "config/agent.yaml"})

        assert "Error:" not in result
        assert "gilfoyle" in result

    def test_read_from_memory_logs(self, tmp_path: Path):
        logs_dir = tmp_path / "memory" / "logs" / "heartbeat"
        logs_dir.mkdir(parents=True)
        (logs_dir / "session.jsonl").write_text('{"type": "prompt"}')

        fs = make_fs(tmp_path)
        tools = get_tools(fs)

        result = tools["read_file"].invoke({"file_path": "memory/logs/heartbeat/session.jsonl"})

        assert "Error:" not in result
        assert "prompt" in result

    def test_ls_data_directory(self, tmp_path: Path):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "TASKS.yaml").write_text("tasks: []")

        fs = make_fs(tmp_path)
        tools = get_tools(fs)

        result = tools["ls"].invoke({"path": "data"})

        assert "Error:" not in result
        assert "TASKS.yaml" in result
