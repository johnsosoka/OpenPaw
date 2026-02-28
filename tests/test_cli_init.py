"""Tests for openpaw init and openpaw list CLI commands."""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from openpaw.cli_init import (
    _build_agent_yaml,
    _create_workspace,
    _handle_init,
    _handle_list,
    _parse_model_string,
    _validate_workspace_name,
    dispatch_command,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_valid_workspace(base: Path, name: str) -> Path:
    """Create a minimal valid workspace directory under base."""
    ws = base / name
    ws.mkdir(parents=True)
    for fname in ["AGENT.md", "USER.md", "SOUL.md", "HEARTBEAT.md"]:
        (ws / fname).write_text(f"# {fname}", encoding="utf-8")
    return ws


# ---------------------------------------------------------------------------
# 1. Name validation
# ---------------------------------------------------------------------------

class TestValidateWorkspaceName:
    """Unit tests for _validate_workspace_name()."""

    @pytest.mark.parametrize("name", ["my_agent", "a1", "test-agent", "ab"])
    def test_valid_names_pass(self, name: str) -> None:
        """Valid names should not raise."""
        _validate_workspace_name(name)

    def test_rejects_uppercase(self) -> None:
        with pytest.raises(ValueError, match="invalid"):
            _validate_workspace_name("MyAgent")

    def test_rejects_spaces(self) -> None:
        with pytest.raises(ValueError, match="invalid"):
            _validate_workspace_name("my agent")

    def test_rejects_special_chars(self) -> None:
        with pytest.raises(ValueError, match="invalid"):
            _validate_workspace_name("my@agent")

    def test_rejects_starts_with_digit(self) -> None:
        with pytest.raises(ValueError, match="invalid"):
            _validate_workspace_name("1agent")

    def test_rejects_starts_with_hyphen(self) -> None:
        with pytest.raises(ValueError, match="invalid"):
            _validate_workspace_name("-agent")

    def test_rejects_too_long(self) -> None:
        with pytest.raises(ValueError, match="too long"):
            _validate_workspace_name("a" * 65)

    def test_rejects_single_char(self) -> None:
        with pytest.raises(ValueError, match="too short"):
            _validate_workspace_name("a")

    def test_rejects_empty_string(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            _validate_workspace_name("")

    def test_accepts_max_length(self) -> None:
        """Exactly 64 chars should be accepted."""
        _validate_workspace_name("a" * 64)

    def test_accepts_min_length(self) -> None:
        """Exactly 2 chars should be accepted."""
        _validate_workspace_name("ab")


# ---------------------------------------------------------------------------
# 2. Workspace creation
# ---------------------------------------------------------------------------

class TestCreateWorkspace:
    """Unit tests for _create_workspace()."""

    def test_creates_required_files(self, tmp_path: Path) -> None:
        """All four required markdown files and agent.yaml must be present."""
        _create_workspace(tmp_path, "my_agent", None, None)

        ws = tmp_path / "my_agent"
        for fname in ["AGENT.md", "USER.md", "SOUL.md", "HEARTBEAT.md", "agent.yaml"]:
            assert (ws / fname).exists(), f"Expected {fname} to exist"

    def test_creates_env_file(self, tmp_path: Path) -> None:
        _create_workspace(tmp_path, "my_agent", None, None)
        assert (tmp_path / "my_agent" / ".env").exists()

    def test_name_placeholder_replaced_in_agent_md(self, tmp_path: Path) -> None:
        _create_workspace(tmp_path, "hal", None, None)
        content = (tmp_path / "hal" / "AGENT.md").read_text()
        assert "AGENT: hal" in content
        assert "{name}" not in content

    def test_name_placeholder_replaced_in_soul_md(self, tmp_path: Path) -> None:
        _create_workspace(tmp_path, "hal", None, None)
        content = (tmp_path / "hal" / "SOUL.md").read_text()
        assert "SOUL: hal" in content
        assert "{name}" not in content

    def test_raises_on_existing_workspace(self, tmp_path: Path) -> None:
        _create_workspace(tmp_path, "dup", None, None)
        with pytest.raises(FileExistsError, match="already exists"):
            _create_workspace(tmp_path, "dup", None, None)

    def test_workspace_passes_loader_validation(self, tmp_path: Path) -> None:
        """WorkspaceLoader._is_valid_workspace() must return True for created workspaces."""
        from openpaw.workspace.loader import WorkspaceLoader

        _create_workspace(tmp_path, "gilfoyle", None, None)
        loader = WorkspaceLoader(tmp_path)
        ws_path = tmp_path / "gilfoyle"
        assert loader._is_valid_workspace(ws_path)

    def test_agent_yaml_parseable_by_workspace_config(self, tmp_path: Path) -> None:
        """agent.yaml must be parseable by WorkspaceConfig without errors."""
        from openpaw.core.config.models import WorkspaceConfig

        _create_workspace(tmp_path, "chomsky", None, None)
        data = yaml.safe_load((tmp_path / "chomsky" / "agent.yaml").read_text())
        # Pydantic should not raise here.
        WorkspaceConfig(**data)

    def test_returns_workspace_path(self, tmp_path: Path) -> None:
        result = _create_workspace(tmp_path, "rex", None, None)
        assert result == tmp_path / "rex"


# ---------------------------------------------------------------------------
# 3. agent.yaml generation
# ---------------------------------------------------------------------------

class TestBuildAgentYaml:
    """Unit tests for _build_agent_yaml()."""

    def test_no_flags_model_section_commented_out(self) -> None:
        yaml_text = _build_agent_yaml("mybot", None, None)
        assert "# model:" in yaml_text
        # The top-level model key must NOT be present as an active YAML key
        # (i.e., no line starting with "model:" without a leading #).
        active_keys = {
            line.split(":")[0]
            for line in yaml_text.splitlines()
            if line and not line.startswith("#") and ":" in line
        }
        assert "model" not in active_keys

    def test_no_flags_channel_section_commented_out(self) -> None:
        yaml_text = _build_agent_yaml("mybot", None, None)
        assert "# channel:" in yaml_text
        active_keys = {
            line.split(":")[0]
            for line in yaml_text.splitlines()
            if line and not line.startswith("#") and ":" in line
        }
        assert "channel" not in active_keys

    def test_model_flag_populates_model_section(self) -> None:
        yaml_text = _build_agent_yaml("mybot", None, "anthropic:claude-sonnet-4-20250514")
        parsed = yaml.safe_load(yaml_text)
        assert parsed["model"]["provider"] == "anthropic"
        assert parsed["model"]["model"] == "claude-sonnet-4-20250514"

    def test_channel_flag_populates_channel_section(self) -> None:
        yaml_text = _build_agent_yaml("mybot", "telegram", None)
        parsed = yaml.safe_load(yaml_text)
        assert parsed["channel"]["type"] == "telegram"

    def test_both_flags_set_both_sections(self) -> None:
        yaml_text = _build_agent_yaml("mybot", "telegram", "openai:gpt-4o")
        parsed = yaml.safe_load(yaml_text)
        assert parsed["model"]["provider"] == "openai"
        assert parsed["channel"]["type"] == "telegram"

    def test_queue_section_always_present(self) -> None:
        yaml_text = _build_agent_yaml("mybot", None, None)
        parsed = yaml.safe_load(yaml_text)
        assert parsed["queue"]["mode"] == "collect"
        assert parsed["queue"]["debounce_ms"] == 1000

    def test_workspace_name_in_name_field(self) -> None:
        yaml_text = _build_agent_yaml("clippy", None, None)
        parsed = yaml.safe_load(yaml_text)
        assert parsed["name"] == "clippy"

    def test_model_without_colon_defaults_to_anthropic(self) -> None:
        """A bare model string without a colon should still produce valid YAML."""
        yaml_text = _build_agent_yaml("mybot", None, "gpt-4o")
        parsed = yaml.safe_load(yaml_text)
        assert parsed["model"]["provider"] == "anthropic"
        assert parsed["model"]["model"] == "gpt-4o"


# ---------------------------------------------------------------------------
# 4. Error cases via _handle_init
# ---------------------------------------------------------------------------

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
        data = yaml.safe_load((tmp_path / "agent_x" / "agent.yaml").read_text())
        assert data["model"]["provider"] == "anthropic"

    def test_channel_flag_passed_through(self, tmp_path: Path) -> None:
        _handle_init(["agent_y", "--path", str(tmp_path), "--channel", "telegram"])
        data = yaml.safe_load((tmp_path / "agent_y" / "agent.yaml").read_text())
        assert data["channel"]["type"] == "telegram"


# ---------------------------------------------------------------------------
# 5. List command
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# 6. Dispatch routing
# ---------------------------------------------------------------------------

class TestDispatchCommand:
    """Tests for the dispatch_command() router."""

    def test_dispatch_init_calls_init_handler(self, tmp_path: Path) -> None:
        with patch("openpaw.cli_init._handle_init") as mock_init:
            dispatch_command("init", ["mybot", "--path", str(tmp_path)])
            mock_init.assert_called_once_with(["mybot", "--path", str(tmp_path)])

    def test_dispatch_list_calls_list_handler(self, tmp_path: Path) -> None:
        with patch("openpaw.cli_init._handle_list") as mock_list:
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


# ---------------------------------------------------------------------------
# 7. Model string parsing and validation
# ---------------------------------------------------------------------------

class TestParseModelString:
    """Tests for _parse_model_string()."""

    def test_splits_provider_and_model(self) -> None:
        assert _parse_model_string("anthropic:claude-sonnet-4-20250514") == (
            "anthropic",
            "claude-sonnet-4-20250514",
        )

    def test_bare_model_defaults_to_anthropic(self) -> None:
        assert _parse_model_string("gpt-4o") == ("anthropic", "gpt-4o")

    def test_rejects_empty_model_id(self) -> None:
        with pytest.raises(ValueError, match="model ID is empty"):
            _parse_model_string("anthropic:")

    def test_rejects_empty_provider(self) -> None:
        with pytest.raises(ValueError, match="provider is empty"):
            _parse_model_string(":claude-sonnet-4-20250514")

    def test_bedrock_model_string(self) -> None:
        provider, model_id = _parse_model_string("bedrock_converse:us.anthropic.claude-haiku:v1:0")
        assert provider == "bedrock_converse"
        assert model_id == "us.anthropic.claude-haiku:v1:0"


# ---------------------------------------------------------------------------
# 8. Bedrock-specific scaffold tests
# ---------------------------------------------------------------------------

class TestBedrockScaffold:
    """Tests ensuring Bedrock providers omit api_key."""

    def test_bedrock_omits_api_key_in_yaml(self) -> None:
        yaml_text = _build_agent_yaml("mybot", None, "bedrock_converse:us.anthropic.claude-haiku:v1:0")
        assert "api_key" not in yaml_text

    def test_bedrock_model_section_valid(self) -> None:
        yaml_text = _build_agent_yaml("mybot", None, "bedrock_converse:us.anthropic.claude-haiku:v1:0")
        parsed = yaml.safe_load(yaml_text)
        assert parsed["model"]["provider"] == "bedrock_converse"
        assert parsed["model"]["model"] == "us.anthropic.claude-haiku:v1:0"

    def test_anthropic_includes_api_key_in_yaml(self) -> None:
        yaml_text = _build_agent_yaml("mybot", None, "anthropic:claude-sonnet-4-20250514")
        assert "api_key" in yaml_text


# ---------------------------------------------------------------------------
# 9. Invalid model flag in init handler
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# 10. List command uses WorkspaceLoader
# ---------------------------------------------------------------------------

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
