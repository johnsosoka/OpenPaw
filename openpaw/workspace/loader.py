"""Agent workspace loading and management."""

import logging
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from openpaw.core.workspace import AgentWorkspace

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from openpaw.core.config import WorkspaceConfig
    from openpaw.core.config.models import CronDefinition


class WorkspaceLoader:
    """Loads agent workspaces from filesystem."""

    REQUIRED_FILES = ["AGENT.md", "USER.md", "SOUL.md", "HEARTBEAT.md"]
    SKILLS_DIR = "skills"
    TOOLS_DIR = "tools"

    def __init__(self, workspaces_root: Path):
        """Initialize the workspace loader.

        Args:
            workspaces_root: Root directory containing agent workspace folders.
        """
        self.workspaces_root = Path(workspaces_root)

    def list_workspaces(self) -> list[str]:
        """List all valid workspace names in the workspaces root.

        Returns:
            List of workspace directory names that contain required files.
        """
        if not self.workspaces_root.exists():
            return []

        workspaces = []
        for path in self.workspaces_root.iterdir():
            if path.is_dir() and not path.name.startswith("."):
                if self._is_valid_workspace(path):
                    workspaces.append(path.name)
        return sorted(workspaces)

    def _is_valid_workspace(self, path: Path) -> bool:
        """Check if a directory contains required workspace files."""
        return all((path / f).exists() for f in self.REQUIRED_FILES)

    def load(self, workspace_name: str) -> AgentWorkspace:
        """Load an agent workspace by name.

        Args:
            workspace_name: Name of the workspace directory.

        Returns:
            Loaded AgentWorkspace instance.

        Raises:
            FileNotFoundError: If workspace or required files don't exist.
        """
        workspace_path = self.workspaces_root / workspace_name

        if not workspace_path.exists():
            raise FileNotFoundError(f"Workspace not found: {workspace_path}")

        missing = [f for f in self.REQUIRED_FILES if not (workspace_path / f).exists()]
        if missing:
            raise FileNotFoundError(f"Missing required files in {workspace_name}: {missing}")

        skills_path = workspace_path / self.SKILLS_DIR
        tools_path = workspace_path / self.TOOLS_DIR

        # Load optional workspace config and crons
        workspace_config = self._load_workspace_config(workspace_path)
        crons = self._load_crons(workspace_path)

        return AgentWorkspace(
            name=workspace_name,
            path=workspace_path,
            agent_md=self._read_file(workspace_path / "AGENT.md"),
            user_md=self._read_file(workspace_path / "USER.md"),
            soul_md=self._read_file(workspace_path / "SOUL.md"),
            heartbeat_md=self._read_file(workspace_path / "HEARTBEAT.md"),
            skills_path=skills_path,
            tools_path=tools_path,
            config=workspace_config,
            crons=crons,
        )

    def _read_file(self, path: Path) -> str:
        """Read file contents, returning empty string if file doesn't exist."""
        if path.exists():
            return path.read_text(encoding="utf-8")
        return ""

    def _load_workspace_config(self, workspace_path: Path) -> "WorkspaceConfig | None":
        """Load agent.yaml configuration from workspace if it exists.

        Args:
            workspace_path: Path to the workspace directory.

        Returns:
            WorkspaceConfig object or None if agent.yaml doesn't exist.
        """
        config_file = workspace_path / "agent.yaml"
        if not config_file.exists():
            return None

        with config_file.open() as f:
            data = yaml.safe_load(f) or {}

        # Import expand_env_vars_recursive at runtime to avoid circular imports
        from openpaw.core.config import WorkspaceConfig, check_unexpanded_vars, expand_env_vars_recursive

        # Apply environment variable substitution
        data = expand_env_vars_recursive(data)
        check_unexpanded_vars(data, source=f"{workspace_path.name}/agent.yaml")

        return WorkspaceConfig(**data)

    def _load_crons(self, workspace_path: Path) -> "list[CronDefinition]":
        """Load all cron definitions from workspace's crons/ directory.

        Args:
            workspace_path: Path to the workspace directory.

        Returns:
            List of CronDefinition objects, empty list if crons/ doesn't exist.
        """
        crons_dir = workspace_path / "crons"
        if not crons_dir.exists() or not crons_dir.is_dir():
            return []

        # Import at runtime to avoid circular import
        from openpaw.core.config import check_unexpanded_vars, expand_env_vars_recursive
        from openpaw.core.config.models import CronDefinition

        cron_definitions = []
        for cron_file in sorted(
            list(crons_dir.glob("*.yaml")) + list(crons_dir.glob("*.yml"))
        ):
            try:
                with cron_file.open() as f:
                    data = yaml.safe_load(f) or {}

                # Apply environment variable substitution
                data = expand_env_vars_recursive(data)
                check_unexpanded_vars(data, source=f"{workspace_path.name}/crons/{cron_file.name}")

                cron_definitions.append(CronDefinition(**data))
            except Exception as e:
                # Log warning but continue loading other crons
                logger.warning(f"Failed to load cron file {cron_file.name}: {e}")
                continue

        return cron_definitions
