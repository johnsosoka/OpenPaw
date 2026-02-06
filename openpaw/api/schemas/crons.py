"""Pydantic schemas for Crons API endpoints."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CronOutputConfig(BaseModel):
    """Output configuration for cron job.

    Specifies where the cron job output should be sent.

    Attributes:
        channel: Channel type (e.g., "telegram")
        chat_id: Target chat/channel ID for output
    """

    channel: str
    chat_id: int

    model_config = ConfigDict(extra="forbid")


class CronJobResponse(BaseModel):
    """Response model for a single cron job.

    Used in GET /crons/{workspace}/{name} and POST /crons responses.

    Attributes:
        id: Cron job ID
        workspace: Workspace name
        name: Cron job name
        schedule: Cron expression (e.g., "0 9 * * *")
        enabled: Whether the cron job is enabled
        prompt: Prompt text to execute
        output: Output configuration
        created_at: Creation timestamp
        updated_at: Last update timestamp
        next_run: Next scheduled run time (None if disabled or invalid schedule)
    """

    id: int
    workspace: str
    name: str
    schedule: str
    enabled: bool
    prompt: str
    output: CronOutputConfig
    created_at: datetime
    updated_at: datetime
    next_run: datetime | None = None

    model_config = ConfigDict(extra="forbid")


class CronJobListResponse(BaseModel):
    """Response model for GET /crons endpoint.

    Contains list of all cron jobs with optional filters applied.
    """

    cron_jobs: list[CronJobResponse]
    total: int

    model_config = ConfigDict(extra="forbid")


class CronJobCreate(BaseModel):
    """Request model for creating a new cron job.

    Used in POST /crons endpoint.

    Attributes:
        workspace: Workspace name
        name: Cron job name (unique per workspace)
        schedule: Cron expression (validated on creation)
        prompt: Prompt text to execute
        output: Output configuration
        enabled: Whether the cron job should be enabled (defaults to True)
    """

    workspace: str
    name: str
    schedule: str
    prompt: str
    output: CronOutputConfig
    enabled: bool = Field(default=True)

    model_config = ConfigDict(extra="forbid")


class CronJobUpdate(BaseModel):
    """Request model for updating a cron job.

    Used in PUT /crons/{workspace}/{name} endpoint.
    All fields are optional - provide only what needs updating.

    Attributes:
        schedule: New cron expression (validated if provided)
        prompt: New prompt text
        output: New output configuration
        enabled: Enable/disable the cron job
    """

    schedule: str | None = None
    prompt: str | None = None
    output: CronOutputConfig | None = None
    enabled: bool | None = None

    model_config = ConfigDict(extra="forbid")


class CronTriggerResponse(BaseModel):
    """Response model for POST /crons/{workspace}/{name}/trigger endpoint.

    Indicates manual trigger was accepted.

    Attributes:
        status: Status message
        workspace: Workspace name
        name: Cron job name
    """

    status: str
    workspace: str
    name: str

    model_config = ConfigDict(extra="forbid")


class CronExecutionResponse(BaseModel):
    """Response model for a single cron execution.

    Used in GET /crons/executions response.

    Attributes:
        id: Execution ID
        workspace: Workspace name
        cron_name: Cron job name
        started_at: Execution start time
        completed_at: Execution completion time (None if still running)
        status: Execution status (success, failed, timeout)
        tokens_in: Input token count
        tokens_out: Output token count
        error_message: Error message if status is failed
    """

    id: int
    workspace: str
    cron_name: str
    started_at: datetime
    completed_at: datetime | None
    status: str
    tokens_in: int
    tokens_out: int
    error_message: str | None = None

    model_config = ConfigDict(extra="forbid")


class CronExecutionListResponse(BaseModel):
    """Response model for GET /crons/executions endpoint.

    Contains list of recent cron executions.
    """

    executions: list[CronExecutionResponse]
    total: int

    model_config = ConfigDict(extra="forbid")
