"""Pydantic input models for cron tool."""

from pydantic import BaseModel, Field


class ScheduleAtInput(BaseModel):
    """Input schema for scheduling a one-time action."""

    run_at: str = Field(
        description=(
            "ISO 8601 timestamp when the action should run. "
            "IMPORTANT: Calculate this from the current time shown in the user's message. "
            "For relative times like 'in 5 minutes', add the minutes to the current time. "
            "Example: if current time is '2026-02-06 14:30' and user says 'in 10 minutes', "
            "use '2026-02-06T14:40:00'. Always use the same timezone as the current time. "
            "Format: 'YYYY-MM-DDTHH:MM:SS' (e.g., '2026-02-06T14:45:00')"
        )
    )
    prompt: str = Field(
        description=(
            "The instruction for the future action. "
            "IMPORTANT: This prompt will be executed by a stateless agent with NO memory "
            "of the current conversation. Include ALL relevant context: the user's name, "
            "what topic to follow up on, and any specific details. "
            "Bad: 'Follow up with Anna'. "
            "Good: 'Follow up with Anna about her migraine — check pain level, "
            "nausea, and whether sumatriptan helped.'"
        )
    )


class ScheduleEveryInput(BaseModel):
    """Input schema for scheduling a recurring action."""

    interval_seconds: int = Field(
        description=(
            "Seconds between each execution. Convert user's time to seconds: "
            "1 min = 60, 5 min = 300, 10 min = 600, 30 min = 1800, 1 hour = 3600. "
            "Minimum 60 seconds."
        ),
        ge=60,
    )
    prompt: str = Field(
        description=(
            "The instruction to repeat on each execution. "
            "IMPORTANT: This prompt will be executed by a stateless agent with NO memory "
            "of the current conversation. Include ALL relevant context: the user's name, "
            "what topic to follow up on, and any specific details. "
            "Bad: 'Follow up with Anna'. "
            "Good: 'Follow up with Anna about her migraine — check pain level, "
            "nausea, and whether sumatriptan helped.'"
        )
    )


class CancelScheduledInput(BaseModel):
    """Input schema for canceling a scheduled task."""

    task_id: str = Field(description="The task ID or short prefix as shown by list_scheduled")
