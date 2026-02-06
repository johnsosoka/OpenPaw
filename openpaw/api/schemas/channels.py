"""Pydantic schemas for Channels API endpoints."""

from typing import Any

from pydantic import BaseModel, ConfigDict


class ChannelTypeInfo(BaseModel):
    """Information about a supported channel type.

    Attributes:
        name: Channel type identifier (e.g., "telegram")
        description: Human-readable description of the channel type
        config_schema: JSON schema describing expected configuration fields
        status: Current implementation status (e.g., "active", "planned")
    """

    name: str
    description: str
    config_schema: dict[str, Any]
    status: str | None = "active"

    model_config = ConfigDict(extra="forbid")


class ChannelTypesResponse(BaseModel):
    """Response model for GET /channels/types endpoint.

    Contains list of all supported channel types and their metadata.
    """

    types: list[ChannelTypeInfo]

    model_config = ConfigDict(extra="forbid")


class ChannelConfigResponse(BaseModel):
    """Response model for channel configuration.

    Used in GET /channels/{workspace} and PUT /channels/{workspace} responses.
    Never includes the actual token value for security reasons.

    Attributes:
        workspace: Workspace name this channel is bound to
        type: Channel type (e.g., "telegram")
        enabled: Whether the channel is enabled
        allowed_users: List of allowed user IDs
        allowed_groups: List of allowed group IDs
        allow_all: Whether to allow all users/groups
        status: Runtime status from orchestrator (if available)
    """

    workspace: str
    type: str
    enabled: bool
    allowed_users: list[int]
    allowed_groups: list[int]
    allow_all: bool
    status: dict[str, Any] | None = None

    model_config = ConfigDict(extra="forbid")


class ChannelConfigUpdate(BaseModel):
    """Request model for updating channel configuration.

    Used in PUT /channels/{workspace} endpoint.
    All fields are optional - provide only what needs updating.

    Attributes:
        type: Channel type (e.g., "telegram")
        token: Channel authentication token (will be encrypted)
        allowed_users: List of allowed user IDs
        allowed_groups: List of allowed group IDs
        allow_all: Whether to allow all users/groups
        enabled: Whether the channel is enabled
    """

    type: str | None = None
    token: str | None = None
    allowed_users: list[int] | None = None
    allowed_groups: list[int] | None = None
    allow_all: bool | None = None
    enabled: bool | None = None

    model_config = ConfigDict(extra="forbid")


class ChannelTestResponse(BaseModel):
    """Response model for POST /channels/{workspace}/test endpoint.

    Contains results of testing the channel connection.

    Attributes:
        status: Test status (e.g., "success", "failed")
        bot_info: Bot information from the channel API (username, id, etc.)
    """

    status: str
    bot_info: dict[str, Any]

    model_config = ConfigDict(extra="forbid")
