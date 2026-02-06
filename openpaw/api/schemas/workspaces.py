"""Pydantic schemas for Workspace API endpoints."""

import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class WorkspaceCreate(BaseModel):
    """Request model for creating a new workspace.

    POST /workspaces
    """

    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Validate workspace name is a valid directory name.

        Must contain only alphanumeric characters, underscores, and hyphens.
        Cannot start with a dot or contain path separators.
        """
        if not v:
            raise ValueError("Workspace name cannot be empty")

        if v.startswith("."):
            raise ValueError("Workspace name cannot start with a dot")

        if "/" in v or "\\" in v:
            raise ValueError("Workspace name cannot contain path separators")

        if not re.match(r"^[a-zA-Z0-9_-]+$", v):
            raise ValueError(
                "Workspace name must contain only alphanumeric characters, "
                "underscores, and hyphens"
            )

        return v

    model_config = ConfigDict(extra="forbid")


class ModelConfigUpdate(BaseModel):
    """Model configuration updates for workspace.

    Partial update model - all fields optional.
    """

    model_provider: str | None = None
    model_name: str | None = None
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_turns: int | None = Field(default=None, ge=1)
    region: str | None = None

    model_config = ConfigDict(extra="forbid")


class QueueConfigUpdate(BaseModel):
    """Queue configuration updates for workspace.

    Partial update model - all fields optional.
    """

    mode: str | None = Field(default=None, pattern="^(collect|steer|followup|interrupt)$")
    debounce_ms: int | None = Field(default=None, ge=0)

    model_config = ConfigDict(extra="forbid")


class WorkspaceUpdate(BaseModel):
    """Request model for updating workspace configuration.

    PUT /workspaces/{name}
    All fields optional for partial updates.
    """

    description: str | None = None
    enabled: bool | None = None
    model_config_update: ModelConfigUpdate | None = Field(default=None, alias="model_config")
    queue_config: QueueConfigUpdate | None = None

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class WorkspaceConfigResponse(BaseModel):
    """Workspace configuration details in response.

    Subset of workspace config returned in WorkspaceResponse.
    """

    model_provider: str | None = None
    model_name: str | None = None
    temperature: float | None = None
    max_turns: int | None = None
    queue_mode: str | None = None
    debounce_ms: int | None = None

    model_config = ConfigDict(extra="forbid")


class ChannelResponse(BaseModel):
    """Channel configuration in workspace response.

    Never includes sensitive data like tokens.
    """

    type: str
    enabled: bool
    allowed_users: list[int] = Field(default_factory=list)
    allowed_groups: list[int] = Field(default_factory=list)
    allow_all: bool

    model_config = ConfigDict(extra="forbid")


class CronSummary(BaseModel):
    """Cron job summary in workspace response."""

    name: str
    schedule: str
    enabled: bool

    model_config = ConfigDict(extra="forbid")


class WorkspaceResponse(BaseModel):
    """Response model for workspace details.

    Used for GET /workspaces/{name}, POST /workspaces, PUT /workspaces/{name}.
    """

    name: str
    description: str | None = None
    enabled: bool
    status: str  # running, stopped
    path: str
    config: WorkspaceConfigResponse | None = None
    channel: ChannelResponse | None = None
    cron_jobs: list[CronSummary] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(extra="forbid")


class WorkspaceListResponse(BaseModel):
    """Response model for workspace list.

    GET /workspaces
    """

    workspaces: list[WorkspaceResponse]
    total: int

    model_config = ConfigDict(extra="forbid")


class WorkspaceControlResponse(BaseModel):
    """Response model for workspace control operations.

    POST /workspaces/{name}/start
    POST /workspaces/{name}/stop
    POST /workspaces/{name}/restart
    """

    status: str  # started, stopped, restarted
    workspace: str

    model_config = ConfigDict(extra="forbid")


class FileListResponse(BaseModel):
    """Response model for workspace file listing.

    GET /workspaces/{name}/files
    """

    files: list[str]

    model_config = ConfigDict(extra="forbid")


class FileContentResponse(BaseModel):
    """Response model for workspace file content.

    GET /workspaces/{name}/files/{filename}
    PUT /workspaces/{name}/files/{filename}
    """

    filename: str
    content: str
    updated_at: datetime | None = None

    model_config = ConfigDict(extra="forbid")


class FileWriteRequest(BaseModel):
    """Request model for writing workspace file.

    PUT /workspaces/{name}/files/{filename}
    """

    content: str

    model_config = ConfigDict(extra="forbid")
