"""Cron job management for OpenPaw."""

import logging
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from openpaw.core.config.models import CronDefinition
from openpaw.model.cron import DynamicCronTask
from openpaw.stores.cron import DynamicCronStore

logger = logging.getLogger(__name__)


class CronJobManager:
    """Manages APScheduler jobs for cron and dynamic task scheduling."""

    def __init__(
        self,
        scheduler: AsyncIOScheduler | None,
        tz: ZoneInfo,
        dynamic_store: DynamicCronStore,
        executor: Any,
        jobs: dict[str, Any],
        dynamic_jobs: dict[str, Any],
    ):
        self._scheduler = scheduler
        self._tz = tz
        self._dynamic_store = dynamic_store
        self._executor = executor
        self._jobs = jobs
        self._dynamic_jobs = dynamic_jobs

    def add_job(self, cron: CronDefinition) -> None:
        """Add a cron job to the scheduler.

        Args:
            cron: The cron definition to schedule.
        """
        if not self._scheduler:
            raise RuntimeError("Scheduler not initialized. Call start() first.")

        from openpaw.runtime.scheduling.cron import CronTrigger  # type: ignore[attr-defined]
        trigger = CronTrigger.from_crontab(cron.schedule, timezone=self._tz)

        job = self._scheduler.add_job(
            func=self._executor.execute_cron,
            trigger=trigger,
            args=[cron],
            id=cron.name,
            name=cron.name,
            replace_existing=True,
        )

        self._jobs[cron.name] = job

    def remove_job(self, name: str) -> None:
        """Remove a cron job by name.

        Args:
            name: The cron job name to remove.
        """
        if not self._scheduler:
            raise RuntimeError("Scheduler not initialized. Call start() first.")

        if name in self._jobs:
            self._scheduler.remove_job(name)
            del self._jobs[name]
            logger.info(f"Removed cron job: {name}")

    def reload_cron(self, cron_def: CronDefinition) -> None:
        """Remove the old job (if present) and re-add it from the updated definition.

        Used by CronManagerBuiltin to apply in-place changes to YAML cron jobs
        without requiring a workspace restart.

        If the definition has ``enabled=False``, the job is removed and not
        re-added, effectively pausing it.

        Args:
            cron_def: Updated cron definition to register.
        """
        if cron_def.name in self._jobs:
            self.remove_job(cron_def.name)

        if cron_def.enabled:
            self.add_job(cron_def)
            logger.info(f"Reloaded cron job: {cron_def.name} ({cron_def.schedule})")
        else:
            logger.info(f"Cron job '{cron_def.name}' is disabled — skipped re-registration")

    def remove_cron(self, name: str) -> None:
        """Remove a YAML-defined cron job from the live scheduler.

        Public wrapper around :meth:`remove_job` for use by CronManagerBuiltin.
        Silently does nothing if the job is not currently registered (e.g., it
        was disabled and never added to the APScheduler instance) or if the
        scheduler has not been started yet.

        Args:
            name: The cron job name to remove.
        """
        if not self._scheduler or name not in self._jobs:
            return
        self.remove_job(name)

    def add_dynamic_job(self, task: DynamicCronTask) -> None:
        """Add a dynamic task to the scheduler.

        Args:
            task: DynamicCronTask to schedule.
        """
        if not self._scheduler:
            raise RuntimeError("Scheduler not initialized. Call start() first.")

        from openpaw.runtime.scheduling.cron import (  # type: ignore[attr-defined]
            DateTrigger,
            IntervalTrigger,
        )
        if task.task_type == "once":
            # Use DateTrigger for one-shot execution
            trigger = DateTrigger(run_date=task.run_at)
        else:
            # Use IntervalTrigger for recurring execution
            trigger = IntervalTrigger(seconds=task.interval_seconds)

        job = self._scheduler.add_job(
            func=self._executor.execute_dynamic_task,
            trigger=trigger,
            args=[task],
            id=f"dynamic_{task.id}",
            name=f"Dynamic: {task.prompt[:30]}...",
            replace_existing=True,
        )

        self._dynamic_jobs[task.id] = job
        self._dynamic_store.add_task(task)  # Persist to disk
        logger.info(f"Added dynamic task: {task.id} ({task.task_type})")

    def remove_dynamic_job(self, task_id: str) -> bool:
        """Remove a dynamic task from the scheduler.

        Note: This method expects a full UUID (used internally). For prefix-based
        cancellation, use the CronTool's cancel_scheduled which resolves prefixes
        via DynamicCronStore before calling _remove_from_live_scheduler.

        Args:
            task_id: Full UUID of the task to remove.

        Returns:
            True if removed, False if not found.
        """
        if not self._scheduler:
            raise RuntimeError("Scheduler not initialized. Call start() first.")

        job_id = f"dynamic_{task_id}"
        if task_id in self._dynamic_jobs:
            self._scheduler.remove_job(job_id)
            del self._dynamic_jobs[task_id]
            self._dynamic_store.remove_task(task_id)
            logger.info(f"Removed dynamic task: {task_id}")
            return True

        logger.warning(f"Dynamic task not found: {task_id}")
        return False

    def _schedule_dynamic_task(self, task: DynamicCronTask) -> None:
        """Schedule a task that was loaded from storage.

        Internal helper that schedules without re-persisting to storage.

        Args:
            task: DynamicCronTask to schedule.
        """
        if not self._scheduler:
            raise RuntimeError("Scheduler not initialized. Call start() first.")

        from openpaw.runtime.scheduling.cron import (  # type: ignore[attr-defined]
            DateTrigger,
            IntervalTrigger,
        )
        if task.task_type == "once":
            # Use DateTrigger for one-shot execution
            trigger = DateTrigger(run_date=task.run_at)
        else:
            # Use IntervalTrigger for recurring execution
            trigger = IntervalTrigger(seconds=task.interval_seconds)

        job = self._scheduler.add_job(
            func=self._executor.execute_dynamic_task,
            trigger=trigger,
            args=[task],
            id=f"dynamic_{task.id}",
            name=f"Dynamic: {task.prompt[:30]}...",
            replace_existing=True,
        )

        self._dynamic_jobs[task.id] = job

    def _prune_expired_tasks(self, tasks: list[DynamicCronTask]) -> list[DynamicCronTask]:
        """Remove expired one-time tasks that will never execute.

        Args:
            tasks: List of tasks to filter.

        Returns:
            List with expired one-time tasks removed.
        """
        now = datetime.now(UTC)
        valid_tasks = []
        pruned_count = 0

        for task in tasks:
            # One-time tasks with run_at in the past are expired
            if task.task_type == "once" and task.run_at:
                if task.run_at < now:
                    self._dynamic_store.remove_task(task.id)
                    pruned_count += 1
                    continue

            valid_tasks.append(task)

        if pruned_count > 0:
            logger.info(f"Pruned {pruned_count} expired one-time task(s)")

        return valid_tasks
