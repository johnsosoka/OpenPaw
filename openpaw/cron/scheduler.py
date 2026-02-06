"""APScheduler-based cron execution for OpenPaw."""

import logging
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from openpaw.channels.base import ChannelAdapter
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
    ):
        """Initialize the cron scheduler.

        Args:
            workspace_path: Path to the agent workspace.
            agent_factory: Factory function to create fresh agent instances.
            channels: Dictionary mapping channel types to channel instances for routing.
        """
        self.workspace_path = Path(workspace_path)
        self.agent_factory = agent_factory
        self.channels = channels
        self._scheduler: AsyncIOScheduler | None = None
        self._jobs: dict[str, Any] = {}

    async def start(self) -> None:
        """Start the scheduler and register all cron jobs."""
        self._scheduler = AsyncIOScheduler()

        loader = CronLoader(self.workspace_path)
        cron_definitions = loader.load_all()

        for cron in cron_definitions:
            if cron.enabled:
                self.add_job(cron)
                logger.info(f"Registered cron job: {cron.name} ({cron.schedule})")

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

        trigger = CronTrigger.from_crontab(cron.schedule)

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
