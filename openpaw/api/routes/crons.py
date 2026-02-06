"""Crons API routes for managing scheduled tasks."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from openpaw.api.dependencies import get_cron_service
from openpaw.api.schemas.crons import (
    CronExecutionListResponse,
    CronExecutionResponse,
    CronJobCreate,
    CronJobListResponse,
    CronJobResponse,
    CronJobUpdate,
    CronTriggerResponse,
)
from openpaw.api.services.cron_service import CronService

router = APIRouter(prefix="/crons", tags=["crons"])


# =============================================================================
# List All Cron Jobs
# =============================================================================


@router.get("", response_model=CronJobListResponse)
async def list_cron_jobs(
    service: Annotated[CronService, Depends(get_cron_service)],
    workspace: str | None = Query(None, description="Filter by workspace name"),
    enabled: bool | None = Query(None, description="Filter by enabled status"),
) -> CronJobListResponse:
    """List all cron jobs with optional filters.

    Returns all cron jobs across all workspaces, or filtered by workspace
    and/or enabled status.

    Args:
        service: Cron service instance
        workspace: Optional workspace name filter
        enabled: Optional enabled status filter

    Returns:
        CronJobListResponse: List of cron jobs with total count
    """
    cron_jobs = await service.list_all(workspace=workspace, enabled=enabled)
    return CronJobListResponse(
        cron_jobs=[CronJobResponse(**c) for c in cron_jobs],
        total=len(cron_jobs),
    )


# =============================================================================
# Create Cron Job
# =============================================================================


@router.post("", response_model=CronJobResponse, status_code=status.HTTP_201_CREATED)
async def create_cron_job(
    data: CronJobCreate,
    service: Annotated[CronService, Depends(get_cron_service)],
) -> CronJobResponse:
    """Create a new cron job.

    Creates a scheduled task for a workspace with the specified schedule,
    prompt, and output configuration.

    Args:
        data: Cron job creation data
        service: Cron service instance

    Returns:
        CronJobResponse: Created cron job details

    Raises:
        HTTPException: 400 if workspace not found or schedule is invalid
        HTTPException: 409 if cron job with this name already exists in workspace
    """
    try:
        created = await service.create(
            workspace=data.workspace,
            name=data.name,
            schedule=data.schedule,
            prompt=data.prompt,
            output=data.output.model_dump(),
            enabled=data.enabled,
        )
        return CronJobResponse(**created)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        # Handle unique constraint violation (duplicate name in workspace)
        if "unique constraint" in str(e).lower() or "duplicate" in str(e).lower():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Cron job '{data.name}' already exists in workspace '{data.workspace}'",
            )
        raise


# =============================================================================
# Execution History (MUST come before {workspace}/{name} routes)
# =============================================================================


@router.get("/executions", response_model=CronExecutionListResponse)
async def list_cron_executions(
    service: Annotated[CronService, Depends(get_cron_service)],
    workspace: str | None = Query(None, description="Filter by workspace name"),
    limit: int = Query(50, ge=1, le=500, description="Maximum number of executions"),
) -> CronExecutionListResponse:
    """List recent cron execution history.

    Returns execution history for all cron jobs, or filtered by workspace.
    Results are ordered by start time descending (most recent first).

    Args:
        service: Cron service instance
        workspace: Optional workspace name filter
        limit: Maximum number of executions to return (1-500)

    Returns:
        CronExecutionListResponse: List of executions with total count
    """
    executions = await service.get_executions(workspace=workspace, limit=limit)
    return CronExecutionListResponse(
        executions=[CronExecutionResponse(**e) for e in executions],
        total=len(executions),
    )


# =============================================================================
# Single Cron Job Operations
# =============================================================================


@router.get("/{workspace}/{name}", response_model=CronJobResponse)
async def get_cron_job(
    workspace: str,
    name: str,
    service: Annotated[CronService, Depends(get_cron_service)],
) -> CronJobResponse:
    """Get a single cron job.

    Returns details for a specific cron job including next scheduled run time.

    Args:
        workspace: Workspace name
        name: Cron job name
        service: Cron service instance

    Returns:
        CronJobResponse: Cron job details

    Raises:
        HTTPException: 404 if cron job not found
    """
    cron = await service.get(workspace, name)
    if cron is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Cron job '{name}' not found in workspace '{workspace}'",
        )
    return CronJobResponse(**cron)


@router.put("/{workspace}/{name}", response_model=CronJobResponse)
async def update_cron_job(
    workspace: str,
    name: str,
    data: CronJobUpdate,
    service: Annotated[CronService, Depends(get_cron_service)],
) -> CronJobResponse:
    """Update a cron job.

    Updates schedule, prompt, output configuration, and/or enabled status.
    All fields are optional - provide only what needs updating.

    Args:
        workspace: Workspace name
        name: Cron job name
        data: Update data with optional fields
        service: Cron service instance

    Returns:
        CronJobResponse: Updated cron job details

    Raises:
        HTTPException: 404 if cron job not found
        HTTPException: 400 if schedule is invalid
    """
    try:
        output_dict = data.output.model_dump() if data.output else None
        updated = await service.update(
            workspace=workspace,
            name=name,
            schedule=data.schedule,
            prompt=data.prompt,
            output=output_dict,
            enabled=data.enabled,
        )
        if updated is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Cron job '{name}' not found in workspace '{workspace}'",
            )
        return CronJobResponse(**updated)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.delete("/{workspace}/{name}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_cron_job(
    workspace: str,
    name: str,
    service: Annotated[CronService, Depends(get_cron_service)],
) -> None:
    """Delete a cron job.

    Permanently removes a cron job and its execution history.

    Args:
        workspace: Workspace name
        name: Cron job name
        service: Cron service instance

    Raises:
        HTTPException: 404 if cron job not found
    """
    deleted = await service.delete(workspace, name)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Cron job '{name}' not found in workspace '{workspace}'",
        )


# =============================================================================
# Manual Trigger
# =============================================================================


@router.post(
    "/{workspace}/{name}/trigger",
    response_model=CronTriggerResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def trigger_cron_job(
    workspace: str,
    name: str,
    service: Annotated[CronService, Depends(get_cron_service)],
) -> CronTriggerResponse:
    """Manually trigger a cron job.

    Queues the cron job for immediate execution outside its normal schedule.

    Args:
        workspace: Workspace name
        name: Cron job name
        service: Cron service instance

    Returns:
        CronTriggerResponse: Trigger acceptance confirmation

    Raises:
        HTTPException: 404 if cron job not found
    """
    triggered = await service.trigger(workspace, name)
    if not triggered:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Cron job '{name}' not found in workspace '{workspace}'",
        )
    return CronTriggerResponse(
        status="accepted",
        workspace=workspace,
        name=name,
    )
