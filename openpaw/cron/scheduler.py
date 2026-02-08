"""APScheduler-based cron execution for OpenPaw."""

import logging
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from openpaw.channels.base import ChannelAdapter
from openpaw.core.metrics import TokenUsageLogger
from openpaw.cron.dynamic import DynamicCronStore, DynamicCronTask
from openpaw.cron.loader import CronDefinition, CronLoader

logger = logging.getLogger(__name__)


class CronScheduler:
    """Manages scheduled agent executions using APScheduler.

    Cron jobs:
    - Run with fresh agent context (no checkpointer)
    - Inject the cron prompt as user message
    - Route response to configured channel/chat
    """

    def __init__(
        self,
        workspace_path: Path,
        agent_factory: Callable[[], Any],
        channels: Mapping[str, ChannelAdapter],
        token_logger: TokenUsageLogger | None = None,
        workspace_name: str = "unknown",
        timezone: str = "UTC",
    ):
        """Initialize the cron scheduler.

        Args:
            workspace_path: Path to the agent workspace.
            agent_factory: Factory function to create fresh agent instances.
            channels: Dictionary mapping channel types to channel instances for routing.
            token_logger: Optional token usage logger for tracking cron invocations.
            workspace_name: Name of the workspace (for logging and token tracking).
            timezone: IANA timezone string for cron schedules (e.g., "America/New_York").
        """
        self.workspace_path = Path(workspace_path)
        self.agent_factory = agent_factory
        self.channels = channels
        self._token_logger = token_logger
        self._workspace_name = workspace_name
        self._timezone = timezone
        self._tz = ZoneInfo(timezone)
        self._scheduler: AsyncIOScheduler | None = None
        self._jobs: dict[str, Any] = {}
        self._dynamic_store = DynamicCronStore(workspace_path)
        self._dynamic_jobs: dict[str, Any] = {}

    async def start(self) -> None:
        """Start the scheduler and register all cron jobs."""
        self._scheduler = AsyncIOScheduler(timezone=self._tz)

        # Load and schedule YAML-defined cron jobs
        loader = CronLoader(self.workspace_path)
        cron_definitions = loader.load_all()

        for cron in cron_definitions:
            if cron.enabled:
                self.add_job(cron)
                logger.info(f"Registered cron job: {cron.name} ({cron.schedule})")

        # Load and schedule dynamic cron tasks (prune expired first)
        dynamic_tasks = self._dynamic_store.load()
        dynamic_tasks = self._prune_expired_tasks(dynamic_tasks)
        for task in dynamic_tasks:
            self._schedule_dynamic_task(task)
            logger.info(f"Loaded dynamic task: {task.id} ({task.task_type})")

        self._scheduler.start()
        logger.info("Cron scheduler started")

    async def stop(self) -> None:
        """Stop the scheduler gracefully."""
        if self._scheduler and self._scheduler.running:
            self._scheduler.shutdown(wait=True)
            logger.info("Cron scheduler stopped")

    async def _execute_cron(self, cron: CronDefinition) -> None:
        """Execute a cron job.

        Args:
            cron: The cron definition to execute.
        """
        logger.info(f"Executing cron job: {cron.name}")

        try:
            agent_runner = self.agent_factory()

            response = await agent_runner.run(message=cron.prompt)

            # Log token usage for cron invocation
            if self._token_logger and self._workspace_name and agent_runner.last_metrics:
                self._token_logger.log(
                    metrics=agent_runner.last_metrics,
                    workspace=self._workspace_name,
                    invocation_type="cron",
                    session_key=None,
                )

            channel = self.channels.get(cron.output.channel)
            if not channel:
                logger.error(f"Channel not found for cron {cron.name}: {cron.output.channel}")
                return

            if cron.output.channel == "telegram" and cron.output.chat_id:
                session_key = channel.build_session_key(cron.output.chat_id)
                await channel.send_message(
                    session_key=session_key,
                    content=response,
                )
            else:
                logger.warning(f"Unsupported output config for cron {cron.name}: {cron.output}")

            logger.info(f"Cron job {cron.name} completed successfully")

        except Exception as e:
            logger.error(f"Failed to execute cron job {cron.name}: {e}", exc_info=True)

    def add_job(self, cron: CronDefinition) -> None:
        """Add a cron job to the scheduler.

        Args:
            cron: The cron definition to schedule.
        """
        if not self._scheduler:
            raise RuntimeError("Scheduler not initialized. Call start() first.")

        trigger = CronTrigger.from_crontab(cron.schedule, timezone=self._tz)

        job = self._scheduler.add_job(
            func=self._execute_cron,
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

    def add_dynamic_job(self, task: DynamicCronTask) -> None:
        """Add a dynamic task to the scheduler.

        Args:
            task: DynamicCronTask to schedule.
        """
        if not self._scheduler:
            raise RuntimeError("Scheduler not initialized. Call start() first.")

        if task.task_type == "once":
            # Use DateTrigger for one-shot execution
            trigger = DateTrigger(run_date=task.run_at)
        else:
            # Use IntervalTrigger for recurring execution
            trigger = IntervalTrigger(seconds=task.interval_seconds)

        job = self._scheduler.add_job(
            func=self._execute_dynamic_task,
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

        Args:
            task_id: Unique task ID to remove.

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

    async def _execute_dynamic_task(self, task: DynamicCronTask) -> None:
        """Execute a dynamic task.

        For one-shot tasks: remove after execution.
        For interval tasks: continue recurring.

        Args:
            task: DynamicCronTask to execute.
        """
        logger.info(f"Executing dynamic task: {task.id}")

        try:
            agent_runner = self.agent_factory()
            response = await agent_runner.run(message=task.prompt)

            # Log token usage for dynamic cron invocation
            if self._token_logger and self._workspace_name and agent_runner.last_metrics:
                self._token_logger.log(
                    metrics=agent_runner.last_metrics,
                    workspace=self._workspace_name,
                    invocation_type="cron",
                    session_key=None,
                )

            # Route response using task's stored routing info
            if task.channel and task.chat_id:
                channel = self.channels.get(task.channel)
                if channel:
                    # Guard against empty responses
                    if response and response.strip():
                        session_key = channel.build_session_key(task.chat_id)
                        await channel.send_message(
                            session_key=session_key,
                            content=response,
                        )
                        logger.info(f"Dynamic task {task.id} response sent to {task.channel}:{task.chat_id}")
                    else:
                        logger.warning(f"Dynamic task {task.id} produced empty response, not sending")
                else:
                    logger.warning(f"Channel '{task.channel}' not found for dynamic task {task.id}")
            else:
                logger.warning(
                    f"Dynamic task {task.id} has no routing config. "
                    f"Response ({len(response) if response else 0} chars) not sent."
                )

            # Clean up one-shot tasks after execution
            if task.task_type == "once":
                # Remove from storage (APScheduler auto-removes DateTrigger jobs)
                if task.id in self._dynamic_jobs:
                    del self._dynamic_jobs[task.id]
                self._dynamic_store.remove_task(task.id)

            logger.info(f"Dynamic task {task.id} completed successfully")

        except Exception as e:
            logger.error(f"Dynamic task {task.id} failed: {e}", exc_info=True)

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

    def _schedule_dynamic_task(self, task: DynamicCronTask) -> None:
        """Schedule a task that was loaded from storage.

        Internal helper that schedules without re-persisting to storage.

        Args:
            task: DynamicCronTask to schedule.
        """
        if not self._scheduler:
            raise RuntimeError("Scheduler not initialized. Call start() first.")

        if task.task_type == "once":
            # Use DateTrigger for one-shot execution
            trigger = DateTrigger(run_date=task.run_at)
        else:
            # Use IntervalTrigger for recurring execution
            trigger = IntervalTrigger(seconds=task.interval_seconds)

        job = self._scheduler.add_job(
            func=self._execute_dynamic_task,
            trigger=trigger,
            args=[task],
            id=f"dynamic_{task.id}",
            name=f"Dynamic: {task.prompt[:30]}...",
            replace_existing=True,
        )

        self._dynamic_jobs[task.id] = job
