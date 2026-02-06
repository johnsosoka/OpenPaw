"""Pydantic schemas for Settings API endpoints."""

from typing import Any

from pydantic import BaseModel, ConfigDict


class SettingsResponse(BaseModel):
    """All settings grouped by category.

    Response model for GET /settings endpoint.
    Contains optional categories: agent, queue, lanes.
    """

    agent: dict[str, Any] | None = None
    queue: dict[str, Any] | None = None
    lanes: dict[str, Any] | None = None

    model_config = ConfigDict(extra="forbid")


class CategorySettings(BaseModel):
    """Settings for a single category.

    Flexible key/value mapping for category-specific settings.
    Used for both request and response models.
    """

    model_config = ConfigDict(extra="allow")


class SettingsImportRequest(BaseModel):
    """Request model for importing settings from YAML file.

    POST /settings/import
    """

    config_path: str
    overwrite: bool = False

    model_config = ConfigDict(extra="forbid")


class SettingsImportResponse(BaseModel):
    """Response model for settings import operation.

    POST /settings/import response.
    """

    imported: dict[str, int]  # {"settings": 10, "builtins": 5}
    skipped: int
    errors: list[str]

    model_config = ConfigDict(extra="forbid")
