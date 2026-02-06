"""Workspace management API routes."""

from datetime import datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from openpaw.api.dependencies import DbSession, Orchestrator, WorkspacesPath
from openpaw.api.schemas.workspaces import (
    FileContentResponse,
    FileListResponse,
    FileWriteRequest,
    WorkspaceControlResponse,
    WorkspaceCreate,
    WorkspaceListResponse,
    WorkspaceResponse,
    WorkspaceUpdate,
)
from openpaw.api.services.workspace_service import WorkspaceService

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


async def get_workspace_service(
    session: DbSession,
    workspaces_path: WorkspacesPath,
    orchestrator: Orchestrator,
) -> WorkspaceService:
    """Dependency to get workspace service instance."""
    return WorkspaceService(session, workspaces_path, orchestrator)


WorkspaceServiceDep = Annotated[WorkspaceService, Depends(get_workspace_service)]


# =============================================================================
# CRUD Operations
# =============================================================================


@router.get("", response_model=WorkspaceListResponse)
async def list_workspaces(
    service: WorkspaceServiceDep,
) -> WorkspaceListResponse:
    """
    List all registered workspaces with their runtime status.

    Returns:
        WorkspaceListResponse: List of all workspaces with total count
    """
    workspaces = await service.list_all()
    return WorkspaceListResponse(workspaces=workspaces, total=len(workspaces))


@router.post("", response_model=WorkspaceResponse, status_code=status.HTTP_201_CREATED)
async def create_workspace(
    data: WorkspaceCreate,
    service: WorkspaceServiceDep,
) -> WorkspaceResponse:
    """
    Create a new workspace with default markdown files.

    Args:
        data: Workspace creation data (name, description)
        service: Workspace service instance

    Returns:
        WorkspaceResponse: Created workspace details

    Raises:
        HTTPException 409: Workspace name already exists
    """
    try:
        workspace = await service.create(data)
        return workspace
    except ValueError as e:
        # Service raises ValueError when workspace already exists
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        ) from e


@router.get("/{name}", response_model=WorkspaceResponse)
async def get_workspace(
    name: str,
    service: WorkspaceServiceDep,
) -> WorkspaceResponse:
    """
    Get detailed workspace information including configuration.

    Args:
        name: Workspace name
        service: Workspace service instance

    Returns:
        WorkspaceResponse: Workspace details with full configuration

    Raises:
        HTTPException 404: Workspace not found
    """
    workspace = await service.get_by_name(name)
    if workspace is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workspace '{name}' not found",
        )
    return workspace


@router.put("/{name}", response_model=WorkspaceResponse)
async def update_workspace(
    name: str,
    data: WorkspaceUpdate,
    service: WorkspaceServiceDep,
) -> WorkspaceResponse:
    """
    Update workspace configuration.

    Args:
        name: Workspace name
        data: Workspace update data (description, enabled, model_config, queue_config)
        service: Workspace service instance

    Returns:
        WorkspaceResponse: Updated workspace details

    Raises:
        HTTPException 404: Workspace not found
    """
    workspace = await service.update(name, data)
    if workspace is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workspace '{name}' not found",
        )
    return workspace


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workspace(
    name: str,
    service: WorkspaceServiceDep,
    delete_files: bool = False,
) -> None:
    """
    Delete workspace from database.

    Args:
        name: Workspace name
        delete_files: If True, also delete workspace files from filesystem (default: False)
        service: Workspace service instance

    Raises:
        HTTPException 404: Workspace not found
    """
    deleted = await service.delete(name, delete_files=delete_files)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workspace '{name}' not found",
        )


# =============================================================================
# Runtime Control
# =============================================================================


@router.post("/{name}/start", response_model=WorkspaceControlResponse)
async def start_workspace(
    name: str,
    service: WorkspaceServiceDep,
) -> WorkspaceControlResponse:
    """
    Start the workspace runner.

    Args:
        name: Workspace name
        service: Workspace service instance

    Returns:
        WorkspaceControlResponse: Control response with status "started"

    Raises:
        HTTPException 404: Workspace not found
        HTTPException 409: Workspace already running
        HTTPException 503: Orchestrator not available
    """
    try:
        await service.start(name)
        return WorkspaceControlResponse(status="started", workspace=name)
    except ValueError as e:
        # Check if it's "not found" or "already running"
        error_msg = str(e)
        if "not found" in error_msg.lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=error_msg,
            ) from e
        elif "already running" in error_msg.lower():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=error_msg,
            ) from e
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=error_msg,
            ) from e
    except RuntimeError as e:
        # Service raises RuntimeError when orchestrator not available
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        ) from e


@router.post("/{name}/stop", response_model=WorkspaceControlResponse)
async def stop_workspace(
    name: str,
    service: WorkspaceServiceDep,
) -> WorkspaceControlResponse:
    """
    Stop the workspace runner.

    Args:
        name: Workspace name
        service: Workspace service instance

    Returns:
        WorkspaceControlResponse: Control response with status "stopped"

    Raises:
        HTTPException 503: Orchestrator not available
    """
    try:
        await service.stop(name)
        return WorkspaceControlResponse(status="stopped", workspace=name)
    except RuntimeError as e:
        # Service raises RuntimeError when orchestrator not available
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        ) from e


@router.post("/{name}/restart", response_model=WorkspaceControlResponse)
async def restart_workspace(
    name: str,
    service: WorkspaceServiceDep,
) -> WorkspaceControlResponse:
    """
    Restart the workspace runner (stop then start).

    Args:
        name: Workspace name
        service: Workspace service instance

    Returns:
        WorkspaceControlResponse: Control response with status "restarted"

    Raises:
        HTTPException 404: Workspace not found
        HTTPException 503: Orchestrator not available
    """
    try:
        await service.restart(name)
        return WorkspaceControlResponse(status="restarted", workspace=name)
    except ValueError as e:
        # Check if it's "not found"
        error_msg = str(e)
        if "not found" in error_msg.lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=error_msg,
            ) from e
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=error_msg,
            ) from e
    except RuntimeError as e:
        # Service raises RuntimeError when orchestrator not available
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        ) from e


# =============================================================================
# File Operations
# =============================================================================


@router.get("/{name}/files", response_model=FileListResponse)
async def list_workspace_files(
    name: str,
    service: WorkspaceServiceDep,
) -> FileListResponse:
    """
    List editable markdown files in workspace.

    Args:
        name: Workspace name
        service: Workspace service instance

    Returns:
        FileListResponse: List of editable files
    """
    files = await service.list_files(name)
    return FileListResponse(files=files)


@router.get("/{name}/files/{filename}", response_model=FileContentResponse)
async def read_workspace_file(
    name: str,
    filename: str,
    service: WorkspaceServiceDep,
) -> FileContentResponse:
    """
    Read a workspace markdown file.

    Args:
        name: Workspace name
        filename: File name (must be in allowed list: AGENT.md, USER.md, SOUL.md, HEARTBEAT.md)
        service: Workspace service instance

    Returns:
        FileContentResponse: File content with metadata

    Raises:
        HTTPException 400: Invalid filename (not in allowed list)
        HTTPException 404: Workspace or file not found
    """
    try:
        content = await service.read_file(name, filename)
        if content is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"File '{filename}' not found in workspace '{name}'",
            )

        # Get file modification time
        workspace = await service.get_by_name(name)
        if workspace:
            file_path = Path(workspace.path) / filename
            updated_at = datetime.fromtimestamp(file_path.stat().st_mtime)
        else:
            updated_at = None

        return FileContentResponse(
            filename=filename,
            content=content,
            updated_at=updated_at,
        )
    except ValueError as e:
        # Service raises ValueError for invalid filenames
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e


@router.put("/{name}/files/{filename}", response_model=FileContentResponse)
async def write_workspace_file(
    name: str,
    filename: str,
    data: FileWriteRequest,
    service: WorkspaceServiceDep,
) -> FileContentResponse:
    """
    Update a workspace markdown file.

    Args:
        name: Workspace name
        filename: File name (must be in allowed list: AGENT.md, USER.md, SOUL.md, HEARTBEAT.md)
        data: File write request with content
        service: Workspace service instance

    Returns:
        FileContentResponse: Updated file content with metadata

    Raises:
        HTTPException 400: Invalid filename (not in allowed list)
        HTTPException 404: Workspace not found
    """
    try:
        success = await service.write_file(name, filename, data.content)
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Workspace '{name}' not found",
            )

        # Get file modification time
        workspace = await service.get_by_name(name)
        if workspace:
            file_path = Path(workspace.path) / filename
            updated_at = datetime.fromtimestamp(file_path.stat().st_mtime)
        else:
            updated_at = None

        return FileContentResponse(
            filename=filename,
            content=data.content,
            updated_at=updated_at,
        )
    except ValueError as e:
        # Service raises ValueError for invalid filenames
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e
