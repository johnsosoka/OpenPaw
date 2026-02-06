"""Business logic for monitoring and metrics."""

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from openpaw.db.models import AgentError, AgentMetric, AgentState, Workspace

if TYPE_CHECKING:
    from openpaw.orchestrator import OpenPawOrchestrator


class MonitoringService:
    """Business logic for monitoring and metrics."""

    def __init__(
        self,
        session: AsyncSession,
        orchestrator: "OpenPawOrchestrator | None" = None,
    ):
        """Initialize MonitoringService.

        Args:
            session: Database session
            orchestrator: Optional orchestrator instance for runtime state
        """
        self.session = session
        self.orchestrator = orchestrator

    # =========================================================================
    # Health & Status
    # =========================================================================

    async def get_health(self) -> dict[str, Any]:
        """Get system health status.

        Returns:
            dict: Health status with database, orchestrator, and workspace stats
        """
        # Count workspaces
        stmt = select(func.count(Workspace.id))
        result = await self.session.execute(stmt)
        total_workspaces = result.scalar() or 0

        running = 0
        if self.orchestrator:
            running = sum(1 for r in self.orchestrator.runners.values() if r._running)

        return {
            "status": "healthy",
            "version": "0.1.0",
            "database": "connected",
            "orchestrator": "running" if self.orchestrator else "unavailable",
            "workspaces": {
                "total": total_workspaces,
                "running": running,
                "stopped": max(0, total_workspaces - running),
            },
        }

    async def get_workspace_states(self) -> list[dict[str, Any]]:
        """Get all workspace states.

        Returns:
            list: List of workspace state dictionaries
        """
        if not self.orchestrator:
            return []

        states = []
        for name, runner in self.orchestrator.runners.items():
            # Get status from runner
            status_dict = self._extract_runner_status(name, runner)
            states.append(status_dict)

        return states

    async def get_workspace_state(self, name: str) -> dict[str, Any] | None:
        """Get detailed workspace state.

        Args:
            name: Workspace name

        Returns:
            dict: Detailed workspace state or None if not found
        """
        if not self.orchestrator or name not in self.orchestrator.runners:
            return None

        runner = self.orchestrator.runners[name]

        # Get metrics from database for today
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

        stmt = (
            select(AgentMetric)
            .join(Workspace)
            .where(Workspace.name == name)
            .where(AgentMetric.created_at >= today_start)
        )
        result = await self.session.execute(stmt)
        metrics = list(result.scalars().all())

        # Get error count for today
        error_stmt = (
            select(func.count(AgentError.id))
            .join(Workspace)
            .where(Workspace.name == name)
            .where(AgentError.created_at >= today_start)
        )
        error_result = await self.session.execute(error_stmt)
        errors_today = error_result.scalar() or 0

        tokens_in = sum(m.tokens_in for m in metrics)
        tokens_out = sum(m.tokens_out for m in metrics)

        # Extract queue stats
        queue_stats = self._extract_queue_stats(runner)

        return {
            "name": name,
            "status": "running" if runner._running else "stopped",
            "state": self._extract_agent_state(runner),
            "channels": self._extract_channel_info(runner),
            "queue": queue_stats,
            "sessions": {
                "total": len(metrics),
                "active": sum(1 for m in metrics if m.state == AgentState.ACTIVE.value),
            },
            "tokens_today": {
                "input": tokens_in,
                "output": tokens_out,
            },
            "errors_today": errors_today,
        }

    async def get_workspace_sessions(self, name: str) -> list[dict[str, Any]] | None:
        """Get active sessions for a workspace.

        Args:
            name: Workspace name

        Returns:
            list: List of session dictionaries or None if workspace not found
        """
        if not self.orchestrator or name not in self.orchestrator.runners:
            return None

        # Get active sessions from database
        stmt = (
            select(AgentMetric)
            .join(Workspace)
            .where(Workspace.name == name)
            .where(AgentMetric.state == AgentState.ACTIVE.value)
        )
        result = await self.session.execute(stmt)
        metrics = list(result.scalars().all())

        sessions = []
        for metric in metrics:
            sessions.append({
                "session_key": metric.session_key,
                "state": metric.state,
                "started_at": metric.created_at,
                "messages_processed": metric.messages_processed,
                "tokens_used": {
                    "input": metric.tokens_in,
                    "output": metric.tokens_out,
                },
                "last_message": metric.last_activity or metric.created_at,
            })

        return sessions

    # =========================================================================
    # Metrics
    # =========================================================================

    async def update_metrics(
        self,
        workspace_name: str,
        session_key: str,
        state: AgentState | None = None,
        tokens_in: int = 0,
        tokens_out: int = 0,
        queue_depth: int | None = None,
    ) -> None:
        """Update or create session metrics.

        Args:
            workspace_name: Workspace name
            session_key: Session identifier
            state: Optional agent state
            tokens_in: Input tokens used
            tokens_out: Output tokens used
            queue_depth: Optional queue depth
        """
        # Get workspace
        workspace_stmt = select(Workspace).where(Workspace.name == workspace_name)
        workspace_result = await self.session.execute(workspace_stmt)
        workspace = workspace_result.scalar_one_or_none()
        if not workspace:
            return

        # Get or create metric
        metric_stmt = select(AgentMetric).where(
            AgentMetric.workspace_id == workspace.id,
            AgentMetric.session_key == session_key,
        )
        metric_result = await self.session.execute(metric_stmt)
        metric = metric_result.scalar_one_or_none()

        if not metric:
            metric = AgentMetric(
                workspace_id=workspace.id,
                session_key=session_key,
            )
            self.session.add(metric)

        if state:
            metric.state = state.value
        metric.tokens_in += tokens_in
        metric.tokens_out += tokens_out
        metric.messages_processed += 1 if tokens_in > 0 else 0
        metric.last_activity = datetime.utcnow()
        if queue_depth is not None:
            metric.queue_depth = queue_depth

        await self.session.flush()

    async def get_aggregated_metrics(
        self,
        period: str = "day",
        workspace: str | None = None,
    ) -> dict[str, Any]:
        """Get aggregated metrics for a period.

        Args:
            period: Time period ("hour", "day", "week")
            workspace: Optional workspace filter

        Returns:
            dict: Aggregated metrics for the period
        """
        delta = {
            "hour": timedelta(hours=1),
            "day": timedelta(days=1),
            "week": timedelta(weeks=1),
        }.get(period, timedelta(days=1))

        start = datetime.utcnow() - delta
        end = datetime.utcnow()

        stmt = select(AgentMetric).where(AgentMetric.updated_at >= start)
        if workspace:
            stmt = stmt.join(Workspace).where(Workspace.name == workspace)

        result = await self.session.execute(stmt)
        metrics = list(result.scalars().all())

        return {
            "period": period,
            "start": start,
            "end": end,
            "metrics": {
                "messages_processed": sum(m.messages_processed for m in metrics),
                "tokens": {
                    "input": sum(m.tokens_in for m in metrics),
                    "output": sum(m.tokens_out for m in metrics),
                },
                "errors": sum(m.error_count for m in metrics),
            },
        }

    # =========================================================================
    # Error Logging
    # =========================================================================

    async def log_error(
        self,
        workspace_name: str,
        error: Exception,
        session_key: str | None = None,
    ) -> None:
        """Log an agent error.

        Args:
            workspace_name: Workspace name
            error: Exception that occurred
            session_key: Optional session identifier
        """
        stmt = select(Workspace).where(Workspace.name == workspace_name)
        result = await self.session.execute(stmt)
        workspace = result.scalar_one_or_none()
        if not workspace:
            return

        import traceback

        agent_error = AgentError(
            workspace_id=workspace.id,
            session_key=session_key,
            error_type=type(error).__name__,
            error_message=str(error),
            stack_trace=traceback.format_exc(),
        )
        self.session.add(agent_error)

        # Update error count in metrics if session exists
        if session_key:
            metric_stmt = select(AgentMetric).where(
                AgentMetric.workspace_id == workspace.id,
                AgentMetric.session_key == session_key,
            )
            metric_result = await self.session.execute(metric_stmt)
            metric = metric_result.scalar_one_or_none()
            if metric:
                metric.error_count += 1

        await self.session.flush()

    async def get_errors(
        self,
        workspace: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Get recent errors.

        Args:
            workspace: Optional workspace filter
            limit: Maximum number of errors to return

        Returns:
            list: List of error dictionaries
        """
        stmt = (
            select(AgentError, Workspace.name)
            .join(Workspace)
            .order_by(AgentError.created_at.desc())
            .limit(limit)
        )

        if workspace:
            stmt = stmt.where(Workspace.name == workspace)

        result = await self.session.execute(stmt)
        rows = result.all()

        return [
            {
                "id": error.id,
                "workspace": workspace_name,
                "session_key": error.session_key,
                "error_type": error.error_type,
                "message": error.error_message,
                "created_at": error.created_at,
            }
            for error, workspace_name in rows
        ]

    async def get_queue_stats(self) -> dict[str, Any]:
        """Get queue statistics across all workspaces.

        Returns:
            dict: Queue statistics by workspace and totals
        """
        if not self.orchestrator:
            return {"queues": {}, "totals": {"queued": 0, "active": 0}}

        queues: dict[str, dict[str, dict[str, int]]] = {}
        total_queued = 0
        total_active = 0

        for name, runner in self.orchestrator.runners.items():
            queue_stats = self._extract_queue_stats(runner)
            queues[name] = queue_stats

            # Sum up totals
            for lane_stats in queue_stats.values():
                total_queued += lane_stats["queued"]
                total_active += lane_stats["active"]

        return {
            "queues": queues,
            "totals": {
                "queued": total_queued,
                "active": total_active,
            },
        }

    # =========================================================================
    # Private Helper Methods
    # =========================================================================

    def _extract_runner_status(self, name: str, runner: Any) -> dict[str, Any]:
        """Extract status information from a WorkspaceRunner.

        Args:
            name: Workspace name
            runner: WorkspaceRunner instance

        Returns:
            dict: Status information
        """
        return {
            "name": name,
            "status": "running" if runner._running else "stopped",
            "state": self._extract_agent_state(runner),
            "channels": list(runner._channels.keys()),
            "active_sessions": 0,  # TODO: Extract from checkpointer if available
            "queue_depth": self._get_queue_depth(runner),
            "last_activity": None,  # TODO: Track in WorkspaceRunner if needed
        }

    def _extract_agent_state(self, runner: Any) -> str:
        """Extract agent state from runner.

        Args:
            runner: WorkspaceRunner instance

        Returns:
            str: Agent state ("idle", "active", "stopped")
        """
        if not runner._running:
            return "stopped"

        # Check if queue has active items
        if hasattr(runner, "_lane_queue"):
            for lane in ["main", "subagent", "cron"]:
                if runner._lane_queue._active.get(lane, 0) > 0:
                    return "active"

        return "idle"

    def _extract_channel_info(self, runner: Any) -> dict[str, Any]:
        """Extract channel information from runner.

        Args:
            runner: WorkspaceRunner instance

        Returns:
            dict: Channel information by channel type
        """
        channels: dict[str, Any] = {}
        for channel_type, channel in runner._channels.items():
            channels[channel_type] = {
                "type": channel_type,
                "enabled": True,  # If it exists, it's enabled
            }
        return channels

    def _extract_queue_stats(self, runner: Any) -> dict[str, dict[str, int]]:
        """Extract queue statistics from runner.

        Args:
            runner: WorkspaceRunner instance

        Returns:
            dict: Queue statistics by lane
        """
        stats: dict[str, dict[str, int]] = {}

        if not hasattr(runner, "_lane_queue"):
            return stats

        lane_queue = runner._lane_queue

        for lane in ["main", "subagent", "cron"]:
            queued = len(lane_queue._queues.get(lane, []))
            active = lane_queue._active.get(lane, 0)
            concurrency = lane_queue._concurrency.get(lane, 1)

            stats[lane] = {
                "queued": queued,
                "active": active,
                "concurrency": concurrency,
            }

        return stats

    def _get_queue_depth(self, runner: Any) -> int:
        """Get total queue depth for a runner.

        Args:
            runner: WorkspaceRunner instance

        Returns:
            int: Total number of queued items
        """
        if not hasattr(runner, "_lane_queue"):
            return 0

        total = 0
        for lane in ["main", "subagent", "cron"]:
            total += len(runner._lane_queue._queues.get(lane, []))

        return total
