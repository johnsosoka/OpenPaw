"""Settings API routes for global configuration management."""

from pathlib import Path
from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException

from openpaw.api.dependencies import get_settings_service
from openpaw.api.schemas.settings import (
    CategorySettings,
    SettingsImportRequest,
    SettingsImportResponse,
    SettingsResponse,
)
from openpaw.api.services.settings_service import SettingsService

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("", response_model=SettingsResponse)
async def get_all_settings(
    service: Annotated[SettingsService, Depends(get_settings_service)],
) -> SettingsResponse:
    """Get all settings grouped by category.

    Returns settings for all valid categories (agent, queue, lanes).

    Returns:
        SettingsResponse: Dictionary with category names as keys and their settings as values
    """
    settings = await service.get_all()
    return SettingsResponse(
        agent=settings.get("agent"),
        queue=settings.get("queue"),
        lanes=settings.get("lanes"),
    )


@router.get("/{category}", response_model=CategorySettings)
async def get_category_settings(
    category: str,
    service: Annotated[SettingsService, Depends(get_settings_service)],
) -> CategorySettings:
    """Get settings for a specific category.

    Args:
        category: Category name (agent, queue, or lanes)
        service: Settings service instance

    Returns:
        CategorySettings: Dictionary of settings for the specified category

    Raises:
        HTTPException: 404 if category is invalid or not found
    """
    settings = await service.get_category(category)
    if settings is None:
        valid_cats = ", ".join(sorted(SettingsService.VALID_CATEGORIES))
        raise HTTPException(
            status_code=404,
            detail=f"Category '{category}' not found. Valid categories: {valid_cats}",
        )
    return CategorySettings(**settings)


@router.put("/{category}", response_model=CategorySettings)
async def update_category_settings(
    category: str,
    data: CategorySettings,
    service: Annotated[SettingsService, Depends(get_settings_service)],
) -> CategorySettings:
    """Update settings for a category.

    Performs upsert operations for each key in the provided data.

    Args:
        category: Category name (agent, queue, or lanes)
        data: New settings values to update
        service: Settings service instance

    Returns:
        CategorySettings: Updated settings for the category

    Raises:
        HTTPException: 404 if category is invalid
    """
    try:
        updated = await service.update_category(category, data.model_dump())
        return CategorySettings(**updated)
    except ValueError as e:
        raise HTTPException(
            status_code=404,
            detail=str(e),
        )


@router.post("/import", response_model=SettingsImportResponse)
async def import_settings(
    request: SettingsImportRequest,
    service: Annotated[SettingsService, Depends(get_settings_service)],
) -> SettingsImportResponse:
    """Import settings from a YAML configuration file.

    Extracts agent, queue, lanes, and builtins sections from the YAML file
    and imports them into the database.

    Args:
        request: Import request with config_path and overwrite flag
        service: Settings service instance

    Returns:
        SettingsImportResponse: Summary of import results with counts and errors

    Raises:
        HTTPException: 400 if file not found or YAML parsing fails
    """
    config_path = Path(request.config_path)

    if not config_path.exists():
        raise HTTPException(
            status_code=400,
            detail=f"Configuration file not found: {config_path}",
        )

    result = await service.import_from_yaml(config_path)

    # If there are critical errors and no successful imports, return 400
    if result["errors"] and not result["imported"]["settings"] and not result["imported"]["builtins"]:
        raise HTTPException(
            status_code=400,
            detail=f"Import failed: {', '.join(result['errors'])}",
        )

    return SettingsImportResponse(
        imported=cast(dict[str, int], result["imported"]),
        skipped=result["skipped"],
        errors=result["errors"],
    )
