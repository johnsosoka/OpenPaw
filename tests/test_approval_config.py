"""Tests for approval gates configuration models."""

import pytest

from openpaw.core.config.models import ApprovalGatesConfig, ToolApprovalConfig
from openpaw.core.config import Config, WorkspaceConfig, merge_configs


class TestToolApprovalConfig:
    """Test ToolApprovalConfig model."""

    def test_default_values(self):
        """Test ToolApprovalConfig has safe defaults."""
        config = ToolApprovalConfig()

        assert config.require_approval is True
        assert config.show_args is True

    def test_custom_values(self):
        """Test overriding default values."""
        config = ToolApprovalConfig(
            require_approval=False,
            show_args=False,
        )

        assert config.require_approval is False
        assert config.show_args is False

    def test_parse_from_dict(self):
        """Test parsing from dict (simulating YAML load)."""
        data = {
            "require_approval": True,
            "show_args": False,
        }
        config = ToolApprovalConfig(**data)

        assert config.require_approval is True
        assert config.show_args is False


class TestApprovalGatesConfig:
    """Test ApprovalGatesConfig model."""

    def test_default_values(self):
        """Test ApprovalGatesConfig has safe defaults."""
        config = ApprovalGatesConfig()

        assert config.enabled is False
        assert config.timeout_seconds == 120
        assert config.default_action == "deny"
        assert config.tools == {}

    def test_custom_values(self):
        """Test overriding all fields."""
        config = ApprovalGatesConfig(
            enabled=True,
            timeout_seconds=60,
            default_action="approve",
            tools={
                "shell": ToolApprovalConfig(require_approval=True, show_args=True),
                "ssh": ToolApprovalConfig(require_approval=True, show_args=False),
            },
        )

        assert config.enabled is True
        assert config.timeout_seconds == 60
        assert config.default_action == "approve"
        assert len(config.tools) == 2
        assert "shell" in config.tools
        assert "ssh" in config.tools
        assert config.tools["shell"].require_approval is True
        assert config.tools["shell"].show_args is True
        assert config.tools["ssh"].require_approval is True
        assert config.tools["ssh"].show_args is False

    def test_parse_from_dict(self):
        """Test parsing from dict (simulating YAML load)."""
        data = {
            "enabled": True,
            "timeout_seconds": 60,
            "default_action": "deny",
            "tools": {
                "shell": {
                    "require_approval": True,
                    "show_args": True,
                },
                "ssh": {
                    "require_approval": True,
                    "show_args": False,
                },
            },
        }
        config = ApprovalGatesConfig(**data)

        assert config.enabled is True
        assert config.timeout_seconds == 60
        assert config.default_action == "deny"
        assert len(config.tools) == 2
        assert config.tools["shell"].require_approval is True
        assert config.tools["shell"].show_args is True
        assert config.tools["ssh"].require_approval is True
        assert config.tools["ssh"].show_args is False

    def test_empty_tools_dict(self):
        """Test with empty tools dict."""
        config = ApprovalGatesConfig(enabled=True, tools={})

        assert config.enabled is True
        assert config.tools == {}


class TestWorkspaceConfigIntegration:
    """Test ApprovalGatesConfig integration with WorkspaceConfig."""

    def test_workspace_config_has_approval_gates_field(self):
        """Test WorkspaceConfig includes approval_gates field."""
        config = WorkspaceConfig()

        assert hasattr(config, "approval_gates")
        assert isinstance(config.approval_gates, ApprovalGatesConfig)
        assert config.approval_gates.enabled is False

    def test_workspace_config_with_custom_approval_gates(self):
        """Test WorkspaceConfig with custom approval gates."""
        config = WorkspaceConfig(
            approval_gates=ApprovalGatesConfig(
                enabled=True,
                timeout_seconds=30,
                default_action="deny",
            )
        )

        assert config.approval_gates.enabled is True
        assert config.approval_gates.timeout_seconds == 30
        assert config.approval_gates.default_action == "deny"

    def test_workspace_config_parse_from_dict(self):
        """Test parsing WorkspaceConfig with approval_gates from dict."""
        data = {
            "name": "test-agent",
            "approval_gates": {
                "enabled": True,
                "timeout_seconds": 90,
                "tools": {
                    "shell": {
                        "require_approval": True,
                        "show_args": False,
                    }
                },
            },
        }
        config = WorkspaceConfig(**data)

        assert config.name == "test-agent"
        assert config.approval_gates.enabled is True
        assert config.approval_gates.timeout_seconds == 90
        assert "shell" in config.approval_gates.tools
        assert config.approval_gates.tools["shell"].require_approval is True
        assert config.approval_gates.tools["shell"].show_args is False


class TestGlobalConfigIntegration:
    """Test ApprovalGatesConfig integration with global Config."""

    def test_global_config_has_approval_gates_field(self):
        """Test Config includes approval_gates field."""
        config = Config()

        assert hasattr(config, "approval_gates")
        assert isinstance(config.approval_gates, ApprovalGatesConfig)
        assert config.approval_gates.enabled is False

    def test_global_config_with_custom_approval_gates(self):
        """Test Config with custom approval gates."""
        config = Config(
            approval_gates=ApprovalGatesConfig(
                enabled=True,
                timeout_seconds=60,
                default_action="deny",
                tools={
                    "shell": ToolApprovalConfig(require_approval=True, show_args=True)
                },
            )
        )

        assert config.approval_gates.enabled is True
        assert config.approval_gates.timeout_seconds == 60
        assert config.approval_gates.default_action == "deny"
        assert "shell" in config.approval_gates.tools

    def test_global_config_parse_from_dict(self):
        """Test parsing Config with approval_gates from dict."""
        data = {
            "approval_gates": {
                "enabled": True,
                "timeout_seconds": 120,
                "default_action": "deny",
                "tools": {
                    "shell": {"require_approval": True, "show_args": True},
                    "ssh": {"require_approval": True, "show_args": False},
                },
            }
        }
        config = Config(**data)

        assert config.approval_gates.enabled is True
        assert config.approval_gates.timeout_seconds == 120
        assert len(config.approval_gates.tools) == 2
        assert config.approval_gates.tools["shell"].show_args is True
        assert config.approval_gates.tools["ssh"].show_args is False


class TestConfigMerging:
    """Test approval_gates config merging between global and workspace."""

    def test_workspace_overrides_global_enabled(self):
        """Test workspace can disable approval gates when global enables them."""
        global_config = {
            "approval_gates": {
                "enabled": True,
                "timeout_seconds": 60,
            }
        }
        workspace_config = {
            "approval_gates": {
                "enabled": False,
            }
        }

        merged = merge_configs(global_config, workspace_config)

        assert merged["approval_gates"]["enabled"] is False
        # Timeout should still come from global
        assert merged["approval_gates"]["timeout_seconds"] == 60

    def test_workspace_overrides_global_timeout(self):
        """Test workspace can override timeout."""
        global_config = {
            "approval_gates": {
                "enabled": True,
                "timeout_seconds": 120,
            }
        }
        workspace_config = {
            "approval_gates": {
                "timeout_seconds": 30,
            }
        }

        merged = merge_configs(global_config, workspace_config)

        assert merged["approval_gates"]["enabled"] is True
        assert merged["approval_gates"]["timeout_seconds"] == 30

    def test_workspace_adds_tools_to_global(self):
        """Test workspace can add tools to global config."""
        global_config = {
            "approval_gates": {
                "enabled": True,
                "tools": {
                    "shell": {"require_approval": True, "show_args": True}
                },
            }
        }
        workspace_config = {
            "approval_gates": {
                "tools": {
                    "ssh": {"require_approval": True, "show_args": False}
                },
            }
        }

        merged = merge_configs(global_config, workspace_config)

        # Note: merge_configs does deep merge on dicts
        # So tools dict should have both shell (from global) and ssh (from workspace)
        assert "shell" in merged["approval_gates"]["tools"]
        assert "ssh" in merged["approval_gates"]["tools"]

    def test_workspace_overrides_specific_tool(self):
        """Test workspace can override specific tool config."""
        global_config = {
            "approval_gates": {
                "tools": {
                    "shell": {"require_approval": True, "show_args": True}
                },
            }
        }
        workspace_config = {
            "approval_gates": {
                "tools": {
                    "shell": {"require_approval": False, "show_args": False}
                },
            }
        }

        merged = merge_configs(global_config, workspace_config)

        # Workspace should completely replace the shell tool config
        assert merged["approval_gates"]["tools"]["shell"]["require_approval"] is False
        assert merged["approval_gates"]["tools"]["shell"]["show_args"] is False

    def test_empty_workspace_inherits_global(self):
        """Test empty workspace config inherits all global approval_gates."""
        global_config = {
            "approval_gates": {
                "enabled": True,
                "timeout_seconds": 60,
                "default_action": "deny",
                "tools": {
                    "shell": {"require_approval": True, "show_args": True}
                },
            }
        }
        workspace_config = {}

        merged = merge_configs(global_config, workspace_config)

        assert merged["approval_gates"]["enabled"] is True
        assert merged["approval_gates"]["timeout_seconds"] == 60
        assert merged["approval_gates"]["default_action"] == "deny"
        assert "shell" in merged["approval_gates"]["tools"]
