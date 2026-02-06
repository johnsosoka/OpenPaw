"""Orchestrator for managing multiple workspace runners."""

import asyncio
import logging
from pathlib import Path

from openpaw.core.config import Config
from openpaw.main import WorkspaceRunner

logger = logging.getLogger(__name__)


class OpenPawOrchestrator:
    """Manages multiple WorkspaceRunner instances."""

    def __init__(self, config: Config, workspace_names: list[str]):
        """Initialize orchestrator with workspaces.

        Args:
            config: Global application configuration.
            workspace_names: List of workspace names to load.
        """
        self.config = config
        self.runners: dict[str, WorkspaceRunner] = {}

        for name in workspace_names:
            logger.info(f"Initializing workspace: {name}")
            self.runners[name] = WorkspaceRunner(config, name)

        logger.info(f"Orchestrator initialized with {len(self.runners)} workspace(s)")

    async def start(self) -> None:
        """Start all workspace runners concurrently.

        Raises:
            RuntimeError: If any workspace runner fails to start.
        """
        logger.info(f"Starting {len(self.runners)} workspace runner(s)...")

        results = await asyncio.gather(
            *[runner.start() for runner in self.runners.values()],
            return_exceptions=True,
        )

        failures: list[tuple[str, Exception]] = []
        for name, result in zip(self.runners.keys(), results):
            if isinstance(result, Exception):
                logger.error(f"Failed to start workspace '{name}': {result}")
                failures.append((name, result))

        if failures:
            failed_names = [name for name, _ in failures]
            raise RuntimeError(f"Failed to start {len(failures)} workspace(s): {failed_names}")

        logger.info("All workspace runners started successfully")

    async def stop(self) -> None:
        """Stop all workspace runners gracefully.

        Logs errors but does not raise - shutdown should complete for all runners.
        """
        logger.info("Stopping all workspace runners...")

        results = await asyncio.gather(
            *[runner.stop() for runner in self.runners.values()],
            return_exceptions=True,
        )

        for name, result in zip(self.runners.keys(), results):
            if isinstance(result, Exception):
                logger.error(f"Error stopping workspace '{name}': {result}")

        logger.info("All workspace runners stopped")

    async def start_workspace(self, name: str) -> None:
        """Start a single workspace runner.

        Args:
            name: Workspace name to start.

        Raises:
            ValueError: If workspace is already running.
        """
        if name in self.runners:
            raise ValueError(f"Workspace '{name}' is already running")

        logger.info(f"Starting workspace: {name}")
        runner = WorkspaceRunner(self.config, name)
        await runner.start()
        self.runners[name] = runner
        logger.info(f"Workspace '{name}' started successfully")

    async def stop_workspace(self, name: str) -> None:
        """Stop a single workspace runner.

        Args:
            name: Workspace name to stop.
        """
        if name not in self.runners:
            logger.warning(f"Workspace '{name}' is not running")
            return

        logger.info(f"Stopping workspace: {name}")
        runner = self.runners[name]
        await runner.stop()
        del self.runners[name]
        logger.info(f"Workspace '{name}' stopped successfully")

    async def restart_workspace(self, name: str) -> None:
        """Restart a single workspace runner.

        Args:
            name: Workspace name to restart.
        """
        logger.info(f"Restarting workspace: {name}")
        await self.stop_workspace(name)
        await self.start_workspace(name)
        logger.info(f"Workspace '{name}' restarted successfully")

    async def reload_workspace_config(self, name: str) -> None:
        """Reload workspace configuration.

        Currently implemented as a full restart since WorkspaceRunner
        does not support hot config reload.

        Args:
            name: Workspace name to reload config for.
        """
        if name not in self.runners:
            logger.warning(f"Workspace '{name}' is not running")
            return

        logger.info(f"Reloading config for workspace '{name}' (triggering restart)")
        await self.restart_workspace(name)

    async def reload_workspace_prompt(self, name: str) -> None:
        """Reload workspace prompt files.

        Workspace prompt files (AGENT.md, USER.md, SOUL.md, HEARTBEAT.md)
        are loaded dynamically at agent invocation time, so no action is
        needed beyond logging.

        Args:
            name: Workspace name to reload prompt for.
        """
        if name not in self.runners:
            logger.warning(f"Workspace '{name}' is not running")
            return

        logger.info(
            f"Workspace '{name}' will reload prompt files on next agent invocation"
        )

    async def trigger_cron(self, workspace: str, cron_name: str) -> None:
        """Trigger a cron job immediately.

        This is a stub for now - full implementation would queue the cron job.

        Args:
            workspace: Workspace name containing the cron.
            cron_name: Name of the cron job to trigger.
        """
        if workspace not in self.runners:
            logger.warning(f"Workspace '{workspace}' is not running")
            return

        logger.info(f"Triggering cron '{cron_name}' in workspace '{workspace}'")

    @classmethod
    def discover_workspaces(cls, workspaces_path: Path) -> list[str]:
        """Discover all valid workspaces in the workspaces directory.

        A valid workspace is a directory containing AGENT.md.

        Args:
            workspaces_path: Path to workspaces directory.

        Returns:
            List of workspace names found.
        """
        workspaces: list[str] = []

        if not workspaces_path.exists():
            logger.warning(f"Workspaces path does not exist: {workspaces_path}")
            return workspaces

        for entry in workspaces_path.iterdir():
            if entry.is_dir() and (entry / "AGENT.md").exists():
                workspaces.append(entry.name)
                logger.debug(f"Discovered workspace: {entry.name}")

        logger.info(f"Discovered {len(workspaces)} workspace(s)")
        return sorted(workspaces)
