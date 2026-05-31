"""Pydantic input schemas for cron manager tools."""

from pydantic import BaseModel, Field


class CreateCronInput(BaseModel):
    """Input schema for creating a persistent cron job."""

    name: str = Field(
        description=(
            "Unique name for this cron job. "
            "Use lowercase letters, digits, and hyphens only "
            "(e.g., 'morning-check', 'daily-summary'). "
            "This becomes the filename and job ID."
        )
    )
    schedule: str = Field(
        description=(
            "Standard cron expression: 'minute hour day-of-month month day-of-week'. "
            "Examples: '0 9 * * *' (daily at 9am), '*/15 * * * *' (every 15 min), "
            "'0 0 * * 0' (every Sunday midnight). "
            "Runs in the workspace timezone."
        )
    )
    prompt: str = Field(
        description=(
            "The instruction the agent will execute when this cron fires. "
            "Include all necessary context — the cron agent has no memory of "
            "previous conversations."
        )
    )
    enabled: bool = Field(
        default=True,
        description="Whether the cron job is active immediately after creation.",
    )
    delivery: str = Field(
        default="channel",
        description=(
            "Where to deliver results: 'channel' (send to user) "
            "or 'agent' (inject into main agent queue)."
        ),
    )


class UpdateCronInput(BaseModel):
    """Input schema for updating an existing cron job."""

    name: str = Field(description="Name of the existing cron job to update.")
    schedule: str | None = Field(
        default=None,
        description=(
            "New cron expression to set. Leave unset to keep the current schedule."
        ),
    )
    prompt: str | None = Field(
        default=None,
        description="New prompt to set. Leave unset to keep the current prompt.",
    )
    enabled: bool | None = Field(
        default=None,
        description=(
            "Set to true to enable or false to disable. "
            "Leave unset to keep the current state."
        ),
    )
    delivery: str | None = Field(
        default=None,
        description=(
            "New delivery mode: 'channel' or 'agent'. "
            "Leave unset to keep the current delivery mode."
        ),
    )


class DeleteCronInput(BaseModel):
    """Input schema for deleting a cron job."""

    name: str = Field(description="Name of the cron job to permanently delete.")


__all__ = ["CreateCronInput", "UpdateCronInput", "DeleteCronInput"]
