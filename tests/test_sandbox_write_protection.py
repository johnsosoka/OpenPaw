"""Tests for write-mode sandbox protection introduced in Phase 1.

These tests verify:
- WRITE_PROTECTED_DIRS blocks writes to data/, config/, memory/logs,
  memory/conversations
- AGENT_WRITABLE_FILES exception: agent/HEARTBEAT.md is always writable
- Reads from protected directories are still permitted (write_mode=False default)
- Backward compatibility: callers that do not pass write_mode still work
"""

from pathlib import Path

import pytest

from openpaw.agent.tools.sandbox import _is_write_protected, resolve_sandboxed_path
from openpaw.core.paths import (
    AGENT_WRITABLE_FILES,
    HEARTBEAT_MD,
    WRITE_PROTECTED_DIRS,
)


# ---------------------------------------------------------------------------
# Unit tests for _is_write_protected helper
# ---------------------------------------------------------------------------


class TestIsWriteProtected:
    """Unit tests for the _is_write_protected helper."""

    # --- data/ directory ---

    def test_data_root_is_protected(self):
        assert _is_write_protected("data") is True

    def test_data_file_is_protected(self):
        assert _is_write_protected("data/TASKS.yaml") is True

    def test_data_nested_file_is_protected(self):
        assert _is_write_protected("data/uploads/2026-01-01/report.pdf") is True

    # --- config/ directory ---

    def test_config_root_is_protected(self):
        assert _is_write_protected("config") is True

    def test_config_agent_yaml_is_protected(self):
        assert _is_write_protected("config/agent.yaml") is True

    def test_config_dotenv_is_protected(self):
        assert _is_write_protected("config/.env") is True

    # --- memory/logs and memory/conversations ---

    def test_memory_logs_is_protected(self):
        assert _is_write_protected("memory/logs") is True

    def test_memory_logs_file_is_protected(self):
        assert _is_write_protected("memory/logs/heartbeat/session.jsonl") is True

    def test_memory_conversations_is_protected(self):
        assert _is_write_protected("memory/conversations") is True

    def test_memory_conversations_file_is_protected(self):
        assert _is_write_protected("memory/conversations/conv_abc.md") is True

    # --- agent/HEARTBEAT.md exception ---

    def test_heartbeat_md_is_not_protected(self):
        """agent/HEARTBEAT.md must bypass protection (explicit writable exception)."""
        assert _is_write_protected("agent/HEARTBEAT.md") is False

    def test_agent_writable_files_set_contains_heartbeat(self):
        """Sanity-check the constant set used by the helper."""
        assert str(HEARTBEAT_MD) in AGENT_WRITABLE_FILES

    # --- Allowed directories / files ---

    def test_workspace_dir_is_not_protected(self):
        assert _is_write_protected("workspace/report.md") is False

    def test_workspace_root_is_not_protected(self):
        assert _is_write_protected("workspace") is False

    def test_agent_dir_general_not_protected(self):
        """agent/ subdirectory other than HEARTBEAT.md is writable (no agent/ protection)."""
        assert _is_write_protected("agent/tools/custom_tool.py") is False

    def test_memory_root_is_not_fully_protected(self):
        """memory/ itself is not listed; only sub-paths logs/ and conversations/ are."""
        assert _is_write_protected("memory") is False

    def test_memory_other_subdir_is_not_protected(self):
        assert _is_write_protected("memory/notes.md") is False

    def test_bare_filename_is_not_protected(self):
        assert _is_write_protected("report.md") is False

    # --- No false positives from similar names ---

    def test_similar_name_data_prefix_not_protected(self):
        """'database/' must not be confused with 'data/'."""
        assert _is_write_protected("database/file.txt") is False

    def test_similar_name_configs_not_protected(self):
        """'configs/' must not be confused with 'config/'."""
        assert _is_write_protected("configs/agent.yaml") is False


# ---------------------------------------------------------------------------
# Integration tests via resolve_sandboxed_path
# ---------------------------------------------------------------------------


class TestResolveSandboxedPathWriteMode:
    """Integration tests for resolve_sandboxed_path with write_mode=True."""

    # --- Protected directories raise ValueError ---

    def test_write_to_data_blocked(self, tmp_path: Path):
        with pytest.raises(ValueError, match="Write access"):
            resolve_sandboxed_path(tmp_path, "data/TASKS.yaml", write_mode=True)

    def test_write_to_data_nested_blocked(self, tmp_path: Path):
        with pytest.raises(ValueError, match="Write access"):
            resolve_sandboxed_path(tmp_path, "data/uploads/report.pdf", write_mode=True)

    def test_write_to_config_blocked(self, tmp_path: Path):
        with pytest.raises(ValueError, match="Write access"):
            resolve_sandboxed_path(tmp_path, "config/agent.yaml", write_mode=True)

    def test_write_to_config_dotenv_blocked(self, tmp_path: Path):
        with pytest.raises(ValueError, match="Write access"):
            resolve_sandboxed_path(tmp_path, "config/.env", write_mode=True)

    def test_write_to_memory_logs_blocked(self, tmp_path: Path):
        with pytest.raises(ValueError, match="Write access"):
            resolve_sandboxed_path(tmp_path, "memory/logs/heartbeat/run.jsonl", write_mode=True)

    def test_write_to_memory_conversations_blocked(self, tmp_path: Path):
        with pytest.raises(ValueError, match="Write access"):
            resolve_sandboxed_path(tmp_path, "memory/conversations/conv_abc.md", write_mode=True)

    # --- HEARTBEAT.md exception ---

    def test_write_to_heartbeat_md_allowed(self, tmp_path: Path):
        """agent/HEARTBEAT.md must not raise even in write mode."""
        result = resolve_sandboxed_path(tmp_path, "agent/HEARTBEAT.md", write_mode=True)
        assert result == (tmp_path / "agent" / "HEARTBEAT.md").resolve()

    # --- Allowed write targets ---

    def test_write_to_workspace_allowed(self, tmp_path: Path):
        result = resolve_sandboxed_path(tmp_path, "workspace/report.md", write_mode=True)
        assert result == (tmp_path / "workspace" / "report.md").resolve()

    def test_write_to_workspace_nested_allowed(self, tmp_path: Path):
        result = resolve_sandboxed_path(tmp_path, "workspace/research/notes.txt", write_mode=True)
        assert result == (tmp_path / "workspace" / "research" / "notes.txt").resolve()

    def test_write_to_agent_tools_allowed(self, tmp_path: Path):
        """Other files in agent/ (not HEARTBEAT.md) are writable."""
        result = resolve_sandboxed_path(tmp_path, "agent/tools/my_tool.py", write_mode=True)
        assert result == (tmp_path / "agent" / "tools" / "my_tool.py").resolve()

    def test_write_to_memory_other_allowed(self, tmp_path: Path):
        """memory/ subdirs outside logs/ and conversations/ are writable."""
        result = resolve_sandboxed_path(tmp_path, "memory/notes.md", write_mode=True)
        assert result == (tmp_path / "memory" / "notes.md").resolve()

    # --- Reads from protected directories are allowed (write_mode=False default) ---

    def test_read_from_data_allowed(self, tmp_path: Path):
        result = resolve_sandboxed_path(tmp_path, "data/TASKS.yaml")
        assert result == (tmp_path / "data" / "TASKS.yaml").resolve()

    def test_read_from_config_allowed(self, tmp_path: Path):
        result = resolve_sandboxed_path(tmp_path, "config/agent.yaml")
        assert result == (tmp_path / "config" / "agent.yaml").resolve()

    def test_read_from_memory_logs_allowed(self, tmp_path: Path):
        result = resolve_sandboxed_path(tmp_path, "memory/logs/heartbeat/run.jsonl")
        assert result == (tmp_path / "memory" / "logs" / "heartbeat" / "run.jsonl").resolve()

    # --- Backward compatibility: existing callers without write_mode ---

    def test_backward_compat_no_write_mode(self, tmp_path: Path):
        """Calling without write_mode parameter still works for all paths."""
        result = resolve_sandboxed_path(tmp_path, "data/TASKS.yaml")
        assert result == (tmp_path / "data" / "TASKS.yaml").resolve()

    # --- Existing security checks are unaffected ---

    def test_absolute_path_still_rejected_in_write_mode(self, tmp_path: Path):
        with pytest.raises(ValueError, match="Absolute paths"):
            resolve_sandboxed_path(tmp_path, "/etc/passwd", write_mode=True)

    def test_path_traversal_still_rejected_in_write_mode(self, tmp_path: Path):
        with pytest.raises(ValueError, match="Path traversal"):
            resolve_sandboxed_path(tmp_path, "../etc/passwd", write_mode=True)

    def test_home_expansion_still_rejected_in_write_mode(self, tmp_path: Path):
        with pytest.raises(ValueError, match="Home directory"):
            resolve_sandboxed_path(tmp_path, "~/secrets.txt", write_mode=True)

    # --- WRITE_PROTECTED_DIRS constant sanity ---

    def test_write_protected_dirs_constant_content(self):
        """Verify the constant contains exactly the directories we expect."""
        assert "data" in WRITE_PROTECTED_DIRS
        assert "config" in WRITE_PROTECTED_DIRS
        assert "memory/logs" in WRITE_PROTECTED_DIRS
        assert "memory/conversations" in WRITE_PROTECTED_DIRS
        # workspace/ and agent/ must NOT be in the set
        assert "workspace" not in WRITE_PROTECTED_DIRS
        assert "agent" not in WRITE_PROTECTED_DIRS
