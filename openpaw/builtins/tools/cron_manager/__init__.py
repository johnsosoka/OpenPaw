"""Persistent cron management builtin for agent-controlled YAML cron jobs.

This package converts the monolithic cron_manager.py into a standard
multi-file package following the proven pattern from spawn/, task/, and browser/.

Public API:
    CronManagerBuiltin — facade class implementing BaseBuiltinTool
"""

import logging
from pathlib import Path
from typing import Any

from openpaw.builtins.base import (
    BaseBuiltinTool,
    BuiltinMetadata,
    BuiltinPrerequisite,
    BuiltinType,
)
from openpaw.builtins.tools.cron_manager.models import (
    CreateCronInput,
    DeleteCronInput,
    UpdateCronInput,
)
from openpaw.builtins.tools.cron_manager.persistence import CronPersistence
from openpaw.builtins.tools.cron_manager.scheduler_bridge import SchedulerBridge
from openpaw.builtins.tools.cron_manager.tools import (
    create_create_cron_tool,
    create_delete_cron_tool,
    create_list_crons_tool,
    create_update_cron_tool,
)
from openpaw.builtins.tools.cron_manager.validators import CronValidator

logger = logging.getLogger(__name__)

__all__ = [
    "CronManagerBuiltin",
    "CreateCronInput",
    "UpdateCronInput",
    "DeleteCronInput",
    "CronPersistence",
    "CronValidator",
    "SchedulerBridge",
]


class CronManagerBuiltin(BaseBuiltinTool):
    """Persistent cron management — create, list, update, and delete YAML cron jobs.

    Unlike the dynamic cron tool (which uses in-memory task scheduling), this
    builtin writes YAML files to the workspace ``config/crons/`` directory.
    Jobs created here survive restarts and are loaded by the cron scheduler at
    startup alongside any hand-authored cron files.

    All changes are also applied to the live scheduler immediately so there is
    no need to restart the workspace.

    Config options:
        crons_dir: Absolute path to the workspace's config/crons/ directory.
        default_channel: Channel name for cron output routing (default: "telegram").
        default_target_id: Target user/channel ID for routing (default: None).
        timezone: Workspace timezone for schedule display (default: "UTC").
    """

    metadata = BuiltinMetadata(
        name="cron_manager",
        display_name="Cron Manager",
        description="Create, list, update, and delete persistent YAML cron jobs",
        builtin_type=BuiltinType.TOOL,
        group="automation",
        prerequisites=BuiltinPrerequisite(),  # No external dependencies required
    )

    def __init__(self, config: dict[str, Any] | None = None):
        """Initialize the cron manager builtin.

        Args:
            config: Configuration dict containing:
                - crons_dir: Absolute path to config/crons/ directory (required)
                - default_channel: Channel name for output routing (default: "telegram")
                - default_target_id: Target ID for output routing (default: None)
                - timezone: Display timezone string (default: "UTC")
        """
        super().__init__(config)

        crons_dir = self.config.get("crons_dir")
        if not crons_dir:
            raise ValueError("CronManagerBuiltin requires 'crons_dir' in config")

        self.crons_dir = Path(crons_dir)
        self.default_channel = self.config.get("default_channel", "telegram")
        self.default_target_id: int | None = self.config.get("default_target_id")
        self.timezone = self.config.get("timezone", "UTC")

        self._persistence = CronPersistence(config)
        self._validator = CronValidator()
        self._scheduler_bridge = SchedulerBridge()

        logger.info(f"CronManagerBuiltin initialized (crons_dir={self.crons_dir})")

    def get_langchain_tool(self) -> list[Any]:
        """Return cron management tools as a list of LangChain StructuredTools."""
        return [
            create_create_cron_tool(self),
            create_list_crons_tool(self),
            create_update_cron_tool(self),
            create_delete_cron_tool(self),
        ]

    def set_scheduler(self, scheduler: Any) -> None:
        """Connect a live CronScheduler for immediate hot-reload on changes.

        Called by lifecycle.py after the scheduler has started. Without a
        scheduler reference, file changes are still persisted to disk and
        will take effect on the next workspace restart.

        Args:
            scheduler: CronScheduler instance.
        """
        self._scheduler_bridge.set_scheduler(scheduler)

    # ------------------------------------------------------------------
    # Backward-compatible wrappers
    # ------------------------------------------------------------------

    def _validate_name(self, name: str) -> str | None:
        """Return an error message if the name is invalid, otherwise None."""
        return self._validator.validate_name(name)

    def _validate_schedule(self, schedule: str) -> str | None:
        """Return an error message if the cron expression is invalid, otherwise None."""
        return self._validator.validate_schedule(schedule)

    def _validate_delivery(self, delivery: str) -> str | None:
        """Return an error message if the delivery mode is invalid, otherwise None."""
        return self._validator.validate_delivery(delivery)

    def _cron_file_path(self, name: str) -> Path:
        """Return the canonical YAML file path for a given cron name."""
        return self._persistence.file_path(name)

    def _cron_exists(self, name: str) -> bool:
        """Check if a YAML cron file exists for the given name."""
        return self._persistence.exists(name)

    def _build_cron_dict(
        self,
        name: str,
        schedule: str,
        prompt: str,
        enabled: bool,
        delivery: str,
    ) -> dict[str, Any]:
        """Build the raw dict that maps 1-to-1 with the YAML file format."""
        return self._persistence.build_dict(name, schedule, prompt, enabled, delivery)

    def _write_cron_yaml(self, cron_dict: dict[str, Any]) -> None:
        """Serialize a cron dict to YAML and write it to disk.

        Creates the crons directory if it does not yet exist.
        """
        self._persistence.write(cron_dict)

    def _load_cron_dict(self, name: str) -> dict[str, Any] | None:
        """Read and parse a YAML cron file. Returns None if not found."""
        return self._persistence.load(name)

    def _reload_in_scheduler(self, name: str) -> None:
        """Hot-reload a YAML cron into the live scheduler if one is available."""
        self._scheduler_bridge.reload(name, self._persistence.workspace_root)

    def _remove_from_scheduler(self, name: str) -> None:
        """Remove a cron job from the live scheduler if one is available."""
        self._scheduler_bridge.remove(name)
