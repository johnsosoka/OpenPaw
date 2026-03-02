"""Orchestrator for managing multiple workspace runners."""

import asyncio
import logging
from pathlib import Path

from openpaw.core.config import Config
from openpaw.core.paths import AGENT_MD
from openpaw.workspace.runner import WorkspaceRunner

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

    @classmethod
    def discover_workspaces(cls, workspaces_path: Path) -> list[str]:
        """Discover all valid workspaces in the workspaces directory.

        A valid workspace is a directory containing the agent identity marker.
        Checks both the new structured layout (``agent/AGENT.md``) and the
        legacy flat layout (``AGENT.md`` at root). Legacy workspaces are
        auto-migrated at startup by ``WorkspaceRunner``.

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
            if not entry.is_dir():
                continue
            # New structured layout or legacy flat layout
            if (entry / str(AGENT_MD)).exists() or (entry / "AGENT.md").exists():
                workspaces.append(entry.name)
                logger.debug(f"Discovered workspace: {entry.name}")

        logger.info(f"Discovered {len(workspaces)} workspace(s)")
        return sorted(workspaces)
