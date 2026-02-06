"""Repository for metrics and error tracking operations."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from openpaw.db.models import AgentError, AgentMetric, Workspace
from openpaw.db.repositories.base import BaseRepository


class MetricsRepository(BaseRepository[AgentMetric]):
    """Repository for metrics and error tracking operations."""

    def __init__(self, session: AsyncSession):
        super().__init__(session, AgentMetric)

    async def get_or_create_metric(
        self,
        workspace_id: int,
        session_key: str,
    ) -> AgentMetric:
        """Get or create a metric entry for a session.

        Args:
            workspace_id: Workspace ID
            session_key: Session identifier

        Returns:
            Existing or newly created AgentMetric
        """
        stmt = select(AgentMetric).where(
            AgentMetric.workspace_id == workspace_id,
            AgentMetric.session_key == session_key,
        )
        result = await self.session.execute(stmt)
        metric = result.scalar_one_or_none()

        if not metric:
            metric = AgentMetric(
                workspace_id=workspace_id,
                session_key=session_key,
            )
            self.session.add(metric)
            await self.session.flush()
            await self.session.refresh(metric)

        return metric

    async def get_by_workspace(self, workspace_name: str) -> list[AgentMetric]:
        """Get all metrics for a workspace.

        Args:
            workspace_name: Name of the workspace

        Returns:
            List of AgentMetric instances
        """
        stmt = (
            select(AgentMetric)
            .join(Workspace)
            .where(Workspace.name == workspace_name)
            .options(selectinload(AgentMetric.workspace))
            .order_by(AgentMetric.last_activity.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def log_error(
        self,
        workspace_id: int,
        error_type: str,
        error_message: str,
        session_key: str | None = None,
        stack_trace: str | None = None,
    ) -> AgentError:
        """Log an agent error.

        Args:
            workspace_id: Workspace ID
            error_type: Type/class of error
            error_message: Error message
            session_key: Optional session identifier
            stack_trace: Optional stack trace

        Returns:
            Created AgentError instance
        """
        error = AgentError(
            workspace_id=workspace_id,
            session_key=session_key,
            error_type=error_type,
            error_message=error_message,
            stack_trace=stack_trace,
        )
        self.session.add(error)
        await self.session.flush()
        await self.session.refresh(error)
        return error

    async def get_recent_errors(
        self,
        workspace_name: str | None = None,
        limit: int = 50,
    ) -> list[AgentError]:
        """Get recent errors, optionally filtered by workspace.

        Args:
            workspace_name: Optional workspace name to filter by
            limit: Maximum number of errors to return

        Returns:
            List of recent AgentError instances
        """
        stmt = (
            select(AgentError)
            .options(selectinload(AgentError.workspace))
            .order_by(AgentError.created_at.desc())
            .limit(limit)
        )

        if workspace_name:
            stmt = stmt.join(Workspace).where(Workspace.name == workspace_name)

        result = await self.session.execute(stmt)
        return list(result.scalars().all())
