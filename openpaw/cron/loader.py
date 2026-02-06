"""Cron definition loader for OpenPaw workspaces."""

from pathlib import Path
from typing import Any

import yaml
from apscheduler.triggers.cron import CronTrigger
from pydantic import BaseModel, Field, field_validator

from openpaw.core.config import expand_env_vars_recursive


class CronOutputConfig(BaseModel):
    """Output routing configuration for a cron job."""

    channel: str = Field(description="Channel type (telegram, discord, etc.)")
    chat_id: int | None = Field(default=None, description="Telegram chat ID")
    guild_id: int | None = Field(default=None, description="Discord guild ID")
    channel_id: int | None = Field(default=None, description="Discord channel ID")


class CronDefinition(BaseModel):
    """Definition of a single cron job from workspace crons/ directory."""

    name: str = Field(description="Unique job identifier")
    schedule: str = Field(description="Cron expression (e.g., '0 9 * * *')")
    enabled: bool = Field(default=True, description="Whether the job is active")
    prompt: str = Field(description="User prompt to inject when cron triggers")
    output: CronOutputConfig = Field(description="Where to send the response")

    @field_validator("schedule")
    @classmethod
    def validate_cron_expression(cls, v: str) -> str:
        """Validate cron expression is parseable at config load time."""
        try:
            CronTrigger.from_crontab(v)
        except (ValueError, KeyError) as e:
            raise ValueError(f"Invalid cron expression '{v}': {e}") from e
        return v


class CronLoader:
    """Loads cron definitions from a workspace's crons/ directory."""

    CRONS_DIR = "crons"

    def __init__(self, workspace_path: Path):
        """Initialize the cron loader.

        Args:
            workspace_path: Path to the agent workspace root.
        """
        self.workspace_path = Path(workspace_path)
        self.crons_path = self.workspace_path / self.CRONS_DIR

    def load_all(self) -> list[CronDefinition]:
        """Load all cron definitions from the workspace.

        Returns:
            List of CronDefinition objects.
        """
        if not self.crons_path.exists():
            return []

        cron_definitions: list[CronDefinition] = []

        for cron_file in self.crons_path.glob("*.yaml"):
            try:
                with cron_file.open() as f:
                    raw_data: dict[str, Any] = yaml.safe_load(f) or {}

                expanded_data = expand_env_vars_recursive(raw_data)

                cron_def = CronDefinition(**expanded_data)
                cron_definitions.append(cron_def)
            except Exception as e:
                raise ValueError(f"Failed to load cron definition from {cron_file}: {e}") from e

        return cron_definitions

    def load_one(self, name: str) -> CronDefinition:
        """Load a specific cron definition by name.

        Args:
            name: The cron job name (filename without .yaml extension).

        Returns:
            CronDefinition object.

        Raises:
            FileNotFoundError: If the cron definition doesn't exist.
        """
        cron_file = self.crons_path / f"{name}.yaml"

        if not cron_file.exists():
            raise FileNotFoundError(f"Cron definition not found: {cron_file}")

        with cron_file.open() as f:
            raw_data: dict[str, Any] = yaml.safe_load(f) or {}

        expanded_data = expand_env_vars_recursive(raw_data)

        return CronDefinition(**expanded_data)
