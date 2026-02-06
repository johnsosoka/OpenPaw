"""Monitoring and health check endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from openpaw.api.dependencies import get_monitoring_service
from openpaw.api.schemas.monitoring import (
    ErrorListResponse,
    ErrorResponse,
    HealthResponse,
    MetricsResponse,
    QueueStatusResponse,
    SessionListResponse,
    SessionResponse,
    WorkspaceDetailResponse,
    WorkspaceStateResponse,
    WorkspaceStatesResponse,
)
from openpaw.api.services.monitoring_service import MonitoringService

router = APIRouter(prefix="/monitoring", tags=["monitoring"])


# =============================================================================
# Health Check
# =============================================================================


@router.get("/health", response_model=HealthResponse)
async def health_check(
    service: Annotated[MonitoringService, Depends(get_monitoring_service)],
) -> HealthResponse:
    """System health check endpoint.

    This endpoint does not require authentication and provides a quick
    overview of system status.

    Args:
        service: Monitoring service instance

    Returns:
        HealthResponse: Health status including database, orchestrator, and workspace stats
    """
    health = await service.get_health()
    return HealthResponse(**health)


# =============================================================================
# Workspace States
# =============================================================================


@router.get("/workspaces", response_model=WorkspaceStatesResponse)
async def list_workspace_states(
    service: Annotated[MonitoringService, Depends(get_monitoring_service)],
) -> WorkspaceStatesResponse:
    """List all workspace states.

    Returns runtime state for all active workspaces including status,
    agent state, channels, sessions, and queue depth.

    Args:
        service: Monitoring service instance

    Returns:
        WorkspaceStatesResponse: List of workspace states
    """
    states = await service.get_workspace_states()
    return WorkspaceStatesResponse(
        workspaces=[WorkspaceStateResponse(**s) for s in states]
    )


@router.get("/workspaces/{name}", response_model=WorkspaceDetailResponse)
async def get_workspace_state(
    name: str,
    service: Annotated[MonitoringService, Depends(get_monitoring_service)],
) -> WorkspaceDetailResponse:
    """Get detailed workspace state.

    Returns comprehensive state information for a specific workspace including
    channel configuration, queue statistics, session counts, and token usage.

    Args:
        name: Workspace name
        service: Monitoring service instance

    Returns:
        WorkspaceDetailResponse: Detailed workspace state

    Raises:
        HTTPException: 404 if workspace not found or not running
    """
    state = await service.get_workspace_state(name)
    if state is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workspace '{name}' not found or not running",
        )
    return WorkspaceDetailResponse(**state)


@router.get("/workspaces/{name}/sessions", response_model=SessionListResponse)
async def list_workspace_sessions(
    name: str,
    service: Annotated[MonitoringService, Depends(get_monitoring_service)],
) -> SessionListResponse:
    """List active sessions for a workspace.

    Returns details for all active agent sessions including message counts,
    token usage, and last activity timestamp.

    Args:
        name: Workspace name
        service: Monitoring service instance

    Returns:
        SessionListResponse: List of active sessions

    Raises:
        HTTPException: 404 if workspace not found or not running
    """
    sessions = await service.get_workspace_sessions(name)
    if sessions is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workspace '{name}' not found or not running",
        )
    return SessionListResponse(sessions=[SessionResponse(**s) for s in sessions])


# =============================================================================
# Metrics
# =============================================================================


@router.get("/metrics", response_model=MetricsResponse)
async def get_aggregated_metrics(
    service: Annotated[MonitoringService, Depends(get_monitoring_service)],
    period: str = Query("day", description="Time period (hour, day, week)"),
) -> MetricsResponse:
    """Get aggregated metrics across all workspaces.

    Returns aggregated statistics for the specified time period including
    messages processed, token usage, and error counts.

    Args:
        service: Monitoring service instance
        period: Time period for aggregation (hour, day, week)

    Returns:
        MetricsResponse: Aggregated metrics for the period
    """
    metrics = await service.get_aggregated_metrics(period=period)
    return MetricsResponse(**metrics)


@router.get("/metrics/{workspace}", response_model=MetricsResponse)
async def get_workspace_metrics(
    workspace: str,
    service: Annotated[MonitoringService, Depends(get_monitoring_service)],
    period: str = Query("day", description="Time period (hour, day, week)"),
) -> MetricsResponse:
    """Get aggregated metrics for a specific workspace.

    Returns aggregated statistics for the specified workspace and time period.

    Args:
        workspace: Workspace name
        service: Monitoring service instance
        period: Time period for aggregation (hour, day, week)

    Returns:
        MetricsResponse: Aggregated metrics for the workspace and period
    """
    metrics = await service.get_aggregated_metrics(period=period, workspace=workspace)
    return MetricsResponse(**metrics)


# =============================================================================
# Errors
# =============================================================================


@router.get("/errors", response_model=ErrorListResponse)
async def list_errors(
    service: Annotated[MonitoringService, Depends(get_monitoring_service)],
    workspace: str | None = Query(None, description="Filter by workspace name"),
    limit: int = Query(50, ge=1, le=500, description="Maximum number of errors"),
) -> ErrorListResponse:
    """List recent errors across all workspaces.

    Returns recent agent errors with optional filtering by workspace.
    Results are ordered by timestamp descending (most recent first).

    Args:
        service: Monitoring service instance
        workspace: Optional workspace name filter
        limit: Maximum number of errors to return (1-500)

    Returns:
        ErrorListResponse: List of recent errors
    """
    errors = await service.get_errors(workspace=workspace, limit=limit)
    return ErrorListResponse(errors=[ErrorResponse(**e) for e in errors])


@router.get("/errors/{workspace}", response_model=ErrorListResponse)
async def list_workspace_errors(
    workspace: str,
    service: Annotated[MonitoringService, Depends(get_monitoring_service)],
    limit: int = Query(50, ge=1, le=500, description="Maximum number of errors"),
) -> ErrorListResponse:
    """List recent errors for a specific workspace.

    Returns recent agent errors for the specified workspace.
    Results are ordered by timestamp descending (most recent first).

    Args:
        workspace: Workspace name
        service: Monitoring service instance
        limit: Maximum number of errors to return (1-500)

    Returns:
        ErrorListResponse: List of recent errors for the workspace
    """
    errors = await service.get_errors(workspace=workspace, limit=limit)
    return ErrorListResponse(errors=[ErrorResponse(**e) for e in errors])


# =============================================================================
# Queue Statistics
# =============================================================================


@router.get("/queues", response_model=QueueStatusResponse)
async def get_queue_statistics(
    service: Annotated[MonitoringService, Depends(get_monitoring_service)],
) -> QueueStatusResponse:
    """Get queue statistics across all workspaces.

    Returns queue statistics for all lanes (main, subagent, cron) across
    all active workspaces, including total counts.

    Args:
        service: Monitoring service instance

    Returns:
        QueueStatusResponse: Queue statistics by workspace and totals
    """
    stats = await service.get_queue_stats()
    return QueueStatusResponse(**stats)
