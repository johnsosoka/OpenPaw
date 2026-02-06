"""Monitoring and health check endpoints."""

from typing import Any

from fastapi import APIRouter
from sqlalchemy import text

from openpaw.api.dependencies import DbSession, Orchestrator

router = APIRouter(prefix="/monitoring", tags=["monitoring"])


@router.get("/health")
async def health_check(
    session: DbSession,
    orchestrator: Orchestrator,
) -> dict[str, Any]:
    """
    System health check endpoint.

    This endpoint does not require authentication and provides a quick
    overview of system status.

    Returns:
        dict: Health status including:
            - status: Overall health ("healthy" or "degraded")
            - version: API version
            - database: Database connection status
            - orchestrator: Orchestrator status
            - workspaces: Workspace statistics
    """
    # Check database connection
    db_status = "connected"
    try:
        await session.execute(text("SELECT 1"))
    except Exception:
        db_status = "disconnected"

    # Check orchestrator status
    orchestrator_status = "unavailable"
    workspace_stats = {
        "total": 0,
        "running": 0,
        "stopped": 0,
    }

    if orchestrator is not None:
        orchestrator_status = "running"

        # Get workspace statistics
        runners = orchestrator.runners
        workspace_stats["total"] = len(runners)

        for runner in runners.values():
            # Check if runner is active (has running tasks/channels)
            # For now, consider all loaded runners as "running"
            # TODO: Add actual runtime status check once WorkspaceRunner exposes it
            if runner:
                workspace_stats["running"] += 1
            else:
                workspace_stats["stopped"] += 1

    # Determine overall status
    overall_status = "healthy"
    if db_status == "disconnected" or orchestrator_status == "unavailable":
        overall_status = "degraded"

    return {
        "status": overall_status,
        "version": "0.1.0",
        "database": db_status,
        "orchestrator": orchestrator_status,
        "workspaces": workspace_stats,
    }
