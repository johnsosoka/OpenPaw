"""APScheduler-based cron execution for OpenPaw."""

import logging
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger  # noqa: F401
from apscheduler.triggers.date import DateTrigger  # noqa: F401
from apscheduler.triggers.interval import IntervalTrigger  # noqa: F401

from openpaw.agent.metrics import TokenUsageLogger
from openpaw.agent.session_logger import SessionLogger
from openpaw.channels.base import ChannelAdapter
from openpaw.core.config.models import CronDefinition, CronOutputConfig
from openpaw.model.cron import DynamicCronTask
from openpaw.runtime.scheduling.cron_executor import CronExecutor
from openpaw.runtime.scheduling.cron_job_manager import CronJobManager
from openpaw.runtime.scheduling.loader import CronLoader
from openpaw.stores.cron import DynamicCronStore

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
        agent_factory: Callable[..., Any],
        channels: Mapping[str, ChannelAdapter],
        token_logger: TokenUsageLogger | None = None,
        workspace_name: str = "unknown",
        timezone: str = "UTC",
        result_callback: Callable[[str, str], Awaitable[None]] | None = None,
        session_logger: SessionLogger | None = None,
    ):
        """Initialize the cron scheduler."""
        self.workspace_path = Path(workspace_path)
        self.agent_factory = agent_factory
        self.channels = channels
        self._token_logger = token_logger
        self._workspace_name = workspace_name
        self._timezone = timezone
        self._tz = ZoneInfo(timezone)
        self._result_callback = result_callback
        self._session_logger = session_logger
        self._scheduler: AsyncIOScheduler | None = None
        self._job_manager: CronJobManager | None = None
        self._jobs: dict[str, Any] = {}
        self._dynamic_store = DynamicCronStore(workspace_path)
        self._dynamic_jobs: dict[str, Any] = {}
        self._executor = CronExecutor(
            workspace_path=self.workspace_path,
            agent_factory=self.agent_factory,
            channels=self.channels,
            workspace_name=self._workspace_name,
            token_logger=self._token_logger,
            session_logger=self._session_logger,
            result_callback=self._result_callback,
            dynamic_store=self._dynamic_store,
            dynamic_jobs=self._dynamic_jobs,
        )

    def _ensure_job_manager(self) -> CronJobManager:
        if self._job_manager is None:
            self._job_manager = CronJobManager(
                scheduler=self._scheduler,
                tz=self._tz,
                dynamic_store=self._dynamic_store,
                executor=self._executor,
                jobs=self._jobs,
                dynamic_jobs=self._dynamic_jobs,
            )
        return self._job_manager

    async def start(self) -> None:
        """Start the scheduler and register all cron jobs."""
        self._scheduler = AsyncIOScheduler(
            timezone=self._tz,
            job_defaults={
                "max_instances": 1,
                "coalesce": True,
                "misfire_grace_time": 300,
            },
        )
        self._ensure_job_manager()

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

    def _log_cron_event(
        self,
        cron_name: str,
        outcome: str,
        duration_ms: float | None = None,
        error: str | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        total_tokens: int | None = None,
        llm_calls: int | None = None,
        session_path: str | None = None,
        delivery: str | None = None,
        tools_used: list[str] | None = None,
    ) -> None:
        """Append cron execution event to workspace JSONL log."""
        self._executor.log_cron_event(
            cron_name=cron_name,
            outcome=outcome,
            duration_ms=duration_ms,
            error=error,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            llm_calls=llm_calls,
            session_path=session_path,
            delivery=delivery,
            tools_used=tools_used,
        )

    async def _execute_cron(self, cron: CronDefinition) -> None:
        """Execute a cron job."""
        await self._executor.execute_cron(cron)

    @staticmethod
    def _resolve_session_key(channel: ChannelAdapter, output: CronOutputConfig) -> str | None:
        """Resolve session key from cron output config."""
        return CronExecutor._resolve_session_key(channel, output)

    def add_job(self, cron: CronDefinition) -> None:
        """Add a cron job to the scheduler."""
        self._ensure_job_manager().add_job(cron)

    def remove_job(self, name: str) -> None:
        """Remove a cron job by name."""
        self._ensure_job_manager().remove_job(name)

    def reload_cron(self, cron_def: CronDefinition) -> None:
        """Remove the old job (if present) and re-add it from the updated definition."""
        self._ensure_job_manager().reload_cron(cron_def)

    def remove_cron(self, name: str) -> None:
        """Remove a YAML-defined cron job from the live scheduler."""
        self._ensure_job_manager().remove_cron(name)

    def add_dynamic_job(self, task: DynamicCronTask) -> None:
        """Add a dynamic task to the scheduler."""
        self._ensure_job_manager().add_dynamic_job(task)

    def remove_dynamic_job(self, task_id: str) -> bool:
        """Remove a dynamic task from the scheduler."""
        return self._ensure_job_manager().remove_dynamic_job(task_id)

    async def _execute_dynamic_task(self, task: DynamicCronTask) -> None:
        """Execute a dynamic task."""
        await self._executor.execute_dynamic_task(task)

    def _prune_expired_tasks(self, tasks: list[DynamicCronTask]) -> list[DynamicCronTask]:
        """Remove expired one-time tasks that will never execute."""
        return self._ensure_job_manager()._prune_expired_tasks(tasks)

    def _schedule_dynamic_task(self, task: DynamicCronTask) -> None:
        """Schedule a task that was loaded from storage."""
        self._ensure_job_manager()._schedule_dynamic_task(task)
