"""Pydantic schemas for API request/response models."""

from openpaw.api.schemas.builtins import (
    AllowlistResponse,
    AllowlistUpdate,
    ApiKeyCreate,
    ApiKeyListResponse,
    ApiKeyResponse,
    BuiltinConfigResponse,
    BuiltinConfigUpdate,
    BuiltinListResponse,
    BuiltinPrerequisites,
    BuiltinResponse,
)
from openpaw.api.schemas.settings import (
    CategorySettings,
    SettingsImportRequest,
    SettingsImportResponse,
    SettingsResponse,
)
from openpaw.api.schemas.workspaces import (
    ChannelResponse,
    CronSummary,
    FileContentResponse,
    FileListResponse,
    FileWriteRequest,
    ModelConfigUpdate,
    QueueConfigUpdate,
    WorkspaceConfigResponse,
    WorkspaceControlResponse,
    WorkspaceCreate,
    WorkspaceListResponse,
    WorkspaceResponse,
    WorkspaceUpdate,
)

__all__ = [
    # Builtin schemas
    "AllowlistResponse",
    "AllowlistUpdate",
    "ApiKeyCreate",
    "ApiKeyListResponse",
    "ApiKeyResponse",
    "BuiltinConfigResponse",
    "BuiltinConfigUpdate",
    "BuiltinListResponse",
    "BuiltinPrerequisites",
    "BuiltinResponse",
    # Settings schemas
    "CategorySettings",
    "SettingsImportRequest",
    "SettingsImportResponse",
    "SettingsResponse",
    # Workspace schemas
    "ChannelResponse",
    "CronSummary",
    "FileContentResponse",
    "FileListResponse",
    "FileWriteRequest",
    "ModelConfigUpdate",
    "QueueConfigUpdate",
    "WorkspaceConfigResponse",
    "WorkspaceControlResponse",
    "WorkspaceCreate",
    "WorkspaceListResponse",
    "WorkspaceResponse",
    "WorkspaceUpdate",
]
