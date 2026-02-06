"""Repository for cron job operations."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from openpaw.db.models import CronJob, Workspace
from openpaw.db.repositories.base import BaseRepository


class CronRepository(BaseRepository[CronJob]):
    """Repository for cron job operations."""

    def __init__(self, session: AsyncSession):
        super().__init__(session, CronJob)

    async def get_by_workspace_and_name(
        self,
        workspace_name: str,
        cron_name: str,
    ) -> CronJob | None:
        """Get cron job by workspace name and cron name.

        Args:
            workspace_name: Name of the workspace
            cron_name: Name of the cron job

        Returns:
            CronJob or None if not found
        """
        stmt = (
            select(CronJob)
            .join(Workspace)
            .where(
                Workspace.name == workspace_name,
                CronJob.name == cron_name,
            )
            .options(selectinload(CronJob.workspace))
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_workspace(self, workspace_name: str) -> list[CronJob]:
        """List all cron jobs for a workspace.

        Args:
            workspace_name: Name of the workspace

        Returns:
            List of CronJob instances
        """
        stmt = (
            select(CronJob)
            .join(Workspace)
            .where(Workspace.name == workspace_name)
            .options(selectinload(CronJob.workspace))
            .order_by(CronJob.name)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_all(self) -> list[CronJob]:
        """List all cron jobs with workspace relationship loaded.

        Returns:
            List of all CronJob instances with workspace loaded
        """
        stmt = (
            select(CronJob)
            .options(selectinload(CronJob.workspace))
            .order_by(CronJob.workspace_id, CronJob.name)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
