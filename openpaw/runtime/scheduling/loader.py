"""Cron definition loader for OpenPaw workspaces."""

from pathlib import Path
from typing import Any

import yaml

from openpaw.core.config import check_unexpanded_vars, expand_env_vars_recursive
from openpaw.core.config.models import CronDefinition
from openpaw.core.paths import CRONS_DIR


class CronLoader:
    """Loads cron definitions from a workspace's config/crons/ directory."""

    def __init__(self, workspace_path: Path):
        """Initialize the cron loader.

        Args:
            workspace_path: Path to the agent workspace root.
        """
        self.workspace_path = Path(workspace_path)
        self.crons_path = self.workspace_path / str(CRONS_DIR)

    def load_all(self) -> list[CronDefinition]:
        """Load all cron definitions from the workspace.

        Returns:
            List of CronDefinition objects.
        """
        if not self.crons_path.exists():
            return []

        cron_definitions: list[CronDefinition] = []

        for cron_file in sorted(
            list(self.crons_path.glob("*.yaml")) + list(self.crons_path.glob("*.yml"))
        ):
            try:
                with cron_file.open() as f:
                    raw_data: dict[str, Any] = yaml.safe_load(f) or {}

                expanded_data = expand_env_vars_recursive(raw_data)
                check_unexpanded_vars(
                    expanded_data,
                    source=f"config/crons/{cron_file.name}",
                )

                cron_def = CronDefinition(**expanded_data)
                cron_definitions.append(cron_def)
            except Exception as e:
                raise ValueError(f"Failed to load cron definition from {cron_file}: {e}") from e

        return cron_definitions

    def load_one(self, name: str) -> CronDefinition:
        """Load a specific cron definition by name.

        Args:
            name: The cron job name (filename without .yaml/.yml extension).

        Returns:
            CronDefinition object.

        Raises:
            FileNotFoundError: If the cron definition doesn't exist.
        """
        cron_file = self.crons_path / f"{name}.yaml"
        if not cron_file.exists():
            cron_file = self.crons_path / f"{name}.yml"
        if not cron_file.exists():
            raise FileNotFoundError(f"Cron definition not found: {name} (checked .yaml and .yml)")

        with cron_file.open() as f:
            raw_data: dict[str, Any] = yaml.safe_load(f) or {}

        expanded_data = expand_env_vars_recursive(raw_data)
        check_unexpanded_vars(expanded_data, source=f"config/crons/{name}")

        return CronDefinition(**expanded_data)
