"""Channels API routes for managing channel bindings and configuration."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from openpaw.api.dependencies import get_channel_service
from openpaw.api.schemas.channels import (
    ChannelConfigResponse,
    ChannelConfigUpdate,
    ChannelTestResponse,
    ChannelTypeInfo,
    ChannelTypesResponse,
)
from openpaw.api.services.channel_service import ChannelService

router = APIRouter(prefix="/channels", tags=["channels"])


# =============================================================================
# Channel Types
# =============================================================================


@router.get("/types", response_model=ChannelTypesResponse)
async def list_channel_types(
    service: Annotated[ChannelService, Depends(get_channel_service)],
) -> ChannelTypesResponse:
    """List supported channel types.

    Returns all supported channel types with their metadata, configuration
    schemas, and implementation status (active, planned).

    Args:
        service: Channel service instance

    Returns:
        ChannelTypesResponse: List of supported channel types
    """
    types = await service.list_types()
    return ChannelTypesResponse(types=[ChannelTypeInfo(**t) for t in types])


# =============================================================================
# Channel Configuration
# =============================================================================


@router.get("/{workspace}", response_model=ChannelConfigResponse)
async def get_channel_config(
    workspace: str,
    service: Annotated[ChannelService, Depends(get_channel_service)],
) -> ChannelConfigResponse:
    """Get channel configuration for a workspace.

    Retrieves the channel binding configuration including type, enabled status,
    access control settings, and runtime status (if orchestrator available).
    The token is never exposed in responses.

    Args:
        workspace: Workspace name
        service: Channel service instance

    Returns:
        ChannelConfigResponse: Channel configuration details

    Raises:
        HTTPException: 404 if no channel configured for workspace
    """
    config = await service.get_config(workspace)
    if config is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No channel configured for workspace '{workspace}'",
        )
    return ChannelConfigResponse(**config)


@router.put("/{workspace}", response_model=ChannelConfigResponse)
async def update_channel_config(
    workspace: str,
    data: ChannelConfigUpdate,
    service: Annotated[ChannelService, Depends(get_channel_service)],
) -> ChannelConfigResponse:
    """Update channel configuration for a workspace.

    Updates or creates a channel binding for the workspace. All fields are
    optional - provide only what needs updating. The token is encrypted
    before storage and never exposed in responses.

    Args:
        workspace: Workspace name
        data: Update data with optional channel configuration fields
        service: Channel service instance

    Returns:
        ChannelConfigResponse: Updated channel configuration

    Raises:
        HTTPException: 400 if validation fails (workspace not found, invalid type, etc.)
    """
    try:
        updated = await service.update_config(
            workspace=workspace,
            channel_type=data.type,
            token=data.token,
            allowed_users=data.allowed_users,
            allowed_groups=data.allowed_groups,
            allow_all=data.allow_all,
            enabled=data.enabled,
        )
        return ChannelConfigResponse(**updated)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


# =============================================================================
# Channel Testing
# =============================================================================


@router.post("/{workspace}/test", response_model=ChannelTestResponse)
async def test_channel_connection(
    workspace: str,
    service: Annotated[ChannelService, Depends(get_channel_service)],
) -> ChannelTestResponse:
    """Test channel connection for a workspace.

    Tests the channel configuration by making an API call to the channel
    provider (e.g., Telegram getMe API). Returns bot information if successful.

    Currently supported: Telegram

    Args:
        workspace: Workspace name
        service: Channel service instance

    Returns:
        ChannelTestResponse: Test result with status and bot information

    Raises:
        HTTPException: 400 if workspace/channel not found or validation fails
        HTTPException: 503 if connection test fails (invalid token, network error, etc.)
    """
    try:
        result = await service.test_connection(workspace)
        return ChannelTestResponse(**result)
    except ValueError as e:
        # Workspace or channel not found
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except RuntimeError as e:
        # Connection test failed
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        )
