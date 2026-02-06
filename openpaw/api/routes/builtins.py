"""Builtins API routes for managing builtin tools, processors, and API keys."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from openpaw.api.dependencies import get_builtin_service
from openpaw.api.schemas.builtins import (
    AllowlistResponse,
    AllowlistUpdate,
    ApiKeyCreate,
    ApiKeyListResponse,
    ApiKeyResponse,
    BuiltinConfigResponse,
    BuiltinConfigUpdate,
    BuiltinListResponse,
    BuiltinResponse,
)
from openpaw.api.services.builtin_service import BuiltinService

router = APIRouter(prefix="/builtins", tags=["builtins"])


# =============================================================================
# Builtin Management
# =============================================================================


@router.get("", response_model=BuiltinListResponse)
async def list_builtins(
    service: Annotated[BuiltinService, Depends(get_builtin_service)],
) -> BuiltinListResponse:
    """List all registered builtins with availability status.

    Returns all builtins from the registry, including their metadata,
    prerequisites, availability status, and enabled state.

    Args:
        service: Builtin service instance

    Returns:
        BuiltinListResponse: List of all registered builtins with total count
    """
    builtins = await service.list_registered()
    return BuiltinListResponse(
        builtins=[BuiltinResponse(**b) for b in builtins],
        total=len(builtins),
    )


@router.get("/available", response_model=BuiltinListResponse)
async def list_available_builtins(
    service: Annotated[BuiltinService, Depends(get_builtin_service)],
) -> BuiltinListResponse:
    """List only builtins with satisfied prerequisites.

    Filters the builtin list to only include those where all prerequisites
    (environment variables and packages) are satisfied.

    Args:
        service: Builtin service instance

    Returns:
        BuiltinListResponse: List of available builtins with total count
    """
    builtins = await service.list_available()
    return BuiltinListResponse(
        builtins=[BuiltinResponse(**b) for b in builtins],
        total=len(builtins),
    )


# =============================================================================
# API Key Management
# =============================================================================


@router.get("/api-keys", response_model=ApiKeyListResponse)
async def list_api_keys(
    service: Annotated[BuiltinService, Depends(get_builtin_service)],
) -> ApiKeyListResponse:
    """List stored API key names.

    Returns metadata for all stored API keys. The actual key values
    are never exposed through this endpoint.

    Args:
        service: Builtin service instance

    Returns:
        ApiKeyListResponse: List of API key metadata with total count
    """
    keys = await service.list_api_keys()
    return ApiKeyListResponse(
        api_keys=[ApiKeyResponse(**k) for k in keys],
        total=len(keys),
    )


@router.post("/api-keys", response_model=ApiKeyResponse, status_code=status.HTTP_201_CREATED)
async def create_api_key(
    data: ApiKeyCreate,
    service: Annotated[BuiltinService, Depends(get_builtin_service)],
) -> ApiKeyResponse:
    """Store a new API key.

    Encrypts and stores an API key for use by builtins. The key value
    is encrypted at rest and never returned in API responses.

    Args:
        data: API key creation data with name, service, and value
        service: Builtin service instance

    Returns:
        ApiKeyResponse: Created API key metadata (without value)

    Raises:
        HTTPException: 409 if API key name already exists
    """
    try:
        created = await service.store_api_key(data.name, data.service, data.value)
        return ApiKeyResponse(**created)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        )


@router.delete("/api-keys/{name}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_api_key(
    name: str,
    service: Annotated[BuiltinService, Depends(get_builtin_service)],
) -> None:
    """Delete a stored API key.

    Permanently removes an API key from storage.

    Args:
        name: API key identifier
        service: Builtin service instance

    Raises:
        HTTPException: 404 if API key not found
    """
    deleted = await service.delete_api_key(name)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"API key '{name}' not found",
        )


# =============================================================================
# Allow/Deny List Management
# =============================================================================


@router.get("/allowlist", response_model=AllowlistResponse)
async def get_allowlist(
    service: Annotated[BuiltinService, Depends(get_builtin_service)],
) -> AllowlistResponse:
    """Get global builtin allow/deny lists.

    Returns the current global allow and deny lists for builtins.
    These lists can contain individual builtin names or group patterns
    (e.g., "group:voice").

    Args:
        service: Builtin service instance

    Returns:
        AllowlistResponse: Current allow and deny lists
    """
    lists = await service.get_allowlist()
    return AllowlistResponse(**lists)


@router.put("/allowlist", response_model=AllowlistResponse)
async def update_allowlist(
    data: AllowlistUpdate,
    service: Annotated[BuiltinService, Depends(get_builtin_service)],
) -> AllowlistResponse:
    """Update global builtin allow/deny lists.

    Replaces the current global allow and deny lists with the provided values.
    Empty lists are valid and will clear existing entries.

    Args:
        data: New allow and deny lists
        service: Builtin service instance

    Returns:
        AllowlistResponse: Updated allow and deny lists
    """
    updated = await service.update_allowlist(data.allow, data.deny)
    return AllowlistResponse(**updated)


# =============================================================================
# Specific Builtin Configuration (must come after specific routes)
# =============================================================================


@router.get("/{name}", response_model=BuiltinConfigResponse)
async def get_builtin_config(
    name: str,
    service: Annotated[BuiltinService, Depends(get_builtin_service)],
) -> BuiltinConfigResponse:
    """Get builtin configuration.

    Retrieves the configuration for a specific builtin including its
    type, group, enabled state, and configuration dictionary.

    Args:
        name: Builtin identifier (e.g., "brave_search")
        service: Builtin service instance

    Returns:
        BuiltinConfigResponse: Builtin configuration details

    Raises:
        HTTPException: 404 if builtin not found
    """
    config = await service.get_config(name)
    if config is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Builtin '{name}' not found",
        )
    return BuiltinConfigResponse(**config)


@router.put("/{name}", response_model=BuiltinConfigResponse)
async def update_builtin_config(
    name: str,
    data: BuiltinConfigUpdate,
    service: Annotated[BuiltinService, Depends(get_builtin_service)],
) -> BuiltinConfigResponse:
    """Update builtin configuration.

    Updates the enabled state and/or configuration for a specific builtin.
    Both fields are optional - provide only what needs updating.

    Args:
        name: Builtin identifier
        data: Update data with optional enabled and config fields
        service: Builtin service instance

    Returns:
        BuiltinConfigResponse: Updated builtin configuration

    Raises:
        HTTPException: 404 if builtin not found
    """
    try:
        updated = await service.update_config(name, data.enabled, data.config)
        return BuiltinConfigResponse(**updated)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
