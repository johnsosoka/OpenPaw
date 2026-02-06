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
from openpaw.api.schemas.channels import (
    ChannelConfigResponse,
    ChannelConfigUpdate,
    ChannelTestResponse,
    ChannelTypeInfo,
    ChannelTypesResponse,
)
from openpaw.api.schemas.crons import (
    CronExecutionListResponse,
    CronExecutionResponse,
    CronJobCreate,
    CronJobListResponse,
    CronJobResponse,
    CronJobUpdate,
    CronOutputConfig,
    CronTriggerResponse,
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
    # Channel schemas
    "ChannelConfigResponse",
    "ChannelConfigUpdate",
    "ChannelTestResponse",
    "ChannelTypeInfo",
    "ChannelTypesResponse",
    # Cron schemas
    "CronExecutionListResponse",
    "CronExecutionResponse",
    "CronJobCreate",
    "CronJobListResponse",
    "CronJobResponse",
    "CronJobUpdate",
    "CronOutputConfig",
    "CronTriggerResponse",
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
