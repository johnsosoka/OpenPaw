"""Business logic for cron job management."""

from datetime import datetime
from typing import Any

from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from openpaw.db.models import CronExecution, CronJob, Workspace
from openpaw.db.repositories.cron_repo import CronRepository


class CronService:
    """Business logic for cron job management.

    Manages cron job lifecycle, scheduling, and execution history.
    Integrates with CronRepository and optionally the orchestrator for runtime control.
    """

    def __init__(
        self,
        session: AsyncSession,
        orchestrator: Any | None = None,
    ):
        self.session = session
        self.orchestrator = orchestrator
        self.repo = CronRepository(session)

    # =========================================================================
    # Cron Job Listing
    # =========================================================================

    async def list_all(
        self, workspace: str | None = None, enabled: bool | None = None
    ) -> list[dict[str, Any]]:
        """List all cron jobs with optional filters.

        Args:
            workspace: Filter by workspace name (optional)
            enabled: Filter by enabled status (optional)

        Returns:
            List of cron job dictionaries with metadata.
        """
        if workspace:
            cron_jobs = await self.repo.list_by_workspace(workspace)
        else:
            cron_jobs = await self.repo.list_all()

        # Apply enabled filter if provided
        if enabled is not None:
            cron_jobs = [c for c in cron_jobs if c.enabled == enabled]

        result = []
        for cron in cron_jobs:
            result.append(await self._cron_to_dict(cron))

        return result

    async def get(self, workspace: str, name: str) -> dict[str, Any] | None:
        """Get single cron job by workspace and name.

        Args:
            workspace: Workspace name
            name: Cron job name

        Returns:
            Cron job dictionary or None if not found.
        """
        cron = await self.repo.get_by_workspace_and_name(workspace, name)
        if not cron:
            return None

        return await self._cron_to_dict(cron)

    # =========================================================================
    # Cron Job Creation
    # =========================================================================

    async def create(
        self,
        workspace: str,
        name: str,
        schedule: str,
        prompt: str,
        output: dict[str, Any],
        enabled: bool = True,
    ) -> dict[str, Any]:
        """Create a new cron job.

        Args:
            workspace: Workspace name
            name: Cron job name (unique per workspace)
            schedule: Cron expression
            prompt: Prompt text to execute
            output: Output configuration dictionary
            enabled: Whether the cron job should be enabled

        Returns:
            Created cron job dictionary

        Raises:
            ValueError: If workspace not found or schedule is invalid
        """
        # Validate schedule
        try:
            CronTrigger.from_crontab(schedule)
        except (ValueError, TypeError) as e:
            raise ValueError(f"Invalid cron schedule: {e}")

        # Get workspace
        workspace_obj = await self._get_workspace(workspace)
        if not workspace_obj:
            raise ValueError(f"Workspace '{workspace}' not found")

        # Create cron job
        cron = CronJob(
            workspace_id=workspace_obj.id,
            name=name,
            schedule=schedule,
            prompt=prompt,
            output_config=output,
            enabled=enabled,
        )
        self.session.add(cron)
        await self.session.flush()
        await self.session.refresh(cron)

        # Load relationship
        await self.session.refresh(cron, ["workspace"])

        return await self._cron_to_dict(cron)

    # =========================================================================
    # Cron Job Updates
    # =========================================================================

    async def update(
        self,
        workspace: str,
        name: str,
        schedule: str | None = None,
        prompt: str | None = None,
        output: dict[str, Any] | None = None,
        enabled: bool | None = None,
    ) -> dict[str, Any] | None:
        """Update a cron job.

        Args:
            workspace: Workspace name
            name: Cron job name
            schedule: New cron expression (optional)
            prompt: New prompt text (optional)
            output: New output configuration (optional)
            enabled: New enabled status (optional)

        Returns:
            Updated cron job dictionary or None if not found

        Raises:
            ValueError: If schedule is invalid
        """
        cron = await self.repo.get_by_workspace_and_name(workspace, name)
        if not cron:
            return None

        # Validate schedule if provided
        if schedule is not None:
            try:
                CronTrigger.from_crontab(schedule)
            except (ValueError, TypeError) as e:
                raise ValueError(f"Invalid cron schedule: {e}")
            cron.schedule = schedule

        if prompt is not None:
            cron.prompt = prompt
        if output is not None:
            cron.output_config = output
        if enabled is not None:
            cron.enabled = enabled

        await self.session.flush()
        await self.session.refresh(cron)

        return await self._cron_to_dict(cron)

    async def delete(self, workspace: str, name: str) -> bool:
        """Delete a cron job.

        Args:
            workspace: Workspace name
            name: Cron job name

        Returns:
            True if deleted, False if not found
        """
        cron = await self.repo.get_by_workspace_and_name(workspace, name)
        if not cron:
            return False

        await self.session.delete(cron)
        await self.session.flush()
        return True

    # =========================================================================
    # Cron Job Execution
    # =========================================================================

    async def trigger(self, workspace: str, name: str) -> bool:
        """Manually trigger a cron job.

        Note: This is a stub for now. Full implementation requires
        orchestrator integration to actually execute the job.

        Args:
            workspace: Workspace name
            name: Cron job name

        Returns:
            True if cron exists (and trigger was queued), False if not found
        """
        cron = await self.repo.get_by_workspace_and_name(workspace, name)
        if not cron:
            return False

        # TODO: Integrate with orchestrator to actually execute the job
        # For now, just verify the cron exists
        return True

    # =========================================================================
    # Execution History
    # =========================================================================

    async def get_executions(
        self, workspace: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Get recent cron execution history.

        Args:
            workspace: Filter by workspace name (optional)
            limit: Maximum number of executions to return

        Returns:
            List of execution dictionaries
        """
        stmt = (
            select(CronExecution)
            .join(CronJob)
            .join(Workspace)
            .options(
                selectinload(CronExecution.cron_job).selectinload(CronJob.workspace)
            )
            .order_by(CronExecution.started_at.desc())
            .limit(limit)
        )

        if workspace:
            stmt = stmt.where(Workspace.name == workspace)

        result = await self.session.execute(stmt)
        executions = result.scalars().all()

        return [
            {
                "id": exec.id,
                "workspace": exec.cron_job.workspace.name,
                "cron_name": exec.cron_job.name,
                "started_at": exec.started_at,
                "completed_at": exec.completed_at,
                "status": exec.status,
                "tokens_in": exec.tokens_in,
                "tokens_out": exec.tokens_out,
                "error_message": exec.error_message,
            }
            for exec in executions
        ]

    async def record_execution(
        self,
        cron_job_id: int,
        status: str,
        started_at: datetime,
        completed_at: datetime | None = None,
        tokens_in: int = 0,
        tokens_out: int = 0,
        error_message: str | None = None,
    ) -> None:
        """Record a cron execution for history tracking.

        This method is intended to be called by CronScheduler after job execution.

        Args:
            cron_job_id: Cron job ID
            status: Execution status (success, failed, timeout)
            started_at: Execution start time
            completed_at: Execution completion time (optional)
            tokens_in: Input token count
            tokens_out: Output token count
            error_message: Error message if status is failed (optional)
        """
        execution = CronExecution(
            cron_job_id=cron_job_id,
            started_at=started_at,
            completed_at=completed_at,
            status=status,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            error_message=error_message,
        )
        self.session.add(execution)
        await self.session.flush()

    # =========================================================================
    # Private Helpers
    # =========================================================================

    async def _get_workspace(self, name: str) -> Workspace | None:
        """Get workspace by name.

        Args:
            name: Workspace name

        Returns:
            Workspace or None if not found
        """
        stmt = select(Workspace).where(Workspace.name == name)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def _cron_to_dict(self, cron: CronJob) -> dict[str, Any]:
        """Convert CronJob model to dictionary.

        Args:
            cron: CronJob instance with workspace relationship loaded

        Returns:
            Dictionary with all cron job fields including next_run
        """
        next_run = None
        if cron.enabled:
            try:
                trigger = CronTrigger.from_crontab(cron.schedule)
                next_run = trigger.get_next_fire_time(None, datetime.utcnow())
            except (ValueError, TypeError):
                # Invalid schedule, leave next_run as None
                pass

        return {
            "id": cron.id,
            "workspace": cron.workspace.name,
            "name": cron.name,
            "schedule": cron.schedule,
            "enabled": cron.enabled,
            "prompt": cron.prompt,
            "output": cron.output_config,
            "created_at": cron.created_at,
            "updated_at": cron.updated_at,
            "next_run": next_run,
        }
