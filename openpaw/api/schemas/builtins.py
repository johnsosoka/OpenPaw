"""Pydantic schemas for Builtins API endpoints."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class BuiltinPrerequisites(BaseModel):
    """Prerequisites required for a builtin to be available.

    Attributes:
        env_vars: List of required environment variables
        packages: List of required Python packages
    """

    env_vars: list[str]
    packages: list[str]

    model_config = ConfigDict(extra="forbid")


class BuiltinResponse(BaseModel):
    """Response model for a single builtin.

    Used in GET /builtins and GET /builtins/available responses.

    Attributes:
        name: Builtin identifier (e.g., "brave_search")
        type: Builtin type ("tool" or "processor")
        group: Group classification (e.g., "search", "voice")
        description: What the builtin does
        prerequisites: Required env vars and packages
        available: Whether prerequisites are satisfied
        enabled: Whether the builtin is enabled
    """

    name: str
    type: str
    group: str
    description: str
    prerequisites: BuiltinPrerequisites
    available: bool
    enabled: bool

    model_config = ConfigDict(extra="forbid")


class BuiltinListResponse(BaseModel):
    """Response model for GET /builtins endpoint.

    Contains list of all registered builtins with availability status.
    """

    builtins: list[BuiltinResponse]
    total: int

    model_config = ConfigDict(extra="forbid")


class BuiltinConfigUpdate(BaseModel):
    """Request model for updating builtin configuration.

    Used in PUT /builtins/{name} endpoint.
    Both fields are optional - provide only what needs updating.

    Attributes:
        enabled: Enable/disable the builtin
        config: Builtin-specific configuration dictionary
    """

    enabled: bool | None = None
    config: dict[str, Any] | None = None

    model_config = ConfigDict(extra="forbid")


class BuiltinConfigResponse(BaseModel):
    """Response model for GET /builtins/{name} endpoint.

    Contains configuration details for a single builtin.

    Attributes:
        name: Builtin identifier
        type: Builtin type ("tool" or "processor")
        group: Group classification
        enabled: Whether the builtin is enabled
        config: Builtin-specific configuration
    """

    name: str
    type: str
    group: str
    enabled: bool
    config: dict[str, Any]

    model_config = ConfigDict(extra="forbid")


class ApiKeyCreate(BaseModel):
    """Request model for storing a new API key.

    Used in POST /builtins/api-keys endpoint.
    The value is encrypted before storage.

    Attributes:
        name: Key identifier (e.g., "BRAVE_API_KEY")
        service: Service name (e.g., "brave_search")
        value: The actual API key (only in request, never in response)
    """

    name: str
    service: str
    value: str

    model_config = ConfigDict(extra="forbid")


class ApiKeyResponse(BaseModel):
    """Response model for API key metadata.

    Used in GET /builtins/api-keys and POST /builtins/api-keys responses.
    Never includes the actual key value.

    Attributes:
        name: Key identifier
        service: Service name
        created_at: When the key was created
    """

    name: str
    service: str
    created_at: datetime

    model_config = ConfigDict(extra="forbid")


class ApiKeyListResponse(BaseModel):
    """Response model for GET /builtins/api-keys endpoint.

    Contains list of stored API key metadata (never actual values).
    """

    api_keys: list[ApiKeyResponse]
    total: int

    model_config = ConfigDict(extra="forbid")


class AllowlistUpdate(BaseModel):
    """Request model for updating builtin allow/deny lists.

    Used in PUT /builtins/allowlist endpoint.

    Attributes:
        allow: List of allowed builtin names or groups (e.g., ["brave_search", "group:voice"])
        deny: List of denied builtin names or groups
    """

    allow: list[str]
    deny: list[str]

    model_config = ConfigDict(extra="forbid")


class AllowlistResponse(BaseModel):
    """Response model for GET /builtins/allowlist endpoint.

    Contains current global allow/deny lists.

    Attributes:
        allow: List of allowed builtin names or groups
        deny: List of denied builtin names or groups
    """

    allow: list[str]
    deny: list[str]

    model_config = ConfigDict(extra="forbid")
