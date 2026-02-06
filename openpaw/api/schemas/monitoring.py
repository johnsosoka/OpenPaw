"""Pydantic schemas for Monitoring API endpoints."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class HealthResponse(BaseModel):
    """Response model for GET /monitoring/health endpoint.

    Contains system health status and workspace statistics.

    Attributes:
        status: Overall health status (e.g., "healthy", "degraded")
        version: API version string
        database: Database connection status (e.g., "connected", "disconnected")
        orchestrator: Orchestrator status (e.g., "running", "unavailable")
        workspaces: Workspace count statistics (total, running, stopped)
    """

    status: str
    version: str
    database: str
    orchestrator: str
    workspaces: dict[str, int]

    model_config = ConfigDict(extra="forbid")


class WorkspaceStateResponse(BaseModel):
    """Response model for workspace state summary.

    Attributes:
        name: Workspace name
        status: Runtime status (e.g., "running", "stopped")
        state: Agent state (e.g., "idle", "active", "stuck")
        channels: List of channel types configured
        active_sessions: Number of active agent sessions
        queue_depth: Number of queued messages
        last_activity: Timestamp of last activity (if available)
    """

    name: str
    status: str
    state: str
    channels: list[str]
    active_sessions: int
    queue_depth: int
    last_activity: datetime | None = None

    model_config = ConfigDict(extra="forbid")


class WorkspaceStatesResponse(BaseModel):
    """Response model for GET /monitoring/workspaces endpoint.

    Contains list of all workspace states.
    """

    workspaces: list[WorkspaceStateResponse]

    model_config = ConfigDict(extra="forbid")


class QueueStats(BaseModel):
    """Queue statistics for a specific lane.

    Attributes:
        queued: Number of messages queued
        active: Number of messages being processed
        concurrency: Maximum concurrent workers for this lane
    """

    queued: int
    active: int
    concurrency: int

    model_config = ConfigDict(extra="forbid")


class WorkspaceDetailResponse(BaseModel):
    """Response model for detailed workspace state.

    Used in GET /monitoring/workspaces/{name} endpoint.

    Attributes:
        name: Workspace name
        status: Runtime status (e.g., "running", "stopped")
        state: Agent state (e.g., "idle", "active", "stuck")
        channels: Channel configuration details
        queue: Queue statistics by lane
        sessions: Session count statistics (total, active)
        tokens_today: Token usage statistics (input, output)
        errors_today: Error count for today
    """

    name: str
    status: str
    state: str
    channels: dict[str, Any]
    queue: dict[str, QueueStats]
    sessions: dict[str, int]
    tokens_today: dict[str, int]
    errors_today: int

    model_config = ConfigDict(extra="forbid")


class SessionResponse(BaseModel):
    """Response model for agent session information.

    Attributes:
        session_key: Session identifier
        state: Session state (e.g., "idle", "active")
        started_at: Session start timestamp
        messages_processed: Number of messages processed
        tokens_used: Token usage statistics (input, output)
        last_message: Timestamp of last message
    """

    session_key: str
    state: str
    started_at: datetime
    messages_processed: int
    tokens_used: dict[str, int]
    last_message: datetime

    model_config = ConfigDict(extra="forbid")


class SessionListResponse(BaseModel):
    """Response model for GET /monitoring/workspaces/{name}/sessions endpoint.

    Contains list of active sessions for a workspace.
    """

    sessions: list[SessionResponse]

    model_config = ConfigDict(extra="forbid")


class MetricsResponse(BaseModel):
    """Response model for aggregated metrics.

    Used in GET /monitoring/metrics endpoints.

    Attributes:
        period: Time period for aggregation (e.g., "hour", "day", "week")
        start: Start timestamp for period
        end: End timestamp for period
        metrics: Aggregated metrics data
    """

    period: str
    start: datetime
    end: datetime
    metrics: dict[str, Any]

    model_config = ConfigDict(extra="forbid")


class ErrorResponse(BaseModel):
    """Response model for single error entry.

    Attributes:
        id: Error record ID
        workspace: Workspace name (if applicable)
        session_key: Session identifier (if applicable)
        error_type: Error type/class name
        message: Error message
        created_at: Error timestamp
    """

    id: int
    workspace: str | None
    session_key: str | None
    error_type: str
    message: str
    created_at: datetime

    model_config = ConfigDict(extra="forbid")


class ErrorListResponse(BaseModel):
    """Response model for GET /monitoring/errors endpoints.

    Contains list of recent errors.
    """

    errors: list[ErrorResponse]

    model_config = ConfigDict(extra="forbid")


class QueueStatusResponse(BaseModel):
    """Response model for GET /monitoring/queues endpoint.

    Contains queue statistics across all workspaces.

    Attributes:
        queues: Queue statistics by workspace and lane
        totals: Total statistics across all queues
    """

    queues: dict[str, dict[str, QueueStats]]
    totals: dict[str, int]

    model_config = ConfigDict(extra="forbid")
