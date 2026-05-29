"""Tests for CLI init command handlers and dispatch routing."""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from openpaw.cli_init.commands import (
    _handle_init,
    _handle_list,
    dispatch_command,
)


def _make_valid_workspace(base: Path, name: str) -> Path:
    """Create a minimal valid workspace directory under base."""
    ws = base / name
    ws.mkdir(parents=True)
    agent_dir = ws / "agent"
    agent_dir.mkdir()
    for fname in ["AGENT.md", "USER.md", "SOUL.md", "HEARTBEAT.md"]:
        (agent_dir / fname).write_text(f"# {fname}", encoding="utf-8")
    return ws


class TestHandleInit:
    """Integration-level tests for the init command handler."""

    def test_invalid_name_exits_1(self, tmp_path: Path, capsys) -> None:
        with pytest.raises(SystemExit) as exc_info:
            _handle_init(["MyBadName", "--path", str(tmp_path)])
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "Error" in captured.err

    def test_duplicate_name_exits_1(self, tmp_path: Path, capsys) -> None:
        _handle_init(["good_name", "--path", str(tmp_path)])
        with pytest.raises(SystemExit) as exc_info:
            _handle_init(["good_name", "--path", str(tmp_path)])
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "already exists" in captured.err

    def test_success_prints_created_message(self, tmp_path: Path, capsys) -> None:
        _handle_init(["my_agent", "--path", str(tmp_path)])
        captured = capsys.readouterr()
        assert "Created workspace: my_agent" in captured.out

    def test_success_prints_next_steps(self, tmp_path: Path, capsys) -> None:
        _handle_init(["my_agent", "--path", str(tmp_path)])
        captured = capsys.readouterr()
        assert "Next steps:" in captured.out
        assert "openpaw -c config.yaml -w my_agent" in captured.out

    def test_model_flag_passed_through(self, tmp_path: Path) -> None:
        _handle_init(["agent_x", "--path", str(tmp_path), "--model", "anthropic:claude-sonnet-4-20250514"])
        data = yaml.safe_load((tmp_path / "agent_x" / "config" / "agent.yaml").read_text())
        assert data["model"]["provider"] == "anthropic"

    def test_channel_flag_passed_through(self, tmp_path: Path) -> None:
        _handle_init(["agent_y", "--path", str(tmp_path), "--channel", "telegram"])
        data = yaml.safe_load((tmp_path / "agent_y" / "config" / "agent.yaml").read_text())
        assert data["channel"]["type"] == "telegram"


class TestHandleList:
    """Tests for the list command handler."""

    def test_lists_valid_workspaces(self, tmp_path: Path, capsys) -> None:
        _make_valid_workspace(tmp_path, "alpha")
        _make_valid_workspace(tmp_path, "beta")
        _handle_list(["--path", str(tmp_path)])
        captured = capsys.readouterr()
        assert "alpha" in captured.out
        assert "beta" in captured.out
        assert "2 workspace(s) found." in captured.out

    def test_skips_invalid_directories(self, tmp_path: Path, capsys) -> None:
        """Directories missing required files should not appear in the list."""
        _make_valid_workspace(tmp_path, "valid_one")
        incomplete = tmp_path / "incomplete"
        incomplete.mkdir()
        (incomplete / "AGENT.md").write_text("# test")
        # Missing USER.md, SOUL.md, HEARTBEAT.md

        _handle_list(["--path", str(tmp_path)])
        captured = capsys.readouterr()
        assert "valid_one" in captured.out
        assert "incomplete" not in captured.out

    def test_empty_directory_prints_no_workspaces(self, tmp_path: Path, capsys) -> None:
        _handle_list(["--path", str(tmp_path)])
        captured = capsys.readouterr()
        assert "No workspaces found" in captured.out

    def test_nonexistent_directory_exits_1(self, tmp_path: Path, capsys) -> None:
        missing = tmp_path / "does_not_exist"
        with pytest.raises(SystemExit) as exc_info:
            _handle_list(["--path", str(missing)])
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "Directory not found" in captured.err

    def test_output_includes_workspace_count(self, tmp_path: Path, capsys) -> None:
        for name in ["one", "two", "three"]:
            _make_valid_workspace(tmp_path, name)
        _handle_list(["--path", str(tmp_path)])
        captured = capsys.readouterr()
        assert "3 workspace(s) found." in captured.out


class TestDispatchCommand:
    """Tests for the dispatch_command() router."""

    def test_dispatch_init_calls_init_handler(self, tmp_path: Path) -> None:
        with patch("openpaw.cli_init.commands._handle_init") as mock_init:
            dispatch_command("init", ["mybot", "--path", str(tmp_path)])
            mock_init.assert_called_once_with(["mybot", "--path", str(tmp_path)])

    def test_dispatch_list_calls_list_handler(self, tmp_path: Path) -> None:
        with patch("openpaw.cli_init.commands._handle_list") as mock_list:
            dispatch_command("list", ["--path", str(tmp_path)])
            mock_list.assert_called_once_with(["--path", str(tmp_path)])

    def test_dispatch_unknown_command_exits_1(self, capsys) -> None:
        with pytest.raises(SystemExit) as exc_info:
            dispatch_command("unknown", [])
        assert exc_info.value.code == 1

    def test_early_dispatch_in_cli_run_calls_dispatch(self, tmp_path: Path) -> None:
        """cli.run() should delegate to dispatch_command for 'init'."""
        from openpaw.cli import run

        with patch("openpaw.cli_init.dispatch_command") as mock_dispatch:
            with patch.object(sys, "argv", ["openpaw", "init", "test_ws"]):
                run()
            mock_dispatch.assert_called_once_with("init", ["test_ws"])

    def test_early_dispatch_in_cli_run_calls_list(self) -> None:
        """cli.run() should delegate to dispatch_command for 'list'."""
        from openpaw.cli import run

        with patch("openpaw.cli_init.dispatch_command") as mock_dispatch:
            with patch.object(sys, "argv", ["openpaw", "list"]):
                run()
            mock_dispatch.assert_called_once_with("list", [])


class TestHandleInitModelValidation:
    """Tests for invalid --model values in the init handler."""

    def test_empty_model_id_exits_1(self, tmp_path: Path, capsys) -> None:
        with pytest.raises(SystemExit) as exc_info:
            _handle_init(["my_agent", "--path", str(tmp_path), "--model", "anthropic:"])
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "model ID is empty" in captured.err

    def test_empty_provider_exits_1(self, tmp_path: Path, capsys) -> None:
        with pytest.raises(SystemExit) as exc_info:
            _handle_init(["my_agent", "--path", str(tmp_path), "--model", ":claude-sonnet"])
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "provider is empty" in captured.err


class TestHandleListIntegration:
    """Integration tests for list command with WorkspaceLoader."""

    def test_list_output_is_alphabetically_sorted(self, tmp_path: Path, capsys) -> None:
        for name in ["zeta", "alpha", "middle"]:
            _make_valid_workspace(tmp_path, name)
        _handle_list(["--path", str(tmp_path)])
        captured = capsys.readouterr()
        lines = [
            line.strip()
            for line in captured.out.strip().splitlines()
            if line.strip()
            and not line.startswith("Workspaces")
            and "workspace(s)" not in line
        ]
        assert lines == sorted(lines)
