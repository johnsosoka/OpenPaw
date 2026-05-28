"""File I/O operations for persistent cron jobs."""

import logging
from pathlib import Path
from typing import Any

import yaml

from openpaw.runtime.scheduling.loader import CronLoader

logger = logging.getLogger(__name__)


class CronPersistence:
    """Handles YAML file persistence for cron job definitions."""

    def __init__(self, config: dict[str, Any] | None = None):
        """Initialize the persistence layer.

        Args:
            config: Configuration dict containing:
                - crons_dir: Absolute path to config/crons/ directory (required)
                - default_channel: Channel name for output routing (default: "telegram")
                - default_target_id: Target ID for output routing (default: None)
                - timezone: Display timezone string (default: "UTC")
        """
        config = config or {}
        crons_dir = config.get("crons_dir")
        if not crons_dir:
            raise ValueError("CronPersistence requires 'crons_dir' in config")

        self.crons_dir = Path(crons_dir)
        self.workspace_root = self.crons_dir.parent.parent
        self.default_channel = config.get("default_channel", "telegram")
        self.default_target_id: int | None = config.get("default_target_id")
        self.timezone = config.get("timezone", "UTC")

    def file_path(self, name: str) -> Path:
        """Return the canonical YAML file path for a given cron name."""
        return self.crons_dir / f"{name}.yaml"

    def exists(self, name: str) -> bool:
        """Check if a YAML cron file exists for the given name."""
        return self.file_path(name).exists()

    def build_dict(
        self,
        name: str,
        schedule: str,
        prompt: str,
        enabled: bool,
        delivery: str,
    ) -> dict[str, Any]:
        """Build the raw dict that maps 1-to-1 with the YAML file format."""
        output: dict[str, Any] = {
            "channel": self.default_channel,
            "delivery": delivery,
        }
        if self.default_target_id is not None:
            output["target_id"] = self.default_target_id

        return {
            "name": name,
            "schedule": schedule,
            "enabled": enabled,
            "prompt": prompt,
            "output": output,
        }

    def write(self, cron_dict: dict[str, Any]) -> None:
        """Serialize a cron dict to YAML and write it to disk.

        Creates the crons directory if it does not yet exist.
        """
        self.crons_dir.mkdir(parents=True, exist_ok=True)
        path = self.file_path(cron_dict["name"])
        with path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(cron_dict, f, default_flow_style=False, sort_keys=False)

    def load(self, name: str) -> dict[str, Any] | None:
        """Read and parse a YAML cron file. Returns None if not found."""
        path = self.file_path(name)
        if not path.exists():
            return None
        with path.open(encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def load_all(self) -> Any:
        """Load all cron definitions from the workspace."""
        loader = CronLoader(self.workspace_root)
        return loader.load_all()

    def load_one(self, name: str) -> Any:
        """Load a single cron definition by name."""
        loader = CronLoader(self.workspace_root)
        return loader.load_one(name)


__all__ = ["CronPersistence"]
