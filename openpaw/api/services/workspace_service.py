"""Business logic for workspace management."""

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sqlalchemy.ext.asyncio import AsyncSession

from openpaw.db.models import Workspace, WorkspaceConfig
from openpaw.db.repositories.workspace_repo import WorkspaceRepository

if TYPE_CHECKING:
    from openpaw.api.schemas.workspaces import (
        WorkspaceCreate,
        WorkspaceResponse,
        WorkspaceUpdate,
    )
    from openpaw.orchestrator import OpenPawOrchestrator

logger = logging.getLogger(__name__)


class WorkspaceService:
    """Business logic for workspace management."""

    EDITABLE_FILES = ["AGENT.md", "USER.md", "SOUL.md", "HEARTBEAT.md"]
    DEFAULT_TEMPLATES = {
        "AGENT.md": "# {name} Agent\n\nDescribe this agent's capabilities.\n",
        "USER.md": "# User Context\n\nDescribe the user this agent serves.\n",
        "SOUL.md": "# Soul\n\nYou are {name}.\n",
        "HEARTBEAT.md": "# Heartbeat\n\nCurrent state and session notes.\n",
    }

    def __init__(
        self,
        session: AsyncSession,
        workspaces_path: Path,
        orchestrator: "OpenPawOrchestrator | None" = None,
    ):
        self.repo = WorkspaceRepository(session)
        self.workspaces_path = workspaces_path
        self.orchestrator = orchestrator

    # =========================================================================
    # CRUD Operations
    # =========================================================================

    async def list_all(self) -> list["WorkspaceResponse"]:
        """List all workspaces with runtime status."""

        workspaces = await self.repo.list_all_with_relations()
        return [self._to_response(ws) for ws in workspaces]

    async def get_by_name(self, name: str) -> "WorkspaceResponse | None":
        """Get workspace by name with full configuration."""

        workspace = await self.repo.get_by_name(name)
        if not workspace:
            return None
        return self._to_response(workspace)

    async def create(self, data: "WorkspaceCreate") -> "WorkspaceResponse":
        """Create new workspace with filesystem scaffold."""
        # Validate name doesn't exist
        existing = await self.repo.get_by_name(data.name)
        if existing:
            raise ValueError(f"Workspace '{data.name}' already exists")

        # Create filesystem structure
        workspace_path = self.workspaces_path / data.name
        self._scaffold_workspace(workspace_path, data.name)

        # Create database record
        workspace = Workspace(
            name=data.name,
            description=data.description,
            enabled=True,
            path=str(workspace_path),
        )
        await self.repo.create(workspace)

        # Re-fetch with relationships loaded
        workspace = await self.repo.get_by_name(data.name)
        if not workspace:
            raise RuntimeError(f"Failed to fetch workspace '{data.name}' after creation")

        return self._to_response(workspace)

    async def update(
        self, name: str, data: "WorkspaceUpdate"
    ) -> "WorkspaceResponse | None":
        """Update workspace configuration."""
        workspace = await self.repo.get_by_name(name)
        if not workspace:
            return None

        # Update basic fields
        if data.description is not None:
            workspace.description = data.description
        if data.enabled is not None:
            workspace.enabled = data.enabled

        # Update model config if provided (field is model_config_update with alias model_config)
        if data.model_config_update:
            # Convert Pydantic model to dict for processing
            model_dict = (
                data.model_config_update.model_dump(exclude_unset=True)
                if hasattr(data.model_config_update, "model_dump")
                else data.model_config_update
            )
            workspace.config = self._update_model_config(
                workspace.config, workspace.id, model_dict
            )

        # Update queue config if provided
        if data.queue_config:
            # Convert Pydantic model to dict for processing
            queue_dict = (
                data.queue_config.model_dump(exclude_unset=True)
                if hasattr(data.queue_config, "model_dump")
                else data.queue_config
            )
            workspace.config = self._update_queue_config(
                workspace.config, workspace.id, queue_dict
            )

        await self.repo.update(workspace)

        # Re-fetch with all relationships loaded
        workspace = await self.repo.get_by_name(name)
        if not workspace:
            raise RuntimeError(f"Failed to fetch workspace '{name}' after update")

        # Trigger hot reload if running
        if self.orchestrator and name in self.orchestrator.runners:
            await self._notify_config_change(name)

        return self._to_response(workspace)

    async def delete(self, name: str, delete_files: bool = False) -> bool:
        """Delete workspace from database, optionally remove files."""
        workspace = await self.repo.get_by_name(name)
        if not workspace:
            return False

        # Stop runner if active
        if self.orchestrator and name in self.orchestrator.runners:
            await self.orchestrator.stop_workspace(name)

        # Delete database record (cascade deletes related records)
        await self.repo.delete(workspace)

        # Optionally delete filesystem
        if delete_files:
            workspace_path = Path(workspace.path)
            if workspace_path.exists():
                import shutil

                shutil.rmtree(workspace_path)

        return True

    # =========================================================================
    # Runtime Control
    # =========================================================================

    async def start(self, name: str) -> None:
        """Start workspace runner."""
        if not self.orchestrator:
            raise RuntimeError("Orchestrator not available")

        workspace = await self.repo.get_by_name(name)
        if not workspace:
            raise ValueError(f"Workspace '{name}' not found")

        if name in self.orchestrator.runners:
            raise ValueError(f"Workspace '{name}' is already running")

        await self.orchestrator.start_workspace(name)

    async def stop(self, name: str) -> None:
        """Stop workspace runner."""
        if not self.orchestrator:
            raise RuntimeError("Orchestrator not available")

        await self.orchestrator.stop_workspace(name)

    async def restart(self, name: str) -> None:
        """Restart workspace runner."""
        await self.stop(name)
        await self.start(name)

    # =========================================================================
    # File Operations
    # =========================================================================

    async def list_files(self, name: str) -> list[str]:
        """List editable files in workspace."""
        workspace = await self.repo.get_by_name(name)
        if not workspace:
            return []

        workspace_path = Path(workspace.path)
        return [f for f in self.EDITABLE_FILES if (workspace_path / f).exists()]

    async def read_file(self, name: str, filename: str) -> str | None:
        """Read workspace file content."""
        if filename not in self.EDITABLE_FILES:
            raise ValueError(f"Cannot read '{filename}'")

        workspace = await self.repo.get_by_name(name)
        if not workspace:
            return None

        file_path = Path(workspace.path) / filename
        if not file_path.exists():
            return None

        return file_path.read_text(encoding="utf-8")

    async def write_file(self, name: str, filename: str, content: str) -> bool:
        """Write content to workspace file."""
        if filename not in self.EDITABLE_FILES:
            raise ValueError(f"Cannot write '{filename}'")

        workspace = await self.repo.get_by_name(name)
        if not workspace:
            return False

        file_path = Path(workspace.path) / filename
        file_path.write_text(content, encoding="utf-8")

        # Notify runner of file change
        if self.orchestrator and name in self.orchestrator.runners:
            await self._notify_file_change(name, filename)

        return True

    # =========================================================================
    # Private Helpers
    # =========================================================================

    def _scaffold_workspace(self, path: Path, name: str) -> None:
        """Create workspace directory structure with default files."""
        path.mkdir(parents=True, exist_ok=True)
        (path / "skills").mkdir(exist_ok=True)
        (path / "crons").mkdir(exist_ok=True)

        for filename, template in self.DEFAULT_TEMPLATES.items():
            file_path = path / filename
            if not file_path.exists():
                file_path.write_text(template.format(name=name), encoding="utf-8")

    def _to_response(self, workspace: Workspace) -> "WorkspaceResponse":
        """Convert database model to response schema."""
        from openpaw.api.schemas.workspaces import (
            ChannelResponse,
            CronSummary,
            WorkspaceConfigResponse,
            WorkspaceResponse,
        )

        status = "stopped"
        if self.orchestrator and workspace.name in self.orchestrator.runners:
            runner = self.orchestrator.runners[workspace.name]
            status = "running" if runner._running else "stopped"

        # Convert config SQLAlchemy model to Pydantic schema
        config_response = None
        if workspace.config:
            config_response = WorkspaceConfigResponse(
                model_provider=workspace.config.model_provider,
                model_name=workspace.config.model_name,
                temperature=workspace.config.temperature,
                max_turns=workspace.config.max_turns,
                queue_mode=workspace.config.queue_mode,
                debounce_ms=workspace.config.debounce_ms,
            )

        # Convert channel binding to response schema
        channel_response = None
        if workspace.channel_binding:
            channel_response = ChannelResponse(
                type=workspace.channel_binding.channel_type,
                enabled=workspace.channel_binding.enabled,
                allowed_users=workspace.channel_binding.allowed_users or [],
                allowed_groups=workspace.channel_binding.allowed_groups or [],
                allow_all=workspace.channel_binding.allow_all,
            )

        # Convert cron jobs to summaries
        cron_summaries = [
            CronSummary(name=cron.name, schedule=cron.schedule, enabled=cron.enabled)
            for cron in (workspace.cron_jobs or [])
        ]

        return WorkspaceResponse(
            name=workspace.name,
            description=workspace.description,
            enabled=workspace.enabled,
            path=workspace.path,
            status=status,
            config=config_response,
            channel=channel_response,
            cron_jobs=cron_summaries,
            created_at=workspace.created_at,
            updated_at=workspace.updated_at,
        )

    def _update_model_config(
        self,
        existing: WorkspaceConfig | None,
        workspace_id: int,
        data: dict[str, Any],
    ) -> WorkspaceConfig:
        """Update or create model configuration."""
        if existing is None:
            existing = WorkspaceConfig(workspace_id=workspace_id)

        for key in ["model_provider", "model_name", "temperature", "max_turns", "region"]:
            if key in data:
                setattr(existing, key, data[key])

        return existing

    def _update_queue_config(
        self,
        existing: WorkspaceConfig | None,
        workspace_id: int,
        data: dict[str, Any],
    ) -> WorkspaceConfig:
        """Update or create queue configuration."""
        if existing is None:
            existing = WorkspaceConfig(workspace_id=workspace_id)

        for key in ["queue_mode", "debounce_ms"]:
            if key in data:
                setattr(existing, key, data[key])

        return existing

    async def _notify_config_change(self, name: str) -> None:
        """Notify running workspace of configuration change."""
        logger.info(f"Config change for '{name}', triggering hot reload")
        if self.orchestrator:
            await self.orchestrator.reload_workspace_config(name)

    async def _notify_file_change(self, name: str, filename: str) -> None:
        """Notify running workspace of file change."""
        logger.info(f"File change: {name}/{filename}")
        if self.orchestrator:
            await self.orchestrator.reload_workspace_prompt(name)
