"""Tests for .yml extension support in cron loaders."""

import tempfile
from pathlib import Path

import pytest
import yaml

from openpaw.runtime.scheduling.loader import CronLoader
from openpaw.workspace.loader import WorkspaceLoader


class TestCronLoaderYmlSupport:
    """Test that CronLoader supports both .yaml and .yml extensions."""

    @pytest.fixture
    def workspace_path(self):
        """Create a temporary workspace directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "test_workspace"
            workspace.mkdir()
            crons_dir = workspace / "config" / "crons"
            crons_dir.mkdir(parents=True, exist_ok=True)
            yield workspace

    def test_load_all_includes_yml_files(self, workspace_path):
        """Test that load_all() includes both .yaml and .yml files."""
        crons_dir = workspace_path / "config" / "crons"

        # Create .yaml file
        yaml_cron = {
            "name": "yaml-cron",
            "schedule": "0 9 * * *",
            "enabled": True,
            "prompt": "YAML cron",
            "output": {"channel": "telegram", "chat_id": 123},
        }
        with (crons_dir / "test.yaml").open("w") as f:
            yaml.dump(yaml_cron, f)

        # Create .yml file
        yml_cron = {
            "name": "yml-cron",
            "schedule": "0 10 * * *",
            "enabled": True,
            "prompt": "YML cron",
            "output": {"channel": "telegram", "chat_id": 456},
        }
        with (crons_dir / "test2.yml").open("w") as f:
            yaml.dump(yml_cron, f)

        loader = CronLoader(workspace_path)
        crons = loader.load_all()

        assert len(crons) == 2
        names = {c.name for c in crons}
        assert "yaml-cron" in names
        assert "yml-cron" in names

    def test_load_all_sorted_order(self, workspace_path):
        """Test that .yaml and .yml files are loaded in sorted order."""
        crons_dir = workspace_path / "config" / "crons"

        # Create files in non-alphabetical order
        for name in ["c.yml", "a.yaml", "b.yml"]:
            cron = {
                "name": name,
                "schedule": "0 9 * * *",
                "enabled": True,
                "prompt": f"Cron {name}",
                "output": {"channel": "telegram", "chat_id": 123},
            }
            with (crons_dir / name).open("w") as f:
                yaml.dump(cron, f)

        loader = CronLoader(workspace_path)
        crons = loader.load_all()

        # Should be sorted alphabetically
        assert len(crons) == 3
        names = [c.name for c in crons]
        assert names == ["a.yaml", "b.yml", "c.yml"]

    def test_load_one_prefers_yaml_then_yml(self, workspace_path):
        """Test that load_one() checks .yaml first, then .yml."""
        crons_dir = workspace_path / "config" / "crons"

        yml_cron = {
            "name": "test-cron",
            "schedule": "0 10 * * *",
            "enabled": True,
            "prompt": "YML version",
            "output": {"channel": "telegram", "chat_id": 456},
        }
        with (crons_dir / "test.yml").open("w") as f:
            yaml.dump(yml_cron, f)

        loader = CronLoader(workspace_path)
        cron = loader.load_one("test")

        assert cron.name == "test-cron"
        assert cron.prompt == "YML version"

    def test_load_one_yaml_takes_precedence(self, workspace_path):
        """Test that .yaml takes precedence over .yml when both exist."""
        crons_dir = workspace_path / "config" / "crons"

        # Create both .yaml and .yml
        yaml_cron = {
            "name": "yaml-version",
            "schedule": "0 9 * * *",
            "enabled": True,
            "prompt": "YAML version",
            "output": {"channel": "telegram", "chat_id": 123},
        }
        with (crons_dir / "test.yaml").open("w") as f:
            yaml.dump(yaml_cron, f)

        yml_cron = {
            "name": "yml-version",
            "schedule": "0 10 * * *",
            "enabled": True,
            "prompt": "YML version",
            "output": {"channel": "telegram", "chat_id": 456},
        }
        with (crons_dir / "test.yml").open("w") as f:
            yaml.dump(yml_cron, f)

        loader = CronLoader(workspace_path)
        cron = loader.load_one("test")

        # Should load .yaml version
        assert cron.name == "yaml-version"
        assert cron.prompt == "YAML version"

    def test_load_one_not_found_error_mentions_both_extensions(self, workspace_path):
        """Test that FileNotFoundError mentions both extensions."""
        loader = CronLoader(workspace_path)

        with pytest.raises(FileNotFoundError) as exc_info:
            loader.load_one("nonexistent")

        error_msg = str(exc_info.value)
        assert "nonexistent" in error_msg
        assert ".yaml and .yml" in error_msg


class TestWorkspaceLoaderYmlSupport:
    """Test that WorkspaceLoader supports both .yaml and .yml cron files."""

    @pytest.fixture
    def workspaces_root(self):
        """Create a temporary workspaces root with a valid workspace."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            workspace = root / "test_workspace"
            workspace.mkdir()

            # Create required workspace files in agent/ subdirectory
            agent_dir = workspace / "agent"
            agent_dir.mkdir(parents=True, exist_ok=True)
            for filename in ["AGENT.md", "USER.md", "SOUL.md", "HEARTBEAT.md"]:
                (agent_dir / filename).write_text(f"# {filename}\n")

            # Create crons directory under config/
            crons_dir = workspace / "config" / "crons"
            crons_dir.mkdir(parents=True, exist_ok=True)

            yield root

    def test_workspace_loader_includes_yml_crons(self, workspaces_root):
        """Test that WorkspaceLoader._load_crons() includes .yml files."""
        workspace_path = workspaces_root / "test_workspace"
        crons_dir = workspace_path / "config" / "crons"

        # Create .yaml file
        yaml_cron = {
            "name": "yaml-cron",
            "schedule": "0 9 * * *",
            "enabled": True,
            "prompt": "YAML cron",
            "output": {"channel": "telegram", "chat_id": 123},
        }
        with (crons_dir / "daily.yaml").open("w") as f:
            yaml.dump(yaml_cron, f)

        # Create .yml file
        yml_cron = {
            "name": "yml-cron",
            "schedule": "0 10 * * *",
            "enabled": True,
            "prompt": "YML cron",
            "output": {"channel": "telegram", "chat_id": 456},
        }
        with (crons_dir / "hourly.yml").open("w") as f:
            yaml.dump(yml_cron, f)

        loader = WorkspaceLoader(workspaces_root)
        workspace = loader.load("test_workspace")

        assert len(workspace.crons) == 2
        names = {c.name for c in workspace.crons}
        assert "yaml-cron" in names
        assert "yml-cron" in names

    def test_workspace_loader_crons_sorted(self, workspaces_root):
        """Test that crons are loaded in sorted order."""
        workspace_path = workspaces_root / "test_workspace"
        crons_dir = workspace_path / "config" / "crons"

        # Create files in non-alphabetical order
        for name in ["z.yml", "a.yaml", "m.yml"]:
            cron = {
                "name": name,
                "schedule": "0 9 * * *",
                "enabled": True,
                "prompt": f"Cron {name}",
                "output": {"channel": "telegram", "chat_id": 123},
            }
            with (crons_dir / name).open("w") as f:
                yaml.dump(cron, f)

        loader = WorkspaceLoader(workspaces_root)
        workspace = loader.load("test_workspace")

        # Should be sorted alphabetically
        assert len(workspace.crons) == 3
        names = [c.name for c in workspace.crons]
        assert names == ["a.yaml", "m.yml", "z.yml"]

    def test_workspace_loader_handles_invalid_yml_gracefully(self, workspaces_root):
        """Test that invalid .yml files are logged as warnings, not errors."""
        workspace_path = workspaces_root / "test_workspace"
        crons_dir = workspace_path / "config" / "crons"

        # Create invalid .yml file
        with (crons_dir / "invalid.yml").open("w") as f:
            f.write("this is not valid yaml: {{{")

        # Create valid .yaml file
        valid_cron = {
            "name": "valid-cron",
            "schedule": "0 9 * * *",
            "enabled": True,
            "prompt": "Valid cron",
            "output": {"channel": "telegram", "chat_id": 123},
        }
        with (crons_dir / "valid.yaml").open("w") as f:
            yaml.dump(valid_cron, f)

        loader = WorkspaceLoader(workspaces_root)
        workspace = loader.load("test_workspace")

        # Should load only the valid cron (invalid one logged as warning)
        assert len(workspace.crons) == 1
        assert workspace.crons[0].name == "valid-cron"
