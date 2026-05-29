"""Scheduler bridge for live cron task updates."""

import logging
from typing import Any

logger = logging.getLogger(__name__)


def set_scheduler(builtin: Any, scheduler: Any) -> None:
    """Set the scheduler reference for live task updates.

    Called after CronScheduler is initialized to enable live scheduling.

    Args:
        builtin: The CronToolBuiltin instance.
        scheduler: CronScheduler instance.
    """
    builtin.scheduler = scheduler
    logger.info(
        f"CronTool connected to live scheduler for workspace: {builtin.workspace_path.name}"
    )


def _add_to_live_scheduler(scheduler: Any, task: Any) -> None:
    """Add a task to the live scheduler if available.

    Args:
        scheduler: The live scheduler instance.
        task: DynamicCronTask to schedule.
    """
    if scheduler:
        try:
            # Use the scheduler's internal method to schedule without re-persisting
            scheduler._schedule_dynamic_task(task)
            logger.info(f"Added task {task.id} to live scheduler")
        except Exception as e:
            logger.warning(f"Failed to add task to live scheduler: {e}")
    else:
        logger.debug(
            "No scheduler reference available. "
            "Task will be loaded on next scheduler restart."
        )


def _remove_from_live_scheduler(scheduler: Any, task_id: str) -> None:
    """Remove a task from the live scheduler if available.

    Args:
        scheduler: The live scheduler instance.
        task_id: ID of task to remove.
    """
    if scheduler:
        try:
            job_id = f"dynamic_{task_id}"
            if hasattr(scheduler, "_scheduler") and scheduler._scheduler:
                scheduler._scheduler.remove_job(job_id)
                logger.info(f"Removed task {task_id} from live scheduler")
        except Exception as e:
            logger.debug(f"Task {task_id} not in live scheduler: {e}")
