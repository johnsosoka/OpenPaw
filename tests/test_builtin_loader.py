"""Tests for BuiltinLoader config handling."""

from pathlib import Path

import pytest

from openpaw.builtins.loader import BuiltinLoader
from openpaw.builtins.registry import BuiltinRegistry
from openpaw.core.config.models import (
    BuiltinItemConfig,
    BuiltinsConfig,
    WorkspaceBuiltinsConfig,
)


@pytest.fixture(autouse=True)
def reset_registry() -> None:
    """Reset the registry singleton before each test."""
    BuiltinRegistry.reset()
    yield


@pytest.fixture
def workspace_path(tmp_path: Path) -> Path:
    """Create a temporary workspace directory."""
    workspace = tmp_path / "test_workspace"
    workspace.mkdir()
    return workspace


def test_get_field_with_pydantic_model() -> None:
    """Test _get_field works with Pydantic models."""
    model = BuiltinItemConfig(enabled=True, config={"key": "value"})

    assert BuiltinLoader._get_field(model, "enabled") is True
    assert BuiltinLoader._get_field(model, "config") == {"key": "value"}
    assert BuiltinLoader._get_field(model, "nonexistent") is None
    assert BuiltinLoader._get_field(model, "nonexistent", "default") == "default"


def test_get_field_with_dict() -> None:
    """Test _get_field works with raw dicts."""
    data = {"enabled": True, "config": {"key": "value"}}

    assert BuiltinLoader._get_field(data, "enabled") is True
    assert BuiltinLoader._get_field(data, "config") == {"key": "value"}
    assert BuiltinLoader._get_field(data, "nonexistent") is None
    assert BuiltinLoader._get_field(data, "nonexistent", "default") == "default"


def test_is_enabled_with_dict_extra_field(workspace_path: Path) -> None:
    """Test _is_enabled correctly reads enabled from extra dict fields."""
    # Simulate a builtin without typed field (stored as dict via extra="allow")
    workspace_config = WorkspaceBuiltinsConfig()

    # Manually set an extra field as a dict (simulates YAML loading)
    workspace_config.__dict__["browser"] = {"enabled": False, "config": {}}

    loader = BuiltinLoader(
        workspace_config=workspace_config,
        workspace_path=workspace_path,
    )

    # Should correctly detect enabled=False from the dict
    assert loader._is_enabled("browser") is False


def test_is_enabled_with_typed_field(workspace_path: Path) -> None:
    """Test _is_enabled works with typed Pydantic fields."""
    workspace_config = WorkspaceBuiltinsConfig(
        shell=BuiltinItemConfig(enabled=False)
    )

    loader = BuiltinLoader(
        workspace_config=workspace_config,
        workspace_path=workspace_path,
    )

    assert loader._is_enabled("shell") is False


def test_get_builtin_config_with_typed_shell_field(workspace_path: Path) -> None:
    """Test workspace shell config flows through loader with typed field."""
    workspace_config = WorkspaceBuiltinsConfig(
        shell=BuiltinItemConfig(
            enabled=True,
            config={"blocked_commands": ["rm", "sudo"]},
        )
    )

    loader = BuiltinLoader(
        workspace_config=workspace_config,
        workspace_path=workspace_path,
    )

    config = loader._get_builtin_config("shell")

    # Workspace config should be present
    assert "blocked_commands" in config
    assert config["blocked_commands"] == ["rm", "sudo"]


def test_get_builtin_config_with_dict_extra_field(workspace_path: Path) -> None:
    """Test workspace config flows through for untyped builtins stored as dicts."""
    workspace_config = WorkspaceBuiltinsConfig()

    # Simulate YAML loading of a builtin without typed field
    workspace_config.__dict__["browser"] = {
        "enabled": True,
        "config": {"allowed_domains": ["example.com"]},
    }

    loader = BuiltinLoader(
        workspace_config=workspace_config,
        workspace_path=workspace_path,
    )

    config = loader._get_builtin_config("browser")

    # Workspace config should be present
    assert "allowed_domains" in config
    assert config["allowed_domains"] == ["example.com"]


def test_workspace_config_overrides_global_config(workspace_path: Path) -> None:
    """Test workspace config overrides global config."""
    global_config = BuiltinsConfig(
        shell=BuiltinItemConfig(
            enabled=True,
            config={"blocked_commands": ["rm"]},
        )
    )

    workspace_config = WorkspaceBuiltinsConfig(
        shell=BuiltinItemConfig(
            enabled=True,
            config={"blocked_commands": ["sudo", "reboot"]},
        )
    )

    loader = BuiltinLoader(
        global_config=global_config,
        workspace_config=workspace_config,
        workspace_path=workspace_path,
    )

    config = loader._get_builtin_config("shell")

    # Workspace config should override global
    assert config["blocked_commands"] == ["sudo", "reboot"]


def test_workspace_enabled_overrides_global_enabled(workspace_path: Path) -> None:
    """Test workspace enabled setting overrides global."""
    global_config = BuiltinsConfig(
        shell=BuiltinItemConfig(enabled=True)
    )

    workspace_config = WorkspaceBuiltinsConfig(
        shell=BuiltinItemConfig(enabled=False)
    )

    loader = BuiltinLoader(
        global_config=global_config,
        workspace_config=workspace_config,
        workspace_path=workspace_path,
    )

    assert loader._is_enabled("shell") is False


def test_ssh_typed_field_config(workspace_path: Path) -> None:
    """Test SSH builtin config with typed field."""
    workspace_config = WorkspaceBuiltinsConfig(
        ssh=BuiltinItemConfig(
            enabled=True,
            config={"default_host": "example.com", "default_user": "admin"},
        )
    )

    loader = BuiltinLoader(
        workspace_config=workspace_config,
        workspace_path=workspace_path,
    )

    config = loader._get_builtin_config("ssh")

    assert config["default_host"] == "example.com"
    assert config["default_user"] == "admin"


def test_default_enabled_is_true(workspace_path: Path) -> None:
    """Test that builtins are enabled by default when not configured."""
    loader = BuiltinLoader(workspace_path=workspace_path)

    assert loader._is_enabled("shell") is True
    assert loader._is_enabled("ssh") is True
    assert loader._is_enabled("browser") is True


def test_global_config_with_dict_extra_field(workspace_path: Path) -> None:
    """Test global config works with dict extra fields."""
    global_config = BuiltinsConfig()

    # Simulate YAML loading of untyped builtin
    global_config.__dict__["browser"] = {
        "enabled": True,
        "config": {"headless": True},
    }

    loader = BuiltinLoader(
        global_config=global_config,
        workspace_path=workspace_path,
    )

    config = loader._get_builtin_config("browser")
    assert config["headless"] is True


def test_workspace_dict_overrides_global_dict(workspace_path: Path) -> None:
    """Test workspace dict config overrides global dict config."""
    global_config = BuiltinsConfig()
    global_config.__dict__["browser"] = {
        "enabled": True,
        "config": {"headless": False},
    }

    workspace_config = WorkspaceBuiltinsConfig()
    workspace_config.__dict__["browser"] = {
        "enabled": True,
        "config": {"headless": True},
    }

    loader = BuiltinLoader(
        global_config=global_config,
        workspace_config=workspace_config,
        workspace_path=workspace_path,
    )

    config = loader._get_builtin_config("browser")
    assert config["headless"] is True
