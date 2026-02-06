"""Repository for workspace operations."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from openpaw.db.models import Workspace
from openpaw.db.repositories.base import BaseRepository


class WorkspaceRepository(BaseRepository[Workspace]):
    """Repository for workspace operations."""

    def __init__(self, session: AsyncSession):
        super().__init__(session, Workspace)

    async def get_by_name(self, name: str) -> Workspace | None:
        """Get workspace by name with related entities."""
        stmt = (
            select(Workspace)
            .where(Workspace.name == name)
            .options(
                selectinload(Workspace.config),
                selectinload(Workspace.channel_binding),
                selectinload(Workspace.cron_jobs),
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_all_with_relations(self) -> list[Workspace]:
        """List all workspaces with configuration loaded."""
        stmt = (
            select(Workspace)
            .options(
                selectinload(Workspace.config),
                selectinload(Workspace.channel_binding),
                selectinload(Workspace.cron_jobs),
            )
            .order_by(Workspace.name)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def delete_by_name(self, name: str) -> bool:
        """Delete workspace by name."""
        workspace = await self.get_by_name(name)
        if workspace:
            await self.delete(workspace)
            return True
        return False
