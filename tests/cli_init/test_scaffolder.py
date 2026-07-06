"""Tests for CLI init scaffolder functions."""

from pathlib import Path

import pytest
import yaml

from openpaw.cli_init.scaffolder import (
    _create_workspace,
    _validate_workspace_name,
)


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


class TestCreateWorkspace:
    """Unit tests for _create_workspace()."""

    def test_creates_required_files(self, tmp_path: Path) -> None:
        """All four required markdown files must be in agent/ and agent.yaml in config/."""
        _create_workspace(tmp_path, "my_agent", None, None)

        ws = tmp_path / "my_agent"
        agent_dir = ws / "agent"
        config_dir = ws / "config"
        for fname in ["AGENT.md", "USER.md", "SOUL.md", "HEARTBEAT.md"]:
            assert (agent_dir / fname).exists(), f"Expected agent/{fname} to exist"
        assert (config_dir / "agent.yaml").exists(), "Expected config/agent.yaml to exist"

    def test_creates_env_file(self, tmp_path: Path) -> None:
        _create_workspace(tmp_path, "my_agent", None, None)
        assert (tmp_path / "my_agent" / "config" / ".env").exists()

    def test_name_placeholder_replaced_in_agent_md(self, tmp_path: Path) -> None:
        _create_workspace(tmp_path, "hal", None, None)
        content = (tmp_path / "hal" / "agent" / "AGENT.md").read_text()
        assert "AGENT: hal" in content
        assert "{name}" not in content

    def test_name_placeholder_replaced_in_soul_md(self, tmp_path: Path) -> None:
        _create_workspace(tmp_path, "hal", None, None)
        content = (tmp_path / "hal" / "agent" / "SOUL.md").read_text()
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
        data = yaml.safe_load((tmp_path / "chomsky" / "config" / "agent.yaml").read_text())
        # Pydantic should not raise here.
        WorkspaceConfig(**data)

    def test_returns_workspace_path(self, tmp_path: Path) -> None:
        result = _create_workspace(tmp_path, "rex", None, None)
        assert result == tmp_path / "rex"

    def test_scaffolds_moonshot_workspace_with_thinking_flag(self, tmp_path: Path) -> None:
        """`--model moonshot:kimi-k2.5` produces a valid native moonshot config."""
        from openpaw.core.config.models import WorkspaceConfig

        _create_workspace(tmp_path, "kimi_agent", None, "moonshot:kimi-k2.5")
        text = (tmp_path / "kimi_agent" / "config" / "agent.yaml").read_text()
        assert "provider: moonshot" in text
        assert "model: kimi-k2.5" in text
        assert "thinking: false" in text
        assert "api_key: ${MOONSHOT_API_KEY}" in text
        # Round-trip through Pydantic — catches the pre-0.4.3 legacy-rejection
        # path so we know this scaffolded yaml will actually boot.
        cfg = WorkspaceConfig(**yaml.safe_load(text))
        assert cfg.model.provider == "moonshot"
        assert cfg.model.thinking is False

    def test_default_harness_is_balanced_and_valid(self, tmp_path: Path) -> None:
        """No harness argument defaults to a balanced tier that Pydantic accepts."""
        from openpaw.core.config.models import WorkspaceConfig

        _create_workspace(tmp_path, "balanced_agent", None, None)
        data = yaml.safe_load(
            (tmp_path / "balanced_agent" / "config" / "agent.yaml").read_text()
        )
        assert data["harness"]["type"] == "balanced"
        cfg = WorkspaceConfig(**data)
        assert cfg.harness.type == "balanced"

    def test_ultra_harness_scaffolds_and_validates(self, tmp_path: Path) -> None:
        """`harness=ultra` writes a workspace whose agent.yaml validates as ultra."""
        from openpaw.core.config.models import WorkspaceConfig

        _create_workspace(tmp_path, "ultra_agent", None, None, "ultra")
        data = yaml.safe_load(
            (tmp_path / "ultra_agent" / "config" / "agent.yaml").read_text()
        )
        assert data["harness"]["type"] == "ultra"
        cfg = WorkspaceConfig(**data)
        assert cfg.harness.type == "ultra"

    def test_scaffolds_ollama_workspace_keyless(self, tmp_path: Path) -> None:
        """`--model ollama:llama3.1` produces a keyless config with base_url + num_ctx."""
        from openpaw.core.config.models import WorkspaceConfig

        _create_workspace(tmp_path, "local_agent", None, "ollama:llama3.1")
        text = (tmp_path / "local_agent" / "config" / "agent.yaml").read_text()
        assert "provider: ollama" in text
        assert "model: llama3.1" in text
        assert "base_url: http://localhost:11434" in text
        assert "num_ctx: 16384" in text
        # Ollama is keyless — make sure scaffolder doesn't emit a bogus api_key line.
        assert "api_key:" not in text
        cfg = WorkspaceConfig(**yaml.safe_load(text))
        assert cfg.model.provider == "ollama"
        assert cfg.model.base_url == "http://localhost:11434"
