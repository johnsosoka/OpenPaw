"""Hot-reload scheduler integration for cron manager."""

import logging
from typing import Any

from openpaw.runtime.scheduling.loader import CronLoader

logger = logging.getLogger(__name__)


class SchedulerBridge:
    """Connects cron file changes to the live scheduler for hot-reload."""

    def __init__(self) -> None:
        """Initialize with no scheduler reference."""
        self.scheduler: Any = None

    def set_scheduler(self, scheduler: Any) -> None:
        """Connect a live CronScheduler for immediate hot-reload on changes.

        Called by lifecycle.py after the scheduler has started. Without a
        scheduler reference, file changes are still persisted to disk and
        will take effect on the next workspace restart.

        Args:
            scheduler: CronScheduler instance.
        """
        self.scheduler = scheduler
        logger.info("CronManager connected to live scheduler")

    def reload(self, name: str, workspace_root: Any) -> None:
        """Hot-reload a YAML cron into the live scheduler if one is available."""
        if not self.scheduler:
            logger.debug(
                "No live scheduler available — cron change will take effect on next restart"
            )
            return

        try:
            loader = CronLoader(workspace_root)
            cron_def = loader.load_one(name)
            self.scheduler.reload_cron(cron_def)
            logger.info(f"Hot-reloaded cron job '{name}' in live scheduler")
        except Exception as e:
            logger.warning(f"Failed to hot-reload cron '{name}' in scheduler: {e}")

    def remove(self, name: str) -> None:
        """Remove a cron job from the live scheduler if one is available."""
        if not self.scheduler:
            logger.debug(
                "No live scheduler available — removal will take effect on next restart"
            )
            return

        try:
            self.scheduler.remove_cron(name)
            logger.info(f"Removed cron job '{name}' from live scheduler")
        except Exception as e:
            logger.debug(f"Cron '{name}' was not in live scheduler: {e}")


__all__ = ["SchedulerBridge"]
